"""Leakage tests. These are not optional - see CLAUDE.md.

The project's most likely failure is a bug that looks like success. These tests
encode the invariants that make such a bug loud instead of silent. They read the
configuration rather than hardcoding dates, so that changing a split or a
reference period in config/ cannot quietly bypass them.

Tests that need modules from later phases activate automatically as soon as those
modules exist - none of them are permanently skipped.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA_CFG = yaml.safe_load((ROOT / "config" / "data.yaml").read_text(encoding="utf-8"))
MODEL_CFG = yaml.safe_load((ROOT / "config" / "model.yaml").read_text(encoding="utf-8"))

# Longest accumulation window computed anywhere in the pipeline. SPI-12 is a
# feature at time t even though it is not a forecast target, so the split gaps
# must cover it.
LONGEST_ACCUMULATION_MONTHS = 12


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _as_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _period(spec: list) -> tuple[date, date]:
    start, end = spec
    return _as_date(start), _as_date(end)


def _overlaps(a: tuple[date, date], b: tuple[date, date]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month) + 1


def accumulation_months(target_name: str) -> int:
    """Months of data the target accumulates.

    SPI-k / SPEI-k accumulate k months. Instantaneous anomalies (soil moisture,
    NDVI) describe a single month, so their window is 1.
    """
    match = re.match(r"^(?:spi|spei)_(\d+)$", target_name)
    if match:
        return int(match.group(1))
    return 1


def baseline_periods() -> dict[str, tuple[date, date]]:
    return {
        name: (_as_date(block["start"]), _as_date(block["end"]))
        for name, block in DATA_CFG["climatology"].items()
    }


def split_periods() -> dict[str, tuple[date, date]]:
    return {name: _period(spec) for name, spec in MODEL_CFG["split"].items()}


# --------------------------------------------------------------------------
# 1. Reference-period leakage
# --------------------------------------------------------------------------
def test_baseline_periods_exclude_val_and_test():
    """Climatology / gamma-fit reference periods must not see held-out data.

    This is the test that would have caught the 1991-2020 baseline carried over
    from the draft spec: that period overlapped validation (2018-2020), so every
    anomaly computed against it would have carried held-out statistics into
    training.
    """
    splits = split_periods()
    held_out = {name: period for name, period in splits.items() if name != "train"}

    violations = []
    for base_name, base in baseline_periods().items():
        for split_name, period in held_out.items():
            if _overlaps(base, period):
                violations.append(
                    f"{base_name} ({base[0]}..{base[1]}) overlaps {split_name} "
                    f"({period[0]}..{period[1]})"
                )
    assert not violations, "reference period leaks held-out data:\n  " + "\n  ".join(violations)


def test_short_baseline_periods_are_declared_as_limitations():
    """A short reference period is allowed, but only if it is declared.

    MODIS cannot reach 30 years. That is a fact about the data, not a defect -
    but it must be stated in the config rather than silently accepted.
    """
    for base_name, (start, end) in baseline_periods().items():
        years = _months_between(start, end) / 12
        if years < 30:
            block = DATA_CFG["climatology"][base_name]
            text = f"{block.get('note', '')} {block.get('caveat', '')}".lower()
            assert "limitation" in text or "below the 30-year" in text, (
                f"{base_name} spans {years:.1f} years, under the 30-year guidance, "
                "and does not declare that as a limitation in config/data.yaml"
            )


def test_each_anomaly_column_has_exactly_one_reference_period():
    assigned = []
    for block in DATA_CFG["climatology"].values():
        assigned.extend(block["applies_to"])
    duplicates = sorted({col for col in assigned if assigned.count(col) > 1})
    assert not duplicates, f"columns assigned to more than one reference period: {duplicates}"


# --------------------------------------------------------------------------
# 2. Target / predictor overlap
# --------------------------------------------------------------------------
def test_no_target_predictor_overlap():
    """SPI-k at lead L overlaps observed months by (k - L). Approved pairs need L >= k."""
    violations = []
    for target in MODEL_CFG["targets"]:
        k = accumulation_months(target["name"])
        lead = target["lead_months"]
        overlap = max(0, k - lead)
        if overlap > 0:
            violations.append(
                f"{target['name']} at lead +{lead} overlaps the observed period by "
                f"{overlap} of {k} months - {overlap / k:.0%} of the target is already "
                "known at forecast time"
            )
    assert not violations, (
        "target overlaps its own predictor window (PROJECT_SPEC.md section 4.1):\n  "
        + "\n  ".join(violations)
    )


def test_known_accumulation_baseline_is_identical_to_climatology_by_construction():
    """Tripwire, not a formality.

    With zero overlap the known-accumulation baseline has nothing observed to work
    with, so it reduces exactly to climatology. That is why the skill table marks
    it "identical to climatology by construction".

    The moment somebody adds an overlapping (target, lead) pair, this test fails -
    and that failure is the signal that the known-accumulation baseline has become
    a distinct, load-bearing control again and must be reported as one.
    """
    for target in MODEL_CFG["targets"]:
        k = accumulation_months(target["name"])
        lead = target["lead_months"]
        overlap = max(0, k - lead)
        assert overlap == 0, (
            f"{target['name']} at lead +{lead} now overlaps by {overlap} month(s). "
            "The known-accumulation baseline is no longer equivalent to climatology: "
            "implement it as a separate baseline and stop labelling it "
            "'identical by construction' in the skill table."
        )


# --------------------------------------------------------------------------
# 3. Split integrity
# --------------------------------------------------------------------------
def test_split_gaps_cover_accumulation_window():
    """Gaps must be at least as long as the longest rolling window, or splits share data."""
    gaps = {name: period for name, period in split_periods().items() if name.startswith("gap")}
    assert gaps, "no gap periods configured between train/validation/test"

    for name, (start, end) in gaps.items():
        length = _months_between(start, end)
        assert length >= LONGEST_ACCUMULATION_MONTHS, (
            f"{name} spans {length} months but the longest accumulation window is "
            f"{LONGEST_ACCUMULATION_MONTHS} - adjacent splits share data through the "
            "rolling sum"
        )


def test_splits_are_ordered_and_disjoint():
    ordered = sorted(split_periods().items(), key=lambda item: item[1][0])
    for (name_a, a), (name_b, b) in zip(ordered, ordered[1:]):
        assert not _overlaps(a, b), f"{name_a} overlaps {name_b}"
        assert a[1] < b[0], f"{name_a} does not end before {name_b} begins"


# --------------------------------------------------------------------------
# 4. Phase 2/3 invariants - these activate as soon as the modules land
# --------------------------------------------------------------------------
def test_no_future_features():
    """No feature at time t may reference data from t+1 or later."""
    build = pytest.importorskip(
        "src.features.build",
        reason="feature builder not implemented yet (Phase 2)",
    )
    check = getattr(build, "assert_no_future_reference", None)
    assert check is not None, (
        "src.features.build exists but exposes no assert_no_future_reference() - "
        "the leakage test cannot verify shift/rolling alignment"
    )
    check()


def test_known_accumulation_baseline_matches_climatology_numerically():
    """The structural tripwire above, verified against the real implementations."""
    baselines = pytest.importorskip(
        "src.models.baselines",
        reason="baselines not implemented yet (Phase 0 step 4)",
    )
    import numpy as np

    for target in MODEL_CFG["targets"]:
        name, lead = target["name"], target["lead_months"]
        clim = np.asarray(baselines.climatology_forecast(name, lead), dtype=float)
        known = np.asarray(baselines.known_accumulation_forecast(name, lead), dtype=float)
        np.testing.assert_allclose(
            known,
            clim,
            rtol=0,
            atol=1e-10,
            err_msg=(
                f"{name} at lead +{lead}: the known-accumulation baseline differs from "
                "climatology despite zero overlap - one of the two is implemented wrongly"
            ),
        )


def test_permutation_yields_no_skill():
    """Shuffled targets must produce a skill score near zero."""
    permutation = pytest.importorskip(
        "src.eval.permutation",
        reason="permutation control not implemented yet (Phase 3)",
    )
    skill = permutation.run_permutation_test()
    assert abs(skill) < 0.05, (
        f"permutation test returned skill={skill:.3f} on shuffled targets. Near-zero is "
        "the only acceptable result; anything else means the pipeline is structurally "
        "leaking."
    )
