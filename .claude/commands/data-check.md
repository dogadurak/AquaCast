---
description: Verify every dataset is reachable before any pipeline work
---

Run `python scripts/check_data_access.py --json reports/data_access.json`.

Summarise: which datasets resolved, their real date ranges, and any blocker.
For each failure, state the concrete fix (register a Cloud project for Earth Engine,
accept a CDS licence in the web interface, install a package).

Do not proceed to pipeline work while a CORE dataset fails.
