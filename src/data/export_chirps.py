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
    atomic_write,
    fetch_features,
    initialize,
    load_config,
    report,
    with_retry,
)
from src.data.grid import GRID_CSV, basin_feature, cell_indices, chirps_projection, lattice_params, make_cell_id

RAW_DIR = ROOT / "data" / "raw" / "chirps"
PENTADS_PER_MONTH = 6
# Konya basin-mean annual total is 417 mm (ministry). A single month above this
# would be the wettest month ever recorded here by a wide margin; the check exists
# to catch a unit or accumulation error, not to bound weather.
MAX_PLAUSIBLE_MONTHLY_MM = 417.0


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
) -> dict[str, Any]:
    path = RAW_DIR / f"chirps_{year}.csv"
    manifest_path = RAW_DIR / f"chirps_{year}.manifest.json"
    if path.exists() and manifest_path.exists():
        print(f"  {year}: already on disk, skipping "
              f"(atomic write means present implies complete)")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

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
    if hottest > MAX_PLAUSIBLE_MONTHLY_MM:
        problems.append(
            f"monthly maximum {hottest:.1f} mm exceeds the basin's whole-year mean "
            f"({MAX_PLAUSIBLE_MONTHLY_MM:.0f} mm) - suspect a unit or accumulation error"
        )
    # Exact zeros: genuine dry month, or masked pixels arriving as 0?
    #
    # Seasonality does not separate them. CHIRPS overestimates low precipitation
    # amounts - a documented bias over Turkiye - so the climatological dry season
    # rarely reaches exact zero here: the basin minimum in July 1990, the driest
    # month of a dry year, was 2.42 mm across all 2,820 cells. Zeros instead mark
    # exceptional months, whatever the season.
    #
    # What does separate them is the shape of the distribution near zero. Masked
    # pixels produce an isolated spike at exactly 0.0 with a gap above it; a real
    # dry month produces a continuous ramp down to zero. March 1990: 2,009 exact
    # zeros accompanied by 50 cells in (0, 0.5] - continuous, therefore real.
    zero_diag = []
    for m, sub in df.groupby("month"):
        values = sub["precip_chirps_mm"]
        n_zero = int((values == 0).sum())
        if not n_zero:
            continue
        near = int(((values > 0) & (values < 1.0)).sum())
        zero_diag.append({
            "month": int(m), "n_zero": n_zero, "n_in_0_1mm": near,
            "mean_mm": float(values.mean()),
        })
        if near == 0:
            problems.append(
                f"month {m}: {n_zero} cells at exactly 0 mm with no values in "
                "(0, 1) mm. An isolated spike at zero is the signature of masked "
                "pixels, not of a dry month"
            )

    if problems:
        raise AssertionError(f"{year}: " + "; ".join(problems))

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
        },
        "n_obs_per_pixel": PENTADS_PER_MONTH,
        "note": (
            "CHIRPS final products are reprocessed from time to time, so the same "
            "export can return different numbers later. fetched_utc is what makes "
            "this reproducible."
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  {year}: {len(df):,} rows, "
          f"mean {manifest['precip_mm']['mean']:.1f} mm, "
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
    print(f"Grid: {len(grid_ids):,} cells; exporting {len(years)} years "
          f"({years[0]}-{years[-1]})")

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
            export_year(config, chirps, region, proj, params, year, grid_ids)
        )

    print("\nAssertions (expected -> actual):")
    total_rows = sum(m["rows"] for m in manifests)
    ok = report("year files", len(years), len(manifests))
    ok &= report("total rows", len(grid_ids) * 12 * len(years), total_rows)

    # Zeros were validated per year by distribution shape (see export_year).
    # Reported here so the numbers are visible rather than merely asserted.
    diags = [(m["year"], d) for m in manifests
             for d in m["precip_mm"].get("zero_month_diagnostics", [])]
    total_zeros = sum(m["precip_mm"]["zero_rows"] for m in manifests)
    print(f"  exact-zero rows: {total_zeros:,} across "
          f"{len(diags)} month(s) with any zeros")
    for year, d in diags[:12]:
        print(f"    {year}-{d['month']:02d}: {d['n_zero']:>6,} zeros, "
              f"{d['n_in_0_1mm']:>4} cells in (0,1) mm, mean {d['mean_mm']:.2f} mm")
    if len(diags) > 12:
        print(f"    ... {len(diags) - 12} more")
    ok &= report("months with an isolated zero spike (masking signature)", 0,
                 sum(1 for _, d in diags if d["n_in_0_1mm"] == 0))

    if not ok:
        raise AssertionError(
            "T2 assertions failed - see above. Artefacts are left in place for "
            "inspection; per docs/working_protocol.md, stop and report."
        )
    print(f"\nWrote {RAW_DIR.relative_to(ROOT)} - {len(manifests)} year files "
          f"plus one manifest each.")


if __name__ == "__main__":
    main()
