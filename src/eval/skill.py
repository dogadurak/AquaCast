"""T8 - the skill table: does the model beat climatology, persistence and the
known-accumulation baseline? This is Phase 0's gate question.

ANALYSIS POPULATION, not the full grid. panel_monthly.parquet (and therefore
predictions.parquet and baselines_monthly.parquet) covers all 2,820 exported grid
cells - the basin plus a one-cell ring kept for boundary insurance (T1) and cells
below the cropland threshold. Scoring over all 2,820 would violate axis (a) of the
comparison rule at the head of .claude/skills/failure-modes/SKILL.md: ring cells
sit partly on the Taurus flank, a different precipitation regime, mixed in with the
basin proper would corrupt every metric in this table. Restricted here to
`in_hydrobasins & ~in_akarcay_lobe & crop_frac_2021 >= mask.min_fraction` - the
"best approximation" population established in T1/T2, pending the official DSI
boundary (reports/phase0_log.md list B).

PER-FORECAST-DATE AGGREGATION, never pooled. CLAUDE.md rule 4: ~2,000 cells at one
date are not 2,000 independent samples. Every metric is computed WITHIN one date
(across its ~1,800 analysis cells - real cross-sectional sample size) and the
headline number is the MEAN of that per-date series across the ~45-48 test months -
never a single number computed by pooling all (cell, date) rows together.

CLASSIFICATION vs REGRESSION METRICS, never mixed. spi_3 (primary, classification):
AUC, Brier score, Brier Skill Score against climatology. spi_1 (secondary,
regression, reported per calendar month per the T5 finding): MAE, RMSE, R², skill
score against each baseline.

Run:  python -m src.eval.skill
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import brier_score_loss, r2_score, roc_auc_score

from src.data.gee_io import ROOT, load_config, provenance

PANEL = ROOT / "data" / "processed" / "panel_monthly.parquet"
PREDICTIONS = ROOT / "data" / "processed" / "predictions.parquet"
BASELINES = ROOT / "data" / "processed" / "baselines_monthly.parquet"
MODEL_CONFIG_PATH = ROOT / "config" / "model.yaml"

SKILL_TABLE_MD = ROOT / "reports" / "skill_table.md"


def git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=15
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------
def analysis_population(config: dict[str, Any]) -> pd.DataFrame:
    """cell_id -> membership, restricted to the population used everywhere since T1."""
    panel_cols = pd.read_parquet(
        PANEL, columns=["cell_id", "in_hydrobasins", "in_akarcay_lobe", "crop_frac_2021"]
    ).drop_duplicates("cell_id")
    threshold = config["grid"]["mask"]["min_fraction"] if "grid" in config else 0.5
    keep = (
        panel_cols["in_hydrobasins"]
        & ~panel_cols["in_akarcay_lobe"]
        & (panel_cols["crop_frac_2021"] >= threshold)
    )
    return panel_cols.loc[keep, ["cell_id"]].reset_index(drop=True)


# --------------------------------------------------------------------------
# per-forecast-date metrics - each computed WITHIN one date, across its cells
# --------------------------------------------------------------------------
def per_date_regression_metrics(df: pd.DataFrame, actual_col: str, pred_col: str) -> pd.DataFrame:
    rows = []
    for date, g in df.groupby("date"):
        g = g.dropna(subset=[actual_col, pred_col])
        if len(g) < 10:  # too few analysis cells that date to trust a spatial R2
            continue
        err = g[pred_col] - g[actual_col]
        r2 = r2_score(g[actual_col], g[pred_col]) if g[actual_col].nunique() > 1 else np.nan
        rows.append({"date": date, "n_cells": len(g), "mae": err.abs().mean(),
                     "rmse": float(np.sqrt((err ** 2).mean())), "r2": r2})
    return pd.DataFrame(rows)


def per_date_classification_metrics(
    df: pd.DataFrame, actual_col: str, pred_col: str,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Returns (per-date metrics, dates dropped entirely, dates with AUC undefined).

    AUC is undefined with one class in a date's cells - which happens here: SPI-3
    below threshold is a ~15-25% event, so over ~45 test months some will show it
    nowhere in the basin (rate=0) or almost everywhere at once during a widespread
    event (rate=1). Brier is NOT undefined in that case - it is a proper scoring
    rule against a 0/1 outcome regardless of whether the date's cells are all one
    class - so a single-class date drops `auc` to NaN (skipped by summarise()'s
    mean) but keeps its `brier` row. This was a real defect until the skeptic audit
    found it: the old code dropped BOTH metrics together on a single-class-only
    condition, silently discarding Brier on the 2 widest-spread drought months in
    the test period (2023-01, 2025-03, both rate=1.0) along with 8 driest ones -
    22% of the record, from a table whose whole point is not silently thinning data.
    `dates_dropped_entirely` still exists for the <10-cells case, where nothing is
    computable.
    """
    rows, dropped_entirely, auc_undefined = [], [], []
    for date, g in df.groupby("date"):
        g = g.dropna(subset=[actual_col, pred_col])
        if len(g) < 10:  # too few analysis cells that date to trust anything
            dropped_entirely.append(str(pd.Timestamp(date).date()))
            continue
        single_class = g[actual_col].nunique() < 2
        if single_class:
            auc_undefined.append(str(pd.Timestamp(date).date()))
        auc = np.nan if single_class else roc_auc_score(g[actual_col], g[pred_col])
        brier = brier_score_loss(g[actual_col], g[pred_col])
        rows.append({"date": date, "n_cells": len(g), "auc": auc, "brier": brier})
    return pd.DataFrame(rows), dropped_entirely, auc_undefined


