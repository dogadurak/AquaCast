# Skill table - Phase 0 gate

Analysis population: **1,823 cells** (`in_hydrobasins & ~in_akarcay_lobe & crop_frac_2021 >= 0.5`).

Metrics computed **per forecast date** across analysis cells, then averaged across test-period dates - never pooled across (cell, date) rows. See CLAUDE.md rule 4.

## spi_3 @ +3 month(s) (classification)

| method | AUC (n=35) | Brier (n=45) | model BSS | p (Brier, Wilcoxon / t-test §) |
|---|---|---|---|---|
| model | 0.4768 | 0.2052 | — | — |
| climatology | 0.5129 | 0.1949 | -0.053 | 0.078 / 0.014 |
| persistence ‡ | 0.4826 | 0.1958 | -0.048 | 0.128 / 0.015 |
| known_accumulation * | 0.5129 | 0.1949 | -0.053 | 0.078 / 0.014 |
| c3s_raw † | nan | nan | N/A | — |

AUC excludes 10 of 45 test dates where every analysis cell fell in the same class (basin-wide drought or none) - undefined for AUC, not for Brier, which scores all 45 dates including those. Dropped for both metrics: 0 date(s) with fewer than 10 analysis cells.

## spi_1 @ +1 month(s) (regression)

| method | MAE | RMSE | R² | model skill (RMSE) | model skill (MAE) | p (MAE, Wilcoxon / t-test §) | n dates |
|---|---|---|---|---|---|---|---|
| model | 0.7296 | 0.8298 | -3.6155 | — | — | — | 47 |
| climatology | 0.6988 | 0.7915 | -3.4429 | -0.048 | -0.044 | 0.105 / 0.303 | 47 |
| persistence | 0.8904 | 1.0278 | -9.5823 | +0.193 | +0.181 | 0.021 / 0.065 | 47 |
| known_accumulation * | 0.6988 | 0.7915 | -3.4429 | -0.048 | -0.044 | 0.105 / 0.303 | 47 |
| c3s_raw † | nan | nan | nan | N/A | N/A | — | 0 |

---

**Footnotes**

\* For every approved (target, lead) pair in PROJECT_SPEC.md section 4.1, overlap with the observed accumulation window is zero (k - L = 0 for spi_1@+1, spi_3@+3, sm_anom@+1, ndvi_anom@+1). Under zero overlap, known-accumulation has nothing observed to condition on and reduces exactly to climatology - so the two columns in the skill table being numerically identical is the expected, designed consequence of section 4.1 (Problem 1's fix), not a bug or a duplicated computation. Verified independently rather than assumed: see tests/test_leakage.py::test_known_accumulation_baseline_matches_climatology_numerically. If a future (target, lead) pair has nonzero overlap, this note and that test's expectation both stop applying and must be revised together.

† CDS access pending - see reports/phase0_log.md open items (list B)

‡ Persistence's probability forecast is CALIBRATED, not a hard 0/1 step function: P(target < threshold, lead months ahead | target < threshold lead-months-ago, the value known at issue time), fit basin-wide on the reference period and applied unchanged - see src/models/baselines.py persistence_probability_forecast. A hard 0/1 form was used through the first T8 run; the skeptic audit found it was a quadratic-scoring-rule worst case that inflated "model beats persistence" from a real margin into mostly an artefact of an uncalibrated baseline. Recalibrating moved spi_3@+3's model_bss (the model's Brier Skill Score against persistence, see src/eval/skill.py skill_score) from +0.377 (hard 0/1) to -0.048 (calibrated, after also fixing a leak the recalibration itself introduced and this project's own "better than expected -> suspect a leak first" rule caught - see reports/phase0_log.md): the model does not beat a properly calibrated persistence at this target either, which the hard-0/1 baseline was hiding. AUC is still coarser than a continuous forecast's because the basin-wide fit yields only two distinct probability values (one per current state) rather than a per-cell continuum - that remaining coarseness is a property of pooling for sample size, not of thresholding, and not a defect.

§ **What the p-values do and do not establish.** Paired t-test and Wilcoxon signed-rank, computed on the model's and each baseline's per-date metric series aligned on the SAME test dates - not a test of the two already-averaged means printed in the table. Both assume the paired differences are independent across dates, which they are NOT here: consecutive test months share autocorrelated weather (spi_3's own accumulation window adds direct overlap between neighbouring dates on top of that). So a p-value here is optimistic - smaller than it would be for truly independent dates - and should be read as "is this gap even plausibly bigger than noise", not as a formal significance claim. Added after the skeptic audit found every skill number in earlier versions of this table was a bare mean with nothing to say whether the two methods were distinguishable at all.

**Why Wilcoxon is printed first.** The paired t-test's standard error is built from the sample variance of the per-date differences under an independence assumption; positive autocorrelation between dates means the TRUE variance of the mean difference is larger than that formula computes, so the t-test mechanically UNDERSTATES its own uncertainty and reports a smaller p-value than a correctly-specified test would - a known, directional bias, not a vague caveat. Wilcoxon is rank-based and does not share that specific mechanism, though it is not immune to dependence either - it is the more conservative of the two here, not a dependence-corrected one. Where the two disagree (spi_3@+3 vs climatology: t=0.014, Wilcoxon=0.078), read Wilcoxon's number as the primary one and the t-test's as a supporting figure that likely overstates significance, not the reverse.

Reliability diagrams and spatially blocked CV are Phase 3 work (reports/phase0_log.md list B), not computed here.

**Why R² looks so negative.** R² here is computed CROSS-SECTIONALLY - across analysis cells within one forecast date, per PROJECT_SPEC.md 4.4's per-forecast-date aggregation (never pooled across rows) - not across time for one cell, which is the usual reading of "R² of a forecast model". SPI at a single date is spatially correlated basin-wide, so its cross-cell spread within one month is narrow (std ~0.2-0.5 SPI units); a modest absolute error against that narrow spread produces a large negative R². Verified by hand for one date against scikit-learn's r2_score (exact match, -0.718) - this is the metric's designed behaviour under PROJECT_SPEC.md 4.4, not a bug.