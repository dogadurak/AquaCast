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
) -> tuple[pd.DataFrame, list[str]]:
    """Returns (per-date metrics, dates dropped for having a single class present).

    AUC is undefined with one class in a date's cells - which happens here: SPI-3
    below threshold is a ~15-25% event, so over ~45 test months some will show it
    nowhere in the basin (rate=0) or almost everywhere at once during a widespread
    event (rate=1). Dropped explicitly and counted, not silently thinned - the drop
    count is itself part of what a ~45-month test period can honestly support.
    """
    rows, dropped = [], []
    for date, g in df.groupby("date"):
        g = g.dropna(subset=[actual_col, pred_col])
        if len(g) < 10 or g[actual_col].nunique() < 2:
            dropped.append(str(pd.Timestamp(date).date()))
            continue
        auc = roc_auc_score(g[actual_col], g[pred_col])
        brier = brier_score_loss(g[actual_col], g[pred_col])
        rows.append({"date": date, "n_cells": len(g), "auc": auc, "brier": brier})
    return pd.DataFrame(rows), dropped


def summarise(per_date: pd.DataFrame, cols: list[str]) -> dict[str, float]:
    """Mean across forecast dates - the aggregation step, never a pooled row-level stat."""
    return {c: float(per_date[c].mean()) if len(per_date) else float("nan") for c in cols}


# --------------------------------------------------------------------------
def build_regression_row(df: pd.DataFrame, pred_col: str, label: str) -> dict[str, Any]:
    """`df` must carry 'date', 'actual' and `pred_col`. One row = one method's summary."""
    per_date = per_date_regression_metrics(df, "actual", pred_col)
    summary = summarise(per_date, ["mae", "rmse", "r2"])
    summary["method"] = label
    summary["n_dates"] = int(len(per_date))
    return summary


def build_classification_row(
    df: pd.DataFrame, pred_col: str, label: str,
) -> dict[str, Any]:
    per_date, dropped_dates = per_date_classification_metrics(df, "actual_prob", pred_col)
    summary = summarise(per_date, ["auc", "brier"])
    summary["method"] = label
    summary["n_dates"] = int(len(per_date))
    summary["n_dates_dropped_single_class"] = len(dropped_dates)
    summary["dates_dropped_single_class"] = dropped_dates
    return summary


def skill_score(model_val: float, baseline_val: float) -> float:
    """1 - error_model/error_baseline. Positive = model beats the baseline."""
    if baseline_val in (0, None) or np.isnan(baseline_val) or np.isnan(model_val):
        return float("nan")
    return 1.0 - model_val / baseline_val


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
        rows = [build_regression_row(pred, "prediction", "model")]
        for base_col, label in [
            ("climatology", "climatology"), ("persistence", "persistence"),
            ("known_accumulation", "known_accumulation"),
        ]:
            rows.append(build_regression_row(base, base_col, label))
        rows.append({"method": "c3s_raw", "mae": float("nan"), "rmse": float("nan"),
                     "r2": float("nan"), "n_dates": 0})
        result["rows"] = rows
        model_rmse = rows[0]["rmse"]
        model_mae = rows[0]["mae"]
        for r in rows[1:]:
            if r["method"] == "c3s_raw":
                r["skill_rmse_vs_model"] = None
                r["skill_mae_vs_model"] = None
                continue
            r["skill_rmse_vs_model"] = skill_score(model_rmse, r["rmse"])
            r["skill_mae_vs_model"] = skill_score(model_mae, r["mae"])
            r["r2_diff_vs_model"] = (rows[0]["r2"] - r["r2"]) if not np.isnan(r["r2"]) else None

    else:  # classification
        rows = [build_classification_row(pred.rename(columns={"actual": "actual_prob",
                                                                "prediction": "prediction"}),
                                          "prediction", "model")]
        for base_col, label in [
            ("climatology_prob", "climatology"), ("persistence_prob", "persistence"),
            ("known_accumulation_prob", "known_accumulation"),
        ]:
            rows.append(build_classification_row(base, base_col, label))
        rows.append({"method": "c3s_raw", "auc": float("nan"), "brier": float("nan"), "n_dates": 0})
        result["rows"] = rows
        model_brier = rows[0]["brier"]
        for r in rows[1:]:
            if r["method"] == "c3s_raw":
                r["bss_vs_model"] = None
                continue
            r["bss_vs_model"] = skill_score(model_brier, r["brier"])

    return result


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
            lines.append("| method | MAE | RMSE | R² | skill (RMSE) | skill (MAE) | n dates |")
            lines.append("|---|---|---|---|---|---|---|")
            for r in t["rows"]:
                skill_r = r.get("skill_rmse_vs_model")
                skill_m = r.get("skill_mae_vs_model")
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
                lines.append(
                    f"| {r['method']}{note} | {mae:.4f} | {rmse:.4f} | "
                    f"{r2:.4f} | {skill_r_s} (vs model) | {skill_m_s} (vs model) | {r['n_dates']} |"
                )
        else:
            drop_note = t["rows"][0].get("n_dates_dropped_single_class", 0)
            lines.append(f"| method | AUC | Brier | BSS (vs model) | n dates ({drop_note} of "
                         f"{t['rows'][0]['n_dates'] + drop_note} dropped - single class present) |")
            lines.append("|---|---|---|---|---|")
            for r in t["rows"]:
                bss = r.get("bss_vs_model")
                note = ""
                if r["method"] == "known_accumulation":
                    note = " *"
                if r["method"] == "c3s_raw":
                    note = " †"
                if r["method"] == "persistence":
                    note += " ‡"
                bss_s = f"{bss:+.3f}" if bss is not None and not np.isnan(bss) else "N/A"
                auc = r["auc"] if not np.isnan(r["auc"]) else float("nan")
                brier = r["brier"] if not np.isnan(r["brier"]) else float("nan")
                lines.append(f"| {r['method']}{note} | {auc:.4f} | {brier:.4f} | {bss_s} | {r['n_dates']} |")
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
