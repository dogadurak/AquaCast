"""T2 result: CHIRPS against the official basin figure - as CONTEXT, not validation.

PROJECT_SPEC 3.2 asks for a precipitation-product comparison, because CHIRPS is
designed for data-sparse tropical regions and has a documented positive bias over
Turkiye. This script reports CHIRPS's basin-mean annual total from the exported panel
and places the ministry's published figure beside it.

IT DOES NOT MEASURE A BIAS, and the number must not be reported as one. Applying the
comparison rule at the head of .claude/skills/failure-modes/SKILL.md:

  (a) POPULATION - FAILS. The official sentence reads "Toplam yagis alani 56.554 km2
      olan Konya Kapali Havzasi'nin yillik ortalama yagis yuksekligi 417 mm". That
      417 mm is the mean over a 56,554 km2 PRECIPITATION AREA, while the same
      report's surface area is 49,805 km2 - 13.6% apart. Our populations span
      49,805-58,374 km2 equivalents, and 56,554 is nearer HydroBASINS than the
      Akarcay-excluded polygon this was being compared with. The anchor's own
      population uncertainty is the same size as the difference being measured, and
      its sign is unknown.
  (b) QUANTITY   - holds. Both sides are precipitation.
  (c) SCALE      - FAILS. The reference period behind 417 mm is not stated anywhere
      in the report: no year range, no "long-term average", no attribution to DSI or
      MGM. Ours is 1981-2025.

Two of three axes unresolved, so 417 mm is kept as CONTEXT and nothing is called a
bias. The real precipitation validation belongs on MGM station records, where all
three axes can be controlled: same point via the station-to-cell mapping in
reports/station_cells.json, same period by restricting CHIRPS to the station's normal
period, same quantity. That is the same station set already needed for the
point-based ERA5 temperature check - one dataset, two validations.

Run:  python -m scripts.report_chirps_vs_official
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.data.gee_io import ROOT, load_config
from src.data.export_chirps import RAW_DIR

OUT_JSON = ROOT / "reports" / "chirps_vs_official_context.json"
OFFICIAL_ANNUAL_MM = 417.0
# The full sentence, not the extracted number - see the module docstring and the
# anchor-sentence rule in the failure-modes skill.
OFFICIAL_SOURCE = (
    "T.C. Tarım ve Orman Bakanlığı, Su Yönetimi Genel Müdürlüğü, Konya Havzası "
    "Tanıtım: \"Toplam yağış alanı 56.554 km2 olan Konya Kapalı Havzası'nın yıllık "
    "ortalama yağış yüksekliği 417 mm; yıllık ortalama akışı ise 191,53 m3/s'dir.\" "
    "The same report gives the surface area as 4,980,534 ha = 49,805 km2. No "
    "reference period is stated."
)
OFFICIAL_PRECIP_AREA_KM2 = 56554.0
OFFICIAL_SURFACE_AREA_KM2 = 49805.0


def load_panel() -> pd.DataFrame:
    files = sorted(RAW_DIR.glob("chirps_*.csv"))
    if not files:
        raise SystemExit(f"no exported years in {RAW_DIR} - run src.data.export_chirps")
    frames = [pd.read_csv(f, usecols=["cell_id", "date", "precip_chirps_mm"]) for f in files]
    df = pd.concat(frames, ignore_index=True)
    df["year"] = df["date"].str.slice(0, 4).astype(int)
    return df


def annual_basin_mean(df: pd.DataFrame, cells: set[int]) -> pd.Series:
    """Mean over cells of each cell's annual total - a spatial mean of annual sums."""
    sub = df[df["cell_id"].isin(cells)]
    per_cell_year = sub.groupby(["year", "cell_id"])["precip_chirps_mm"].sum()
    return per_cell_year.groupby("year").mean()


