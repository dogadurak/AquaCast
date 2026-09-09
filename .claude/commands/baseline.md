---
description: Produce the skill table - model vs all four baselines
---

Retrain or reload the current model, then produce the skill table:

- rows: (target, lead) pairs
- columns: model, climatology, persistence, known-accumulation baseline, raw C3S
- plus the skill score of the model against each baseline

Aggregate per forecast date, not pooled across rows.

Write to `reports/skill_table.md` and print it.
State plainly whether the model beats every baseline, and where it does not.
