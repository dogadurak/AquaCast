---
description: Independent skeptic audit for data leakage and inflated metrics
---

Invoke the `skeptic` agent on the current state of `src/features`, `src/models` and
`src/eval`, plus the latest `reports/metrics_*.json` and the diff since the last audit.

Give it the file list and the current skill table. Ask for a ranked findings list
with file:line evidence.

Do not summarise away its findings - report them verbatim, then propose fixes
separately.
