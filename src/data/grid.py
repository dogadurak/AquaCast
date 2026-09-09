"""T1 - build the analysis grid.

The analysis grid IS the CHIRPS 0.05 degree lattice (PROJECT_SPEC.md section 2.3).
Precipitation is never resampled, because SPI is computed from it and SPI is the
primary target.

Two design decisions carry most of the weight here:

**Grid constants are derived, not assumed.** Origin and step come from the CHIRPS
collection's own `crs_transform` at runtime. Hardcoding `(lon + 180 - 0.025) / 0.05`
would test the assumption against itself, and a wrong origin differing by a whole
multiple of the step would pass silently - which is exactly the plausible mistake.

**Membership is a column, never a row filter.** Cells are exported for the basin
plus one ring beyond it, and which of them count is decided later by
`aoi.membership_column`. The official basin boundary is about 17% smaller than
HydroBASINS, so it almost certainly lies inside it; keeping every cell means a
boundary revision adds an `in_official` column instead of re-running every export.

Run:  python -m src.data.grid
"""

from __future__ import annotations

import json
import math
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

INTERIM = ROOT / "data" / "interim"
GRID_CSV = INTERIM / "grid_cells.csv"
GRID_GEOJSON = INTERIM / "grid.geojson"

# cell_id = i * ID_STRIDE + j, with i,j the CHIRPS lattice indices. The stride is
# larger than any possible j (global latitude span / 0.05 = 3600), so the mapping
# is injective and reversible.
ID_STRIDE = 100_000


# --------------------------------------------------------------------------
# grid geometry, derived from the source projection
# --------------------------------------------------------------------------
def chirps_projection(config: dict[str, Any]) -> "ee.Projection":
    asset = config["sources"]["precipitation_primary"]
    return ee.Image(ee.ImageCollection(asset).first()).projection()


def lattice_params(proj_info: dict[str, Any]) -> dict[str, float]:
    """Origin and step read from the collection's crs_transform.

    GDAL-style transform: [x_step, x_shear, x_origin, y_shear, y_step, y_origin].
    y_step is negative because rows run north to south.
    """
    t = proj_info["transform"]
    params = {
        "origin_lon": float(t[2]),
        "step_lon": float(t[0]),
        "origin_lat": float(t[5]),
        "step_lat": float(t[4]),
    }
    if params["step_lon"] <= 0 or params["step_lat"] >= 0:
        raise ValueError(f"unexpected CHIRPS transform orientation: {t}")
    return params


def cell_indices(lon: pd.Series, lat: pd.Series, p: dict[str, float]) -> tuple[pd.Series, pd.Series]:
    """Lattice indices of the cells whose CENTRES are at (lon, lat).

    Pixel i spans [origin + i*step, origin + (i+1)*step], so its centre sits at
    origin + (i + 0.5) * step.
    """
    i = (lon - p["origin_lon"]) / p["step_lon"] - 0.5
    j = (lat - p["origin_lat"]) / p["step_lat"] - 0.5
    return i, j


def make_cell_id(i: pd.Series, j: pd.Series) -> pd.Series:
    return (i.round().astype("int64") * ID_STRIDE + j.round().astype("int64")).astype("int64")


# --------------------------------------------------------------------------
# source layers
# --------------------------------------------------------------------------
def basin_feature(config: dict[str, Any]) -> "ee.Feature":
    fc = ee.FeatureCollection(config["aoi"]["boundary_source"])
    hybas_id = config["aoi"]["hybas_id"]
    return ee.Feature(fc.filter(ee.Filter.eq("HYBAS_ID", hybas_id)).first())


def akarcay_lobe_geometry(config: dict[str, Any]) -> "ee.Geometry":
    """The level-6 sub-basin that accounts for the excess area.

    See the akarcay_* keys in config/data.yaml. Kept as a separate membership
    column rather than subtracted from the grid, so that choosing a boundary
    stays a config decision and no export has to be repeated.
    """
    main_bas = config["aoi"]["akarcay_lobe_main_bas"]
    fc = ee.FeatureCollection("WWF/HydroSHEDS/v1/Basins/hybas_6")
    return fc.filter(ee.Filter.eq("MAIN_BAS", main_bas)).geometry()


