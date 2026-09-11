# Skill table - Phase 0 gate

Analysis population: **1,823 cells** (`in_hydrobasins & ~in_akarcay_lobe & crop_frac_2021 >= 0.5`).

Metrics computed **per forecast date** across analysis cells, then averaged across test-period dates - never pooled across (cell, date) rows. See CLAUDE.md rule 4.

## spi_3 @ +3 month(s) (classification)

| method | AUC (n=35) | Brier (n=45) | model BSS | p (Brier, t-test / Wilcoxon / sign §) |
|---|---|---|---|---|
| model | 0.4768 | 0.2052 | — | — |
| climatology | 0.5129 | 0.1949 | -0.053 | t=0.014 / w=0.078 / sign=0.233, r₁=+0.51 |
| persistence ‡ | 0.4826 | 0.1955 | -0.050 | t=0.015 / w=0.117 / sign=0.766, r₁=+0.53 |
| known_accumulation * | 0.5129 | 0.1949 | -0.053 | t=0.014 / w=0.078 / sign=0.233, r₁=+0.51 |
| c3s_raw † | nan | nan | N/A | — |

AUC excludes 10 of 45 test dates where every analysis cell fell in the same class (basin-wide drought or none) - undefined for AUC, not for Brier, which scores all 45 dates including those. Dropped for both metrics: 0 date(s) with fewer than 10 analysis cells.

## spi_1 @ +1 month(s) (regression)

| method | MAE | RMSE | R² | model skill (RMSE) | model skill (MAE) | p (MAE, t-test / Wilcoxon / sign §) | n dates |
|---|---|---|---|---|---|---|---|
| model | 0.7296 | 0.8298 | -3.6155 | — | — | — | 47 |
| climatology | 0.6988 | 0.7915 | -3.4429 | -0.048 | -0.044 | t=0.303 / w=0.105 / sign=0.040, r₁=+0.10 | 47 |
| persistence | 0.8904 | 1.0278 | -9.5823 | +0.193 | +0.181 | t=0.065 / w=0.021 / sign=0.040, r₁=-0.06 | 47 |
| known_accumulation * | 0.6988 | 0.7915 | -3.4429 | -0.048 | -0.044 | t=0.303 / w=0.105 / sign=0.040, r₁=+0.10 | 47 |
| c3s_raw † | nan | nan | nan | N/A | N/A | — | 0 |

---

**Footnotes**

\* For every approved (target, lead) pair in PROJECT_SPEC.md section 4.1, overlap with the observed accumulation window is zero (k - L = 0 for spi_1@+1, spi_3@+3, sm_anom@+1, ndvi_anom@+1). Under zero overlap, known-accumulation has nothing observed to condition on and reduces exactly to climatology - so the two columns in the skill table being numerically identical is the expected, designed consequence of section 4.1 (Problem 1's fix), not a bug or a duplicated computation. Verified independently rather than assumed: see tests/test_leakage.py::test_known_accumulation_baseline_matches_climatology_numerically. If a future (target, lead) pair has nonzero overlap, this note and that test's expectation both stop applying and must be revised together.

† CDS access pending - see reports/phase0_log.md open items (list B)

‡ Persistence's probability forecast is CALIBRATED, not a hard 0/1 step function: P(target < threshold, lead months ahead | target < threshold lead-months-ago, the value known at issue time), fit basin-wide on the reference period and applied unchanged - see src/models/baselines.py persistence_probability_forecast. A hard 0/1 form was used through the first T8 run; the skeptic audit found it was a quadratic-scoring-rule worst case that inflated "model beats persistence" from a real margin into mostly an artefact of an uncalibrated baseline. Recalibrating moved spi_3@+3's model_bss (the model's Brier Skill Score against persistence, see src/eval/skill.py skill_score) from +0.377 (hard 0/1) to -0.050 (calibrated, after also fixing two more issues the second skeptic audit found: a small fit-boundary overrun and the fit pooling across cells outside the analysis population - see reports/phase0_log.md for both). Either way the model does not beat a properly calibrated persistence at this target, which the hard-0/1 baseline was hiding - though see the significance footnote in reports/skill_table.md: none of this table's gaps is statistically established at this sample size, in either direction. AUC is still coarser than a continuous forecast's because the basin-wide fit yields only two distinct probability values (one per current state) rather than a per-cell continuum. THRESHOLDING IS PART OF WHY, not just pooling for sample size as an earlier version of this note claimed (corrected by the second skeptic audit): `persistence_probability_forecast` binarises the CONDITIONING variable itself (today's state, above/below threshold) before estimating a rate, so even a per-cell fit would still yield exactly two values per cell - pooling removes cross-cell variation on top of that, it does not cause the two-value ceiling.
STATED PLAINLY, not left for a reader to notice: the two calibrated rates on the analysis population are 0.1570 and 0.1754 - 1.8 points apart, both close to the ~0.159 basin base rate. Calibrated persistence is therefore numerically close to a near-constant forecast here, not far from climatology's own row (Brier 0.1955 vs climatology's 0.1949, within 0.001) - it satisfies CLAUDE.md rule 1's "four baselines" formally, but it barely adds information beyond the climatology row for spi_3@+3 in this run. This does not mean persistence is the wrong baseline to compute - a target with a stronger true persistence signal would separate the two rates further - it means this specific result (SPI-3 at +3 months) is one where persistence has little to say, which is itself informative and should be read alongside the BSS number, not instead of it.

