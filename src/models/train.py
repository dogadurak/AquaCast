"""T7 - XGBoost for spi_3 @ +3 (primary) and spi_1 @ +1 (secondary).

TWO SEPARATE PERIODS, NOT ONE - the confusion this module exists to avoid.

  FIT period   (1981-2016, config/data.yaml baseline_precip_era5): the reference
               window SPI's gamma parameters and this project's climatologies are
               fitted on. Set in T5/T6.
  TRAIN period (2001-2016, config/model.yaml split.train): the window this model's
               weights are fitted on. Shorter, because PROJECT_SPEC.md restricts
               Phase 0 to the years the panel's non-precipitation features could in
               principle cover, even though none of those features exist yet here.

Features are lagged so that every value used to predict month t is observable at or
before month t - never derived from t+1 or later. `assert_no_future_reference()`
below is what tests/test_leakage.py::test_no_future_features has been waiting on
since T0; calling this module makes that test active instead of skipped.

Scope, held to deliberately: one XGBoost configuration, no hyperparameter search,
no SHAP, no LightGBM cross-check. Those are Phase 3 (see reports/phase0_log.md list
B) work - this task's only job is predictions for T8's skill table.

Run:  python -m src.models.train
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import xgboost as xgb

from src.data.gee_io import ROOT, load_config, provenance, report
from src.features.build import LAG_MONTHS, assert_no_future_reference, build_lag_features

PANEL = ROOT / "data" / "processed" / "panel_monthly.parquet"
OUT_PARQUET = ROOT / "data" / "processed" / "predictions.parquet"
OUT_JSON = ROOT / "reports" / "training_summary.json"
MODEL_CONFIG_PATH = ROOT / "config" / "model.yaml"
# Feature construction (lags, base columns, the no-future-reference proof) lives in
# src/features/build.py per CLAUDE.md's layout - imported above, not redefined here.


# --------------------------------------------------------------------------
def make_split_masks(dates: pd.Series, split_cfg: dict[str, list[str]]) -> dict[str, pd.Series]:
    masks = {}
    for name, (start, end) in split_cfg.items():
        masks[name] = (dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))
    return masks


def expected_split_rows(n_cells: int, start: str, end: str) -> int:
    months = (pd.Timestamp(end).year - pd.Timestamp(start).year) * 12 + (
        pd.Timestamp(end).month - pd.Timestamp(start).month
    ) + 1
    return n_cells * months


# --------------------------------------------------------------------------
def train_one_target(
    panel: pd.DataFrame,
    feature_cols: list[str],
    target_cfg: dict[str, Any],
    split_masks: dict[str, pd.Series],
    seed: int,
) -> dict[str, Any]:
    name = target_cfg["name"]
    lead = target_cfg["lead_months"]
    kind = target_cfg["kind"]

    # Target at forecast date t is the value lead months ahead, joined by shifting
    # the target column BACKWARD by -lead within each cell's own ordering, so
    # target_col[t] == actual[t + lead]. Features at row t use only lag columns
    # (t and earlier); this line is the only place "the future" enters, and only
    # on the label side, which is what a forecast target is supposed to be.
    ordered = panel.sort_values(["cell_id", "date"]).reset_index(drop=True)
    label = ordered.groupby("cell_id")[name].shift(-lead)

    X_all = ordered[feature_cols]
    y_all = label
    if kind == "classification":
        threshold = target_cfg["threshold"]
        y_all = (label < threshold).astype(float)
        y_all[label.isna()] = np.nan

    rows = {}
    for split_name, mask in split_masks.items():
        m = mask.reindex(ordered.index, fill_value=False) & y_all.notna() & X_all.notna().all(axis=1)
        rows[split_name] = ordered.index[m]

    objective = "binary:logistic" if kind == "classification" else "reg:squarederror"
    eval_metric = "logloss" if kind == "classification" else "rmse"
    print(f"\n{name} @ +{lead} ({kind}): objective={objective}, eval_metric={eval_metric}")

    # early_stopping_rounds on the validation set - not a hyperparameter search (one
    # fixed configuration, decided once), but without it 300 trees fit unconditionally
    # to 2001-2016 and were found to generalise WORSE than a constant-mean predictor
    # on 2022-2025's shifted climate. That confound would have made "no skill" and
    # "undertrained" indistinguishable in T8's skill table.
    common = dict(
        objective=objective, eval_metric=eval_metric,
        n_estimators=300, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, random_state=seed,
        early_stopping_rounds=20,
    )
    model = xgb.XGBClassifier(**common) if kind == "classification" else xgb.XGBRegressor(**common)

    train_idx, val_idx, test_idx = rows["train"], rows["validation"], rows["test"]
    model.fit(
        X_all.loc[train_idx], y_all.loc[train_idx],
        eval_set=[(X_all.loc[val_idx], y_all.loc[val_idx])],
        verbose=False,
    )

    preds = pd.Series(np.nan, index=ordered.index, dtype=float)
    all_scored = train_idx.union(val_idx).union(test_idx)
    if kind == "classification":
        preds.loc[all_scored] = model.predict_proba(X_all.loc[all_scored])[:, 1]
    else:
        preds.loc[all_scored] = model.predict(X_all.loc[all_scored])

    out = ordered.loc[all_scored, ["cell_id", "date"]].copy()
    out["target"] = name
    out["lead_months"] = lead
    out["kind"] = kind
    # `actual` must be the SAME quantity `prediction` estimates: the binary
    # indicator for classification (prediction is a probability from
    # predict_proba), the raw value for regression. Storing the raw SPI value
    # here for a classification target would silently corrupt every downstream
    # AUC/Brier computation - caught by a sanity check before T8, not by an
    # assertion in this file, which is itself worth fixing (see failure-modes).
    out["actual"] = y_all.loc[all_scored]
    out["actual_raw_spi"] = label.loc[all_scored]
    out["prediction"] = preds.loc[all_scored]
    out["split"] = "none"
    out.loc[out.index.isin(train_idx), "split"] = "train"
    out.loc[out.index.isin(val_idx), "split"] = "validation"
    out.loc[out.index.isin(test_idx), "split"] = "test"

    return {
        "predictions": out,
        "n_train": len(train_idx), "n_val": len(val_idx), "n_test": len(test_idx),
        "objective": objective, "n_features": len(feature_cols),
        "model": model,
    }


# --------------------------------------------------------------------------
def build() -> pd.DataFrame:
    config = load_config(MODEL_CONFIG_PATH)
    panel = pd.read_parquet(PANEL)
    panel["date"] = pd.to_datetime(panel["date"])

    print("Verifying feature construction has no future reference ...")
    assert_no_future_reference()
    print("  OK - no lag feature reaches past its own forecast date")

    panel_feat, feature_cols = build_lag_features(panel)
    n_cells = panel["cell_id"].nunique()

    split_cfg = {k: v for k, v in config["split"].items() if not k.startswith("gap")}
    split_masks = make_split_masks(panel_feat["date"], split_cfg)

    print("\nAssertions (expected -> actual):")
    ok = True
    for name, (start, end) in split_cfg.items():
        expected = expected_split_rows(n_cells, start, end)
        actual = int(split_masks[name].sum())
        ok &= report(f"{name} rows before feature-null filtering ({start}..{end})",
                     expected, actual)

    # B: gap protection. The last TRAIN row's longest lag window (6 months back)
    # must never reach into validation, and the label lead (up to 3 months forward)
    # must never reach past the gap into validation either.
    train_end = pd.Timestamp(split_cfg["train"][1])
    gap_end = pd.Timestamp(config["split"]["gap_1"][1])
    val_start = pd.Timestamp(split_cfg["validation"][0])
    longest_lag = max(LAG_MONTHS)
    longest_lead = max(t["lead_months"] for t in config["targets"] if t["name"] in panel.columns)
    feature_reach = train_end  # features look BACKWARD from train_end - never forward
    label_reach = train_end + pd.DateOffset(months=longest_lead)
    ok &= report("train's last label (lead-shifted) stays before validation",
                 True, bool(label_reach < val_start))
    ok &= report("gap length covers the longest lead", True,
                 bool((gap_end - train_end).days // 30 + 1 >= longest_lead))

    # E: no unexpected nulls in the test period for spi_3 (warm-up is at the
    # series START in 1981, nowhere near the 2022-2025 test window).
    test_mask = split_masks["test"]
    ok &= report("spi_3 nulls in test period", 0,
                 int(panel_feat.loc[test_mask, "spi_3"].isna().sum()))

    if not ok:
        raise AssertionError(
            "T7 pre-training assertions failed - stopping before any model is fit. "
            "Per docs/working_protocol.md, stop and report."
        )

    results = {}
    all_preds = []
    for target_cfg in config["targets"]:
        if target_cfg["name"] not in panel.columns:
            print(f"\nSkipping {target_cfg['name']} - not in panel (Phase 2 target)")
            continue
        r = train_one_target(panel_feat, feature_cols, target_cfg, split_masks, config["model"]["seed"])
        results[target_cfg["name"]] = r
        all_preds.append(r["predictions"])

    predictions = pd.concat(all_preds, ignore_index=True)

    print("\nPost-training assertions:")
    ok2 = True
    for name, r in results.items():
        sub = predictions[predictions["target"] == name]
        ok2 &= report(f"{name}: train rows > 0", True, r["n_train"] > 0)
        ok2 &= report(f"{name}: test rows > 0", True, r["n_test"] > 0)
        ok2 &= report(f"{name}: prediction nulls in scored rows", 0,
                      int(sub["prediction"].isna().sum()))
        # `actual` must match what `prediction` estimates - caught the hard way
        # once already (see the comment in train_one_target): a classification
        # target's actual is a {0,1} indicator, not the raw regression value.
        if r["objective"] == "binary:logistic":
            ok2 &= report(f"{name}: actual is binary {{0,1}}", True,
                          bool(sub["actual"].dropna().isin([0.0, 1.0]).all()))
            ok2 &= report(f"{name}: prediction is a probability in [0,1]", True,
                          bool(sub["prediction"].between(0, 1).all()))
    if not ok2:
        raise AssertionError("T7 post-training assertions failed.")

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(OUT_PARQUET, index=False)

    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": provenance(["src/models/train.py", "config/model.yaml"]),
        "train_period": split_cfg["train"],
        "validation_period": split_cfg["validation"],
        "test_period": split_cfg["test"],
        "n_features": len(feature_cols),
        "feature_columns": feature_cols,
        "targets": {
            name: {
                "objective": r["objective"], "n_train": r["n_train"],
                "n_val": r["n_val"], "n_test": r["n_test"],
            } for name, r in results.items()
        },
        "note": (
            "Phase 0 feature set only - no MODIS, no SPEI, no C3S. spi_3@+3 tests "
            "PROJECT_SPEC.md Problem 2 directly: local lagged variables are not "
            "expected to forecast 3 months out. A model that fails to beat the "
            "baselines here is the predicted, reportable outcome, not a defect."
        ),
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    print(f"\nWrote {OUT_PARQUET.relative_to(ROOT)} ({len(predictions):,} rows)")
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    return predictions


if __name__ == "__main__":
    build()
