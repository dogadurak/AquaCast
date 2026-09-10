"""T2 result: CHIRPS bias against the official basin climatology.

This is a finding, not a gate. CHIRPS is designed for data-sparse tropical regions
and has a documented positive bias over Türkiye; PROJECT_SPEC §3.2 flags it as a risk
and asks for the comparison to be run and reported. This is that number for this
basin, computed from the exported per-cell panel rather than from a server-side
reduction, so it describes the data the model will actually be trained on.

Reference: basin-mean annual precipitation 417 mm, T.C. Tarım ve Orman Bakanlığı,
Su Yönetimi Genel Müdürlüğü, "Konya Havzası Tanıtım". The same report gives the
basin area as 4,980,534 ha = 49,805 km², matching the official area figure in
config/data.yaml, so both describe one delineation.

THE COMPARISON RULE, applied to this figure honestly (see the head of
.claude/skills/failure-modes/SKILL.md):

  (a) POPULATION - only approximately matched. The official mean is over the DSI
      basin (49,805 km2); ours is over HydroBASINS cells. Three populations are
      therefore reported, and their 14 mm spread is the size of that mismatch.
  (b) QUANTITY  - matched. Both sides are precipitation over the same basin, which
      is what makes "bias" the right word here, unlike the ERA5 pev vs FAO-56 ET0
      comparison where the two quantities differ by definition.
  (c) SCALE     - NOT ESTABLISHED. The reference period behind the ministry's
      417 mm is unknown to us; ours is 1981-2025. If theirs is an older normal,
      part of what we are calling bias is a period difference. This is an OPEN
      ASSUMPTION and the figure carries it until the period is confirmed.

Run:  python -m scripts.report_chirps_bias
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.data.gee_io import ROOT, load_config
from src.data.export_chirps import RAW_DIR

OUT_JSON = ROOT / "reports" / "chirps_bias.json"
OFFICIAL_ANNUAL_MM = 417.0
OFFICIAL_SOURCE = (
    "T.C. Tarım ve Orman Bakanlığı, Su Yönetimi Genel Müdürlüğü - "
    "Konya Havzası Tanıtım (417 mm, 4,980,534 ha)"
)


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
    print(f"{'population':<24} {'cells':>7} {'CHIRPS mm/yr':>13} {'bias':>9}")

    results = {}
    for name, mask in populations.items():
        cells = set(grid.loc[mask, "cell_id"].astype("int64"))
        series = annual_basin_mean(df, cells)
        mean_annual = float(series.mean())
        bias = mean_annual / OFFICIAL_ANNUAL_MM - 1
        results[name] = {
            "cells": len(cells),
            "mean_annual_mm": mean_annual,
            "bias_fraction": bias,
            "annual_mm": {int(y): float(v) for y, v in series.items()},
        }
        print(f"{name:<24} {len(cells):>7,} {mean_annual:>13.1f} {bias:>+8.1%}")

    spread = (
        max(r["mean_annual_mm"] for r in results.values())
        - min(r["mean_annual_mm"] for r in results.values())
    )
    print(f"\nSpread across cell populations: {spread:.1f} mm/yr "
          f"({spread / OFFICIAL_ANNUAL_MM:.1%} of the reference) - i.e. how much the "
          f"unresolved\nbasin boundary and the cropland mask move this number.")
    print("\nOPEN ASSUMPTION - axis (c) of the comparison rule is not established.")
    print("  The reference period behind the official 417 mm is unknown to us; ours")
    print("  is 1981-2025. If the official figure is an older normal, part of what is")
    print("  labelled bias above is a period effect. The word 'bias' is justified on")
    print("  axis (b) - both sides are precipitation - but not yet on axis (c).")

    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "official_annual_mm": OFFICIAL_ANNUAL_MM,
        "official_source": OFFICIAL_SOURCE,
        "years_exported": [int(years[0]), int(years[-1])],
        "n_years": len(years),
        "mask_min_fraction": threshold,
        "populations": results,
        "population_spread_mm": spread,
        "open_assumption_reference_period": (
            "The reference period behind the official 417 mm has not been "
            "established. Ours is 1981-2025. If the official figure is an older "
            "normal, some of the difference reported here is a period effect "
            "rather than product bias."
        ),
        "interpretation": (
            "CHIRPS is designed for data-sparse tropical regions and has a documented "
            "positive bias over Türkiye, strongest for low precipitation amounts. This "
            "is that bias measured for the Konya basin on the exported panel. It is a "
            "result to report, not a gate: the model is trained on CHIRPS throughout, "
            "so a constant multiplicative bias is absorbed by the standardisation that "
            "produces SPI. What it does affect is any statement in absolute mm."
        ),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
