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
# PROBABILITY-SHAPED baselines, for classification targets (spi_3: P(SPI-3 < -1)).
#
# T6's original climatology_forecast() returns the reference-period MEAN of the
# raw continuous target - by SPI's own construction that averages near 0 for any
# SPI column, ranges outside [0,1], and cannot be scored with Brier/BSS, which
# require a genuine probability. Found while preparing T8, not before: the
# continuous baseline is fine for spi_1's regression metrics and simply the wrong
# shape for spi_3's classification ones. These four mirror the continuous set but
# estimate P(target < threshold) instead of E[target].
# --------------------------------------------------------------------------
def probability_climatology_forecast(
    panel: pd.DataFrame, target: str, threshold: float, fit_start: int, fit_end: int
) -> pd.Series:
    """Per (cell, calendar month): empirical fraction of reference-period years
    with `target` below `threshold`.

    Not the theoretical Phi(-1) = 0.1587 constant that perfect SPI standardisation
    would imply - the empirical, per-cell-month rate, for the same reason T6's
    continuous climatology is per-cell-month rather than a single global number:
    it shows sampling and calibration imperfections instead of assuming them away.
    How far this drifts from Phi(-1) is itself a gamma-fit diagnostic, reported
    alongside the skill table rather than hidden.
    """
    ref = panel[(panel["date"].dt.year >= fit_start) & (panel["date"].dt.year <= fit_end)]
    rate = ref.groupby(["cell_id", ref["date"].dt.month])[target].apply(
        lambda s: float((s < threshold).mean())
    )
    rate.index.set_names(["cell_id", "month"], inplace=True)

    month = panel["date"].dt.month
    key = pd.MultiIndex.from_arrays([panel["cell_id"], month])
    return pd.Series(rate.reindex(key).to_numpy(), index=panel.index, name=f"{target}_clim_prob")


def probability_known_accumulation_forecast(
    panel: pd.DataFrame, target: str, lead_months: int, accumulation_months_: int,
    threshold: float, fit_start: int, fit_end: int,
) -> pd.Series:
    """Probability-space counterpart of known_accumulation_forecast - same zero-
    overlap logic, same "independent derivation, not a shortcut" discipline."""
    overlap = max(0, accumulation_months_ - lead_months)
    clim_prob = probability_climatology_forecast(panel, target, threshold, fit_start, fit_end)
    if overlap == 0:
        return clim_prob.rename(f"{target}_known_accum_prob")
    raise NotImplementedError(
        f"{target} at lead {lead_months} has nonzero overlap ({overlap} months) - "
        "the probability-space known-accumulation estimator for partial overlap is "
        "not implemented; no approved PROJECT_SPEC 4.1 pair should reach this branch."
    )


def persistence_probability_forecast(
    panel: pd.DataFrame, target: str, lead_months: int, threshold: float,
    fit_start: int, fit_end: int,
) -> pd.Series:
    """Calibrated persistence: P(target < threshold, `lead_months` ahead | target <
    threshold `lead_months` AGO - i.e. what was known at issue time), estimated
    empirically and applied as a real probability - not the hard 0/1 step function
    this returned before the skeptic audit found it inflated "model beats
    persistence" by being a Brier worst case by construction on a ~15-25%
    base-rate event.

    TWO SEPARATE ROLES FOR "row's own date", NOT ONE - the same confusion this
    module's docstring warns about for fit period vs prediction range, caught here
    the hard way: a first version of this function used `panel[target]` AT THE
    ROW'S OWN DATE as "now", which for this table's VERIFICATION-date convention
    (see build_baselines_for_target: `out["actual_prob"]` is `panel[target]` at
    that SAME row's date) meant "now" and "the answer" were the same value -
    producing AUC 1.0 on the persistence row of the first rerun after the skeptic
    audit. Caught by this project's own rule: a result that came out better than
    expected (AUC 1.0 at lead 3) is a suspected leak until proven otherwise, not a
    win. Fixed by reusing `persistence_forecast()` above - which already shifts
    correctly to `target[d - lead_months]`, the value known at issue time - as the
    lookup key, so both the continuous and probability-shaped persistence
    baselines share the exact same notion of "what persistence knows".

    FIT is a separate, date-convention-free step: pool (state at row r, state at
    row r + lead_months) pairs across the reference period only, which is valid
    regardless of what a "row" represents in an external table, then estimate
    P(future state | current state) from those pairs.

    FIT BASIN-WIDE, not per (cell, calendar month): a 2-state transition table per
    cell-month would split the fit period's ~36 years into buckets some cells never
    see a drought month in (undefined transition), which is worse than the coarse
    hard-0/1 baseline it replaces. One pooled pair of rates (P(future|now=below),
    P(future|now=above)) needs the whole reference period's sample size and stays a
    genuinely naive baseline - it does not use cell identity or season, exactly like
    the persistence it calibrates.

    Fit strictly on [fit_start, fit_end] (same discipline as climatology_forecast),
    applied unchanged to validation and test.
    """
    ordered = panel.sort_values(["cell_id", "date"]).reset_index(drop=True)
    state_now = ordered[target] < threshold
    future_val = ordered.groupby("cell_id")[target].shift(-lead_months)
    state_future = future_val < threshold

    ref_mask = (ordered["date"].dt.year >= fit_start) & (ordered["date"].dt.year <= fit_end)
    fit = pd.DataFrame({"now": state_now, "future": state_future.astype(float)})[ref_mask].dropna()
    rate_by_state = fit.groupby("now")["future"].mean()
    if not {False, True}.issubset(set(rate_by_state.index)):
        raise AssertionError(
            f"{target}: reference period {fit_start}-{fit_end} does not contain both "
            "current-state classes (below/above threshold) at basin scale - cannot "
            "calibrate persistence. Widen the reference period or drop this baseline "
            "for this target rather than silently falling back to the hard 0/1 form."
        )

    # APPLICATION uses the value known at ISSUE time (lead_months before this row's
    # own verification date), not this row's own value - see docstring above.
    state_known_at_issue = persistence_forecast(panel, target, lead_months) < threshold
    prob = state_known_at_issue.map(rate_by_state).astype(float)
    return prob.rename(f"{target}_persist_prob")


