"""T2 pre-flight: is the CHIRPS v3 series one product, or several stitched together?

Why this runs before the export and not after. The reference period is 1981-2016
and the test period is 2022-2025. If the series switches production line somewhere
between them - CHIRPS has an ERA5-based reanalysis line and an IMERG-based
near-real-time line, plus a final/preliminary distinction - then anomalies would be
measured with one product against a baseline fitted on another. That systematic
offset looks exactly like a climate signal. It would produce a spurious trend, and
what the model learned would be the product change.

Three checks:

1. **Metadata.** Does the collection carry a source or version flag per image?
   (Measured answer: no - only year, month, pentad. So metadata cannot settle it and
   the time series is the only available evidence.)
2. **Steps.** Basin-mean annual totals across 1981-2025. A production-line change
   shows up as a level shift, and a level shift is visible without statistics.
3. **Magnitude against an independent figure.** Basin-mean annual total against the
   417 mm published by the ministry. This is not only an assertion - CHIRPS's
   deviation from the official station climatology is the first number of the
   project's precipitation-product comparison.

Run:  python -m scripts.check_chirps_continuity
"""

from __future__ import annotations

import json
import math
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import ee
import matplotlib.pyplot as plt
import pandas as pd

from src.data.gee_io import ROOT, fetch_features, initialize, load_config, report, with_retry
from src.data.grid import basin_feature, chirps_projection

FIGDIR = ROOT / "reports" / "figures"
OUT_JSON = ROOT / "reports" / "chirps_continuity.json"

# Basin-mean annual precipitation published by the ministry for the Konya basin.
# The same report gives the area as 4,980,534 ha = 49,805 km2, matching the
# official area figure already recorded in config - so it is the same delineation.
OFFICIAL_ANNUAL_MM = 417.0
# CHIRPS has a documented positive bias over Turkiye, so an exact match is not
# expected. Outside this band the series is not describing this basin.
PLAUSIBLE_ANNUAL_MM = (350.0, 500.0)

THEMES = {
    "light": {"surface": "#fcfcfb", "text": "#0b0b0b", "muted": "#52514e",
              "grid": "#e3e3de", "series": "#2a78d6", "accent": "#eb6834"},
    "dark": {"surface": "#1a1a19", "text": "#ffffff", "muted": "#c3c2b7",
             "grid": "#333330", "series": "#3987e5", "accent": "#d95926"},
}


def monthly_basin_series(config: dict) -> pd.DataFrame:
    """Basin-mean monthly total, plus the pentad count that produced it."""
    asset = config["sources"]["precipitation_primary"]
    start_year = int(str(config["period"]["export_start"])[:4])
    end_year = int(str(config["period"]["export_end"])[:4])
    n_months = (end_year - start_year + 1) * 12

    chirps = ee.ImageCollection(asset)
    basin = basin_feature(config).geometry()
    proj = chirps_projection(config)
    scale = proj.nominalScale()
    origin = ee.Date(f"{start_year}-01-01")

    def one_month(offset):
        start = origin.advance(ee.Number(offset), "month")
        end = start.advance(1, "month")
        window = chirps.filterDate(start, end)
        total = window.sum().rename("precip_mm")
        mean = total.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=basin, crs=proj,
            scale=scale, maxPixels=int(1e9),
        )
        return ee.Feature(
            None,
            {
                "date": start.format("YYYY-MM"),
                "year": start.get("year"),
                "month": start.get("month"),
                "n_pentads": window.size(),
                "precip_mm": mean.get("precip_mm"),
            },
        )

    fc = ee.FeatureCollection(ee.List.sequence(0, n_months - 1).map(one_month))
    df = fetch_features(fc, what="chirps basin monthly series", expected_rows=n_months)
    return df.sort_values("date").reset_index(drop=True)


