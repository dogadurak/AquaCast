# Skill table - Phase 0 gate

Analysis population: **1,823 cells** (`in_hydrobasins & ~in_akarcay_lobe & crop_frac_2021 >= 0.5`).

Metrics computed **per forecast date** across analysis cells, then averaged across test-period dates - never pooled across (cell, date) rows. See CLAUDE.md rule 4.

## spi_3 @ +3 month(s) (classification)

| method | AUC | Brier | BSS (vs model) | n dates (10 of 45 dropped - single class present) |
|---|---|---|---|---|
| model | 0.4904 | 0.2113 | N/A | 35 |
| climatology | 0.5129 | 0.2039 | -0.036 | 35 |
| persistence ‡ | 0.4826 | 0.3391 | +0.377 | 35 |
| known_accumulation * | 0.5129 | 0.2039 | -0.036 | 35 |
| c3s_raw † | nan | nan | N/A | 0 |

## spi_1 @ +1 month(s) (regression)

| method | MAE | RMSE | R² | skill (RMSE) | skill (MAE) | n dates |
|---|---|---|---|---|---|---|
| model | 0.7842 | 0.8861 | -4.6312 | N/A (vs model) | N/A (vs model) | 47 |
| climatology | 0.6988 | 0.7915 | -3.4429 | -0.120 (vs model) | -0.122 (vs model) | 47 |
| persistence | 0.8904 | 1.0278 | -9.5823 | +0.138 (vs model) | +0.119 (vs model) | 47 |
| known_accumulation * | 0.6988 | 0.7915 | -3.4429 | -0.120 (vs model) | -0.122 (vs model) | 47 |
| c3s_raw † | nan | nan | nan | N/A (vs model) | N/A (vs model) | 0 |

---

**Footnotes**

\* For every approved (target, lead) pair in PROJECT_SPEC.md section 4.1, overlap with the observed accumulation window is zero (k - L = 0 for spi_1@+1, spi_3@+3, sm_anom@+1, ndvi_anom@+1). Under zero overlap, known-accumulation has nothing observed to condition on and reduces exactly to climatology - so the two columns in the skill table being numerically identical is the expected, designed consequence of section 4.1 (Problem 1's fix), not a bug or a duplicated computation. Verified independently rather than assumed: see tests/test_leakage.py::test_known_accumulation_baseline_matches_climatology_numerically. If a future (target, lead) pair has nonzero overlap, this note and that test's expectation both stop applying and must be revised together.

† CDS access pending - see reports/phase0_log.md open items (list B)

‡ Persistence's probability forecast for a classification target is a hard 0/1 step function (today's state, carried forward unchanged) rather than a calibrated probability - see src/models/baselines.py persistence_probability_forecast. Its AUC and Brier score are therefore expected to look coarser / more discretised than a continuous forecast's. This is a property of thresholding, not a defect in the baseline.

Reliability diagrams and spatially blocked CV are Phase 3 work (reports/phase0_log.md list B), not computed here.

**Why R² looks so negative.** R² here is computed CROSS-SECTIONALLY - across analysis cells within one forecast date, per PROJECT_SPEC.md 4.4's per-forecast-date aggregation (never pooled across rows) - not across time for one cell, which is the usual reading of "R² of a forecast model". SPI at a single date is spatially correlated basin-wide, so its cross-cell spread within one month is narrow (std ~0.2-0.5 SPI units); a modest absolute error against that narrow spread produces a large negative R². Verified by hand for one date against scikit-learn's r2_score (exact match, -0.718) - this is the metric's designed behaviour under PROJECT_SPEC.md 4.4, not a bug.