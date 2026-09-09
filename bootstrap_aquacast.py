#!/usr/bin/env python3
"""
AquaCast repo bootstrap.

Creates the full project skeleton, including the .claude/ configuration that
Claude Code reads: subagents, slash commands, skills, settings.

Usage:
    python bootstrap_aquacast.py                 # creates ./aquacast
    python bootstrap_aquacast.py --path ~/dev/aquacast
    python bootstrap_aquacast.py --force         # overwrite existing files

After running:
    cd aquacast
    python -m venv .venv && source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
    pip install -r requirements.txt
    earthengine authenticate
    git init && git add -A && git commit -m "chore: scaffold AquaCast"
    claude

Then paste the Phase 0 prompt from AGENT_WORKFLOW.md section 6.

Note: PROJECT_SPEC.md, CLAUDE.md and AGENT_WORKFLOW.md are NOT written by this
script - copy the versions you already have into the project root.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

DIRS = [
    "config",
    "data/raw",
    "data/interim",
    "data/processed",
    "docs",
    "frontend",
    "notebooks",
    "reports/figures",
    "scripts",
    "src/data",
    "src/features",
    "src/models",
    "src/eval",
    "src/api",
    "tests",
    ".claude/agents",
    ".claude/commands",
    ".claude/skills/spi-indices",
    ".claude/skills/gee-export",
    ".claude/skills/forecast-eval",
    ".claude/skills/cds-access",
]

FILES: dict[str, str] = {}

# ---------------------------------------------------------------- .gitignore
FILES[".gitignore"] = """\
.venv/
__pycache__/
*.pyc
.env
.cdsapirc

# data is reproducible - never commit it
data/raw/*
data/interim/*
data/processed/*
!data/**/.gitkeep

