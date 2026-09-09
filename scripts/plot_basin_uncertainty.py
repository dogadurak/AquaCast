"""Characterise the basin-boundary uncertainty, and draw the analysis grid.

The question this figure answers is not "how big is the difference" - that is one
number, +17% - but **where** it is. A difference concentrated in one contiguous
lobe is a definitional disagreement about which sub-basin belongs to the basin:
explainable and defensible. A difference spread as a thin fringe along the whole
perimeter is delineation noise. They call for different sentences in the model
card, so the shape has to be looked at.

Honest limit: the true difference polygon is `HydroBASINS minus official`, and the
official geometry is not in hand - only its published area. What is drawn instead
is the HydroBASINS polygon decomposed into HydroSHEDS level 6 endorheic
sub-basins. If level 5 has merged sub-basins that HydroSHEDS itself treats as
separate endorheic systems, that shows up here as distinct lobes, and those lobes
are the candidates for the excess area. The figure is completed, not replaced,
when the official boundary arrives.

Run:  python -m scripts.plot_basin_uncertainty
"""

from __future__ import annotations

import math
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from shapely.geometry import shape

from src.data.gee_io import ROOT, initialize, load_config, with_retry
from src.data.grid import basin_feature

import ee

FIGDIR = ROOT / "reports" / "figures"
GRID_CSV = ROOT / "data" / "interim" / "grid_cells.csv"

# Categorical slots 1-3 from the dataviz reference palette. Only the first three
# validate on the all-pairs pairlist, which is the one that applies to a map:
# every region is on screen at once, so non-adjacent pairs must separate too.
THEMES = {
    "light": {
        "surface": "#fcfcfb",
        "text_primary": "#0b0b0b",
        "text_secondary": "#52514e",
        "muted": "#8a8a84",
        "series": ["#2a78d6", "#eb6834", "#1baf7a"],
        "other": "#b9b9b2",
        "ramp": ["#eef4fc", "#2a78d6"],
        "outline": "#0b0b0b",
    },
    "dark": {
        "surface": "#1a1a19",
        "text_primary": "#ffffff",
        "text_secondary": "#c3c2b7",
        "muted": "#6f6f68",
        "series": ["#3987e5", "#d95926", "#199e70"],
        "other": "#4a4a45",
        "ramp": ["#20303f", "#3987e5"],
        "outline": "#ffffff",
    },
}


# --------------------------------------------------------------------------
def fetch_geometries(config: dict) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    initialize(config)
    basin = basin_feature(config)
    g5 = basin.geometry()

    l5_geo = with_retry(
        lambda: g5.simplify(maxError=500).getInfo(), what="L5 geometry"
    )
    l5 = gpd.GeoDataFrame(
        {"name": ["HydroBASINS L5"]}, geometry=[shape(l5_geo)], crs="EPSG:4326"
    )

    h6 = ee.FeatureCollection("WWF/HydroSHEDS/v1/Basins/hybas_6").filterBounds(g5)
    h6 = h6.map(lambda f: f.setGeometry(f.geometry().simplify(maxError=500)))
    l6_geo = with_retry(lambda: h6.getInfo(), what="L6 features")

    records = []
    for feat in l6_geo["features"]:
        props = feat["properties"]
        records.append(
            {
                "HYBAS_ID": props["HYBAS_ID"],
                "MAIN_BAS": props["MAIN_BAS"],
                "ENDO": props["ENDO"],
                "SUB_AREA": props["SUB_AREA"],
                "geometry": shape(feat["geometry"]),
            }
        )
    l6 = gpd.GeoDataFrame(records, crs="EPSG:4326")

    # Keep only sub-basins actually inside the L5 polygon, not merely touching it.
    inside = l6.geometry.representative_point().within(l5.geometry.iloc[0])
    return l5, l6[inside].copy()


def load_grid() -> gpd.GeoDataFrame:
    df = pd.read_csv(GRID_CSV)
    return gpd.GeoDataFrame(
        df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs="EPSG:4326"
    )