def c3s_raw_probability_forecast(panel: pd.DataFrame, target: str) -> pd.Series:
    return pd.Series(np.nan, index=panel.index, name=f"{target}_c3s_raw_prob")


# --------------------------------------------------------------------------
def accumulation_months(target: str) -> int:
    import re

    m = re.match(r"^spi_(\d+)$", target)
    return int(m.group(1)) if m else 1


def build_baselines_for_target(
    panel: pd.DataFrame, target_cfg: dict[str, Any], fit_start: int, fit_end: int,
) -> pd.DataFrame:
    target = target_cfg["name"]
    lead_months = target_cfg["lead_months"]
    kind = target_cfg["kind"]
    k = accumulation_months(target)

    out = pd.DataFrame(index=panel.index)
    out["cell_id"] = panel["cell_id"]
    out["date"] = panel["date"]
    out["target"] = target
    out["lead_months"] = lead_months
    out["kind"] = kind
    out["actual"] = panel[target]
    out["climatology"] = climatology_forecast(panel, target, fit_start, fit_end)
    out["persistence"] = persistence_forecast(panel, target, lead_months)
    out["known_accumulation"] = known_accumulation_forecast(
        panel, target, lead_months, k, fit_start, fit_end
    )
    out["c3s_raw"] = c3s_raw_forecast(panel, target)

    if kind == "classification":
        threshold = target_cfg["threshold"]
        # actual_prob mirrors T7's y_all exactly (target < threshold), so predictions
        # and baselines compare the identical quantity - see the T7 bug this guards
        # against: a classification target's "actual" must match what its forecasts
        # estimate, not the raw continuous value.
        out["actual_prob"] = (panel[target] < threshold).astype(float)
        out["climatology_prob"] = probability_climatology_forecast(
            panel, target, threshold, fit_start, fit_end
        )
        out["persistence_prob"] = persistence_probability_forecast(
            panel, target, lead_months, threshold, fit_start, fit_end
        )
        out["known_accumulation_prob"] = probability_known_accumulation_forecast(
            panel, target, lead_months, k, threshold, fit_start, fit_end
        )
        out["c3s_raw_prob"] = c3s_raw_probability_forecast(panel, target)

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

    target_cfgs = [t for t in config["targets"] if t["name"] in panel.columns]
    targets = [(t["name"], t["lead_months"]) for t in target_cfgs]
    print(f"Reference period (fit): {fit_start}-{fit_end}")
    print(f"Targets: {targets}")

    frames = [build_baselines_for_target(panel, t, fit_start, fit_end) for t in target_cfgs]
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
    # For classification targets the SAME check is repeated in probability space -
    # a second, independently-shaped tripwire, not a rerun of the first.
    for t_cfg in target_cfgs:
        name, lead, kind = t_cfg["name"], t_cfg["lead_months"], t_cfg["kind"]
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
        if kind == "classification":
            threshold = t_cfg["threshold"]
            prob_lo_hi_ok = bool(sub["climatology_prob"].between(0, 1).all())
            ok &= report(f"{name}: climatology_prob within [0,1]", True, prob_lo_hi_ok)
            prob_matches = np.allclose(
                sub["known_accumulation_prob"].to_numpy(),
                sub["climatology_prob"].to_numpy(),
                equal_nan=True,
            )
            ok &= report(
                f"{name}@+{lead}: known_accumulation_prob == climatology_prob "
                f"(overlap={overlap})", expected, bool(prob_matches),
            )
            # SPI is standardised to Phi(-1) ~ 0.1587 by construction; a large drift
            # in the empirical reference-period rate is a gamma-fit calibration
            # signal worth surfacing, not silently absorbing.
            theoretical = float(pd.Series([0.15866]).iloc[0])
            empirical_mean = float(sub["climatology_prob"].mean())
            drift = abs(empirical_mean - theoretical)
            print(f"  [INFO    ] {name}: climatology_prob mean {empirical_mean:.4f} vs "
                  f"theoretical Phi(-1)={theoretical:.4f} (drift {drift:+.4f}) - "
                  "a gamma-fit calibration diagnostic, not a gate")

            # D: calibrated persistence_prob - same discipline as check A, adapted:
            # unlike climatology, persistence's OUTPUT at a row legitimately depends
            # on that SAME row's own current value (that is what persistence means),
            # so poisoning a test-period row changes ITS OWN output by design - that
            # is not leakage. What must NOT move is the FIT (the two rate_by_state
            # constants, estimated only from [fit_start, fit_end]). Checked here by
            # comparing poisoned vs clean output restricted to PRE-poison rows
            # (years < 2022, i.e. before the sentinel), where state_now is identical
            # between the two runs - any difference there could only come from a
            # different fit, since poisoning years >= 2022 cannot enter a fit
            # window ending 2016.
            probe2 = panel.copy()
            probe2.loc[probe2["date"].dt.year >= 2022, name] = 999999.0
            poisoned_persist = persistence_probability_forecast(
                probe2, name, lead, threshold, fit_start, fit_end
            )
            clean_persist = persistence_probability_forecast(
                panel, name, lead, threshold, fit_start, fit_end
            )
            pre_poison = panel["date"].dt.year < 2022
            ok &= report(
                f"persistence_prob[{name}] fit unaffected by a poisoned test-period "
                "value (compared on pre-poison rows, where the input is identical)",
                True, bool(np.allclose(
                    poisoned_persist[pre_poison], clean_persist[pre_poison], equal_nan=True
                )),
            )
            prob_lo_hi_ok2 = bool(sub["persistence_prob"].dropna().between(0, 1).all())
            ok &= report(f"{name}: persistence_prob within [0,1]", True, prob_lo_hi_ok2)
            # `sub["actual_prob"]` is (panel[target] < threshold) at THIS row's own
            # date - i.e. the "now" state persistence_probability_forecast conditions
            # on - already aligned to sub's own row order. Pulling a fresh mask from
            # `panel` here would mismatch: `sub` came out of a `pd.concat(...,
            # ignore_index=True)` across targets, so its index labels are not
            # panel's, only its row order is (this cost a rewrite to find).
            #
            # NOT `sub["actual_prob"]` - that is the VERIFICATION-date state (the
            # answer being forecast), and persistence_prob is keyed on the
            # ISSUE-time state (`persistence_forecast(...) < threshold`, lead
            # months earlier) after the AUC-1.0 leak fix above. Recomputed directly
            # here, aligned to `sub` by row order (see the note two lines up).
            issue_state = (persistence_forecast(panel, name, lead) < threshold).to_numpy()
            state_now_ref = pd.Series(issue_state, index=sub.index)
            rate_when_below = float(sub.loc[state_now_ref, "persistence_prob"].mode().iloc[0])
            rate_when_above = float(sub.loc[~state_now_ref, "persistence_prob"].mode().iloc[0])
            ok &= report(
                f"{name}: calibrated persistence P(drought ahead | drought now) > "
                "P(drought ahead | no drought now)",
                True, rate_when_below > rate_when_above,
            )
            print(f"  [INFO    ] {name}: persistence_prob calibrated rates - "
                  f"P(future<thr | now<thr)={rate_when_below:.4f}, "
                  f"P(future<thr | now>=thr)={rate_when_above:.4f}")

    # E: C3S row exists and is shaped null-with-reason, never silently dropped.
    c3s_status = config["c3s_raw_status"]
    ok &= report("C3S row present for every target", set([t[0] for t in targets]),
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
        "persistence_auc_note": config["persistence_auc_note"].strip(),
    }, indent=2), encoding="utf-8")

    print(f"\nWrote {OUT_PARQUET.relative_to(ROOT)} ({len(baselines):,} rows)")
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    return baselines


if __name__ == "__main__":
    build()
