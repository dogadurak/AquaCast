# Agent Workflow — how to actually build AquaCast with coding agents

This answers three questions: how many agents, which skills, which commands.

---

## 1. How many agents

**Recommendation: one main agent, four specialist subagents, at most two running concurrently — and usually one.**

Parallel agents help when tasks are genuinely independent and touch disjoint files. A data-science pipeline is the opposite: features depend on the panel schema, models depend on features, evaluation depends on models, and all of them share `config/` and the data contract. Running four agents at once on this repository produces merge conflicts, duplicated helper functions, and two incompatible SPI implementations — spending more time reconciling than the parallelism saved.

The one exception worth taking: **Phase 5 (frontend) can run concurrently with late Phase 3/4 work**, because the frontend touches only `frontend/` and consumes a fixed GeoJSON contract. Agree the contract first, then parallelise.

There is a second, more important reason to keep agent count low. The main risk in this project is a subtle data leak that makes results look excellent. An agent that writes the pipeline and then evaluates its own pipeline will not find its own leak — it has the same blind spot in both roles. That is why the skeptic below is a **separate agent invoked in a fresh context**, given the diff and the metrics but not the reasoning that produced them. Its independence is the entire point; do not let the implementing agent "self-review" instead.

### The four specialists

| Agent | Runs during | Owns | Never touches |
|---|---|---|---|
| `data-engineer` | Phase 1 | `src/data/`, GEE export scripts, CDS ingestion | models, evaluation |
| `ml-scientist` | Phase 2–3 | `src/features/`, `src/models/` | frontend, data ingestion |
| `skeptic` | end of Phase 0, 2, 3 | nothing — read-only audit | everything (read-only) |
| `frontend` | Phase 4–5 | `frontend/`, `src/api/` | models, features |

The main agent keeps the thread: plans phases, checks gates, integrates, and decides. Don't delegate the decisions — delegate the bounded work.

---

## 2. Agent definitions

Save each under `.claude/agents/`.

### `.claude/agents/skeptic.md`

```markdown
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
Do not soften findings, and do not propose fixes unless asked — your value is
diagnosis.
```

### `.claude/agents/data-engineer.md`

```markdown
---
name: data-engineer
description: Builds and maintains the data ingestion layer — Earth Engine exports, CDS downloads, and the monthly panel. Use for Phase 1 work and any ingestion bug.
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
```

### `.claude/agents/ml-scientist.md`

```markdown
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
- Approved (target, lead) pairs only — PROJECT_SPEC.md §4.1. No target may overlap
  its predictor window.
- Validate the SPI implementation against a reference (`climate_indices` package or
  Copernicus GDO values) before trusting a single downstream number.
- Fit all normalisation on the training period only.
- Report metrics per forecast date, per lead, per land-cover class, and per cell.
- XGBoost first. LightGBM as a cross-check. LSTM only with evidence of underfitting.
- SHAP for drivers, computed on the test period.
- Every run writes `reports/metrics_<timestamp>.json` with the git SHA and config hash.

When results improve sharply after a change, your first hypothesis is a leak, not a
breakthrough. Investigate before reporting.
```

### `.claude/agents/frontend.md`

```markdown
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
- Cells with no measured skill (BSS <= 0) must be visually unmistakable — hatched or
  greyed, never a colour on the same scale as skilful cells. This is a correctness
  requirement, not a style preference: a confident colour over a skill-less forecast
  is the interface lying to its user.
- Every forecast view shows its lead time, its measured skill, and a link to the
  model card.
- The cell inspector shows: history since 2001, current drivers (SHAP), forecast
  with uncertainty, and that cell's skill.
```

---

## 3. Skills

Save under `.claude/skills/<name>/SKILL.md`. Skills carry knowledge the agent
would otherwise get wrong every time.

| Skill | Why it earns its place |
|---|---|
| `spi-indices` | SPI is where implementations quietly go wrong: gamma fitting with zero-precipitation months requires a mixed distribution, the fit must come from the training period, and the reference period must be stated. Getting this wrong invalidates everything downstream and produces no error message. |
| `gee-export` | Chunking strategy, EECU budget awareness, `Export.table.toDrive` patterns, scale/CRS pitfalls, why `reduceRegions` beats per-cell loops. |
| `forecast-eval` | Skill scores, Brier Skill Score, reliability diagrams, blocked CV, per-date aggregation. Encodes the rules the skeptic checks, so the implementer follows them from the start. |
| `cds-access` | Licence acceptance requirement, token setup, queueing behaviour, resumable chunked downloads, C3S seasonal request structure. |