def cropland_fraction(config: dict[str, Any], proj: "ee.Projection") -> "ee.Image":
    """Fraction of each analysis cell that is cropland or rangeland, 2021 epoch.

    Aggregating 10 m WorldCover straight into a 0.05 degree cell would need about
    555 x 555 = 308,000 input pixels per output pixel, nearly five times
    reduceResolution's 65,536 ceiling - it fails, and no tileScale fixes an
    arithmetic limit. Instead the binary mask is sampled on a regular 100 m grid
    and averaged to the analysis grid: roughly 3,100 samples per cell, an
    unbiased estimator of the same fraction with a standard error under 1%.

    The column is named for its epoch. WorldCover v200 maps 2021 only, while the
    panel spans 1981-2025, and irrigated agriculture in this basin expanded
    substantially over that period.
    """
    classes = config["grid"]["mask"]["landcover_classes"]
    wc = ee.ImageCollection(config["sources"]["landcover"]).first()
    binary = wc.remap(classes, [1] * len(classes), 0).unmask(0)
    subsampled = binary.reproject(crs="EPSG:4326", scale=100)
    return (
        subsampled.reduceResolution(ee.Reducer.mean(), maxPixels=4000)
        .reproject(proj)
        .rename("crop_frac_2021")
    )


def worldcover_gap_count(config: dict[str, Any], geom: "ee.Geometry", proj: "ee.Projection") -> int:
    """Cells where WorldCover has genuinely no data.

    `unmask(0)` turns a real gap into "0% cropland", which would silently exclude
    a cell rather than flagging it. WorldCover covers all land, so this should be
    zero; if it is not, the mask is hiding something.
    """
    wc = ee.ImageCollection(config["sources"]["landcover"]).first()
    # Same 100 m intermediate as cropland_fraction. Reducing 10 m straight to the
    # analysis grid needs 360,001 input pixels per output pixel against a 65,536
    # ceiling - failure-modes entry 13, walked into once while writing this file.
    missing = wc.mask().Not().rename("missing").reproject(crs="EPSG:4326", scale=100)
    gaps = missing.reduceResolution(ee.Reducer.mean(), maxPixels=4000)
    counted = gaps.reproject(proj).gt(0).selfMask().reduceRegion(
        reducer=ee.Reducer.count(), geometry=geom, crs=proj,
        scale=proj.nominalScale(), maxPixels=int(1e9),
    )
    value = with_retry(lambda: counted.getInfo(), what="worldcover gap count")
    return int(sum(v or 0 for v in value.values()))


# --------------------------------------------------------------------------
# sampling
# --------------------------------------------------------------------------
def sample_cells(image: "ee.Image", geom: "ee.Geometry", proj: "ee.Projection", what: str) -> pd.DataFrame:
    fc = image.sample(region=geom, projection=proj, geometries=False, dropNulls=False)
    return fetch_features(fc, what=what)


def build(config: dict[str, Any] | None = None) -> pd.DataFrame:
    config = config if config is not None else load_config()
    project = initialize(config)
    print(f"Earth Engine project: {project}")

    proj = chirps_projection(config)
    proj_info = with_retry(lambda: proj.getInfo(), what="chirps projection")
    params = lattice_params(proj_info)
    nominal_scale = with_retry(lambda: proj.nominalScale().getInfo(), what="nominal scale")
    print("\nCHIRPS lattice, derived from crs_transform (not assumed):")
    print(f"  crs          : {proj_info['crs']}")
    print(f"  transform    : {proj_info['transform']}")
    print(f"  origin lon   : {params['origin_lon']}")
    print(f"  origin lat   : {params['origin_lat']}")
    print(f"  step lon/lat : {params['step_lon']} / {params['step_lat']}")
    print(f"  nominal scale: {nominal_scale:.1f} m")

    basin = basin_feature(config)
    basin_geom = basin.geometry()
    ring_cells = int(config["grid"]["buffer_cells"])
    buffer_m = ring_cells * float(nominal_scale)
    buffered_geom = basin_geom.buffer(buffer_m)

    frac = cropland_fraction(config, proj)
    lonlat = ee.Image.pixelLonLat().reproject(proj)
    image = lonlat.addBands(frac)

    lobe_geom = akarcay_lobe_geometry(config)

    print(f"\nSampling (buffer {ring_cells} cell = {buffer_m:.0f} m) ...")
    buffered_df = sample_cells(image, buffered_geom, proj, "buffered grid")
    basin_df = sample_cells(image, basin_geom, proj, "basin grid")
    lobe_df = sample_cells(image, lobe_geom, proj, "akarcay lobe")

    for df in (buffered_df, basin_df, lobe_df):
        i, j = cell_indices(df["longitude"], df["latitude"], params)
        df["i"], df["j"] = i, j
        df["cell_id"] = make_cell_id(i, j)

    grid = buffered_df.rename(columns={"longitude": "lon", "latitude": "lat"}).copy()
    grid["in_hydrobasins"] = grid["cell_id"].isin(set(basin_df["cell_id"]))
    grid["in_akarcay_lobe"] = grid["cell_id"].isin(set(lobe_df["cell_id"]))
    grid = grid[
        ["cell_id", "lon", "lat", "i", "j", "crop_frac_2021",
         "in_hydrobasins", "in_akarcay_lobe"]
    ]
    grid = grid.sort_values("cell_id").reset_index(drop=True)

    areas = _areas(basin, buffered_geom)
    gap_cells = worldcover_gap_count(config, basin_geom, proj)
    _assert_invariants(grid, basin_df, params, config, gap_cells)
    _write_outputs(grid, params)
    _report_area(config, areas)
    return grid