# --------------------------------------------------------------------------
def draw(theme_name: str, l5: gpd.GeoDataFrame, l6: gpd.GeoDataFrame,
         grid: gpd.GeoDataFrame, config: dict) -> Path:
    t = THEMES[theme_name]
    aoi = config["aoi"]
    official = float(aoi["official_area_km2_text"])
    hydro = float(aoi["area_km2_hydrobasins"])
    lobe_id = aoi["akarcay_lobe_main_bas"]

    # Degrees of longitude are shorter than degrees of latitude away from the
    # equator, so aspect="equal" on raw lon/lat stretches the map east-west.
    mean_lat = float(grid["lat"].mean())
    aspect = 1.0 / math.cos(math.radians(mean_lat))

    fig, axes = plt.subplots(1, 2, figsize=(14.0, 6.4), facecolor=t["surface"])
    fig.subplots_adjust(left=0.05, right=0.955, top=0.865, bottom=0.255, wspace=0.14)

    def caption(ax, text: str) -> None:
        ax.text(0.0, -0.235, textwrap.fill(text, 92), transform=ax.transAxes,
                color=t["text_secondary"], fontsize=8.4, va="top", ha="left",
                linespacing=1.5)

    def legend_below(ax, handles) -> None:
        leg = ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.0, -0.035),
                        frameon=False, fontsize=8.5, ncol=1, handlelength=1.4,
                        borderpad=0.0, labelspacing=0.45)
        for text in leg.get_texts():
            text.set_color(t["text_secondary"])

    # ---- Panel A: where the excess area sits -----------------------------
    ax = axes[0]
    ax.set_facecolor(t["surface"])
    endo = l6[l6["ENDO"] != 0]
    lobe = endo[endo["MAIN_BAS"] == lobe_id]
    konya = endo[endo["MAIN_BAS"] != lobe_id]
    konya_area, lobe_area = konya["SUB_AREA"].sum(), lobe["SUB_AREA"].sum()

    konya.plot(ax=ax, facecolor=t["series"][0], edgecolor=t["surface"],
               linewidth=0.9, alpha=0.9, zorder=2)
    lobe.plot(ax=ax, facecolor=t["series"][1], edgecolor=t["surface"],
              linewidth=0.9, alpha=0.95, zorder=2)
    l5.boundary.plot(ax=ax, color=t["outline"], linewidth=1.8, zorder=3)

    ax.set_title("The excess area is one contiguous lobe, not a fringe",
                 color=t["text_primary"], fontsize=12.5, fontweight="bold",
                 loc="left", pad=9)
    legend_below(ax, [
        mpatches.Patch(facecolor=t["series"][0], edgecolor="none",
                       label=f"Konya sinks, {len(konya)} sub-basins — {konya_area:,.0f} km²"),
        mpatches.Patch(facecolor=t["series"][1], edgecolor="none",
                       label=f"Akarçay lobe, MAIN_BAS {lobe_id} — {lobe_area:,.0f} km²"),
    ])
    caption(ax, (
        f"HydroBASINS L5 is {hydro:,.0f} km² against an official {official:,.0f} km², "
        f"{hydro / official - 1:+.1%}. Excluding the lobe gives {konya_area:,.0f} km², "
        f"{konya_area / official - 1:+.1%} — every other single sub-basin is at least "
        f"7.5% off."
    ))

    # ---- Panel B: the analysis grid --------------------------------------
    ax = axes[1]
    ax.set_facecolor(t["surface"])
    cmap = LinearSegmentedColormap.from_list("crop", t["ramp"])
    ring = grid[~grid["in_hydrobasins"]]
    inside = grid[grid["in_hydrobasins"]]
    lobe_cells = inside[inside["in_akarcay_lobe"]]

    ring.plot(ax=ax, color=t["muted"], markersize=4, marker="x", linewidth=0.5, zorder=2)
    inside.plot(ax=ax, column="crop_frac_2021", cmap=cmap, markersize=5.5,
                vmin=0, vmax=1, zorder=3)
    lobe_cells.plot(ax=ax, facecolor="none", edgecolor=t["series"][1], markersize=22,
                    marker="o", linewidth=0.45, zorder=4)
    l5.boundary.plot(ax=ax, color=t["outline"], linewidth=1.4, zorder=5)

    ax.set_title("Analysis grid — CHIRPS 0.05° lattice",
                 color=t["text_primary"], fontsize=12.5, fontweight="bold",
                 loc="left", pad=9)
    legend_below(ax, [
        plt.Line2D([], [], color=t["muted"], marker="x", linestyle="none", markersize=5,
                   label=f"ring cell, outside basin, exported anyway ({len(ring):,})"),
        plt.Line2D([], [], markerfacecolor="none", markeredgecolor=t["series"][1],
                   marker="o", linestyle="none", markersize=6.5,
                   label=f"in_akarcay_lobe ({len(lobe_cells):,})"),
    ])
    n_mask = int((inside["crop_frac_2021"] >= config["grid"]["mask"]["min_fraction"]).sum())
    caption(ax, (
        f"{len(grid):,} cells exported: {len(inside):,} in basin, {len(ring):,} in the "
        f"one-cell ring. {n_mask:,} pass crop_frac_2021 ≥ 0.5. Membership is a column, "
        f"never a row filter — nothing here is dropped at export time."
    ))

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=0, vmax=1))
    cb = fig.colorbar(sm, ax=ax, fraction=0.032, pad=0.025,
                      ticks=[0, 0.25, 0.5, 0.75, 1.0])
    cb.set_label("crop_frac_2021", color=t["text_secondary"], fontsize=8.5)
    cb.ax.tick_params(colors=t["text_secondary"], labelsize=7.5)
    cb.outline.set_visible(False)

    for ax in axes:
        ax.set_xlabel(""); ax.set_ylabel("")
        ax.tick_params(colors=t["text_secondary"], labelsize=7.5, length=2)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_aspect(aspect)

    fig.text(0.05, 0.016,
             "The official DSİ/SYGM boundary is not drawn — only its published area is known. "
             "This decomposes HydroBASINS rather than differencing it against the official "
             "polygon, and is completed when that geometry is obtained.",
             color=t["muted"], fontsize=7.8, va="bottom", ha="left")

    FIGDIR.mkdir(parents=True, exist_ok=True)
    out = FIGDIR / f"basin_boundary_uncertainty_{theme_name}.png"
    fig.savefig(out, dpi=170, facecolor=t["surface"])
    plt.close(fig)
    return out


