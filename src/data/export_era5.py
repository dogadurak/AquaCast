"""T3 - export ERA5-Land monthly fields for the analysis grid, 1981-2025.

ERA5-Land is 0.1 degrees (~9 km); the analysis grid is CHIRPS's 0.05 degree lattice.
That gap is where this task's dangerous mistake lives, and it is the reason for the
distinct-value check below.

Run:  python -m src.data.export_era5
      python -m src.data.export_era5 --years 1981-1990
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
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
from src.data.grid import (
    GRID_CSV,
    basin_feature,
    cell_indices,
    chirps_projection,
    lattice_params,
    make_cell_id,
)

RAW_DIR = ROOT / "data" / "raw" / "era5"
CHIRPS_DIR = ROOT / "data" / "raw" / "chirps"

# ERA5-Land MONTHLY_AGGR holds exactly one image per month.
IMAGES_PER_MONTH = 1

# Resampling from 0.1 to 0.05 degrees quadruples the cell count. Under bilinear
# almost every analysis cell gets its own interpolated value; under Earth Engine's
# DEFAULT nearest neighbour each native pixel is copied into roughly four cells, so
# the number of distinct values collapses to about a quarter. Nothing errors, the
# field looks smooth and plausible, and every claim this project makes about
# resolution honesty would be quietly false.
#
# The basin plus ring covers ~68,772 km2; a 0.1 degree cell at 38N is ~97 km2, so
# nearest would give roughly 700 distinct values across 2,820 cells - a ratio near
# 0.25. Bilinear gives a ratio near 1.0.
MIN_DISTINCT_RATIO = 0.90

# Absurd guards, not reference-anchored checks - declared as weak on purpose.
# No published basin-mean temperature or PET figure has been obtained yet; the
# point-based station comparison (scripts/station_cells.py) is what will replace
# these. See failure-modes 15.
T2M_PLAUSIBLE_C = (-25.0, 40.0)
BASIN_MEAN_T2M_PLAUSIBLE_C = (8.0, 14.0)

# ERA5 vs CHIRPS on identical cells and months. They are different products, so
# they must not match - only agree in magnitude and covary between years. This is
# the anchor that catches a unit or accumulation misreading (either would be off by
# a factor of ~30), and it is also a reportable finding.
MAX_PRECIP_DIVERGENCE = 0.35
MIN_PRECIP_CORRELATION = 0.70


def era5_bands(config: dict[str, Any]) -> dict[str, str]:
    return dict(config["era5_bands"])


def month_image(config: dict[str, Any], era5: "ee.ImageCollection", start: "ee.Date"):
    """Monthly ERA5-Land fields on the analysis grid, resampled BILINEARLY.

    `resample("bilinear")` must be set on the source image; Earth Engine's implicit
    reprojection is nearest neighbour otherwise.
    """
    bands = era5_bands(config)
    window = era5.filterDate(start, start.advance(1, "month"))
    src = window.first().resample("bilinear")

    kelvin = src.select(bands["t2m_c"]).subtract(273.15).rename("t2m_c")
    tmin = src.select("temperature_2m_min").subtract(273.15).rename("t2m_min_c")
    tmax = src.select("temperature_2m_max").subtract(273.15).rename("t2m_max_c")
    precip = src.select(bands["precip_era5_mm"]).multiply(1000).rename("precip_era5_mm")

    # ERA5 fluxes are positive downward, so evaporation is negative. The raw value
    # is carried alongside the converted one so the sign convention is testable
    # rather than assumed: pet_era5_mm must come out positive.
    pet_raw = src.select(bands["pet_mm"]).rename("pet_era5_raw_m")
    pet = pet_raw.multiply(-1000).rename("pet_era5_mm")

    swvl = [
        src.select(bands[f"swvl{k}"]).rename(f"swvl{k}") for k in range(1, 5)
    ]
    n_obs = window.select(bands["t2m_c"]).count().rename("n_obs")

    image = kelvin.addBands([tmin, tmax, precip, pet_raw, pet, *swvl, n_obs])
    return image, window.size()


def native_cell_image(config: dict[str, Any], era5: "ee.ImageCollection") -> "ee.Image":
    """Coordinates of the ERA5 native pixel each analysis cell draws from.

    Sampled with the default nearest neighbour on purpose: the question here is
    which native pixel a cell sits in, not what an interpolated value would be.
    Phase 3 needs this - four neighbouring analysis cells sharing one ERA5 pixel are
    not four independent samples, and the effective sample size for ERA5-derived
    features is roughly a quarter of the row count.
    """
    proj = ee.Image(era5.first()).projection()
    return (
        ee.Image.pixelLonLat()
        .reproject(proj)
        .rename(["era5_native_lon", "era5_native_lat"])
    )


def fetch_month(
    config: dict[str, Any],
    era5: "ee.ImageCollection",
    native: "ee.Image",
    region: "ee.Geometry",
    proj: "ee.Projection",
    params: dict[str, float],
    year: int,
    month: int,
    expected_cells: int,
) -> pd.DataFrame:
    start = ee.Date(f"{year}-{month:02d}-01")
    image, n_images = month_image(config, era5, start)

    sampled = (
        ee.Image.pixelLonLat()
        .reproject(proj)
        .addBands(image)
        .addBands(native)
        .addBands(ee.Image.constant(n_images).rename("n_images").toInt())
    )
    fc = sampled.sample(region=region, projection=proj, geometries=False, dropNulls=False)
    df = fetch_features(
        fc, what=f"era5 {year}-{month:02d}", expected_rows=expected_cells,
        max_retries=int(config["export"]["max_retries"]),
        backoff_base=float(config["export"]["backoff_base_seconds"]),
    )

    bad = df.loc[df["n_images"] != IMAGES_PER_MONTH, "n_images"]
    if len(bad):
        raise AssertionError(
            f"{year}-{month:02d}: expected {IMAGES_PER_MONTH} monthly image, found "
            f"{sorted(bad.unique())}"
        )

    i, j = cell_indices(df["longitude"], df["latitude"], params)
    df["cell_id"] = make_cell_id(i, j)
    df["date"] = f"{year}-{month:02d}-01"
    df["month"] = month
    return df


def export_year(
    config: dict[str, Any],
    era5: "ee.ImageCollection",
    native: "ee.Image",
    region: "ee.Geometry",
    proj: "ee.Projection",
    params: dict[str, float],
    year: int,
    grid_ids: set[int],
    basin_ids: set[int],
) -> dict[str, Any]:
    path = RAW_DIR / f"era5_{year}.csv"
    manifest_path = RAW_DIR / f"era5_{year}.manifest.json"
    if path.exists() and manifest_path.exists():
        print(f"  {year}: already on disk, skipping")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    frames = [
        fetch_month(config, era5, native, region, proj, params, year, m, len(grid_ids))
        for m in range(1, 13)
    ]
    df = pd.concat(frames, ignore_index=True)

    problems: list[str] = []
    if len(df) != len(grid_ids) * 12:
        problems.append(f"rows: expected {len(grid_ids) * 12}, got {len(df)}")
    if set(df["cell_id"]) != grid_ids:
        problems.append("cell_id set does not match the analysis grid")

    # --- land/sea mask: ERA5-Land is a land product -----------------------
    # Tuz Golu, Beysehir and Aksehir are large enough to be masked. Count them,
    # name them, and neither fill nor drop them. T4 has to know before it joins.
    null_by_month = df.groupby("month")["t2m_c"].apply(lambda s: frozenset(
        df.loc[s.index[s.isna()], "cell_id"]
    ))
    null_sets = set(null_by_month.values)
    if len(null_sets) > 1:
        problems.append(
            f"the set of ERA5 no-data cells varies between months ({len(null_sets)} "
            "distinct sets); ERA5-Land's land mask is static, so it should not"
        )
    water_cells = sorted(next(iter(null_sets))) if null_sets else []
    land = df[df["t2m_c"].notna()]

    # --- bilinear, not nearest --------------------------------------------
    ratios = []
    for m, sub in land.groupby("month"):
        ratios.append(sub["t2m_c"].nunique() / len(sub))
    min_ratio = min(ratios) if ratios else 0.0
    if min_ratio < MIN_DISTINCT_RATIO:
        problems.append(
            f"distinct-value ratio {min_ratio:.3f} is below {MIN_DISTINCT_RATIO}. "
            "Around 0.25 means Earth Engine resampled with nearest neighbour, so "
            "every ERA5 pixel was copied into ~4 analysis cells and the 0.05 degree "
            "grid carries no more information than 0.1 degrees"
        )

    # --- units and signs ---------------------------------------------------
    lo, hi = T2M_PLAUSIBLE_C
    if not (land["t2m_c"].between(lo, hi).all()):
        problems.append(
            f"t2m_c outside [{lo}, {hi}] degC (min {land['t2m_c'].min():.1f}, "
            f"max {land['t2m_c'].max():.1f}) - suspect a Kelvin conversion"
        )
    neg_pet = int((land["pet_era5_mm"] <= 0).sum())
    if neg_pet:
        problems.append(
            f"{neg_pet} rows have pet_era5_mm <= 0. ERA5 fluxes are positive "
            "downward so potential evaporation should be negative and the sign flip "
            "should make it positive; this says the convention is the other way"
        )
    for k in range(1, 5):
        col = f"swvl{k}"
        if not land[col].between(0.0, 1.0).all():
            problems.append(f"{col} outside [0, 1] m3/m3")
    if (land["precip_era5_mm"] < 0).any():
        problems.append("negative precip_era5_mm")

    basin_land = land[land["cell_id"].isin(basin_ids)]
    basin_t2m = float(basin_land.groupby("cell_id")["t2m_c"].mean().mean())
    tlo, thi = BASIN_MEAN_T2M_PLAUSIBLE_C
    if not (tlo <= basin_t2m <= thi):
        problems.append(
            f"basin-mean annual t2m {basin_t2m:.2f} degC outside the [{tlo}, {thi}] "
            "guard (weak check - see module docstring)"
        )

    # --- the anchor: ERA5 against CHIRPS on identical cells and months -----
    # Two independent products measuring the same quantity over the same cells.
    # They must not agree exactly - they must agree in magnitude. A unit error
    # (m vs mm) or an accumulation misreading (daily mean vs monthly sum) is a
    # factor of ~30 and cannot survive this.
    chirps_path = CHIRPS_DIR / f"chirps_{year}.csv"
    chirps_mean = None
    if chirps_path.exists():
        ch = pd.read_csv(chirps_path, usecols=["cell_id", "precip_chirps_mm"])
        ch = ch[ch["cell_id"].isin(basin_ids)]
        chirps_mean = float(ch.groupby("cell_id")["precip_chirps_mm"].sum().mean())
        era5_mean = float(basin_land.groupby("cell_id")["precip_era5_mm"].sum().mean())
        divergence = abs(era5_mean / chirps_mean - 1)
        if divergence > MAX_PRECIP_DIVERGENCE:
            problems.append(
                f"ERA5 basin-mean annual precipitation {era5_mean:.1f} mm differs "
                f"from CHIRPS {chirps_mean:.1f} mm by {divergence:.1%}, over the "
                f"{MAX_PRECIP_DIVERGENCE:.0%} tolerance. Two products should differ, "
                "not disagree by this much - suspect a unit or accumulation error"
            )
    else:
        print(f"    (no CHIRPS file for {year} yet - cross-check deferred)")

    if problems:
        raise AssertionError(f"{year}: " + "; ".join(problems))

    keep = [
        "cell_id", "date", "month", "t2m_c", "t2m_min_c", "t2m_max_c",
        "precip_era5_mm", "pet_era5_mm", "pet_era5_raw_m",
        "swvl1", "swvl2", "swvl3", "swvl4",
        "era5_native_lon", "era5_native_lat", "n_images",
    ]
    out = df[keep].copy()
    out["era5_native_cell_id"] = (
        (out["era5_native_lon"] * 1000).round().astype("int64") * 1_000_000
        + (out["era5_native_lat"] * 1000).round().astype("int64")
    )
    atomic_write(out, path)

    manifest = {
        "year": year,
        "collection": config["sources"]["reanalysis"],
        "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": len(out),
        "cells": len(grid_ids),
        "resampling": "bilinear",
        "min_distinct_value_ratio": min_ratio,
        "nearest_neighbour_would_give": "~0.25",
        "era5_native_cells_covering_grid": int(out["era5_native_cell_id"].nunique()),
        "water_masked_cells": len(water_cells),
        "water_masked_cell_ids": water_cells,
        "basin_mean_annual_t2m_c": basin_t2m,
        "basin_mean_annual_precip_mm": float(
            basin_land.groupby("cell_id")["precip_era5_mm"].sum().mean()
        ),
        "basin_mean_annual_pet_mm": float(
            basin_land.groupby("cell_id")["pet_era5_mm"].sum().mean()
        ),
        "chirps_basin_mean_annual_mm": chirps_mean,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  {year}: {len(out):,} rows, T {basin_t2m:.2f} C, "
          f"P {manifest['basin_mean_annual_precip_mm']:.0f} mm, "
          f"PET {manifest['basin_mean_annual_pet_mm']:.0f} mm, "
          f"distinct ratio {min_ratio:.3f}, water cells {len(water_cells)}")
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
    parser.add_argument("--years", default=None)
    args = parser.parse_args()

    config = load_config()
    initialize(config)
    years = parse_years(args.years, config)

    grid = pd.read_csv(GRID_CSV)
    grid_ids = set(grid["cell_id"].astype("int64"))
    basin_ids = set(grid.loc[grid["in_hydrobasins"], "cell_id"].astype("int64"))

    proj = chirps_projection(config)
    params = lattice_params(with_retry(lambda: proj.getInfo(), what="projection"))
    nominal = with_retry(lambda: proj.nominalScale().getInfo(), what="scale")
    region = basin_feature(config).geometry().buffer(
        int(config["grid"]["buffer_cells"]) * float(nominal)
    )
    era5 = ee.ImageCollection(config["sources"]["reanalysis"])
    native = native_cell_image(config, era5)

    print(f"Grid: {len(grid_ids):,} cells ({len(basin_ids):,} in basin); "
          f"exporting {len(years)} years ({years[0]}-{years[-1]})")
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    manifests = [
        export_year(config, era5, native, region, proj, params, y, grid_ids, basin_ids)
        for y in years
    ]

    print("\nAssertions (expected -> actual):")
    ok = report("year files", len(years), len(manifests))
    ok &= report("total rows", len(grid_ids) * 12 * len(years),
                 sum(m["rows"] for m in manifests))
    worst = min(m["min_distinct_value_ratio"] for m in manifests)
    print(f"  [{'OK      ' if worst >= MIN_DISTINCT_RATIO else 'MISMATCH'}] "
          f"distinct-value ratio (bilinear vs nearest): expected >= "
          f"{MIN_DISTINCT_RATIO} -> actual {worst:.3f}  (nearest would give ~0.25)")
    ok &= worst >= MIN_DISTINCT_RATIO

    water = {tuple(m["water_masked_cell_ids"]) for m in manifests}
    ok &= report("water-masked cell set identical across years", 1, len(water))
    n_water = len(next(iter(water))) if water else 0
    print(f"  ERA5-Land no-data cells (open water): {n_water} of {len(grid_ids):,}. "
          "Neither filled nor dropped - recorded for T4.")
    # Interannual covariation - one year cannot show it, so it is checked here.
    paired = [(m["chirps_basin_mean_annual_mm"], m["basin_mean_annual_precip_mm"])
              for m in manifests if m.get("chirps_basin_mean_annual_mm")]
    if len(paired) >= 5:
        a = pd.Series([x for x, _ in paired])
        b = pd.Series([y for _, y in paired])
        r = float(a.corr(b))
        print(f"  [{'OK      ' if r >= MIN_PRECIP_CORRELATION else 'MISMATCH'}] "
              f"ERA5 vs CHIRPS annual correlation over {len(paired)} years: "
              f"expected >= {MIN_PRECIP_CORRELATION} -> actual {r:.3f}")
        ok &= r >= MIN_PRECIP_CORRELATION
        print(f"     mean ERA5 {b.mean():.0f} mm vs CHIRPS {a.mean():.0f} mm "
              f"({b.mean() / a.mean() - 1:+.1%})")
    else:
        print(f"  [SKIP    ] ERA5 vs CHIRPS correlation: only {len(paired)} paired "
              "year(s); needs 5. Re-run once the CHIRPS export finishes.")

    native_cells = max(m["era5_native_cells_covering_grid"] for m in manifests)
    print(f"  ERA5 native pixels covering the grid: {native_cells} for "
          f"{len(grid_ids):,} analysis cells "
          f"(~{len(grid_ids) / max(native_cells, 1):.1f} cells per native pixel)")

    if not ok:
        raise AssertionError("T3 assertions failed - see above.")


if __name__ == "__main__":
    main()
