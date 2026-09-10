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
    provenance,
    schema_fingerprint,
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

# Columns this exporter writes. Recorded in every manifest so resume can tell
# "already fetched" from "fetched under a different schema". Adding a band without
# bumping this would leave earlier years silently skipped and the panel mixed.
EXPECTED_SCHEMA = [
    "cell_id", "date", "month",
    # monthly aggregates - correct as MONTHLY_AGGR provides them
    "t2m_c", "precip_era5_mm", "pet_era5_mm", "pet_era5_raw_mm",
    "swvl1", "swvl2", "swvl3", "swvl4",
    # FAO-56 inputs derived from DAILY_AGGR - see DAILY_SOURCE below
    "t2m_max_c", "t2m_min_c", "dewpoint_c", "wind10m_ms", "wind2m_ms",
    "srad_down_mj_m2_day", "net_solar_mj_m2_day", "net_thermal_mj_m2_day",
    "surface_pressure_kpa",
    "era5_native_lon", "era5_native_lat", "n_images", "era5_native_cell_id",
]

# MONTHLY_AGGR's temperature_2m_max/min are the month's single HOURLY extremes, not
# the mean of daily extremes that FAO-56 requires. Measured at Konya for 1990-07:
# MONTHLY_AGGR gives 34.08 / 12.59 C, which matches the hourly extremes exactly,
# while the mean of daily extremes is 30.34 / 16.97 C. Using the monthly bands
# would inflate (Tmax - Tmin) by 61% and Hargreaves ET0 by about 27%.
#
# DAILY_AGGR averaged over the month reproduces 30.34 / 16.97 exactly, at 31 images
# per month against HOURLY's 744.
DAILY_SOURCE = "ECMWF/ERA5_LAND/DAILY_AGGR"

# ERA5 wind is at 10 m; FAO-56 wants 2 m. u2 = u10 * 4.87 / ln(67.8*10 - 5.42).
WIND_10M_TO_2M = 0.748