Also use the built-in `dataviz` skill for every chart and the map's colour scales — drought maps have a strong convention (diverging brown-to-blue) and violating it costs credibility for no gain.

---

## 4. Slash commands

Save under `.claude/commands/`. These exist so that the rigorous path is the *easy*
path — a discipline you have to remember is a discipline you skip at 2am.

### `/data-check`
```markdown
Run `python scripts/check_data_access.py --json reports/data_access.json`.
Summarise: which datasets resolved, their real date ranges, and any blocker.
For each failure, state the concrete fix (register a project, accept a licence,
install a package). Do not proceed to pipeline work while a CORE dataset fails.
```

### `/baseline`
```markdown
Retrain or reload the current model, then produce the skill table:
rows = (target, lead); columns = model, climatology, persistence,
known-accumulation baseline, raw C3S; plus skill score of model vs each.
Aggregate per forecast date, not pooled across rows.
Write to reports/skill_table.md and print it.
State plainly whether the model beats every baseline, and where it does not.
```

### `/leakage-audit`
```markdown
Invoke the `skeptic` agent on the current state of src/features, src/models and
src/eval, plus the latest reports/metrics_*.json and the diff since the last audit.
Give it the file list and the current skill table. Ask for a ranked findings list
with file:line evidence. Do not summarise away its findings — report them verbatim,
then propose fixes separately.
```

### `/phase-gate`
```markdown
Read the gate criteria for the current phase in PROJECT_SPEC.md section 6.
Check each criterion against the actual repository state — run the tests, check the
artefacts exist, verify the metrics reproduce. Report PASS or FAIL per criterion
with evidence. If any criterion fails, state what remains and do not start the next
phase.
```

### `/eval-report`
```markdown
Regenerate all evaluation artefacts: metrics JSON, skill table, reliability diagram,
per-cell skill map, SHAP summary. Update reports/model_card.md with the current
numbers, training period, baselines, and known limitations. Every claim in the model
card must trace to a number in metrics JSON.
```

---

## 5. Suggested working loop

```
/data-check                      once, before anything else
  -> Phase 0 spike (main agent, ml-scientist for the model)
/baseline                        the Phase 0 deliverable
/leakage-audit                   before believing any of it
/phase-gate                      decide: continue as planned, or re-scope Tier 2
  -> Phase 1  data-engineer
/phase-gate
  -> Phase 2  ml-scientist
/leakage-audit ; /phase-gate
  -> Phase 3  ml-scientist
/eval-report ; /leakage-audit ; /phase-gate
  -> Phase 4-5  frontend  (may overlap late Phase 3)
/phase-gate
  -> Phase 6  documentation
```

The single most valuable habit: run `/leakage-audit` **before** you get attached to a
number, not after you have put it in a README.

---

## 6. First session prompt

Paste this to start:

```
Read PROJECT_SPEC.md and CLAUDE.md in full before doing anything.

We are starting Phase 0, the feasibility spike. The goal is NOT a working product.
The goal is a single answer: does an ML model beat climatology, persistence and the
known-accumulation baseline for SPI-3 at +3 months over the Konya Closed Basin, and
by how much?

Do this in order:
1. Run scripts/check_data_access.py and report blockers. Stop if a CORE dataset fails.
2. Write a minimal GEE export for the basin: CHIRPS v3 monthly precipitation and
   ERA5-Land monthly temperature and soil moisture, 2001-2025, on a 1 km grid masked
   to cropland. Export as CSV.
3. Compute SPI-1 and SPI-3, validating against a reference implementation.
4. Implement all four baselines BEFORE any model.
5. Train XGBoost for SPI-1 at +1 month and SPI-3 at +3 months.
6. Produce the skill table.

Do not build an API, a database, or a frontend. Do not add a dependency without
asking. If the result looks good, assume it is leaking and check before telling me
it worked.
```