def _areas(basin: "ee.Feature", buffered: "ee.Geometry") -> dict[str, float]:
    attribute = with_retry(lambda: basin.get("SUB_AREA").getInfo(), what="SUB_AREA")
    geodesic = with_retry(
        lambda: basin.geometry().area(maxError=100).getInfo(), what="basin area"
    )
    buffered_area = with_retry(
        lambda: buffered.area(maxError=100).getInfo(), what="buffered area"
    )
    return {
        "attribute_km2": float(attribute),
        "geodesic_km2": geodesic / 1e6,
        "buffered_km2": buffered_area / 1e6,
    }


# --------------------------------------------------------------------------
# assertions - written before the run, per docs/working_protocol.md
# --------------------------------------------------------------------------
def _assert_invariants(
    grid: pd.DataFrame,
    basin_df: pd.DataFrame,
    params: dict[str, float],
    config: dict[str, Any],
    gap_cells: int,
) -> None:
    print("\nAssertions (expected -> actual):")
    ok = True
    analysis = config["grid"]["analysis"]

    # A. lattice alignment - catches a half-cell offset, which shifts every cell
    #    ~2.8 km without erroring and without looking wrong on a map.
    i_err = float((grid["i"] - grid["i"].round()).abs().max())
    j_err = float((grid["j"] - grid["j"].round()).abs().max())
    ok &= report("max |i - round(i)| < 1e-6", True, i_err < 1e-6)
    ok &= report("max |j - round(j)| < 1e-6", True, j_err < 1e-6)
    print(f"             (i error {i_err:.2e}, j error {j_err:.2e})")

    lon_steps = pd.Series(sorted(grid["lon"].unique())).diff().dropna()
    step_err = float((lon_steps - params["step_lon"]).abs().max())
    ok &= report("unique lon spacing == step_lon", True, step_err < 1e-6)

    # B. cell_id determinism - an id from row order would renumber on every run and
    #    silently misalign every downstream join.
    recomputed = make_cell_id(*cell_indices(grid["lon"], grid["lat"], params))
    ok &= report("cell_id recomputed from lon/lat matches", True, bool((recomputed == grid["cell_id"]).all()))
    ok &= report("cell_id unique", len(grid), int(grid["cell_id"].nunique()))

    # C. WorldCover gaps - unmask(0) would turn a real data gap into "not cropland"
    ok &= report("WorldCover no-data cells in basin", 0, gap_cells)

    # D. membership is a column, nothing was filtered out
    n_basin = int(grid["in_hydrobasins"].sum())
    ok &= report("in_hydrobasins count == basin sample size", len(basin_df), n_basin)
    ok &= report("basin cells are a subset of buffered cells", True, n_basin == len(basin_df))
    ok &= report("buffered set strictly larger than basin set", True, len(grid) > n_basin)
    below = int((grid["crop_frac_2021"] < config["grid"]["mask"]["min_fraction"]).sum())
    ok &= report("low-crop cells retained, not filtered", True, below > 0)

    # E. fraction domain
    lo, hi = float(grid["crop_frac_2021"].min()), float(grid["crop_frac_2021"].max())
    ok &= report("0 <= crop_frac_2021 <= 1", True, lo >= 0.0 and hi <= 1.0)
    print(f"             (min {lo:.4f}, max {hi:.4f})")

    # F. counts against the independent reduceRegion measurement recorded in config.
    #    Reported rather than asserted equal: sample() uses pixel-centre containment
    #    while reduceRegion weights partial pixels, so a small difference is a
    #    definition difference, not a bug. A large one is not.
    expected_basin = int(analysis["cells_in_basin"])
    drift = abs(n_basin - expected_basin) / expected_basin
    print(f"  [{'OK      ' if drift <= 0.02 else 'REVIEW  '}] "
          f"basin cell count vs config: expected {expected_basin} -> actual {n_basin} "
          f"({drift:+.2%})")
    ok &= drift <= 0.02

    masked = int(((grid["crop_frac_2021"] >= config["grid"]["mask"]["min_fraction"]) & grid["in_hydrobasins"]).sum())
    expected_masked = int(analysis["cells_after_mask"])
    mdrift = abs(masked - expected_masked) / expected_masked
    print(f"  [{'OK      ' if mdrift <= 0.02 else 'REVIEW  '}] "
          f"masked cell count vs config: expected {expected_masked} -> actual {masked} "
          f"({mdrift:+.2%})")
    ok &= mdrift <= 0.02

    # G. Akarcay lobe - an independent-ish cross-check between the vector areas and
    #    the raster cell counts. They are computed by completely different means, so
    #    agreement is evidence; disagreement means one of the two is wrong.
    n_lobe = int((grid["in_hydrobasins"] & grid["in_akarcay_lobe"]).sum())
    outside = int((grid["in_akarcay_lobe"] & ~grid["in_hydrobasins"]).sum())
    ok &= report("lobe cells outside the basin polygon", 0, outside)
    ok &= report("lobe is non-empty", True, n_lobe > 0)

    aoi = config["aoi"]
    hydro_area = float(aoi["area_km2_hydrobasins"])
    lobe_area = float(aoi["akarcay_lobe_area_km2"])
    expected_ratio = (hydro_area - lobe_area) / hydro_area
    actual_ratio = (n_basin - n_lobe) / n_basin
    ratio_err = abs(actual_ratio - expected_ratio)
    print(f"  [{'OK      ' if ratio_err <= 0.02 else 'REVIEW  '}] "
          f"area ratio vs cell ratio: expected {expected_ratio:.4f} -> actual "
          f"{actual_ratio:.4f} (|diff| {ratio_err:.4f})")
    ok &= ratio_err <= 0.02
    print(f"             ({n_lobe} lobe cells of {n_basin} in basin)")

    if not ok:
        raise AssertionError(
            "T1 invariants failed - no artefact written. Per docs/working_protocol.md "
            "the task is HATA; do not adjust the expectation to match the output."
        )
    print("\nAll T1 invariants hold.")