def draw(theme_name: str, monthly: pd.DataFrame, annual: pd.Series, stats: dict) -> Path:
    t = THEMES[theme_name]
    fig, axes = plt.subplots(2, 1, figsize=(12.4, 7.6), facecolor=t["surface"],
                             height_ratios=[1.15, 1.0])
    fig.subplots_adjust(left=0.075, right=0.975, top=0.9, bottom=0.135, hspace=0.62)

    # ---- annual totals - a production-line change shows as a level shift
    ax = axes[0]
    ax.set_facecolor(t["surface"])
    ax.bar(annual.index, annual.values, color=t["series"], width=0.72, zorder=3)
    ax.axhline(OFFICIAL_ANNUAL_MM, color=t["accent"], linewidth=2, zorder=4)
    ax.text(0.995, OFFICIAL_ANNUAL_MM, f"official {OFFICIAL_ANNUAL_MM:.0f} mm ",
            transform=ax.get_yaxis_transform(), color=t["accent"],
            fontsize=8.5, va="bottom", ha="right")
    ax.set_title("Basin-mean annual precipitation, CHIRPS v3",
                 color=t["text"], fontsize=12.5, fontweight="bold", loc="left", pad=30)
    ax.text(0.0, 1.02,
            f"Mean {stats['mean_annual_mm']:.0f} mm against a published {OFFICIAL_ANNUAL_MM:.0f} mm "
            f"({stats['bias_pct']:+.1f}%). A production-line change would appear as a level shift.",
            transform=ax.transAxes, color=t["muted"], fontsize=8.6, va="bottom", ha="left")
    ax.set_ylabel("mm / year", color=t["muted"], fontsize=9)

    # ---- monthly series with a 12-month rolling mean
    ax = axes[1]
    ax.set_facecolor(t["surface"])
    x = pd.to_datetime(monthly["date"] + "-01")
    ax.plot(x, monthly["precip_mm"], color=t["series"], linewidth=0.7, alpha=0.45, zorder=3)
    ax.plot(x, monthly["precip_mm"].rolling(12, center=True).mean(),
            color=t["accent"], linewidth=2.0, zorder=4)
    ax.set_title("Monthly series and 12-month rolling mean",
                 color=t["text"], fontsize=12.5, fontweight="bold", loc="left", pad=30)
    ax.text(0.0, 1.02,
            "The rolling mean is the step detector: a discontinuity in production would "
            "break its level, not just its variance.",
            transform=ax.transAxes, color=t["muted"], fontsize=8.6, va="bottom", ha="left")
    ax.set_ylabel("mm / month", color=t["muted"], fontsize=9)

    for ax in axes:
        ax.grid(axis="y", color=t["grid"], linewidth=0.8, zorder=1)
        ax.set_axisbelow(True)
        ax.tick_params(colors=t["muted"], labelsize=8, length=2)
        for side, spine in ax.spines.items():
            spine.set_visible(side == "bottom")
            if side == "bottom":
                spine.set_color(t["grid"])

    fig.text(0.075, 0.022, textwrap.fill(
        "CHIRPS v3 PENTAD carries no source or version property per image - only year, "
        "month and pentad - so a production-line change cannot be read from metadata. "
        "This figure is the evidence available instead.", 132),
        color=t["muted"], fontsize=7.8, va="bottom", ha="left", linespacing=1.5)

    FIGDIR.mkdir(parents=True, exist_ok=True)
    out = FIGDIR / f"chirps_continuity_{theme_name}.png"
    fig.savefig(out, dpi=170, facecolor=t["surface"])
    plt.close(fig)
    return out


