"""T4 - assemble the monthly panel from the exported sources.

The dangerous failure here is not a crash and not a missing row. It is a join that
produces exactly the right number of rows, no nulls, and the wrong pairings: values
bound to the wrong cell or the wrong month. Row counts, null audits and dtype checks
all pass in that case.

So the gate is a **checksum of (key, value) pairs computed without joining**. Each
source is sorted by (cell_id, date) and its value column hashed; the same is done on
the panel. Equal digests mean every value sits against the right key - full coverage
rather than a sample, and a second route to the answer that never performs a join.

Run:  python -m src.data.build_panel
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.export_chirps import RAW_DIR as CHIRPS_DIR, zero_diagnostics
from src.data.export_era5 import RAW_DIR as ERA5_DIR
from src.data.gee_io import ROOT, atomic_write, load_config, provenance, report
from src.data.grid import GRID_CSV

PANEL = ROOT / "data" / "processed" / "panel_monthly.parquet"
INTEGRITY = ROOT / "reports" / "panel_integrity.json"

KEY = ["cell_id", "date"]
GRID_COLUMNS = [
    "cell_id", "lon", "lat", "i", "j",
    "crop_frac_2021", "in_hydrobasins", "in_akarcay_lobe",
]


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------
def load_source(directory: Path, prefix: str) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    files = sorted(directory.glob(f"{prefix}_*.csv"))
    if not files:
        raise SystemExit(f"no {prefix} files in {directory}")
    frames = [pd.read_csv(f) for f in files]
    manifests = [
        json.loads((directory / f"{f.stem}.manifest.json").read_text(encoding="utf-8"))
        for f in files
    ]
    df = pd.concat(frames, ignore_index=True)
    # Normalise the date on BOTH sides before anything compares them. A string that
    # differs by a timezone suffix or a month-end convention joins to nothing and
    # reports no error.
    df["date"] = pd.to_datetime(df["date"], utc=False).dt.normalize()
    df["cell_id"] = df["cell_id"].astype("int64")
    return df, manifests


def key_value_digest(df: pd.DataFrame, column: str) -> str:
    """Hash of (cell_id, date, value) ordered by key - the join-independent identity.

    Computed the same way on a source and on the panel. Equality proves every value
    is bound to the same key in both, without performing or trusting a join.
    """
    ordered = df.sort_values(KEY)[column]
    h = hashlib.sha256()
    h.update(pd.util.hash_pandas_object(df.sort_values(KEY)[KEY], index=False).values.tobytes())
    h.update(pd.util.hash_pandas_object(ordered, index=False).values.tobytes())
    return h.hexdigest()[:16]


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------
def check_provenance(manifests: list[dict[str, Any]], source: str, problems: list[str]) -> dict:
    """Within one source, every year must come from one producing code state.

    Not a commit SHA: a documentation commit mid-export changes that while the
    producing code is untouched. Not a whole-tree hash either, which would be
    unsatisfiable across sources. The unit is the digest of the modules that produce
    THIS artefact. No exceptions - an exception here kills the assertion for
    everything it was meant to protect.
    """
    provs = [m.get("provenance") for m in manifests]
    missing = sum(1 for p in provs if not p)
    if missing:
        problems.append(
            f"{source}: {missing} of {len(manifests)} manifests carry no provenance. "
            "Re-export rather than granting an exception"
        )
        return {"missing": missing}
    digests = {p.get("producer_digest") for p in provs}
    dirty = [p["git_sha"] for p in provs if p.get("git_dirty")]
    if len(digests) != 1:
        problems.append(
            f"{source}: {len(digests)} distinct producer digests {digests}. Years were "
            "produced by different code; schema equality cannot see this"
        )
    if dirty:
        problems.append(
            f"{source}: {len(dirty)} years produced from a dirty working tree"
        )
    return {
        "producer_digests": sorted(d for d in digests if d),
        "git_shas": sorted({p["git_sha"] for p in provs}),
        "dirty_years": len(dirty),
    }


def stratified_sample(panel: pd.DataFrame, sources: dict[str, pd.DataFrame]) -> list[dict]:
    """A handful of rows a person can read, deliberately spread across the strata.

    Evidence for the reader, never the gate - the gate is the checksum. See
    failure-modes 24.
    """
    picks: list[pd.Series] = []
    for year in (1981, 2003, 2025):
        for month in (1, 7):
            for ring in (False, True):
                sub = panel[
                    (panel["date"].dt.year == year)
                    & (panel["date"].dt.month == month)
                    & (panel["in_hydrobasins"] != ring)
                ]
                if len(sub):
                    picks.append(sub.iloc[len(sub) // 2])
    rows = []
    for row in picks:
        entry = {
            "cell_id": int(row["cell_id"]),
            "date": row["date"].strftime("%Y-%m-%d"),
            "in_hydrobasins": bool(row["in_hydrobasins"]),
        }
        for name, src in sources.items():
            col = "precip_chirps_mm" if name == "chirps" else "t2m_c"
            match = src[(src["cell_id"] == row["cell_id"]) & (src["date"] == row["date"])]
            entry[f"{col}_panel"] = float(row[col])
            entry[f"{col}_source"] = float(match[col].iloc[0]) if len(match) else None
        rows.append(entry)
    return rows


# --------------------------------------------------------------------------
def build() -> pd.DataFrame:
    config = load_config()
    grid = pd.read_csv(GRID_CSV)
    grid["cell_id"] = grid["cell_id"].astype("int64")

    chirps, chirps_manifests = load_source(CHIRPS_DIR, "chirps")
    era5, era5_manifests = load_source(ERA5_DIR, "era5")

    problems: list[str] = []
    print("Provenance (one producing code state per source, no exceptions):")
    prov = {
        "chirps": check_provenance(chirps_manifests, "chirps", problems),
        "era5": check_provenance(era5_manifests, "era5", problems),
    }
    for name, info in prov.items():
        print(f"  {name}: digests={info.get('producer_digests')} "
              f"shas={len(info.get('git_shas', []))} dirty={info.get('dirty_years')}")

    print("\nKeys:")
    n_cells = len(grid)
    n_months = chirps["date"].nunique()
    ok = report("cells in grid", n_cells, n_cells)
    ok &= report("distinct dates, chirps", n_months, chirps["date"].nunique())
    ok &= report("distinct dates, era5", n_months, era5["date"].nunique())
    # Set equality, not count equality: two sources can hold 540 dates each and
    # still not hold the SAME 540.
    ok &= report("date SETS identical", True,
                 set(chirps["date"]) == set(era5["date"]))
    ok &= report("cell_id SETS identical (chirps vs era5)", True,
                 set(chirps["cell_id"]) == set(era5["cell_id"]))
    ok &= report("cell_id SETS identical (chirps vs grid)", True,
                 set(chirps["cell_id"]) == set(grid["cell_id"]))
    ok &= report("duplicate keys in chirps", 0, int(chirps.duplicated(KEY).sum()))
    ok &= report("duplicate keys in era5", 0, int(era5.duplicated(KEY).sum()))

    # Digests BEFORE the join, so they describe the sources rather than the result.
    value_columns = {
        "chirps": [c for c in chirps.columns if c not in KEY + ["month"]],
        "era5": [c for c in era5.columns if c not in KEY + ["month"]],
    }
    before = {
        f"{src}.{col}": key_value_digest(df, col)
        for src, df in (("chirps", chirps), ("era5", era5))
        for col in value_columns[src]
    }

    # Outer, never inner. An inner join drops a missing cell silently and leaves a
    # plausible row count behind.
    era5_join = era5.drop(columns=["month"])
    panel = chirps.merge(era5_join, on=KEY, how="outer", validate="one_to_one")
    panel = panel.merge(grid[GRID_COLUMNS], on="cell_id", how="left", validate="many_to_one")

    print("\nJoin:")
    expected_rows = n_cells * n_months
    ok &= report("rows", expected_rows, len(panel))
    ok &= report("duplicate keys in panel", 0, int(panel.duplicated(KEY).sum()))
    ok &= report("cell_id dtype preserved", "int64", str(panel["cell_id"].dtype))
    collided = [c for c in panel.columns if c.endswith(("_x", "_y"))]
    ok &= report("collided column names", [], collided)

    nulls = {c: int(panel[c].isna().sum()) for c in panel.columns}
    worst = {c: n for c, n in nulls.items() if n}
    ok &= report("columns with any null", {}, worst)

    # THE GATE: every value bound to the right key, verified in full.
    print("\nValue integrity (full verification, not a sample):")
    after = {f"{src}.{col}": key_value_digest(panel, col)
             for src, cols in value_columns.items() for col in cols}
    mismatched = sorted(k for k in before if before[k] != after.get(k))
    ok &= report("columns whose (key,value) digest changed", [], mismatched)
    print(f"             ({len(before)} columns hashed across {len(panel):,} rows)")

    # Derived at panel stage, not present in the raw export - see the data dictionary.
    diag, isolated_total = zero_diagnostics(
        panel.assign(month=panel["date"].dt.month), "precip_chirps_mm"
    )
    isolated_ids = {c for d in diag for c in d["isolated_cell_ids"]}
    panel["precip_zero_isolated"] = (
        panel["cell_id"].isin(isolated_ids) & (panel["precip_chirps_mm"] == 0)
    )
    print(f"\n  precip_zero_isolated: {int(panel['precip_zero_isolated'].sum()):,} rows "
          f"flagged (DERIVED here, not in the raw export)")

    panel = panel.sort_values(KEY).reset_index(drop=True)
    if not ok:
        raise AssertionError(
            "T4 assertions failed - no panel written. Per docs/working_protocol.md, "
            "stop and report; do not adjust an expectation to match the output."
        )

    atomic_write(panel, PANEL)
    samples = stratified_sample(panel, {"chirps": chirps, "era5": era5})
    INTEGRITY.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance_of_this_build": provenance(
            ["src/data/build_panel.py", "src/data/gee_io.py", "config/data.yaml"]
        ),
        "source_provenance": prov,
        "rows": len(panel),
        "cells": n_cells,
        "months": n_months,
        "date_range": [str(panel["date"].min().date()), str(panel["date"].max().date())],
        "columns": list(panel.columns),
        "null_counts": nulls,
        "key_value_digests": before,
        "digest_note": (
            "Computed on each source before the join and on the panel after it, both "
            "ordered by (cell_id, date). Equality proves every value is bound to the "
            "same key in both, without performing or trusting a join. Full coverage, "
            "not a sample - see failure-modes 24."
        ),
        "precip_zero_isolated_rows": int(panel["precip_zero_isolated"].sum()),
        "stratified_sample": samples,
        "sample_note": (
            "Human-readable evidence only. The gate is key_value_digests."
        ),
    }, indent=2, default=str), encoding="utf-8")

    size_mb = PANEL.stat().st_size / 1e6
    print(f"\nWrote {PANEL.relative_to(ROOT)} ({len(panel):,} rows x "
          f"{len(panel.columns)} cols, {size_mb:.1f} MB)")
    print(f"Wrote {INTEGRITY.relative_to(ROOT)}")
    return panel


if __name__ == "__main__":
    build()
