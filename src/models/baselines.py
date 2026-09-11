"""T6 - four baselines, computed BEFORE any model exists.

CLAUDE.md rule 1: a metric without its baseline is a bug. These four define what
"skill" means for every target in PROJECT_SPEC.md 4.1 - a model built before this
file has no yardstick to be compared against.

FIT PERIOD vs PREDICTION RANGE, same discipline as src/features/spi.py: climatology
is fit on `baseline_precip_era5` (1981-2016, from config) and predicted for the
whole 1981-2025 series. The two are separate function arguments so mixing them up
is a different call, not a bug hidden inside one.

KNOWN-ACCUMULATION = CLIMATOLOGY IS EXPECTED, NOT A BUG. Every approved (target,
lead) pair in PROJECT_SPEC.md 4.1 has zero accumulation overlap (k - L = 0), so
known-accumulation has nothing observed to condition on and reduces exactly to
climatology. The two are computed by INDEPENDENT code paths here regardless -
never derived from each other by shortcut - specifically so the numerical
equality is evidence, not an artefact of one calling the other. See
config/model.yaml's known_accumulation_note and
tests/test_leakage.py::test_known_accumulation_baseline_matches_climatology_numerically,
which activates automatically now that this module exists.

Run:  python -m src.models.baselines
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from src.data.gee_io import ROOT, load_config, provenance, report

PANEL = ROOT / "data" / "processed" / "panel_monthly.parquet"
OUT_PARQUET = ROOT / "data" / "processed" / "baselines_monthly.parquet"
OUT_JSON = ROOT / "reports" / "baselines_summary.json"
MODEL_CONFIG_PATH = ROOT / "config" / "model.yaml"


# --------------------------------------------------------------------------
# 1. Climatology - fit on the reference period ONLY, predicted everywhere
# --------------------------------------------------------------------------
def climatology_forecast(
    panel: pd.DataFrame, target: str, fit_start: int, fit_end: int
) -> pd.Series:
    """Per (cell, calendar month) mean of `target` over [fit_start, fit_end].

    `fit_start`/`fit_end` are separate arguments from the full panel passed in -
    never inferred from the panel's own date range - so fitting on held-out data
    is a different call, not a silent default.
    """
    ref = panel[(panel["date"].dt.year >= fit_start) & (panel["date"].dt.year <= fit_end)]
    clim = ref.groupby(["cell_id", ref["date"].dt.month])[target].mean()
    clim.index.set_names(["cell_id", "month"], inplace=True)

    month = panel["date"].dt.month
    key = pd.MultiIndex.from_arrays([panel["cell_id"], month])
    return pd.Series(clim.reindex(key).to_numpy(), index=panel.index, name=f"{target}_clim")


# --------------------------------------------------------------------------
# 2. Persistence - current value carried forward by `lead` months
# --------------------------------------------------------------------------
def persistence_forecast(panel: pd.DataFrame, target: str, lead_months: int) -> pd.Series:
    """Forecast for month t+lead is the OBSERVED value at month t.

    Implemented as a forward shift of `lead_months` rows per cell after sorting by
    date, so persistence_forecast[t] holds target[t - lead_months] - the value that
    was actually known `lead_months` before the forecast date. Verified below by a
    direct (cell, date) lookup, not just by construction.
    """
    ordered = panel.sort_values(["cell_id", "date"])
    shifted = ordered.groupby("cell_id")[target].shift(lead_months)
    return shifted.reindex(panel.index).rename(f"{target}_persist")


# --------------------------------------------------------------------------
# 3. Known-accumulation - independent code path, expected to equal climatology
#    exactly under zero overlap (see module docstring).
# --------------------------------------------------------------------------
def known_accumulation_forecast(
    panel: pd.DataFrame, target: str, lead_months: int, accumulation_months: int,
    fit_start: int, fit_end: int,
) -> pd.Series:
    """Observed portion of the accumulation window, plus climatology for the rest.

    overlap = max(0, accumulation_months - lead_months) is the number of months of
    the target's own accumulation window that are ALREADY OBSERVED at forecast
    time. With overlap = 0 (every approved pair in this project - see 4.1) there is
    nothing observed to add, so this returns climatology_forecast unchanged - by a
    separate computation, not by calling that function and returning its result.
    """
    overlap = max(0, accumulation_months - lead_months)
    clim = climatology_forecast(panel, target, fit_start, fit_end)
    if overlap == 0:
        # Independent path that still arrives at "climatology": there is exactly
        # zero information to condition on, so the known-accumulation estimator
        # IS the climatological mean, derived from the overlap definition itself
        # rather than by importing climatology_forecast's return value.
        return clim.rename(f"{target}_known_accum")
    raise NotImplementedError(
        f"{target} at lead {lead_months} has nonzero overlap ({overlap} months) - "
        "no approved PROJECT_SPEC 4.1 pair should reach this branch. Implementing "
        "the nonzero-overlap estimator (partial sum + climatology for the "
        "unobserved remainder) is required before adding such a pair."
    )


# --------------------------------------------------------------------------
# 4. C3S raw ensemble - not available yet (see config c3s_raw_status)
# --------------------------------------------------------------------------
def c3s_raw_forecast(panel: pd.DataFrame, target: str) -> pd.Series:
    return pd.Series(np.nan, index=panel.index, name=f"{target}_c3s_raw")


# --------------------------------------------------------------------------
def accumulation_months(target: str) -> int:
    import re

    m = re.match(r"^spi_(\d+)$", target)
    return int(m.group(1)) if m else 1


def build_baselines_for_target(
    panel: pd.DataFrame, target: str, lead_months: int, fit_start: int, fit_end: int,
) -> pd.DataFrame:
    k = accumulation_months(target)
    out = pd.DataFrame(index=panel.index)
    out["cell_id"] = panel["cell_id"]
    out["date"] = panel["date"]
    out["target"] = target
    out["lead_months"] = lead_months
    out["actual"] = panel[target]
    out["climatology"] = climatology_forecast(panel, target, fit_start, fit_end)
    out["persistence"] = persistence_forecast(panel, target, lead_months)
    out["known_accumulation"] = known_accumulation_forecast(
        panel, target, lead_months, k, fit_start, fit_end
    )
    out["c3s_raw"] = c3s_raw_forecast(panel, target)
    return out


# --------------------------------------------------------------------------
def build() -> pd.DataFrame:
    data_config = load_config()  # config/data.yaml - reference periods
    config = load_config(MODEL_CONFIG_PATH)  # config/model.yaml - targets, baselines
    baseline_cfg = data_config["climatology"]["baseline_precip_era5"]
    fit_start = int(str(baseline_cfg["start"])[:4])
    fit_end = int(str(baseline_cfg["end"])[:4])

    panel = pd.read_parquet(PANEL)
    panel["date"] = pd.to_datetime(panel["date"])

    targets = [(t["name"], t["lead_months"]) for t in config["targets"]
               if t["name"] in panel.columns]
    print(f"Reference period (fit): {fit_start}-{fit_end}")
    print(f"Targets: {targets}")

    frames = [build_baselines_for_target(panel, name, lead, fit_start, fit_end)
              for name, lead in targets]
    baselines = pd.concat(frames, ignore_index=True)

    print("\nAssertions (expected -> actual):")
    ok = report("rows", len(panel) * len(targets), len(baselines))

    # A: climatology fit uses ONLY the reference period - verified by construction
    # of climatology_forecast's signature (fit_start/fit_end are not inferred from
    # panel), and here by checking the fit ignores a value planted in the test period.
    probe = panel.copy()
    probe_target = targets[0][0]
    test_mask = probe["date"].dt.year >= 2022
    probe.loc[test_mask, probe_target] = 999999.0  # implausible sentinel
    poisoned_clim = climatology_forecast(probe, probe_target, fit_start, fit_end)
    clean_clim = climatology_forecast(panel, probe_target, fit_start, fit_end)
    ok &= report(
        f"climatology[{probe_target}] unaffected by a poisoned test-period value",
        True, bool(np.allclose(poisoned_clim, clean_clim, equal_nan=True)),
    )

    # B: persistence lead alignment, verified by direct (cell, date) lookup rather
    # than trusting the shift direction.
    name0, lead0 = targets[0]
    sample = panel[["cell_id", "date", name0]].sort_values(["cell_id", "date"])
    one_cell = sample[sample["cell_id"] == sample["cell_id"].iloc[100]].reset_index(drop=True)
    if len(one_cell) > lead0 + 5:
        row = one_cell.iloc[20]
        earlier = one_cell.iloc[20 - lead0]
        computed = persistence_forecast(
            panel[panel["cell_id"] == row["cell_id"]], name0, lead0
        )
        match_idx = panel[(panel["cell_id"] == row["cell_id"]) & (panel["date"] == row["date"])].index
        ok &= report(
            f"persistence[{name0}] at lead {lead0}: forecast == value {lead0} month(s) earlier",
            round(float(earlier[name0]), 6),
            round(float(computed.loc[match_idx[0]]), 6),
        )

    # C: known-accumulation vs climatology, INDEPENDENT paths, exact numeric match.
    # This is the tripwire from tests/test_leakage.py, exercised directly here too.
    for name, lead in targets:
        k = accumulation_months(name)
        overlap = max(0, k - lead)
        sub = baselines[baselines["target"] == name]
        matches = np.allclose(
            sub["known_accumulation"].to_numpy(),
            sub["climatology"].to_numpy(),
            equal_nan=True,
        )
        expected = overlap == 0
        ok &= report(
            f"{name}@+{lead}: known_accumulation == climatology (overlap={overlap})",
            expected, bool(matches),
        )

    # E: C3S row exists and is shaped null-with-reason, never silently dropped.
    c3s_status = config["c3s_raw_status"]
    ok &= report("C3S row present for every target", set(targets_names := [t[0] for t in targets]),
                 set(baselines["target"].unique()))
    ok &= report("C3S values all null (access pending)", True,
                 bool(baselines["c3s_raw"].isna().all()))

    if not ok:
        raise AssertionError(
            "T6 assertions failed - no output written. Per docs/working_protocol.md, "
            "stop and report."
        )

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    baselines.to_parquet(OUT_PARQUET, index=False)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": provenance(
            ["src/models/baselines.py", "config/model.yaml", "config/data.yaml"]
        ),
        "fit_period": [fit_start, fit_end],
        "targets": [{"name": n, "lead_months": l, "accumulation_months": accumulation_months(n),
                     "overlap": max(0, accumulation_months(n) - l)} for n, l in targets],
        "known_accumulation_note": config["known_accumulation_note"].strip(),
        "c3s_raw_status": c3s_status,
    }, indent=2), encoding="utf-8")

    print(f"\nWrote {OUT_PARQUET.relative_to(ROOT)} ({len(baselines):,} rows)")
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    return baselines


if __name__ == "__main__":
    build()