def main() -> None:
    config = load_config()
    initialize(config)

    print("1. Metadata check")
    props = with_retry(
        lambda: ee.Image(
            ee.ImageCollection(config["sources"]["precipitation_primary"]).first()
        ).propertyNames().getInfo(),
        what="property names",
    )
    non_system = sorted(p for p in props if not p.startswith("system:"))
    version_flags = [p for p in non_system
                     if any(k in p.lower() for k in ("version", "source", "product", "prelim", "status"))]
    print(f"   non-system properties: {non_system}")
    ok = report("source/version flag present", False, bool(version_flags))
    print("   -> no per-image production flag, so metadata cannot settle continuity;"
          "\n      the time series below is the only available evidence.")

    print("\n2. Fetching basin-mean monthly series ...")
    monthly = monthly_basin_series(config)
    monthly["precip_mm"] = pd.to_numeric(monthly["precip_mm"])
    monthly["n_pentads"] = pd.to_numeric(monthly["n_pentads"])

    bad = monthly[monthly["n_pentads"] != 6]
    ok &= report("months with exactly 6 pentads", len(monthly), int((monthly["n_pentads"] == 6).sum()))
    if len(bad):
        print(f"   offending months: {bad[['date', 'n_pentads']].to_dict('records')[:12]}")

    ok &= report("months with a null basin mean", 0, int(monthly["precip_mm"].isna().sum()))

    annual = monthly.groupby("year")["precip_mm"].sum()
    mean_annual = float(annual.mean())
    bias_pct = (mean_annual / OFFICIAL_ANNUAL_MM - 1) * 100

    print("\n3. Magnitude against the published figure")
    lo, hi = PLAUSIBLE_ANNUAL_MM
    in_band = lo <= mean_annual <= hi
    print(f"   [{'OK      ' if in_band else 'MISMATCH'}] basin-mean annual total: "
          f"expected {lo:.0f}-{hi:.0f} mm -> actual {mean_annual:.1f} mm")
    print(f"   official (SYGM) {OFFICIAL_ANNUAL_MM:.0f} mm -> CHIRPS bias {bias_pct:+.1f}%")
    ok &= in_band

    print("\n4. Level shifts by era (eyeball the figure too)")
    eras = {"1981-1990": (1981, 1990), "1991-2000": (1991, 2000),
            "2001-2010": (2001, 2010), "2011-2016": (2011, 2016),
            "2017-2021": (2017, 2021), "2022-2025": (2022, 2025)}
    era_means = {}
    for label, (a, b) in eras.items():
        sel = annual[(annual.index >= a) & (annual.index <= b)]
        era_means[label] = float(sel.mean())
        print(f"   {label}: {sel.mean():>6.1f} mm/yr  (n={len(sel)})")
    spread = max(era_means.values()) - min(era_means.values())
    print(f"   spread across eras: {spread:.1f} mm/yr "
          f"({spread / mean_annual:.1%} of the mean)")

    # An era mean on its own is a poor step detector: one extreme year drags it.
    # A production-line change pushes EVERY year after the transition to a new
    # level, so a single post-transition year above the long-term mean rules a
    # level shift out. Interannual variability does not.
    print()
    print("5. Level shift or interannual variability?")
    test_years = annual[annual.index >= 2022]
    above = test_years[test_years > mean_annual]
    driest = annual.nsmallest(8)
    print(f"   test-period years above the 1981-2025 mean: "
          f"{[f'{y} ({v:.0f} mm)' for y, v in above.items()] or 'none'}")
    print(f"   eight driest years, whole record: "
          f"{[f'{y}' for y in driest.index.tolist()]}")
    decades = sorted({y // 10 * 10 for y in driest.index})
    print(f"   they span {len(decades)} decades: {decades}")
    step_ruled_out = len(above) > 0 and len(decades) >= 3
    print(f"   [{'OK      ' if step_ruled_out else 'REVIEW  '}] level shift ruled out: "
          f"expected True -> actual {step_ruled_out}")
    stats_extra = {
        "test_years_above_mean": {int(y): float(v) for y, v in above.items()},
        "driest_years": [int(y) for y in driest.index],
        "driest_years_span_decades": len(decades),
        "level_shift_ruled_out": bool(step_ruled_out),
    }

    stats = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collection": config["sources"]["precipitation_primary"],
        "non_system_properties": non_system,
        "has_version_flag": bool(version_flags),
        "n_months": len(monthly),
        "months_with_6_pentads": int((monthly["n_pentads"] == 6).sum()),
        "mean_annual_mm": mean_annual,
        "official_annual_mm": OFFICIAL_ANNUAL_MM,
        "bias_pct": bias_pct,
        "era_mean_annual_mm": era_means,
        "era_spread_mm": spread,
        "annual_mm": {int(k): float(v) for k, v in annual.items()},
        **stats_extra,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT_JSON.relative_to(ROOT)}")

    for theme in ("light", "dark"):
        out = draw(theme, monthly, annual, stats)
        print(f"wrote {out.relative_to(ROOT)}")

    if not ok:
        raise AssertionError(
            "CHIRPS continuity pre-flight failed - do not run the T2 export. "
            "Per docs/working_protocol.md, stop and report."
        )
    print("\nPre-flight checks pass. Inspect the figure for a level shift before T2.")


if __name__ == "__main__":
    main()