# keep metrics and figures, they are the results
!reports/**

.ipynb_checkpoints/
node_modules/
.DS_Store
"""

# ------------------------------------------------------------- requirements
FILES["requirements.txt"] = """\
earthengine-api>=1.1.0
cdsapi>=0.7.7
requests>=2.31
numpy>=1.26
pandas>=2.2
pyarrow>=15.0
geopandas>=1.0
shapely>=2.0
rasterio>=1.3
xarray>=2024.3
netCDF4>=1.6
scipy>=1.12
scikit-learn>=1.4
xgboost>=2.0
lightgbm>=4.3
shap>=0.45
climate-indices>=2.0
matplotlib>=3.8
pytest>=8.0
fastapi>=0.110
uvicorn>=0.29
pyyaml>=6.0
"""

# ------------------------------------------------------------------ Makefile
FILES["Makefile"] = """\
.PHONY: check data features train eval api test all

check:
\tpython scripts/check_data_access.py --json reports/data_access.json

data:
\tpython -m src.data.build_panel --config config/data.yaml

features:
\tpython -m src.features.build_features --config config/features.yaml

train:
\tpython -m src.models.train --config config/model.yaml

eval:
\tpython -m src.eval.evaluate --config config/model.yaml

api:
\tuvicorn src.api.main:app --reload

test:
\tpytest -q

all: data features train eval
"""

# ------------------------------------------------------------------- configs
FILES["config/data.yaml"] = """\
aoi:
  name: konya_closed_basin
  bbox: [31.4, 36.7, 35.2, 39.4]      # W, S, E, N (EPSG:4326)
  boundary_source: hydrobasins_l5      # replace with DSI boundary when obtained

grid:
  resolution_m: 1000
  crs: EPSG:4326
  mask_landcover: [cropland, grassland]

period:
  start: 2001-01-01
  end: 2025-12-31

climatology:
  baseline_start: 1991-01-01
  baseline_end: 2020-12-31
  # baseline statistics must be computed from TRAINING data only

sources:
  precipitation_primary: UCSB-CHC/CHIRPS/V3/PENTAD
  reanalysis: ECMWF/ERA5_LAND/MONTHLY_AGGR
  ndvi: MODIS/061/MOD13A2
  ndvi_successor: NASA/VIIRS/002/VNP13A1
  evapotranspiration: MODIS/061/MOD16A2GF
  lst: MODIS/061/MOD11A2
  landcover: ESA/WorldCover/v200
  dem: USGS/SRTMGL1_003

export:
  chunk_by: year          # never export the whole record in one job
  drive_folder: aquacast_exports
"""

FILES["config/model.yaml"] = """\
targets:
  # (target, lead) pairs must not overlap their predictor window
  - name: spi_1
    lead_months: 1
    tier: 1
    kind: regression
  - name: sm_anom
    lead_months: 1
    tier: 1
    kind: regression
  - name: spi_3
    lead_months: 3
    tier: 2
    kind: classification      # P(SPI-3 < -1)
    threshold: -1.0

split:
  train: [2001-01-01, 2016-12-31]
  gap_1: [2017-01-01, 2017-12-31]     # gap >= longest accumulation window
  validation: [2018-01-01, 2020-12-31]
  gap_2: [2021-01-01, 2021-12-31]
  test: [2022-01-01, 2025-12-31]

baselines:
  - climatology
  - persistence
  - known_accumulation      # the anti-leakage control - mandatory
  - c3s_raw                 # tier 2 only

model:
  primary: xgboost
  crosscheck: lightgbm
  seed: 42

evaluation:
  aggregate: per_forecast_date     # never pool across all rows
  report_by: [lead, landcover, cell]
  metrics_regression: [mae, rmse, r2, skill_score]
  metrics_probabilistic: [brier_skill_score, roc_auc, reliability]
  spatial_blocked_cv: true
  permutation_test: true
"""

# ------------------------------------------------------------------- agents
FILES[".claude/agents/skeptic.md"] = """\
---
name: skeptic
description: Independent audit of the modelling pipeline for data leakage, inflated metrics, and unsupported claims. Invoke at the end of Phase 0, Phase 2 and Phase 3, and after any change to features, targets, splits or evaluation.
tools: Read, Grep, Glob, Bash
model: opus
---

You audit a drought forecasting pipeline for the Konya Closed Basin. You did not
write this code and you should not trust its author's reasoning. Your job is to
find reasons the reported skill is not real.

Assume good results are wrong until proven otherwise. In this project a model
that looks excellent is more likely to be leaking than to be good.

Work through this checklist and report findings with file:line evidence.

## Accumulation overlap
- For every (target, lead) pair actually trained, does the target's accumulation
  window overlap months observable at forecast time? SPI-k at lead L overlaps by
  (k - L) months when L < k.
- Is the known-accumulation baseline implemented, and does the model beat it?

## Temporal leakage
- Are climatology, gamma-fit parameters for SPI, anomaly baselines and scalers
  fitted on training data only?
- Are there gap years between train/validation/test at least as long as the
  longest accumulation window?
- Does any feature at time t use data from t+1 or later? Check every shift(),
  rolling() and merge for direction and alignment.

## Evaluation validity
- Are metrics computed per forecast date and then aggregated, or pooled across
  all rows? Pooling across ~600k spatially autocorrelated rows is invalid.
- Are all four baselines reported alongside every headline metric?
- Is the probabilistic tier evaluated with Brier Skill Score and a reliability
  diagram, not just accuracy?

## Sanity controls
- Does a permutation test on shuffled targets return near-zero skill? If not,
  something is structurally wrong.
- Do per-cell skill maps show plausible spatial structure, or suspiciously
  uniform high skill?

## Claims
- Does any README, report, notebook or docstring state a skill claim without
  naming the baseline it beats and the margin?

Report as a ranked list: severity, file:line, what is wrong, and the concrete
failure it causes. If you find nothing, say so plainly and name what you checked.
Do not soften findings, and do not propose fixes unless asked - your value is
diagnosis.
"""

FILES[".claude/agents/data-engineer.md"] = """\
---
name: data-engineer
description: Builds and maintains the data ingestion layer - Earth Engine exports, CDS downloads, and the monthly panel. Use for Phase 1 work and any ingestion bug.
tools: Read, Write, Edit, Bash, Grep, Glob, WebFetch
---

You own `src/data/` and the export scripts. You produce exactly one artefact:
`data/processed/panel_monthly.parquet`, matching the schema in CLAUDE.md.

Rules:
- All raster reduction happens in Earth Engine. Nothing downstream touches a raster.
- Chunk GEE exports by year. A single whole-record export will exceed the free-tier
  EECU budget and time out.
- CDS requests queue for hours. Make them resumable and idempotent; never re-download
  what exists on disk.
- Vegetation and ET access goes through the MODIS/VIIRS source abstraction. MODIS
  ends in late 2026/early 2027; the VIIRS path must work before it is needed.
- Every column in the panel is documented in `docs/data_dictionary.md` with units,
  source, native resolution and known biases.
- Write an integrity report: missing months per cell, outliers, unit sanity checks.
- Resolution mismatch must be recorded, not hidden: a 1 km grid fed by 9 km ERA5-Land
  carries 9 km information.

Never fabricate a value to fill a gap. Missing stays missing, with a flag column.
"""

FILES[".claude/agents/ml-scientist.md"] = """\
---
name: ml-scientist
description: Feature engineering, SPI/SPEI computation, model training and evaluation. Use for Phase 2 and Phase 3 work.
tools: Read, Write, Edit, Bash, Grep, Glob
---

You own `src/features/`, `src/models/` and `src/eval/`.

Order of work, and it is not negotiable: baselines first, model second. Implement
climatology, persistence, the known-accumulation baseline and the raw C3S ensemble
before training anything. They define what "good" means; a model built before them
has no yardstick.

Rules:
- Approved (target, lead) pairs only - PROJECT_SPEC.md section 4.1. No target may
  overlap its predictor window.
- Validate the SPI implementation against a reference (`climate_indices` package or
  Copernicus GDO values) before trusting a single downstream number.
- Fit all normalisation on the training period only.
- Report metrics per forecast date, per lead, per land-cover class, and per cell.
- XGBoost first. LightGBM as a cross-check. LSTM only with evidence of underfitting.
- SHAP for drivers, computed on the test period.
- Every run writes `reports/metrics_<timestamp>.json` with the git SHA and config hash.

When results improve sharply after a change, your first hypothesis is a leak, not a
breakthrough. Investigate before reporting.
"""

FILES[".claude/agents/frontend.md"] = """\
---
name: frontend
description: Map, dashboard and API layer. Use for Phase 4-5 work only, after the Phase 3 gate passes.
tools: Read, Write, Edit, Bash, Grep, Glob
---

You own `frontend/` and `src/api/`. You consume precomputed GeoJSON and metrics
JSON; you never compute a forecast.

Rules:
- MapLibre GL JS + Plotly. Vanilla JS or minimal React. No Next.js in v1.
- No tile server, no on-the-fly raster rendering.
- FastAPI serves files. No database in v1.
- Cells with no measured skill (BSS <= 0) must be visually unmistakable - hatched or
  greyed, never a colour on the same scale as skilful cells. This is a correctness
  requirement, not a style preference: a confident colour over a skill-less forecast
  is the interface lying to its user.
- Every forecast view shows its lead time, its measured skill, and a link to the
  model card.
- The cell inspector shows: history since 2001, current drivers (SHAP), forecast
  with uncertainty, and that cell's skill.
"""

# ----------------------------------------------------------------- commands
FILES[".claude/commands/data-check.md"] = """\
---
description: Verify every dataset is reachable before any pipeline work
---

Run `python scripts/check_data_access.py --json reports/data_access.json`.

Summarise: which datasets resolved, their real date ranges, and any blocker.
For each failure, state the concrete fix (register a Cloud project for Earth Engine,
accept a CDS licence in the web interface, install a package).

Do not proceed to pipeline work while a CORE dataset fails.
"""

FILES[".claude/commands/baseline.md"] = """\
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
"""

FILES[".claude/commands/leakage-audit.md"] = """\
---
description: Independent skeptic audit for data leakage and inflated metrics
---

Invoke the `skeptic` agent on the current state of `src/features`, `src/models` and
`src/eval`, plus the latest `reports/metrics_*.json` and the diff since the last audit.

Give it the file list and the current skill table. Ask for a ranked findings list
with file:line evidence.

Do not summarise away its findings - report them verbatim, then propose fixes
separately.
"""

FILES[".claude/commands/phase-gate.md"] = """\
---
description: Check the current phase gate before moving on
---

Read the gate criteria for the current phase in PROJECT_SPEC.md section 6.

Check each criterion against the actual repository state - run the tests, check the
artefacts exist, verify the metrics reproduce from a clean run.

Report PASS or FAIL per criterion with evidence. If any criterion fails, state what
remains and do not start the next phase.
"""

FILES[".claude/commands/eval-report.md"] = """\
---
description: Regenerate all evaluation artefacts and the model card
---

Regenerate: metrics JSON, skill table, reliability diagram, per-cell skill map,
SHAP summary.

Update `reports/model_card.md` with the current numbers, training period, baselines,
and known limitations.

Every claim in the model card must trace to a number in the metrics JSON.
"""

# ------------------------------------------------------------------- skills
FILES[".claude/skills/spi-indices/SKILL.md"] = """\
---
name: spi-indices
description: Correct computation of SPI, SPEI and standardised anomalies for drought analysis. Use whenever computing, validating or debugging a drought index, or when choosing a reference period.
---

# Drought index computation

SPI failures are silent. A wrong implementation returns plausible numbers and no
error, and every downstream result inherits the mistake. Validate before trusting.

## SPI, correctly

1. Aggregate precipitation over the accumulation window (k months, rolling sum).
2. Fit a gamma distribution **per cell, per calendar month** - seasonality means a
   single fit across all months is wrong.
3. Handle zero precipitation explicitly. The gamma distribution is undefined at
   zero, so use the mixed distribution: `H(x) = q + (1-q) * G(x)` where `q` is the
   probability of zero. Skipping this biases arid-month values, which in a drought
   study is exactly where accuracy matters.
4. Transform the cumulative probability to the standard normal quantile.

## Rules that are not optional

- **Fit parameters on the training period only.** Fitting on the full record leaks
  test-period statistics into training. State the reference period everywhere.
- **State the reference period in every output and figure.** SPI values are
  meaningless without it; 1991-2020 is the current WMO normal.
- **Minimum record length: 30 years for stable fits.** With 25 years, say so as a
  limitation rather than pretending otherwise.
- **Accumulation window vs forecast lead.** SPI-k at lead L < k overlaps the
  observed period by (k - L) months. Never forecast such a pair without the
  known-accumulation baseline.

## SPEI

SPEI replaces precipitation with (precipitation - PET) and fits a log-logistic
distribution, not gamma. Use Hargreaves PET when only temperature is available;
Penman-Monteith when radiation, wind and humidity are available (ERA5-Land provides
them). Do not mix PET methods within one study.

## Validation, before anything downstream

Compare against the `climate_indices` package or published Copernicus GDO values for
the same cells and months. Agreement within a small tolerance, or find out why not.
"""

FILES[".claude/skills/gee-export/SKILL.md"] = """\
---
name: gee-export
description: Google Earth Engine export patterns, quota management and pitfalls. Use when writing or debugging any GEE export, or when an export times out or exceeds quota.
---

# Earth Engine exports

## Quota

Noncommercial tiers: Community 150 EECU-hours/month, Contributor 1,000. A basin-scale
monthly export fits comfortably if chunked; a single whole-record job will not.

## Rules

- **Chunk by year.** One export task per year, named deterministically so reruns skip
  completed years.
- **Reduce server-side.** `reduceRegions` over the analysis grid, never a client-side
  loop over cells with `getInfo()` per cell - that is the most common way to turn a
  five-minute job into an hour and a quota overrun.
- **Set `scale` and `crs` explicitly** on every reducer and export. Defaults silently
  reproject and the result is wrong at the edges.
- **Export tables, not rasters.** The pipeline consumes a monthly panel. Use
  `Export.table.toDrive` with CSV; never download GeoTIFFs.
- **`tileScale`** raises to 4 or 8 when hitting memory errors, at some speed cost.
- **Monthly compositing:** build the month list explicitly and map over it; do not
  rely on `.filterDate` inside a client-side loop.
- **Masking:** apply the land-cover and basin masks before reduction, not after.

## Debugging

- "Computation timed out" -> chunk smaller, raise tileScale
- "User memory limit exceeded" -> raise tileScale, reduce band count per job
- Empty results -> check `filterBounds` geometry CRS and that the collection actually
  covers the AOI dates
"""

FILES[".claude/skills/forecast-eval/SKILL.md"] = """\
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
"""

FILES[".claude/skills/cds-access/SKILL.md"] = """\
---
name: cds-access
description: Copernicus Climate Data Store access - authentication, licence acceptance, seasonal forecast requests, queue behaviour. Use when downloading ERA5-Land or C3S seasonal forecast data.
---

# Copernicus CDS access

## Setup

1. Register at cds.climate.copernicus.eu
2. Copy the personal access token into `~/.cdsapirc`:
   ```
   url: https://cds.climate.copernicus.eu/api
   key: <personal-access-token>
   ```
3. `pip install "cdsapi>=0.7.7"`
4. **Accept the licence in the web interface for each dataset**, separately. This is
   the most common first-day failure: API requests fail until the licence is accepted
   on the dataset's own page. Needed for *ERA5-Land monthly averaged data* and
   *Seasonal forecast monthly statistics on single levels*.

## Behaviour to design around

- Requests **queue**, sometimes for hours. Never block a pipeline on a live request.
- Make downloads **resumable and idempotent**: check for the file on disk first, and
  chunk by year or by initialisation month so a failure costs one chunk.
- Request only the AOI via `area: [north, west, south, east]` - full-globe requests
  queue far longer for no benefit.

## Seasonal forecasts (tier 2)

`seasonal-monthly-single-levels` provides multi-system ensembles up to 6 months lead,
with hindcasts from at least 1993-2016 for skill assessment.

Key request fields: `originating_centre`, `system`, `year`, `month` (initialisation),
`leadtime_month`, `variable`, `product_type` (`monthly_mean`).

Download the hindcast archive **once, early, in the background**. It is the long pole
in the data schedule.

Bias correction against ERA5-Land over the hindcast period is required before the
forecasts are usable as features - raw seasonal model output carries systematic bias.
"""

# ------------------------------------------------------------------ settings
FILES[".claude/settings.json"] = """\
{
  "permissions": {
    "allow": [
      "Bash(python:*)",
      "Bash(pytest:*)",
      "Bash(make:*)",
      "Bash(git status)",
      "Bash(git diff:*)",
      "Bash(git log:*)"
    ]
  }
}
"""

# ---------------------------------------------------------------- placeholders
FILES["docs/data_dictionary.md"] = """\
# Data dictionary

Every column in `data/processed/panel_monthly.parquet` is documented here:
name, units, source dataset, native resolution, known biases, missing-data handling.

Filled in during Phase 1. A column that is not documented here does not exist as far
as the rest of the pipeline is concerned.
"""

FILES["reports/model_card.md"] = """\
# Model card - AquaCast

Filled in during Phase 3. Every number here must trace to a `reports/metrics_*.json`.

## Intended use
## Training data and period
## Baselines and measured skill
## Where the model has no skill
## Known limitations
## Data provenance
"""

FILES["tests/test_leakage.py"] = '''\
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
'''

FILES["README.md"] = """\
# AquaCast

Basin-scale drought forecasting for the Konya Closed Basin, with honest skill
reporting.

See `PROJECT_SPEC.md` for the design, `CLAUDE.md` for the working rules, and
`AGENT_WORKFLOW.md` for how the project is built with coding agents.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
earthengine authenticate
make check          # verify every dataset is reachable
```

## Status

Phase 0 - feasibility spike. No skill claims yet.

Results will be published here only alongside the baselines they beat and by how
much. A metric without its baseline is not a result.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="aquacast", help="target directory")
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    args = parser.parse_args()

    root = Path(args.path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    for d in DIRS:
        p = root / d
        p.mkdir(parents=True, exist_ok=True)
        if d.startswith("data/") or d.startswith("reports"):
            (p / ".gitkeep").touch()

    written, skipped = 0, 0
    for rel, content in FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not args.force:
            skipped += 1
            continue
        path.write_text(content, encoding="utf-8")
        written += 1

    for pkg in ["src", "src/data", "src/features", "src/models", "src/eval", "src/api"]:
        init = root / pkg / "__init__.py"
        if not init.exists():
            init.touch()

    print(f"AquaCast scaffold created at: {root}")
    print(f"  files written: {written}, skipped (already present): {skipped}")
    print()
    print("Next steps:")
    print(f"  1. Copy PROJECT_SPEC.md, CLAUDE.md, AGENT_WORKFLOW.md into {root}")
    print(f"  2. Copy check_data_access.py into {root / 'scripts'}")
    print("  3. python -m venv .venv && source .venv/bin/activate")
    print("  4. pip install -r requirements.txt")
    print("  5. earthengine authenticate")
    print("  6. git init && git add -A && git commit -m 'chore: scaffold AquaCast'")
    print("  7. claude          # then run /data-check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