# There is no wind-speed band, only u and v components, and taking hypot() of their
# MONTHLY means yields the magnitude of the vector mean - opposing winds cancel and
# the speed comes out low, which lowers ET0. Measured at Konya for 1990-07 against
# the true scalar mean from hourly data: monthly u,v hypot -14.9%, daily hypot
# -8.6%. Daily is used; the residual -8.6% is recorded as a limitation rather than
# spending 24x the compute on hourly for a second-order term.
WIND_SCALAR_BIAS_NOTE = "daily hypot underestimates the scalar mean by ~8.6%"

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
# Potential evaporation is positive almost everywhere almost always, but not
# strictly: see the sign-convention check in export_year.
# PROVISIONAL - both are placeholders, not measurements.
# Observed so far, from ONE year (1983): 0.065% non-positive, minimum -0.53 mm.
# These bounds are 30x and 10x looser than that, which is the same mistake as the
# 1000 mm ceiling in T2: loose enough to pass any realistic error. They are set
# wide on purpose because one year is not the distribution - a colder year could
# bring December and February in too. TIGHTEN THEM at the close of T3, from the
# 45-year distribution recorded in the manifests (pet_nonpositive_rows,
# pet_min_mm), to roughly 3x the observed maximum.
PET_POSITIVE_MIN_SHARE = 0.98
PET_MIN_PLAUSIBLE_MM = -5.0

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

    precip = src.select(bands["precip_era5_mm"]).multiply(1000).rename("precip_era5_mm")

    # FAO-56 inputs from DAILY_AGGR, averaged over the month. See DAILY_SOURCE.
    daily = (
        ee.ImageCollection(DAILY_SOURCE)
        .filterDate(start, start.advance(1, "month"))
    )
    wind_daily = daily.map(
        lambda i: i.select("u_component_of_wind_10m")
        .hypot(i.select("v_component_of_wind_10m"))
        .rename("wind10m_ms")
    )
    dmean = daily.mean().resample("bilinear")
    # The WHOLE temperature family comes from DAILY_AGGR, deliberately.
    #
    # MONTHLY_AGGR and DAILY_AGGR are separate products and their monthly-mean
    # temperature is NOT the same number: measured over the basin for 1990-01 and
    # 1990-07, they differ by -0.40 / -0.23 C on average but by up to 4.4 / 5.9 C at
    # individual cells. Mixing MONTHLY's t2m with DAILY's min, max and dewpoint
    # therefore broke physical invariants that cannot fail on consistent data -
    # 255 rows with t2m outside [tmin, tmax] and 107 with dewpoint above air
    # temperature. Sourced consistently from DAILY, both invariants hold with
    # comfortable margins.
    kelvin = dmean.select("temperature_2m").subtract(273.15).rename("t2m_c")
    tmax = dmean.select("temperature_2m_max").subtract(273.15).rename("t2m_max_c")
    tmin = dmean.select("temperature_2m_min").subtract(273.15).rename("t2m_min_c")
    dew = dmean.select("dewpoint_temperature_2m").subtract(273.15).rename("dewpoint_c")
    w10 = wind_daily.mean().resample("bilinear").rename("wind10m_ms")
    w2 = w10.multiply(WIND_10M_TO_2M).rename("wind2m_ms")
    # Radiation _sum bands accumulate J/m2 over each day; the monthly mean of those
    # is J/m2/day, and FAO-56 works in MJ/m2/day.
    srad = dmean.select("surface_solar_radiation_downwards_sum").divide(1e6).rename("srad_down_mj_m2_day")
    nsol = dmean.select("surface_net_solar_radiation_sum").divide(1e6).rename("net_solar_mj_m2_day")
    nthe = dmean.select("surface_net_thermal_radiation_sum").divide(1e6).rename("net_thermal_mj_m2_day")
    pres = dmean.select("surface_pressure").divide(1000).rename("surface_pressure_kpa")

    # ERA5 fluxes are positive downward, so evaporation is negative. The raw value
    # is carried alongside the converted one so the sign convention is testable
    # rather than assumed: pet_era5_mm must come out positive.
    pet_raw = src.select(bands["pet_mm"]).multiply(1000).rename("pet_era5_raw_mm")
    pet = pet_raw.multiply(-1).rename("pet_era5_mm")

    swvl = [
        src.select(bands[f"swvl{k}"]).rename(f"swvl{k}") for k in range(1, 5)
    ]
    n_obs = window.select(bands["t2m_c"]).count().rename("n_obs")

    image = kelvin.addBands([
        precip, pet_raw, pet, *swvl,
        tmax, tmin, dew, w10, w2, srad, nsol, nthe, pres, n_obs,
    ])
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
        cached = json.loads(manifest_path.read_text(encoding="utf-8"))
        if cached.get("schema_fingerprint") == schema_fingerprint(EXPECTED_SCHEMA):
            print(f"  {year}: already on disk, skipping")
            return cached
        print(f"  {year}: on disk but written under a different schema "
              f"({cached.get('schema_fingerprint')} != "
              f"{schema_fingerprint(EXPECTED_SCHEMA)}) - refetching")
        path.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)

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
    # Sign convention, tested by proportion rather than by every row.
    #
    # ERA5 fluxes are positive downward, so potential evaporation arrives negative
    # and is flipped. Requiring pet > 0 everywhere was too strict: over frozen ground
    # in midwinter the flux genuinely reverses. Measured for 1983, all 22
    # non-positive rows fall in January, at cells averaging 1,481 m and -6.3 degC,
    # with values between -0.53 and -0.0 mm/month - deposition, not an error.
    #
    # If the convention were the other way round, essentially EVERY row would be
    # negative, not 0.065% of them. So the test is the share, plus a bound on how
    # negative a real frost value can plausibly get.
    nonpositive = int((land["pet_era5_mm"] <= 0).sum())
    positive_share = float((land["pet_era5_mm"] > 0).mean())
    worst = float(land["pet_era5_mm"].min())
    if positive_share < PET_POSITIVE_MIN_SHARE:
        problems.append(
            f"only {positive_share:.1%} of pet_era5_mm rows are positive, below "
            f"{PET_POSITIVE_MIN_SHARE:.0%}. A handful of negatives is midwinter "
            "deposition; this many means the sign convention is inverted"
        )
    if worst < PET_MIN_PLAUSIBLE_MM:
        problems.append(
            f"pet_era5_mm reaches {worst:.2f} mm, below {PET_MIN_PLAUSIBLE_MM} mm. "
            "Frost deposition is a fraction of a millimetre; this is something else"
        )
    for k in range(1, 5):
        col = f"swvl{k}"
        if not land[col].between(0.0, 1.0).all():
            problems.append(f"{col} outside [0, 1] m3/m3")

    # Physical invariants, not range guards. These hold everywhere on Earth in every
    # month, so they cannot fire on correct data - but they break immediately if two
    # bands are swapped, if a unit conversion is applied to the wrong one, or if the
    # daily and monthly sources are mixed up. That is a stronger test than any
    # plausibility band, and it needs no external reference.
    bad_order = int((~(
        (land["t2m_min_c"] <= land["t2m_c"] + 1e-6)
        & (land["t2m_c"] <= land["t2m_max_c"] + 1e-6)
    )).sum())
    if bad_order:
        problems.append(
            f"{bad_order} rows violate t2m_min <= t2m <= t2m_max - the temperature "
            "bands are swapped or drawn from mismatched sources"
        )
    bad_dew = int((land["dewpoint_c"] > land["t2m_c"] + 1e-6).sum())
    if bad_dew:
        problems.append(
            f"{bad_dew} rows have dewpoint above air temperature, which is "
            "physically impossible - suspect a band or unit mix-up"
        )
    if not land["wind10m_ms"].gt(0).all():
        problems.append("wind10m_ms is not strictly positive")
    if not land["srad_down_mj_m2_day"].between(0.5, 45.0).all():
        problems.append(
            f"srad_down_mj_m2_day outside [0.5, 45] MJ/m2/day (min "
            f"{land['srad_down_mj_m2_day'].min():.2f}, max "
            f"{land['srad_down_mj_m2_day'].max():.2f}) - suspect a J->MJ error"
        )
    if not land["surface_pressure_kpa"].between(60.0, 110.0).all():
        problems.append("surface_pressure_kpa outside [60, 110] kPa")
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

    out = df[[c for c in EXPECTED_SCHEMA if c != "era5_native_cell_id"]].copy()
    out["era5_native_cell_id"] = (
        (out["era5_native_lon"] * 1000).round().astype("int64") * 1_000_000
        + (out["era5_native_lat"] * 1000).round().astype("int64")
    )
    if out.columns.tolist() != EXPECTED_SCHEMA:
        raise AssertionError(
            f"{year}: columns {out.columns.tolist()} do not match EXPECTED_SCHEMA "
            f"{EXPECTED_SCHEMA} - update the constant deliberately, do not drift"
        )
    atomic_write(out, path)

    manifest = {
        "year": year,
        "collection": config["sources"]["reanalysis"],
        "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": len(out),
        "cells": len(grid_ids),
        "t2m_source": DAILY_SOURCE,
        "t2m_source_note": (
            "MONTHLY_AGGR and DAILY_AGGR disagree on monthly mean temperature by up "
            "to ~6 C at individual cells; the temperature family is taken wholly "
            "from DAILY_AGGR so the physical invariants hold."
        ),
        "wind_note": WIND_SCALAR_BIAS_NOTE,
        "pet_nonpositive_rows": nonpositive,
        "pet_min_mm": worst,
        "provenance": provenance(),
        "schema_fingerprint": schema_fingerprint(EXPECTED_SCHEMA),
        "schema_columns": EXPECTED_SCHEMA,
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
