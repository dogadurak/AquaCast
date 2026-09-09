#!/usr/bin/env python3
"""
AquaCast - Phase 0 data access verification.

Run this BEFORE writing any pipeline code. It answers one question:
"Can I actually get every dataset this project depends on, for my AOI,
for the full training period?"

If a check fails, the project design must change - not the check.

Usage
-----
    python scripts/check_data_access.py                 # GEE + HTTP checks
    python scripts/check_data_access.py --with-cds      # also test a real CDS request (slow, queued)
    python scripts/check_data_access.py --json report.json

Prerequisites
-------------
    pip install earthengine-api requests
    earthengine authenticate          # one time
    # optional, for --with-cds:
    pip install "cdsapi>=0.7.7"       # plus ~/.cdsapirc with your CDS personal access token
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# CONFIG - Konya Closed Basin (bounding box; the real basin polygon is
# clipped later in the pipeline, this is only for availability testing)
# --------------------------------------------------------------------------
AOI_BBOX = [31.4, 36.7, 35.2, 39.4]  # [west, south, east, north] in EPSG:4326
TRAIN_START = "2001-01-01"
TRAIN_END = "2025-12-31"

# Candidate Earth Engine asset IDs per variable. The script tries them in
# order and reports the first that resolves, plus its real date range.
# Multiple candidates are listed on purpose: collection IDs get versioned
# and renamed, so the script discovers what exists today rather than
# trusting a hardcoded name.
GEE_CANDIDATES: dict[str, dict] = {
    "precipitation": {
        "role": "CORE - SPI/SPEI input",
        "ids": [
            "UCSB-CHC/CHIRPS/V3/PENTAD",
            "UCSB-CHC/CHIRPS/V3/DAILY_RNL",
            "UCSB-CHG/CHIRPS/PENTAD",
            "UCSB-CHG/CHIRPS/DAILY",
        ],
        "type": "ImageCollection",
    },
    "meteo_reanalysis": {
        "role": "CORE - precipitation, temperature, soil moisture, PET",
        "ids": [
            "ECMWF/ERA5_LAND/MONTHLY_AGGR",
            "ECMWF/ERA5_LAND/MONTHLY_BY_HOUR",
            "ECMWF/ERA5_LAND/HOURLY",
        ],
        "type": "ImageCollection",
    },
    "ndvi": {
        "role": "CORE - vegetation stress (agricultural drought)",
        "ids": [
            "MODIS/061/MOD13A2",
            "MODIS/061/MOD13Q1",
            "MODIS/061/MYD13A2",
        ],
        "type": "ImageCollection",
    },
    "ndvi_successor": {
        "role": "CONTINUITY - VIIRS, replaces MODIS after Terra/Aqua shutdown",
        "ids": [
            "NASA/VIIRS/002/VNP13A1",
            "NOAA/VIIRS/001/VNP13A1",
        ],
        "type": "ImageCollection",
    },
    "evapotranspiration": {
        "role": "SUPPORTING - ET/PET water stress ratio",
        "ids": [
            "MODIS/061/MOD16A2GF",
            "MODIS/061/MOD16A2",
        ],
        "type": "ImageCollection",
    },
    "land_surface_temperature": {
        "role": "SUPPORTING - thermal stress, TCI",
        "ids": [
            "MODIS/061/MOD11A2",
            "MODIS/061/MYD11A2",
        ],
        "type": "ImageCollection",
    },
    "soil_moisture_satellite": {
        "role": "OPTIONAL - validation only (record starts 2015, too short to train on)",
        "ids": [
            "NASA/SMAP/SPL4SMGP/008",
            "NASA/SMAP/SPL4SMGP/007",
            "NASA_USDA/HSL/SMAP10KM_soil_moisture",
        ],
        "type": "ImageCollection",
    },
    "terrestrial_water_storage": {
        "role": "OPTIONAL - basin-scale groundwater signal (~300 km, NOT a map layer)",
        "ids": [
            "NASA/GRACE/MASS_GRIDS_V04/LAND",
            "NASA/GRACE/MASS_GRIDS_V03/LAND",
            "NASA/GRACE/MASS_GRIDS/LAND",
        ],
        "type": "ImageCollection",
    },
    "land_cover": {
        "role": "MASKING - restrict analysis to cropland / rangeland",
        "ids": [
            "ESA/WorldCover/v200",
            "ESA/WorldCover/v100",
            "COPERNICUS/Landcover/100m/Proba-V-C3/Global",
        ],
        "type": "ImageCollection",
    },
    "basin_boundary": {
        "role": "AOI - fallback basin polygon if no official DSI boundary is available",
        "ids": [
            "WWF/HydroSHEDS/v1/Basins/hybas_5",
            "WWF/HydroSHEDS/v1/Basins/hybas_6",
        ],
        "type": "FeatureCollection",
    },
    "dem": {
        "role": "SUPPORTING - elevation, slope, aspect as static predictors",
        "ids": [
            "USGS/SRTMGL1_003",
            "COPERNICUS/DEM/GLO30",
        ],
        "type": "Image",
    },
}

HTTP_ENDPOINTS = {
    "Copernicus GDO WCS (benchmark SPI / GRACE TWS)": (
        "https://drought.emergency.copernicus.eu/api/wcs"
        "?service=WCS&version=2.0.1&request=GetCapabilities"
    ),
    "CHIRPS direct archive (UCSB)": "https://data.chc.ucsb.edu/products/CHIRPS/",
    "CDS API root (needs token for real requests)": "https://cds.climate.copernicus.eu/api",
}

REQUIRED_PACKAGES = [
    "ee", "requests", "numpy", "pandas", "geopandas", "rasterio",
    "xarray", "scipy", "sklearn", "xgboost", "shap",
]


@dataclass
class Check:
    name: str
    status: str  # OK | WARN | FAIL | SKIP
    detail: str = ""
    extra: dict = field(default_factory=dict)


results: list[Check] = []


def record(name: str, status: str, detail: str = "", **extra) -> None:
    results.append(Check(name=name, status=status, detail=detail, extra=extra))
    symbol = {"OK": "[ OK ]", "WARN": "[WARN]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}[status]
    print(f"{symbol} {name}: {detail}")


# --------------------------------------------------------------------------
# 1. Python environment
# --------------------------------------------------------------------------
def check_packages() -> None:
    print("\n=== 1. Python packages ===")
    import importlib
    missing = []
    for pkg in REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg)
        except Exception:
            missing.append(pkg)
    if missing:
        record("python packages", "WARN", f"missing: {', '.join(missing)}")
    else:
        record("python packages", "OK", "all required packages importable")


# --------------------------------------------------------------------------
# 2. Earth Engine
# --------------------------------------------------------------------------
def check_earth_engine(project: str | None) -> None:
    print("\n=== 2. Google Earth Engine ===")
    try:
        import ee
    except ImportError:
        record("earthengine-api", "FAIL", "not installed - pip install earthengine-api")
        return

    try:
        ee.Initialize(project=project) if project else ee.Initialize()
        record("GEE auth", "OK", f"initialized (project={project or 'default'})")
    except Exception as exc:
        record(
            "GEE auth", "FAIL",
            f"{type(exc).__name__}: {exc}. Run 'earthengine authenticate' and register a "
            "Cloud project for noncommercial use."
        )
        return

    aoi = ee.Geometry.Rectangle(AOI_BBOX)

    for var, cfg in GEE_CANDIDATES.items():
        resolved = None
        errors = []
        for asset_id in cfg["ids"]:
            try:
                info = probe_gee_asset(ee, asset_id, cfg["type"], aoi)
                resolved = (asset_id, info)
                break
            except Exception as exc:
                errors.append(f"{asset_id}: {type(exc).__name__}")
        if resolved:
            asset_id, info = resolved
            status = "OK"
            detail = f"{asset_id} | {info}"
            if cfg["role"].startswith("CORE") and "n=0" in info:
                status = "FAIL"
                detail += " | CORE dataset returned no images over AOI"
            record(f"GEE {var} ({cfg['role'].split(' - ')[0]})", status, detail, asset=asset_id)
        else:
            status = "FAIL" if cfg["role"].startswith("CORE") else "WARN"
            record(f"GEE {var}", status, "no candidate resolved -> " + "; ".join(errors))


def probe_gee_asset(ee, asset_id: str, kind: str, aoi) -> str:
    """Return a short human-readable availability string, or raise."""
    if kind == "ImageCollection":
        col = ee.ImageCollection(asset_id).filterBounds(aoi)
        full = ee.ImageCollection(asset_id)
        # date range of the whole collection
        rng = full.reduceColumns(
            ee.Reducer.minMax(), ["system:time_start"]
        ).getInfo()
        train = col.filterDate(TRAIN_START, TRAIN_END)
        n = train.size().getInfo()
        bands = ee.Image(full.first()).bandNames().getInfo()
        first = fmt_ms(rng.get("min"))
        last = fmt_ms(rng.get("max"))
        return (
            f"coverage {first} -> {last} | n={n} in training window | "
            f"bands={len(bands)} e.g. {bands[:4]}"
        )
    if kind == "Image":
        img = ee.Image(asset_id)
        bands = img.bandNames().getInfo()
        return f"static image | bands={bands[:4]}"
    if kind == "FeatureCollection":
        fc = ee.FeatureCollection(asset_id).filterBounds(aoi)
        n = fc.size().getInfo()
        return f"features intersecting AOI n={n}"
    raise ValueError(f"unknown kind {kind}")


def fmt_ms(ms) -> str:
    if not ms:
        return "?"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m")


# --------------------------------------------------------------------------
# 3. HTTP endpoints
# --------------------------------------------------------------------------
def check_http() -> None:
    print("\n=== 3. HTTP endpoints ===")
    try:
        import requests
    except ImportError:
        record("requests", "FAIL", "not installed")
        return
    for name, url in HTTP_ENDPOINTS.items():
        try:
            resp = requests.get(url, timeout=30)
            status = "OK" if resp.status_code < 400 else "WARN"
            record(name, status, f"HTTP {resp.status_code}", url=url)
        except Exception as exc:
            record(name, "FAIL", f"{type(exc).__name__}: {exc}", url=url)


# --------------------------------------------------------------------------
# 4. Copernicus CDS (ERA5-Land + C3S seasonal forecasts)
# --------------------------------------------------------------------------
def check_cds(run_request: bool) -> None:
    print("\n=== 4. Copernicus CDS ===")
    try:
        import cdsapi  # noqa: F401
    except ImportError:
        record("cdsapi", "WARN", "not installed - pip install 'cdsapi>=0.7.7'")
        return

    rc = os.path.expanduser("~/.cdsapirc")
    if not os.path.exists(rc):
        record(
            "CDS credentials", "WARN",
            "~/.cdsapirc not found. Register at cds.climate.copernicus.eu, copy your "
            "personal access token, and accept the licences for 'ERA5-Land monthly "
            "averaged data' and 'Seasonal forecast monthly statistics on single levels'."
        )
        return
    record("CDS credentials", "OK", "~/.cdsapirc present")

    if not run_request:
        record("CDS live request", "SKIP", "re-run with --with-cds to submit a real test request")
        return

    try:
        import cdsapi
        client = cdsapi.Client()
        client.retrieve(
            "reanalysis-era5-land-monthly-means",
            {
                "product_type": ["monthly_averaged_reanalysis"],
                "variable": ["2m_temperature"],
                "year": ["2020"],
                "month": ["06"],
                "time": ["00:00"],
                "data_format": "netcdf",
                "download_format": "unarchived",
                "area": [AOI_BBOX[3], AOI_BBOX[0], AOI_BBOX[1], AOI_BBOX[2]],
            },
            os.path.join(tempfile.gettempdir(), "aquacast_cds_test.nc"),
        )
        record("CDS live request", "OK", "ERA5-Land monthly test download succeeded")
    except Exception as exc:
        record("CDS live request", "FAIL", f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-cds", action="store_true", help="submit a real CDS test request")
    parser.add_argument("--project", default=None, help="Google Cloud project registered for Earth Engine")
    parser.add_argument("--json", default=None, help="write full report to this JSON file")
    args = parser.parse_args()

    print("AquaCast - data access verification")
    print(f"AOI bbox : {AOI_BBOX}")
    print(f"Training : {TRAIN_START} -> {TRAIN_END}")

    check_packages()
    try:
        check_earth_engine(args.project)
    except Exception:
        traceback.print_exc()
        record("GEE checks", "FAIL", "unhandled exception, see traceback")
    check_http()
    check_cds(args.with_cds)

    print("\n=== SUMMARY ===")
    counts = {}
    for c in results:
        counts[c.status] = counts.get(c.status, 0) + 1
    print(" ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    fails = [c for c in results if c.status == "FAIL"]
    if fails:
        print("\nBLOCKERS - do not start the pipeline until these are resolved:")
        for c in fails:
            print(f"  - {c.name}: {c.detail}")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump([asdict(c) for c in results], fh, indent=2)
        print(f"\nreport written to {args.json}")

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