# --------------------------------------------------------------------------
def main() -> None:
    config = load_config()
    l5, l6 = fetch_geometries(config)
    grid = load_grid()

    endo = l6[l6["ENDO"] != 0]
    groups = endo.groupby("MAIN_BAS")["SUB_AREA"].sum().sort_values(ascending=False)
    official = float(config["aoi"]["official_area_km2_text"])
    hydro = float(config["aoi"]["area_km2_hydrobasins"])

    print("HydroSHEDS L6 sub-basins with representative point inside the L5 polygon:")
    print(f"  total sub-basins        : {len(l6)}")
    print(f"  endorheic (ENDO != 0)   : {len(endo)}")
    print(f"  distinct endorheic sinks: {len(groups)}")
    for main_bas, area in groups.items():
        n = int((endo['MAIN_BAS'] == main_bas).sum())
        print(f"    MAIN_BAS {main_bas}: {area:>9,.0f} km2  ({n} sub-basin(s))")
    print(f"\n  L5 polygon area   : {hydro:>9,.0f} km2")
    print(f"  official (SYGM)   : {official:>9,.0f} km2")
    print(f"  excess to explain : {hydro - official:>9,.0f} km2")
    largest = groups.iloc[0] if len(groups) else 0
    print(f"  largest single sink: {largest:>9,.0f} km2")

    for theme in ("light", "dark"):
        out = draw(theme, l5, l6, grid, config)
        print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
