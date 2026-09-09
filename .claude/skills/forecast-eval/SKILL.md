---
name: forecast-eval
description: Evaluating spatio-temporal forecasts honestly - skill scores, blocked validation, probabilistic metrics. Use whenever computing, reporting or reviewing model performance.
---

# Forecast evaluation

A metric without a baseline is not a result. This project reports skill scores
against explicit baselines, always.

## Skill score

```
SS = 1 - (error_model / error_baseline)
```
Positive means better than the baseline; zero or negative means the baseline wins and
the model has no value at that lead time and location. Report SS against every
baseline, not just the easiest one.

## Mandatory baselines

1. **Climatology** - long-term probability for that cell and calendar month
2. **Persistence** - current value carried forward
3. **Known-accumulation** - observed part of the accumulation window plus climatology
   for the rest. This is the control for accumulation-overlap leakage and it is the
   one that most often beats a naive model.
4. **Raw dynamical forecast** - C3S ensemble used directly, for tier 2

## Aggregation

Compute metrics **per forecast date**, then summarise across dates. Pooling all
cell-months treats spatially autocorrelated neighbours as independent samples and
inflates confidence by an order of magnitude.

## Splitting

Temporal split with **gap periods** at least as long as the longest accumulation
window, otherwise adjacent train and test periods share data through the rolling sum.
Add spatially blocked CV as a robustness check.

## Probabilistic forecasts

- **Brier Skill Score** against climatology, not raw Brier
- **Reliability diagram** - a forecast saying 70% should verify near 70%
- **ROC AUC** for discrimination
- Never report accuracy alone on imbalanced drought classes

## Sanity controls

- Permutation test: shuffle the target, retrain, confirm skill collapses to ~0
- Per-cell skill maps: real skill has spatial structure; uniform high skill is a
  symptom of leakage