def summarise(per_date: pd.DataFrame, cols: list[str]) -> dict[str, float]:
    """Mean across forecast dates - the aggregation step, never a pooled row-level stat."""
    return {c: float(per_date[c].mean()) if len(per_date) else float("nan") for c in cols}


# --------------------------------------------------------------------------
def build_regression_row(
    df: pd.DataFrame, pred_col: str, label: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """`df` must carry 'date', 'actual' and `pred_col`. One row = one method's summary.

    Returns the per-date DataFrame too (indexed by date) - not for the table, for
    the paired significance test in build_target_table, which needs the model's
    and a baseline's per-date series aligned on the SAME dates, not just their
    already-averaged means.
    """
    per_date = per_date_regression_metrics(df, "actual", pred_col)
    summary = summarise(per_date, ["mae", "rmse", "r2"])
    summary["method"] = label
    summary["n_dates"] = int(len(per_date))
    return summary, per_date.set_index("date") if len(per_date) else per_date


def build_classification_row(
    df: pd.DataFrame, pred_col: str, label: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    per_date, dropped_entirely, auc_undefined = per_date_classification_metrics(
        df, "actual_prob", pred_col
    )
    summary = summarise(per_date, ["auc", "brier"])
    summary["method"] = label
    # Brier's own denominator: every date with >=10 cells, single-class included.
    summary["n_dates"] = int(len(per_date))
    # AUC's own denominator: single-class dates are excluded from just this mean.
    summary["n_dates_auc"] = int(len(per_date) - len(auc_undefined))
    summary["n_dates_dropped_entirely"] = len(dropped_entirely)
    summary["n_dates_auc_undefined"] = len(auc_undefined)
    summary["dates_auc_undefined"] = auc_undefined
    return summary, per_date.set_index("date") if len(per_date) else per_date


def skill_score(model_val: float, baseline_val: float) -> float:
    """1 - error_model/error_baseline. Positive = MODEL beats THIS baseline.

    The return value is the MODEL's skill relative to the baseline passed in -
    it is stored on the baseline's own table row (there is nowhere else to put
    a per-baseline number), which the skeptic audit flagged as a real defect in
    the RENDERED table, not in this arithmetic: `render_markdown` printed it
    under a "(vs model)" suffix on the climatology row, which a reader parses as
    "climatology's skill against the model" - the opposite of what the number
    means. E.g. spi_1@+1: skill_score(model_rmse=0.886, climatology_rmse=0.791)
    = -0.120, correctly meaning the MODEL is 12% worse than climatology - but
    rendered as "climatology ... skill -0.120 (vs model)" it reads as
    "climatology is 12% worse than the model", backwards. Fixed by relabelling
    in render_markdown (column header states whose skill it is, no per-cell
    "(vs X)" suffix that can be read either direction) rather than by negating
    the arithmetic, which is correct as written.
    """
    if baseline_val in (0, None) or np.isnan(baseline_val) or np.isnan(model_val):
        return float("nan")
    return 1.0 - model_val / baseline_val


def paired_significance(model_series: pd.Series, baseline_series: pd.Series) -> dict[str, Any]:
    """Paired test of model vs baseline on the SAME per-date metric values, not on
    the two already-averaged means the table prints.

    Added after the first skeptic audit: every headline number in this table was
    a mean over ~35-47 dates with no measure of whether the two methods' means
    are distinguishable at all. Reports THREE tests, none declared "primary" -
    an earlier version of this function and its table footnote claimed Wilcoxon
    should be read as the conservative, primary number because the paired
    t-test's variance estimator is anti-conservative under positive
    autocorrelation. The SECOND skeptic audit found that claim indefensible on
    two counts: (1) Wilcoxon's own null variance formula assumes independent
    differences too - a rank transform confers no special robustness to serial
    dependence, so calling it "the conservative one" overstated what is actually
    known; (2) the premise (positive autocorrelation) does not hold uniformly -
    measured lag-1 autocorrelation of the paired differences varies by
    comparison (large for spi_3 vs climatology, near zero for spi_1's rows) - and
    applying a blanket rule regardless let the ONE comparison that happened to
    clear 0.05 under Wilcoxon (spi_1 vs persistence, MAE) read as significant
    while the same comparison's t-test (0.065) did not - the report's only
    positive claim was standing on a rule invented to justify it, not on
    evidence. Fixed by removing the "primary" framing entirely: t-test, Wilcoxon
    and a sign test (the least assumption-heavy of the three - only uses which
    method won each date, not the size of the gap) are reported side by side
    with the measured autocorrelation, and the table's footnote leaves the
    reader to judge rather than nominating a winner.

    WHAT THIS DOES NOT FIX, stated rather than hidden: consecutive SPI-3 forecast
    dates share up to 2 of their 3 accumulation months, so the ~35-45 test dates
    are NOT independent draws - all three tests assume independence in some form,
    so p-values here are generally optimistic (too small), not rigorous. Treat
    them as "is the gap even plausibly bigger than noise", not as a formal
    significance claim - and see the table's footnote for the multiple-
    comparisons problem this function does not correct for either.
    """
    common = model_series.index.intersection(baseline_series.index)
    m = model_series.loc[common].to_numpy()
    b = baseline_series.loc[common].to_numpy()
    finite = np.isfinite(m) & np.isfinite(b)
    m, b = m[finite], b[finite]
    n = len(m)
    if n < 5 or np.allclose(m, b):
        return {
            "n_paired": n, "identical": bool(n >= 5 and np.allclose(m, b)),
            "p_ttest": float("nan"), "p_wilcoxon": float("nan"), "p_sign": float("nan"),
            "lag1_autocorr": float("nan"),
        }
    diff = m - b
    t_res = stats.ttest_rel(m, b)
    try:
        w_res = stats.wilcoxon(m, b)
        p_wilcoxon = float(w_res.pvalue)
    except ValueError:
        # all differences zero, or too few non-zero differences - wilcoxon refuses
        p_wilcoxon = float("nan")
    # Sign test: does the model win on more than half the dates, ignoring margin
    # size entirely - the test least sensitive to the autocorrelation/skew
    # issues that make the t-test and Wilcoxon disagree with each other here.
    wins = int((diff < 0).sum())  # model_val < baseline_val = model wins (lower error/Brier)
    ties = int((diff == 0).sum())
    n_decisive = n - ties
    p_sign = float(stats.binomtest(wins, n_decisive, p=0.5).pvalue) if n_decisive > 0 else float("nan")
    # Lag-1 autocorrelation of the paired differences - the diagnostic that
    # replaces the withdrawn "Wilcoxon is conservative" claim: report the
    # measurement, let the reader judge, per this project's own pattern (bake in
    # the measurement, keep the interpretation out of the code).
    if n > 3 and np.std(diff) > 0:
        lag1 = float(np.corrcoef(diff[:-1], diff[1:])[0, 1])
    else:
        lag1 = float("nan")
    return {
        "n_paired": n,
        "mean_diff_model_minus_baseline": float(np.mean(diff)),
        "p_ttest": float(t_res.pvalue),
        "p_wilcoxon": p_wilcoxon,
        "p_sign": p_sign,
        "sign_wins_model": wins, "sign_n_decisive": n_decisive,
        "lag1_autocorr": lag1,
    }


# --------------------------------------------------------------------------
def build_target_table(
    target_cfg: dict[str, Any], predictions: pd.DataFrame, baselines: pd.DataFrame,
    population: pd.DataFrame, test_start: str, test_end: str,
) -> dict[str, Any]:
    name, lead, kind = target_cfg["name"], target_cfg["lead_months"], target_cfg["kind"]
    ts, te = pd.Timestamp(test_start), pd.Timestamp(test_end)

    pred = predictions[predictions["target"] == name].merge(population, on="cell_id", how="inner")
    base = baselines[baselines["target"] == name].merge(population, on="cell_id", how="inner")

    # DATE CONVENTIONS DIFFER BETWEEN THE TWO SOURCES, and treating "date" as the
    # same column meant something in each was a real bug caught while building this
    # table: predictions.parquet's "date" is the forecast ISSUE date (T7's `actual`
    # is the target's value at issue_date + lead - see train.py's label = shift(-lead)).
    # baselines_monthly.parquet's "date" is the target's own VERIFICATION date (T6's
    # `actual` is panel[target] at that row's own date, with persistence looking
    # BACKWARD by lead to build its forecast). Confirmed empirically: shifting
    # predictions' date forward by `lead` months reproduces baselines' date-indexed
    # actual_prob series with 45/45 exact matches, zero mismatches.
    #
    # Canonicalised here to VERIFICATION date - the month a forecast is ABOUT, which
    # is what "skill at forecasting March 2023" means to a reader - by shifting
    # predictions forward. Filtering both by the same window on the same date
    # meaning is what makes the comparison a comparison rather than two averages
    # over overlapping-but-different sets of forecast instances.
    pred = pred.copy()
    pred["date"] = pred["date"] + pd.DateOffset(months=lead)
    pred = pred[(pred["date"] >= ts) & (pred["date"] <= te) & (pred["split"] == "test")]

    # Restrict baselines to the EXACT verification dates the model produced a
    # forecast for - not just the [ts, te] window. The model's earliest issue date
    # is test_start (2022-01), so its earliest verification date is test_start+lead
    # (2022-04 for lead=3): baselines filtered by [ts,te] alone would include
    # test_start .. test_start+lead-1 (Jan-Mar 2022 here) where the model made no
    # forecast at all, which is not a comparison, it is extra credit or blame with
    # nothing on the other side of the ledger. Caught by re-checking date coverage
    # after the lead-shift fix above, not anticipated in the original plan.
    base = base[base["date"].isin(pred["date"].unique())]

    # Prove the alignment rather than trust the comment above it: for every date
    # both sides cover, the raw target value they each derive "actual" from must
    # agree exactly. If a future change to either T6 or T7 breaks this silently,
    # this is what catches it - not a rerun that "looks plausible".
    # Column NAMES differ too: predictions.parquet's binary indicator is "actual"
    # (T7's fix), baselines_monthly.parquet's is "actual_prob" - same quantity,
    # different name, checked here rather than assumed to match.
    pred_check_col = "actual"
    base_check_col = "actual_prob" if kind == "classification" else "actual"
    p_rate = pred.groupby("date")[pred_check_col].mean()
    b_rate = base.groupby("date")[base_check_col].mean()
    common_dates = p_rate.index.intersection(b_rate.index)
    if len(common_dates) == 0:
        raise AssertionError(
            f"{name}: after date-convention alignment, predictions and baselines "
            "share zero common dates - the alignment is broken, not just imprecise"
        )
    mismatch = ~np.isclose(p_rate.loc[common_dates], b_rate.loc[common_dates], equal_nan=True)
    if mismatch.any():
        raise AssertionError(
            f"{name}: {int(mismatch.sum())} of {len(common_dates)} aligned dates have "
            f"predictions.actual != baselines.actual after the lead-month date shift - "
            "the two sources disagree about the target's own value, which should be "
            "impossible since both derive it from the same panel column"
        )

    result: dict[str, Any] = {"target": name, "lead_months": lead, "kind": kind}

    if kind == "regression":
        model_row, model_per_date = build_regression_row(pred, "prediction", "model")
        rows = [model_row]
        per_date_by_method = {"model": model_per_date}
        for base_col, label in [
            ("climatology", "climatology"), ("persistence", "persistence"),
            ("known_accumulation", "known_accumulation"),
        ]:
            r, pd_r = build_regression_row(base, base_col, label)
            rows.append(r)
            per_date_by_method[label] = pd_r
        rows.append({"method": "c3s_raw", "mae": float("nan"), "rmse": float("nan"),
                     "r2": float("nan"), "n_dates": 0})
        result["rows"] = rows
        model_rmse = rows[0]["rmse"]
        model_mae = rows[0]["mae"]
        # Stored on each BASELINE's row (there is nowhere else to put a per-baseline
        # number), but the key name says whose skill it is: "model_skill_rmse" on
        # the climatology row is unambiguously "the MODEL's skill, measured against
        # climatology" - not "climatology's skill". See skill_score()'s docstring;
        # this naming is the actual fix for the sign-reads-backwards defect the
        # skeptic audit found, the arithmetic underneath was already correct.
        for r in rows[1:]:
            if r["method"] == "c3s_raw":
                r["model_skill_rmse"] = None
                r["model_skill_mae"] = None
                continue
            r["model_skill_rmse"] = skill_score(model_rmse, r["rmse"])
            r["model_skill_mae"] = skill_score(model_mae, r["mae"])
            r["r2_diff_vs_model"] = (rows[0]["r2"] - r["r2"]) if not np.isnan(r["r2"]) else None
            # Paired on MAE, the metric with a direct per-date physical unit (SPI
            # units of error), not RMSE (dominated by whichever date has the worst
            # spatial spread) - see paired_significance()'s docstring for the
            # independence caveat this does NOT resolve.
            r["significance"] = paired_significance(
                per_date_by_method["model"]["mae"], per_date_by_method[r["method"]]["mae"]
            )

    else:  # classification
        model_row, model_per_date = build_classification_row(
            pred.rename(columns={"actual": "actual_prob", "prediction": "prediction"}),
            "prediction", "model",
        )
        rows = [model_row]
        per_date_by_method = {"model": model_per_date}
        for base_col, label in [
            ("climatology_prob", "climatology"), ("persistence_prob", "persistence"),
            ("known_accumulation_prob", "known_accumulation"),
        ]:
            r, pd_r = build_classification_row(base, base_col, label)
            rows.append(r)
            per_date_by_method[label] = pd_r
        rows.append({"method": "c3s_raw", "auc": float("nan"), "brier": float("nan"), "n_dates": 0})
        result["rows"] = rows
        model_brier = rows[0]["brier"]
        for r in rows[1:]:
            if r["method"] == "c3s_raw":
                r["model_bss"] = None
                continue
            # model_bss on the climatology row = the MODEL's Brier Skill Score
            # measured against climatology - same naming fix as model_skill_rmse
            # above, same underlying arithmetic (skill_score's docstring).
            r["model_bss"] = skill_score(model_brier, r["brier"])
            r["significance"] = paired_significance(
                per_date_by_method["model"]["brier"], per_date_by_method[r["method"]]["brier"]
            )

    return result


def format_significance(sig: dict[str, Any] | None) -> str:
    """t-test / Wilcoxon / sign-test p-values, all three, none nominated as
    primary - see paired_significance()'s docstring for why an earlier version
    of this table picking Wilcoxon as "the conservative one" was itself a
    defect the second skeptic audit found."""
    if not sig:
        return "—"
    if sig.get("identical"):
        return "identical"  # distinguishable from "—" (not computed at all)
    if np.isnan(sig.get("p_ttest", float("nan"))):
        return "—"
    r1 = sig.get("lag1_autocorr", float("nan"))
    r1_s = f", r₁={r1:+.2f}" if not np.isnan(r1) else ""
    return f"t={sig['p_ttest']:.3f} / w={sig['p_wilcoxon']:.3f} / sign={sig['p_sign']:.3f}{r1_s}"


# --------------------------------------------------------------------------
def render_markdown(tables: list[dict[str, Any]], config: dict[str, Any], pop_size: int) -> str:
    lines = [
        "# Skill table - Phase 0 gate",
        "",
        f"Analysis population: **{pop_size:,} cells** "
        "(`in_hydrobasins & ~in_akarcay_lobe & crop_frac_2021 >= "
        f"{config['grid']['mask']['min_fraction'] if 'grid' in config else 0.5}`).",
        "",
        "Metrics computed **per forecast date** across analysis cells, then averaged "
        "across test-period dates - never pooled across (cell, date) rows. "
        "See CLAUDE.md rule 4.",
        "",
    ]
    for t in tables:
        lines.append(f"## {t['target']} @ +{t['lead_months']} month(s) ({t['kind']})")
        lines.append("")
        if t["kind"] == "regression":
            # Column headers state WHOSE skill this is - "model skill (RMSE)" is
            # unambiguous on every row, including the baseline rows it's computed
            # against. Previously "skill (RMSE)" with a per-cell "(vs model)" suffix
            # printed on the climatology row read as "climatology's skill against
            # the model", backwards from its actual meaning; the skeptic audit
            # caught this as a rendering defect, not an arithmetic one - see
            # skill_score()'s docstring. Positive = the model beats that row.
            # "p (MAE, ...)" tests whether the model's and this row's per-date MAE
            # series actually differ - added after the first skeptic audit found
            # every skill number here was a bare mean with no test of whether it's
            # distinguishable from noise. Three tests, NONE nominated as primary -
            # see paired_significance()'s docstring for why an earlier version's
            # "Wilcoxon is the conservative one, read it first" rule was itself
            # withdrawn as a defect (it does not hold up statistically and, in
            # practice, was the only thing making the table's one positive claim
            # clear 0.05). r₁ is the measured lag-1 autocorrelation of the paired
            # per-date differences - large where it appears, near zero elsewhere;
            # judge each p accordingly rather than trusting a blanket rule.
            lines.append(
                "| method | MAE | RMSE | R² | model skill (RMSE) | model skill (MAE) | "
                "p (MAE, t-test / Wilcoxon / sign §) | n dates |"
            )
            lines.append("|---|---|---|---|---|---|---|---|")
            for r in t["rows"]:
                skill_r = r.get("model_skill_rmse")
                skill_m = r.get("model_skill_mae")
                note = ""
                if r["method"] == "known_accumulation":
                    note = " *"
                if r["method"] == "c3s_raw":
                    note = " †"
                skill_r_s = f"{skill_r:+.3f}" if skill_r is not None and not np.isnan(skill_r) else "N/A"
                skill_m_s = f"{skill_m:+.3f}" if skill_m is not None and not np.isnan(skill_m) else "N/A"
                mae = r["mae"] if not np.isnan(r["mae"]) else float("nan")
                rmse = r["rmse"] if not np.isnan(r["rmse"]) else float("nan")
                r2 = r.get("r2", float("nan"))
                p_s = format_significance(r.get("significance"))
                if r["method"] == "model":
                    skill_r_s = skill_m_s = "—"  # a method has no skill score against itself
                lines.append(
                    f"| {r['method']}{note} | {mae:.4f} | {rmse:.4f} | "
                    f"{r2:.4f} | {skill_r_s} | {skill_m_s} | {p_s} | {r['n_dates']} |"
                )
        else:
            # AUC and Brier have DIFFERENT denominators here: AUC is undefined on a
            # single-class date (all cells drought or none), Brier is not - fixed
            # after the skeptic audit found single-class dates were dropping BOTH
            # metrics together, silently discarding Brier (and both widest-spread
            # drought months, 2023-01 and 2025-03) on ~22% of the test record. See
            # per_date_classification_metrics()'s docstring.
            model_row = t["rows"][0]
            n_brier, n_auc = model_row["n_dates"], model_row["n_dates_auc"]
            n_auc_undefined = model_row["n_dates_auc_undefined"]
            lines.append(
                f"| method | AUC (n={n_auc}) | Brier (n={n_brier}) | model BSS | "
                "p (Brier, t-test / Wilcoxon / sign §) |"
            )
            lines.append("|---|---|---|---|---|")
            for r in t["rows"]:
                bss = r.get("model_bss")
                note = ""
                if r["method"] == "known_accumulation":
                    note = " *"
                if r["method"] == "c3s_raw":
                    note = " †"
                if r["method"] == "persistence":
                    note += " ‡"
                bss_s = f"{bss:+.3f}" if bss is not None and not np.isnan(bss) else "N/A"
                p_s = format_significance(r.get("significance"))
                if r["method"] == "model":
                    bss_s = "—"
                auc = r["auc"] if not np.isnan(r["auc"]) else float("nan")
                brier = r["brier"] if not np.isnan(r["brier"]) else float("nan")
                lines.append(f"| {r['method']}{note} | {auc:.4f} | {brier:.4f} | {bss_s} | {p_s} |")
            lines.append("")
            lines.append(
                f"AUC excludes {n_auc_undefined} of {n_brier} test dates where every "
                "analysis cell fell in the same class (basin-wide drought or none) - "
                "undefined for AUC, not for Brier, which scores all "
                f"{n_brier} dates including those. Dropped for both metrics: "
                f"{model_row['n_dates_dropped_entirely']} date(s) with fewer than "
                "10 analysis cells."
            )
        lines.append("")

    lines += [
        "---",
        "",
        "**Footnotes**",
        "",
        f"\\* {config['known_accumulation_note'].strip()}",
        "",
        f"† {config['c3s_raw_status']['reason']}",
        "",
        f"‡ {config['persistence_auc_note'].strip()}",
        "",
        "§ **What the p-values do and do not establish.** Three tests, computed on "
        "the model's and each baseline's per-date metric series aligned on the SAME "
        "test dates - not on the two already-averaged means printed in the table - "
        "and NONE of the three is nominated as primary. All three assume the paired "
        "differences are independent across dates, which they are NOT here: "
        "consecutive test months share autocorrelated weather (spi_3's own "
        "accumulation window adds direct overlap between neighbouring dates on top "
        "of that), so every p-value here is generally optimistic (too small), not "
        "rigorous - read as \"is this gap even plausibly bigger than noise\", never "
        "as a formal significance claim. r₁ is the measured lag-1 autocorrelation "
        "of each comparison's paired differences, printed alongside so a reader can "
        "judge how much to discount a given p rather than trusting a rule.\n\n"
        "**A withdrawn claim, corrected rather than deleted.** An earlier version "
        "of this table printed Wilcoxon before the t-test and told readers to treat "
        "it as the conservative, primary number, reasoning that the t-test's "
        "variance estimator is anti-conservative under positive autocorrelation. "
        "The second skeptic audit found this indefensible: Wilcoxon's own null "
        "variance formula assumes independent differences too, so a rank transform "
        "confers no documented robustness to serial dependence - the claimed "
        "mechanism does not single out Wilcoxon as safer. Worse, the premise "
        "(positive autocorrelation) does not hold uniformly - r₁ is large for "
        "spi_3 vs climatology but near zero for spi_1's rows - so the rule was "
        "applied where its own justification did not apply. In practice it was the "
        "only thing that put this table's one positive claim (model beats "
        "persistence at spi_1@+1) under 0.05: Wilcoxon gives 0.021 there, the "
        "t-test 0.065, and the sign test (the test least sensitive to "
        "autocorrelation or skew - model wins 31 of 47 dates) 0.040 - all three "
        "actually agree the gap is suggestive, but their p-values still span a "
        "wide range (0.021-0.065) on the same 47 dates, which is itself the point: "
        "no single one of the three should be quoted alone as THE p-value for this "
        "comparison.\n\n"
        "**Multiple comparisons, not corrected for.** Six paired tests are reported "
        "across the two targets' baseline rows (two of the six, known_accumulation, "
        "duplicate climatology's numbers by construction - see \\*). With six tests "
        "and no correction, a naive 0.05 threshold understates how easily one gap "
        "clears it by chance; a Bonferroni-adjusted threshold over four independent "
        "comparisons would be 0.05/4 = 0.0125, which none of this table's p-values "
        "clears on all three tests simultaneously. This project does not claim the "
        "model beats or loses to any baseline at conventional significance - the "
        "honest summary is that none of these gaps is established, in either "
        "direction, at this sample size.",
        "",
        "Reliability diagrams and spatially blocked CV are Phase 3 work "
        "(reports/phase0_log.md list B), not computed here.",
        "",
        "**Why R² looks so negative.** R² here is computed CROSS-SECTIONALLY - across "
        "analysis cells within one forecast date, per PROJECT_SPEC.md 4.4's "
        "per-forecast-date aggregation (never pooled across rows) - not across time "
        "for one cell, which is the usual reading of \"R² of a forecast model\". "
        "SPI at a single date is spatially correlated basin-wide, so its cross-cell "
        "spread within one month is narrow (std ~0.2-0.5 SPI units); a modest absolute "
        "error against that narrow spread produces a large negative R². Verified by "
        "hand for one date against scikit-learn's r2_score (exact match, -0.718) - "
        "this is the metric's designed behaviour under PROJECT_SPEC.md 4.4, not a bug.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
def build() -> list[dict[str, Any]]:
    config = load_config(MODEL_CONFIG_PATH)
    data_config = load_config()
    test_start, test_end = config["split"]["test"]

    predictions = pd.read_parquet(PREDICTIONS)
    baselines = pd.read_parquet(BASELINES)
    predictions["date"] = pd.to_datetime(predictions["date"])
    baselines["date"] = pd.to_datetime(baselines["date"])

    combined_grid_cfg = {"grid": data_config["grid"]}
    population = analysis_population(combined_grid_cfg)
    print(f"Analysis population: {len(population):,} cells "
          f"(in_hydrobasins & ~in_akarcay_lobe & crop_frac >= "
          f"{data_config['grid']['mask']['min_fraction']})")
    print(f"Test period: {test_start} .. {test_end}")

    tables = []
    for target_cfg in config["targets"]:
        if target_cfg["name"] not in predictions["target"].unique():
            continue
        t = build_target_table(target_cfg, predictions, baselines, population,
                                test_start, test_end, )
        tables.append(t)
        print(f"\n{t['target']} @ +{t['lead_months']} ({t['kind']}):")
        for r in t["rows"]:
            print(f"  {r}")

    md = render_markdown(tables, {**config, "grid": data_config["grid"]}, len(population))
    SKILL_TABLE_MD.write_text(md, encoding="utf-8")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    metrics_path = ROOT / "reports" / f"metrics_{timestamp}.json"
    metrics_path.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "provenance": provenance(["src/eval/skill.py", "config/model.yaml"]),
        "analysis_population_cells": len(population),
        "test_period": [test_start, test_end],
        "aggregation": "per_forecast_date_then_mean",
        "tables": tables,
    }, indent=2, default=str), encoding="utf-8")

    print(f"\nWrote {SKILL_TABLE_MD.relative_to(ROOT)}")
    print(f"Wrote {metrics_path.relative_to(ROOT)}")
    return tables


if __name__ == "__main__":
    build()
