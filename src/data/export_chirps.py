"""T2 - export CHIRPS v3 monthly precipitation for the analysis grid, 1981-2025.

Request granularity is the month (~2,820 features), file granularity is the year.
Collapsing the two would put ~33,840 features in one request, close enough to the
size limits that a partial result becomes possible - and a partial result here is
silent, because nothing downstream can tell a short month from a month that genuinely
had fewer cells.

Run `python -m scripts.check_chirps_continuity` first. It settles, before any of this
runs, that the series is one product rather than several spliced together, and that
each month really does hold six pentads.

Run:  python -m src.data.export_chirps
      python -m src.data.export_chirps --years 1981-1990   # a subset
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ee
import pandas as pd

from src.data.gee_io import (
    ROOT,
    provenance,
    schema_fingerprint,
    atomic_write,
    fetch_features,
    initialize,
    load_config,
    report,
    with_retry,
)
from src.data.grid import ID_STRIDE, GRID_CSV, basin_feature, cell_indices, chirps_projection, lattice_params, make_cell_id

RAW_DIR = ROOT / "data" / "raw" / "chirps"
CONTINUITY_JSON = ROOT / "reports" / "chirps_continuity.json"
PENTADS_PER_MONTH = 6

# Isolated zeros are recorded and flagged, not treated as fatal. They become fatal
# only if widespread, which would mean systematic masking rather than an artefact.
ISOLATED_ZERO_MAX_SHARE = 0.01
# A zero cluster whose surrounding ring is all above this is a cliff, not a gradient -
# rainfall fields do not step from 0 to several mm across one cell.
ZERO_CLIFF_MM = 2.0

# Columns this exporter writes. Recorded in every manifest so that resume can tell
# "already fetched" from "fetched under a different schema" - see gee_io.schema_fingerprint.
EXPECTED_SCHEMA = ["cell_id", "date", "month", "precip_chirps_mm", "n_pentads", "n_obs"]

# A catastrophic-scale ceiling only. It is deliberately far above anything weather
# produces here, because it guards against a scale or accumulation blunder - summing
# a year instead of a month, say - and nothing subtler. Subtler errors are caught by
# the basin-mean cross-check below, which is anchored to an independent computation.
#
# An earlier version used 417 mm, the basin-MEAN ANNUAL total, as a bound on a
# per-CELL MONTHLY value. That is a category error twice over: a single cell is not
# bounded by a basin mean, and an annual total is not a monthly one. It fired on
# 1981 against a genuinely correct 720.6 mm - in a RING cell on the Taurus flank,
# outside the basin, where 1,500-2,000 mm/year is normal. See failure-modes 15.
ABSURD_MONTHLY_MM = 2000.0

# The exported per-cell values, averaged over the basin, must reproduce the
# basin-mean series that the pre-flight computed by a completely different route
# (server-side reduceRegion over the polygon). Agreement is evidence the sampling
# and the accumulation window are both right.
BASIN_MEAN_TOLERANCE = 0.02


def zero_diagnostics(df: pd.DataFrame, value_col: str = "precip_chirps_mm") -> tuple[list[dict], int]:
    """Per month: exact-zero cells, and which of them look like artefacts.

    Seasonality does not separate a real dry month from masked pixels arriving as 0.
    CHIRPS overestimates low precipitation amounts, so the climatological dry season
    rarely reaches exact zero here - the basin minimum in July 1990, the driest month
    of a dry year, was 2.42 mm across all 2,820 cells.

    Neither does a per-cell neighbour test. Requiring a neighbour in (0,1] mm flags a
    genuinely dry month almost entirely, because there the neighbours are zero too:
    1990-03 came out as 1,882 "isolated" of 2,009 zeros, which is the opposite of
    the truth.

    What separates them is the CLUSTER BOUNDARY. Rainfall fields are continuous, so a
    real dry patch is surrounded by a gradient down to zero, while a masking artefact
    is an island with a cliff at its edge. So: find connected components of exact
    zeros, then look at the ring of non-zero cells touching each one. A low boundary
    minimum means a gradient and the cluster is real; a high one means a cliff.

    1996-04 is the case that prompted this: nine contiguous cells at exactly 0 in a
    month averaging 64.5 mm, with the nearest non-zero neighbour at 3.11 mm.

    Returns (per-month diagnostics, total cells in artefact-like clusters).
    """
    diagnostics: list[dict] = []
    total_isolated = 0
    for month, sub in df.groupby("month"):
        values = dict(zip(sub["cell_id"].astype("int64"), sub[value_col]))
        zeros = {c for c, v in values.items() if v == 0}
        if not zeros:
            continue

        neighbours = lambda c: [                      # noqa: E731
            (c // ID_STRIDE + di) * ID_STRIDE + (c % ID_STRIDE + dj)
            for di in (-1, 0, 1) for dj in (-1, 0, 1) if (di, dj) != (0, 0)
        ]

        seen: set[int] = set()
        isolated: list[int] = []
        clusters = []
        for start in zeros:
            if start in seen:
                continue
            stack, component = [start], []
            seen.add(start)
            while stack:
                cell = stack.pop()
                component.append(cell)
                for nb in neighbours(cell):
                    if nb in zeros and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
            boundary = [
                values[nb] for cell in component for nb in neighbours(cell)
                if nb in values and values[nb] > 0
            ]
            boundary_min = min(boundary) if boundary else None
            artefact = boundary_min is not None and boundary_min > ZERO_CLIFF_MM
            clusters.append({
                "size": len(component),
                "boundary_min_mm": round(boundary_min, 4) if boundary_min is not None else None,
                "artefact": artefact,
            })
            if artefact:
                isolated.extend(component)

        total_isolated += len(isolated)
        diagnostics.append({
            "month": int(month),
            "n_zero": len(zeros),
            "n_clusters": len(clusters),
            "n_isolated": len(isolated),
            "isolated_cell_ids": sorted(isolated),
            "largest_cluster": max(c["size"] for c in clusters),
            "min_boundary_of_artefacts": min(
                [c["boundary_min_mm"] for c in clusters if c["artefact"]], default=None
            ),
            "mean_mm": float(sub[value_col].mean()),
        })
    return diagnostics, total_isolated


def month_image(chirps: "ee.ImageCollection", start: "ee.Date") -> tuple["ee.Image", "ee.Number"]:
    """Monthly total, plus a PER-PIXEL count of the pentads that contributed.

    The per-pixel count is the one that matters. `size()` only says six images
    exist in the window; if a pixel is masked in two of them, `sum()` silently
    returns a total built from four pentads and nothing anywhere reports it. The
    result is a plausible, too-low value - the kind of error that survives every
    range check.
    """
    window = chirps.filterDate(start, start.advance(1, "month"))
    band = window.select("precipitation")
    return (
        window.sum().rename("precip_chirps_mm").addBands(band.count().rename("n_obs")),
        window.size(),
    )


def fetch_month(
    config: dict[str, Any],
    chirps: "ee.ImageCollection",
    region: "ee.Geometry",
    proj: "ee.Projection",
    params: dict[str, float],
    year: int,
    month: int,
    expected_cells: int,
) -> pd.DataFrame:
    start = ee.Date(f"{year}-{month:02d}-01")
    image, n_pentads = month_image(chirps, start)

    # sample() returns the sampled BANDS only, so the coordinates have to be bands
    # too. Deriving cell_id from them - rather than trusting row order - is what
    # guarantees this month's rows line up with the grid built in T1.
    # The pentad count rides along as a band as well: carrying it server-side saves
    # a round trip per month (540 of them across the export) and still lets every
    # row be checked. A missing pentad is a silent ~17% shortfall in that month.
    sampled = (
        ee.Image.pixelLonLat()
        .reproject(proj)
        .addBands(image)
        .addBands(ee.Image.constant(n_pentads).rename("n_pentads").toInt())
    )
    fc = sampled.sample(region=region, projection=proj, geometries=False, dropNulls=False)
    df = fetch_features(
        fc, what=f"chirps {year}-{month:02d}", expected_rows=expected_cells,
        max_retries=int(config["export"]["max_retries"]),
        backoff_base=float(config["export"]["backoff_base_seconds"]),
    )
    bad = df.loc[df["n_pentads"] != PENTADS_PER_MONTH, "n_pentads"]
    if len(bad):
        raise AssertionError(
            f"{year}-{month:02d}: expected {PENTADS_PER_MONTH} pentads in the "
            f"collection, found {sorted(bad.unique())}. A missing pentad is a silent "
            "~17% shortfall in the month's total."
        )
    short = df.loc[df["n_obs"] != PENTADS_PER_MONTH]
    if len(short):
        raise AssertionError(
            f"{year}-{month:02d}: {len(short)} of {len(df)} cells accumulated fewer "
            f"than {PENTADS_PER_MONTH} pentads (values {sorted(short['n_obs'].unique())}). "
            "Partial masking makes sum() return a plausible but too-low total."
        )
    i, j = cell_indices(df["longitude"], df["latitude"], params)
    df["cell_id"] = make_cell_id(i, j)
    df["date"] = f"{year}-{month:02d}-01"
    df["month"] = month
    return df[["cell_id", "date", "month", "precip_chirps_mm", "n_pentads", "n_obs"]]


def export_year(
    config: dict[str, Any],
    chirps: "ee.ImageCollection",
    region: "ee.Geometry",
    proj: "ee.Projection",
    params: dict[str, float],
    year: int,
    grid_ids: set[int],
    basin_ids: set[int],
    reference_annual: dict[int, float],
) -> dict[str, Any]:
    path = RAW_DIR / f"chirps_{year}.csv"
    manifest_path = RAW_DIR / f"chirps_{year}.manifest.json"
    if path.exists() and manifest_path.exists():
        cached = json.loads(manifest_path.read_text(encoding="utf-8"))
        if cached.get("schema_fingerprint") == schema_fingerprint(EXPECTED_SCHEMA):
            print(f"  {year}: already on disk, skipping (atomic write means present implies complete)")
            return cached
        print(f"  {year}: on disk but written under a different schema "
              f"({cached.get('schema_fingerprint')} != "
              f"{schema_fingerprint(EXPECTED_SCHEMA)}) - refetching")
        path.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)

    expected_cells = len(grid_ids)
    frames = []
    for month in range(1, 13):
        frames.append(
            fetch_month(config, chirps, region, proj, params, year, month, expected_cells)
        )
    df = pd.concat(frames, ignore_index=True)

    expected_rows = expected_cells * 12
    problems = []
    if len(df) != expected_rows:
        problems.append(f"rows: expected {expected_rows}, got {len(df)}")
    if df["date"].nunique() != 12:
        problems.append(f"distinct months: expected 12, got {df['date'].nunique()}")
    if set(df["cell_id"]) != grid_ids:
        missing = len(grid_ids - set(df["cell_id"]))
        extra = len(set(df["cell_id"]) - grid_ids)
        problems.append(f"cell_id set mismatch: {missing} missing, {extra} unexpected")
    nulls = int(df["precip_chirps_mm"].isna().sum())
    if nulls:
        problems.append(f"null precipitation values: {nulls}")
    negatives = int((df["precip_chirps_mm"] < 0).sum())
    if negatives:
        problems.append(f"negative precipitation values: {negatives}")
    hottest = float(df["precip_chirps_mm"].max())
    if hottest > ABSURD_MONTHLY_MM:
        problems.append(
            f"monthly maximum {hottest:.1f} mm is beyond anything weather produces - "
            "suspect a scale or accumulation blunder"
        )

    # The real guard. Range checks are applied to the ANALYSIS population only:
    # ring cells exist as boundary insurance and sit partly on the Taurus flank,
    # a different precipitation regime entirely, so their values say nothing about
    # whether the basin export is correct.
    basin = df[df["cell_id"].isin(basin_ids)]
    basin_mean_annual = float(basin.groupby("cell_id")["precip_chirps_mm"].sum().mean())
    expected_mean = reference_annual.get(year)
    if expected_mean is None:
        problems.append(
            f"no pre-flight basin mean for {year} - run scripts.check_chirps_continuity first"
        )
    else:
        drift = abs(basin_mean_annual / expected_mean - 1)
        if drift > BASIN_MEAN_TOLERANCE:
            problems.append(
                f"basin-mean annual total {basin_mean_annual:.1f} mm differs from the "
                f"pre-flight value {expected_mean:.1f} mm by {drift:.2%}, over the "
                f"{BASIN_MEAN_TOLERANCE:.0%} tolerance. The per-cell sampling and the "
                "server-side basin reduction disagree, so one of them is wrong"
            )
    zero_diag, isolated_total = zero_diagnostics(df)

    isolated_share = isolated_total / (len(grid_ids) * 12)
    if isolated_share > ISOLATED_ZERO_MAX_SHARE:
        problems.append(
            f"{isolated_total} isolated zero cells ({isolated_share:.2%} of rows) "
            f"exceeds {ISOLATED_ZERO_MAX_SHARE:.0%}. Scattered artefacts are one "
            "thing; this many means masked pixels are arriving as 0 systematically"
        )

    if problems:
        raise AssertionError(f"{year}: " + "; ".join(problems))

    if df.columns.tolist() != EXPECTED_SCHEMA:
        raise AssertionError(
            f"{year}: columns {df.columns.tolist()} do not match EXPECTED_SCHEMA "
            f"{EXPECTED_SCHEMA} - update the constant deliberately, do not drift"
        )
    atomic_write(df, path)
    manifest = {
        "year": year,
        "collection": config["sources"]["precipitation_primary"],
        "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": len(df),
        "cells": expected_cells,
        "months": 12,
        "pentads_per_month": PENTADS_PER_MONTH,
        "images_used": PENTADS_PER_MONTH * 12,
        "precip_mm": {
            "min": float(df["precip_chirps_mm"].min()),
            "max": hottest,
            "mean": float(df["precip_chirps_mm"].mean()),
            "zero_rows": int((df["precip_chirps_mm"] == 0).sum()),
            "zero_rows_by_month": {
                int(m): int(n) for m, n in
                df.loc[df["precip_chirps_mm"] == 0, "month"].value_counts().sort_index().items()
            },
            "zero_month_diagnostics": zero_diag,
            "isolated_zero_cells": isolated_total,
        },
        "n_obs_per_pixel": PENTADS_PER_MONTH,
        "provenance": provenance(),
        "schema_fingerprint": schema_fingerprint(EXPECTED_SCHEMA),
        "schema_columns": EXPECTED_SCHEMA,
        "basin_mean_annual_mm": basin_mean_annual,
        "preflight_basin_mean_annual_mm": expected_mean,
        "note": (
            "CHIRPS final products are reprocessed from time to time, so the same "
            "export can return different numbers later. fetched_utc is what makes "
            "this reproducible."
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  {year}: {len(df):,} rows, basin-mean annual "
          f"{basin_mean_annual:.1f} mm vs pre-flight {expected_mean:.1f} "
          f"({basin_mean_annual / expected_mean - 1:+.2%}), "
          f"max {hottest:.1f} mm, zeros {manifest['precip_mm']['zero_rows']:,}")
    return manifest


def parse_years(spec: str | None, config: dict[str, Any]) -> list[int]:
    if not spec:
        return list(range(int(str(config["period"]["export_start"])[:4]),
                          int(str(config["period"]["export_end"])[:4]) + 1))
    if "-" in spec:
        a, b = spec.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(spec)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", default=None, help="e.g. 1990 or 1981-1990")
    args = parser.parse_args()

    config = load_config()
    initialize(config)
    years = parse_years(args.years, config)

    grid = pd.read_csv(GRID_CSV)
    grid_ids = set(grid["cell_id"].astype("int64"))
    basin_ids = set(grid.loc[grid["in_hydrobasins"], "cell_id"].astype("int64"))

    if not CONTINUITY_JSON.exists():
        raise SystemExit(
            "reports/chirps_continuity.json is missing. Run "
            "`python -m scripts.check_chirps_continuity` first: the export checks "
            "itself against the basin-mean series that pre-flight computes."
        )
    reference_annual = {
        int(k): float(v)
        for k, v in json.loads(CONTINUITY_JSON.read_text(encoding="utf-8"))["annual_mm"].items()
    }
    print(f"Grid: {len(grid_ids):,} cells ({len(basin_ids):,} in basin); "
          f"exporting {len(years)} years ({years[0]}-{years[-1]})")

    proj = chirps_projection(config)
    params = lattice_params(with_retry(lambda: proj.getInfo(), what="projection"))
    nominal = with_retry(lambda: proj.nominalScale().getInfo(), what="scale")
    region = basin_feature(config).geometry().buffer(
        int(config["grid"]["buffer_cells"]) * float(nominal)
    )

    chirps = ee.ImageCollection(config["sources"]["precipitation_primary"])
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    manifests = []
    for year in years:
        manifests.append(
            export_year(config, chirps, region, proj, params, year,
                        grid_ids, basin_ids, reference_annual)
        )

    print("\nAssertions (expected -> actual):")
    total_rows = sum(m["rows"] for m in manifests)
    ok = report("year files", len(years), len(manifests))
    ok &= report("total rows", len(grid_ids) * 12 * len(years), total_rows)

    # Zeros are validated per month by LOCAL continuity (see export_year).
    # Reported here so the numbers are visible rather than merely asserted.
    diags = [(m["year"], d) for m in manifests
             for d in m["precip_mm"].get("zero_month_diagnostics", [])]
    total_zeros = sum(m["precip_mm"]["zero_rows"] for m in manifests)
    isolated = sum(m["precip_mm"].get("isolated_zero_cells", 0) for m in manifests)
    print(f"  exact-zero rows: {total_zeros:,} across {len(diags)} month(s)")
    flagged = [(y, d) for y, d in diags if d["n_isolated"]]
    if flagged:
        print(f"  isolated zeros (no near-zero neighbour) - artefact candidates:")
        for year, d in flagged[:10]:
            print(f"    {year}-{d['month']:02d}: {d['n_isolated']:>4} isolated of "
                  f"{d['n_zero']:>5} zeros, basin mean {d['mean_mm']:6.2f} mm")
        if len(flagged) > 10:
            print(f"    ... {len(flagged) - 10} more month(s)")
    share = isolated / max(sum(m["rows"] for m in manifests), 1)
    passed = share <= ISOLATED_ZERO_MAX_SHARE
    print(f"  [{'OK      ' if passed else 'MISMATCH'}] isolated-zero share: expected "
          f"<= {ISOLATED_ZERO_MAX_SHARE:.0%} -> actual {share:.4%} ({isolated} rows). "
          "Flagged for T4, neither filled nor dropped.")
    ok &= passed

    if not ok:
        raise AssertionError(
            "T2 assertions failed - see above. Artefacts are left in place for "
            "inspection; per docs/working_protocol.md, stop and report."
        )
    print(f"\nWrote {RAW_DIR.relative_to(ROOT)} - {len(manifests)} year files "
          f"plus one manifest each.")


if __name__ == "__main__":
    main()
