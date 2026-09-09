"""Leakage tests. These are not optional - see CLAUDE.md."""

import pytest


@pytest.mark.skip(reason="implement in Phase 2")
def test_no_target_predictor_overlap():
    """SPI-k at lead L must not overlap observed months (requires L >= k)."""


@pytest.mark.skip(reason="implement in Phase 2")
def test_climatology_fitted_on_train_only():
    """Baseline statistics must not see validation or test periods."""


@pytest.mark.skip(reason="implement in Phase 2")
def test_no_future_features():
    """No feature at time t may reference data from t+1 or later."""


@pytest.mark.skip(reason="implement in Phase 3")
def test_permutation_yields_no_skill():
    """Shuffled targets must produce skill score near zero."""


@pytest.mark.skip(reason="implement in Phase 3")
def test_split_gaps_cover_accumulation_window():
    """Gap between splits >= longest accumulation window."""