# --------------------------------------------------------------------------
# outputs
# --------------------------------------------------------------------------
def _write_outputs(grid: pd.DataFrame, params: dict[str, float]) -> None:
    atomic_write(grid, GRID_CSV)

    half_lon, half_lat = params["step_lon"] / 2.0, abs(params["step_lat"]) / 2.0
    features = []
    for row in grid.itertuples(index=False):
        w, e = row.lon - half_lon, row.lon + half_lon
        s, n = row.lat - half_lat, row.lat + half_lat
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
                },
                "properties": {
                    "cell_id": int(row.cell_id),
                    "lon": float(row.lon),
                    "lat": float(row.lat),
                    "crop_frac_2021": round(float(row.crop_frac_2021), 6),
                    "in_hydrobasins": bool(row.in_hydrobasins),
                    "in_akarcay_lobe": bool(row.in_akarcay_lobe),
                },
            }
        )
    payload = {"type": "FeatureCollection", "features": features}
    tmp = GRID_GEOJSON.with_suffix(".geojson.partial")
    GRID_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(GRID_GEOJSON)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    print(f"\nWrote {GRID_CSV.relative_to(ROOT)}  ({len(grid)} cells)")
    print(f"Wrote {GRID_GEOJSON.relative_to(ROOT)} ({GRID_GEOJSON.stat().st_size / 1e6:.1f} MB)")


def _report_area(config: dict[str, Any], areas: dict[str, float]) -> None:
    """Compare against PUBLISHED areas, not against our own measurement.

    Asserting the polygon is within 1% of an area measured from that same polygon
    is a tautology - it cannot fail under any state of the world, including a
    completely wrong polygon. See failure-modes entry 10.
    """
    aoi = config["aoi"]
    official_text = float(aoi["official_area_km2_text"])
    official_table = float(aoi["official_area_km2_table"])
    hydro = areas["geodesic_km2"]
    print("\nBasin area against independent published figures:")
    print(f"  HydroBASINS attribute SUB_AREA : {areas['attribute_km2']:>10.1f} km2")
    print(f"  HydroBASINS geodesic recompute : {hydro:>10.1f} km2")
    print(f"  Official (SYGM, prose)         : {official_text:>10.1f} km2  "
          f"-> HydroBASINS is {(hydro / official_text - 1):+.1%}")
    print(f"  Official (SYGM, table)         : {official_table:>10.1f} km2  "
          f"-> HydroBASINS is {(hydro / official_table - 1):+.1%}")
    lobe = float(aoi["akarcay_lobe_area_km2"])
    print(f"  Buffered export region         : {areas['buffered_km2']:>10.1f} km2")
    print(f"  Less the Akarcay lobe          : {hydro - lobe:>10.1f} km2  "
          f"-> {(hydro - lobe) / official_text - 1:+.2%} prose, "
          f"{(hydro - lobe) / official_table - 1:+.2%} table")
    print("  Membership is a column, so a boundary revision is a filter, not a re-export.")


if __name__ == "__main__":
    build()
