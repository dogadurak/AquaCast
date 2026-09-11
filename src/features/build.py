"""Lag feature construction, shared by T7 training and the leakage test suite.

Lives in src/features/, not src/models/, per CLAUDE.md's layout - feature
engineering and model training are different concerns even when the only current
consumer of these features is src/models/train.py.

Every feature at row t must be derivable from data at or before t. Lagging is the
only transformation used here; `assert_no_future_reference()` proves it rather than
assuming it, and is what tests/test_leakage.py::test_no_future_features has been
waiting on since T0.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Lag depths for feature construction - months of history looked back from t.
# Bounded at 6 so the longest feature window (6) plus the longest lead (3) never
# needs to reach past t, and the 12-month split gap safely covers it.
LAG_MONTHS = (1, 2, 3, 6)
BASE_FEATURE_COLUMNS = [
    "precip_chirps_mm", "spi_1", "spi_3", "t2m_c",
    "swvl1", "swvl2", "swvl3", "swvl4", "pet_era5_mm",
]


def build_lag_features(panel: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Return (panel with lag/cyclic columns added, list of feature column names)."""
    ordered = panel.sort_values(["cell_id", "date"]).reset_index(drop=True)
    feature_cols: list[str] = []
    for col in BASE_FEATURE_COLUMNS:
        for lag in LAG_MONTHS:
            name = f"{col}_lag{lag}"
            ordered[name] = ordered.groupby("cell_id")[col].shift(lag)
            feature_cols.append(name)
    # Cyclic month-of-year encoding - static, uses only the forecast date itself.
    month = ordered["date"].dt.month
    ordered["month_sin"] = np.sin(2 * np.pi * month / 12)
    ordered["month_cos"] = np.cos(2 * np.pi * month / 12)
    feature_cols += ["month_sin", "month_cos"]
    return ordered, feature_cols


def assert_no_future_reference() -> None:
    """Prove every feature column is a lag or a static function of t - never t+1+.

    Constructs a small synthetic panel, plants a sentinel far in the future for one
    cell, and confirms no feature at any row equals or derives from that sentinel
    until the row whose lag actually reaches it.
    """
    dates = pd.date_range("2001-01-01", periods=20, freq="MS")
    synth = pd.DataFrame({
        "cell_id": [1] * 20,
        "date": dates,
        **{col: np.arange(20, dtype=float) for col in BASE_FEATURE_COLUMNS},
    })
    sentinel_row = 15
    sentinel_value = 999999.0
    for col in BASE_FEATURE_COLUMNS:
        synth.loc[sentinel_row, col] = sentinel_value

    out, _ = build_lag_features(synth)
    for lag in LAG_MONTHS:
        for col in BASE_FEATURE_COLUMNS:
            fcol = f"{col}_lag{lag}"
            # The sentinel may only appear at row (sentinel_row + lag) or later -
            # never earlier, which would mean the feature reached into the future.
            leaked = out.loc[: sentinel_row + lag - 1, fcol]
            if (leaked == sentinel_value).any():
                raise AssertionError(
                    f"{fcol} at a row before {sentinel_row + lag} carries the "
                    f"sentinel planted at row {sentinel_row} - this feature reaches "
                    "into the future"
                )
            if sentinel_row + lag < len(out):
                if out.loc[sentinel_row + lag, fcol] != sentinel_value:
                    raise AssertionError(
                        f"{fcol} at row {sentinel_row + lag} should equal the "
                        f"sentinel from row {sentinel_row} (lag {lag}) and does not - "
                        "the shift direction or amount is wrong"
                    )
