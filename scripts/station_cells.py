"""Locate MGM stations on the analysis grid, for point-based ERA5 validation.

A basin mean cannot be anchored to a station reading. The basin spans the Konya
plateau and the Taurus rim, so its mean temperature is genuinely lower than any
plateau station records - the disagreement would be correct behaviour, and a check
built on it would fire on correct data. Same category error as failure-modes 19.

The comparison that does work is point-based: each station against the ERA5 value
in the grid cell the station falls in. Same location, same period, same quantity.

This script produces the station-to-cell mapping so the published normals can be
matched to the right cells. Station coordinates below are approximate and must be
replaced with MGM's own; a 0.05 deg cell is about 5 km, so a few km of error can
move a station into the neighbouring cell. The output prints the distance from the
station to its cell centre so that risk is visible per station.

Run:  python -m scripts.station_cells
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import ee
import pandas as pd

from src.data.gee_io import ROOT, initialize, load_config, with_retry
from src.data.grid import GRID_CSV, chirps_projection, lattice_params, make_cell_id

OUT_JSON = ROOT / "reports" / "station_cells.json"

# Approximate MGM synoptic stations spanning the basin by elevation and position.
# UNVERIFIED - to be replaced with MGM's published coordinates.
STATIONS = [
    {"name": "Konya",    "wmo": "17244", "lat": 37.9838, "lon": 32.5742, "elev_m_claimed": 1031},
    {"name": "Karaman",  "wmo": "17246", "lat": 37.1930, "lon": 33.2170, "elev_m_claimed": 1023},
    {"name": "Aksaray",  "wmo": "17193", "lat": 38.3705, "lon": 33.9985, "elev_m_claimed": 970},
    {"name": "Nigde",    "wmo": "17250", "lat": 37.9667, "lon": 34.6792, "elev_m_claimed": 1211},
    {"name": "Beysehir", "wmo": "17902", "lat": 37.6772, "lon": 31.7522, "elev_m_claimed": 1141},
]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main() -> None:
    config = load_config()
    initialize(config)
    proj = chirps_projection(config)
    params = lattice_params(with_retry(lambda: proj.getInfo(), what="projection"))
    grid = pd.read_csv(GRID_CSV).set_index("cell_id")

    dem = ee.Image(config["sources"]["dem"])
    points = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([s["lon"], s["lat"]]), {"name": s["name"]})
        for s in STATIONS
    ])
    # Mean SRTM elevation over the 0.05 deg cell, not at the point: the comparison
    # is against a cell-average ERA5 value, so the relevant terrain is the cell's.
    cell_elev = with_retry(
        lambda: dem.reduceRegions(
            collection=points.map(lambda f: f.buffer(2783)),  # ~half a cell
            reducer=ee.Reducer.mean(), scale=90,
        ).getInfo(),
        what="cell elevation",
    )
    elev_by_name = {f["properties"]["name"]: f["properties"].get("mean") for f in cell_elev["features"]}

    rows = []
    for s in STATIONS:
        i = round((s["lon"] - params["origin_lon"]) / params["step_lon"] - 0.5)
        j = round((s["lat"] - params["origin_lat"]) / params["step_lat"] - 0.5)
        cell_id = int(make_cell_id(pd.Series([i]), pd.Series([j])).iloc[0])
        centre_lon = params["origin_lon"] + (i + 0.5) * params["step_lon"]
        centre_lat = params["origin_lat"] + (j + 0.5) * params["step_lat"]
        in_grid = cell_id in grid.index
        row = {
            **s,
            "cell_id": cell_id,
            "cell_lon": round(centre_lon, 5),
            "cell_lat": round(centre_lat, 5),
            "km_to_cell_centre": round(haversine_km(s["lat"], s["lon"], centre_lat, centre_lon), 2),
            "in_exported_grid": in_grid,
            "in_hydrobasins": bool(grid.loc[cell_id, "in_hydrobasins"]) if in_grid else None,
            "crop_frac_2021": round(float(grid.loc[cell_id, "crop_frac_2021"]), 4) if in_grid else None,
            "cell_mean_elev_m": round(elev_by_name.get(s["name"]), 1) if elev_by_name.get(s["name"]) else None,
        }
        rows.append(row)

    print(f"{'station':<10} {'cell_id':>11} {'cell lon/lat':>18} {'km off':>7} "
          f"{'in basin':>9} {'cell elev':>10} {'stn elev':>9}")
    for r in rows:
        print(f"{r['name']:<10} {r['cell_id']:>11} "
              f"{r['cell_lon']:>8.3f},{r['cell_lat']:>7.3f} "
              f"{r['km_to_cell_centre']:>7.2f} "
              f"{str(r['in_hydrobasins']):>9} "
              f"{str(r['cell_mean_elev_m']):>10} {r['elev_m_claimed']:>9}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "note": (
            "Station coordinates are APPROXIMATE and must be replaced with MGM's "
            "published values before the comparison is reported. A 0.05 deg cell is "
            "about 5 km; km_to_cell_centre shows how much room each station has "
            "before it falls into a neighbouring cell."
        ),
        "stations": rows,
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