def main() -> None:
    config = load_config()
    grid = pd.read_csv(ROOT / "data" / "interim" / "grid_cells.csv")
    threshold = float(config["grid"]["mask"]["min_fraction"])
    df = load_panel()

    populations = {
        "in_hydrobasins": grid["in_hydrobasins"],
        "in_hydrobasins_masked": grid["in_hydrobasins"] & (grid["crop_frac_2021"] >= threshold),
        "excl_akarcay_masked": (
            grid["in_hydrobasins"] & ~grid["in_akarcay_lobe"]
            & (grid["crop_frac_2021"] >= threshold)
        ),
    }

    years = sorted(df["year"].unique())
    print(f"Exported years: {years[0]}-{years[-1]} ({len(years)} of 45)")
    print(f"Official reference: {OFFICIAL_ANNUAL_MM:.0f} mm/yr")
    print(f"  {OFFICIAL_SOURCE}\n")
    print(f"{'population':<24} {'cells':>7} {'CHIRPS mm/yr':>13} {'ratio':>9}")

    results = {}
    for name, mask in populations.items():
        cells = set(grid.loc[mask, "cell_id"].astype("int64"))
        series = annual_basin_mean(df, cells)
        mean_annual = float(series.mean())
        ratio = mean_annual / OFFICIAL_ANNUAL_MM - 1
        results[name] = {
            "cells": len(cells),
            "mean_annual_mm": mean_annual,
            "ratio_to_official": ratio,
            "annual_mm": {int(y): float(v) for y, v in series.items()},
        }
        print(f"{name:<24} {len(cells):>7,} {mean_annual:>13.1f} {ratio:>+8.1%}")

    spread = (
        max(r["mean_annual_mm"] for r in results.values())
        - min(r["mean_annual_mm"] for r in results.values())
    )
    print(f"\nSpread across cell populations: {spread:.1f} mm/yr "
          f"({spread / OFFICIAL_ANNUAL_MM:.1%} of the reference) - i.e. how much the "
          f"unresolved\nbasin boundary and the cropland mask move this number.")
    print("\nTHIS IS NOT A BIAS MEASUREMENT. Two of the three comparison axes fail:")
    print(f"  (a) POPULATION - the official 417 mm is the mean over a "
          f"{OFFICIAL_PRECIP_AREA_KM2:,.0f} km2 PRECIPITATION")
    print(f"      AREA, not the {OFFICIAL_SURFACE_AREA_KM2:,.0f} km2 surface area in "
          "the same report - 13.6% apart. The")
    print("      anchor's own population uncertainty is the size of the difference")
    print("      above, and its direction is unknown.")
    print("  (b) QUANTITY   - holds; both sides are precipitation.")
    print("  (c) SCALE      - the reference period behind 417 mm is stated nowhere in")
    print("      the report. Ours is 1981-2025.")
    print("\n  So 417 mm is CONTEXT, not validation. Real precipitation validation goes")
    print("  on MGM station records, where all three axes can be controlled - the same")
    print("  stations already needed for the point-based ERA5 temperature check.")

    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "official_annual_mm": OFFICIAL_ANNUAL_MM,
        "official_source": OFFICIAL_SOURCE,
        "years_exported": [int(years[0]), int(years[-1])],
        "n_years": len(years),
        "mask_min_fraction": threshold,
        "populations": results,
        "population_spread_mm": spread,
        "official_precipitation_area_km2": OFFICIAL_PRECIP_AREA_KM2,
        "official_surface_area_km2": OFFICIAL_SURFACE_AREA_KM2,
        "is_bias_measurement": False,
        "comparison_axes": {
            "population": (
                f"FAILS. 417 mm is the mean over a {OFFICIAL_PRECIP_AREA_KM2:,.0f} km2 "
                f"precipitation area; the same report's surface area is "
                f"{OFFICIAL_SURFACE_AREA_KM2:,.0f} km2, 13.6% apart. The anchor's own "
                "population uncertainty matches the size of the difference measured "
                "against it, with unknown sign."
            ),
            "quantity": "HOLDS. Both sides are precipitation.",
            "scale": (
                "FAILS. No reference period is stated anywhere in the report - no year "
                "range, no 'long-term average', no attribution to DSI or MGM. "
                "Ours is 1981-2025."
            ),
        },
        "interpretation": (
            "CONTEXT, not validation, and not a bias. Two of the three comparison axes "
            "are unresolved, so this ratio cannot be attributed to product error. It is "
            "reported because it tells a reader roughly where CHIRPS sits relative to "
            "the published basin figure, and because the spread across cell populations "
            "shows how much the unresolved boundary moves it. The precipitation "
            "validation PROJECT_SPEC 3.2 asks for belongs on MGM station records, where "
            "point, period and quantity can all be matched - the same station set "
            "already required for the point-based ERA5 temperature check."
        ),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