§ **What the p-values do and do not establish.** Three tests, computed on the model's and each baseline's per-date metric series aligned on the SAME test dates - not on the two already-averaged means printed in the table - and NONE of the three is nominated as primary. All three assume the paired differences are independent across dates, which they are NOT here: consecutive test months share autocorrelated weather (spi_3's own accumulation window adds direct overlap between neighbouring dates on top of that), so every p-value here is generally optimistic (too small), not rigorous - read as "is this gap even plausibly bigger than noise", never as a formal significance claim. r₁ is the measured lag-1 autocorrelation of each comparison's paired differences, printed alongside so a reader can judge how much to discount a given p rather than trusting a rule.

**A withdrawn claim, corrected rather than deleted.** An earlier version of this table printed Wilcoxon before the t-test and told readers to treat it as the conservative, primary number, reasoning that the t-test's variance estimator is anti-conservative under positive autocorrelation. The second skeptic audit found this indefensible: Wilcoxon's own null variance formula assumes independent differences too, so a rank transform confers no documented robustness to serial dependence - the claimed mechanism does not single out Wilcoxon as safer. Worse, the premise (positive autocorrelation) does not hold uniformly - r₁ is large for spi_3 vs climatology but near zero for spi_1's rows - so the rule was applied where its own justification did not apply. In practice it was the only thing that put this table's one positive claim (model beats persistence at spi_1@+1) under 0.05: Wilcoxon gives 0.021 there, the t-test 0.065, and the sign test (the test least sensitive to autocorrelation or skew - model wins 31 of 47 dates) 0.040 - all three actually agree the gap is suggestive, but their p-values still span a wide range (0.021-0.065) on the same 47 dates, which is itself the point: no single one of the three should be quoted alone as THE p-value for this comparison.

**Multiple comparisons, not corrected for.** Six paired tests are reported across the two targets' baseline rows (two of the six, known_accumulation, duplicate climatology's numbers by construction - see \*). With six tests and no correction, a naive 0.05 threshold understates how easily one gap clears it by chance; a Bonferroni-adjusted threshold over four independent comparisons would be 0.05/4 = 0.0125, which none of this table's p-values clears on all three tests simultaneously. This project does not claim the model beats or loses to any baseline at conventional significance - the honest summary is that none of these gaps is established, in either direction, at this sample size.

Reliability diagrams and spatially blocked CV are Phase 3 work (reports/phase0_log.md list B), not computed here.

**Why R² looks so negative.** R² here is computed CROSS-SECTIONALLY - across analysis cells within one forecast date, per PROJECT_SPEC.md 4.4's per-forecast-date aggregation (never pooled across rows) - not across time for one cell, which is the usual reading of "R² of a forecast model". SPI at a single date is spatially correlated basin-wide, so its cross-cell spread within one month is narrow (std ~0.2-0.5 SPI units); a modest absolute error against that narrow spread produces a large negative R². Verified by hand for one date against scikit-learn's r2_score (exact match, -0.718) - this is the metric's designed behaviour under PROJECT_SPEC.md 4.4, not a bug.