# HANDOFF — read this first, before anything else

For a new agent session (or Doğa, picking this back up later) with no memory of
how the project got here. Read this, then `CLAUDE.md` (the rules), then
`PROJECT_SPEC.md` (the design) — in that order. Do not start writing code before
reading `CLAUDE.md`'s "Karar protokolü" section.

**Update this file whenever you finish a phase, close a gate, or leave an open
decision for Doğa.** It goes stale the moment it stops being read before work
starts.

---

## What AquaCast is, in one paragraph

A drought forecasting system for the Konya Closed Basin (Türkiye), built as a
portfolio piece for GIS employers (Esri/Başarsoft-tier) and MSc admissions
(İTÜ/Germany). Its entire differentiator is **honest skill measurement** — the
project's standard is "survives inspection," not "looks like it works." If a
result looks better than expected, the default hypothesis is a leak, checked
before it is reported as success.

## Where the project is right now

**Phase 0 gate: PASSED** (see `PROJECT_SPEC.md` §6 for the criteria, and the
gate report near the end of `reports/phase0_log.md` for the evidence).
**Phase 1 is in progress**, CDS-independent parts only — see "What's next" below.

## The headline result — say this plainly, do not soften it

A skill table exists (`reports/skill_table.md`) comparing an XGBoost model
against four baselines (climatology, persistence, known-accumulation, C3S — the
last one null, CDS access pending) for two targets: SPI-3 at +3 months (primary,
classification) and SPI-1 at +1 month (secondary, regression).

**The model does not clearly beat climatology at either target**, and does not
clearly beat a properly calibrated persistence baseline either. None of the
score gaps in the table are statistically distinguishable from noise at this
sample size (~35-47 test months) — the table reports three significance tests
(t-test, Wilcoxon, sign test) side by side, none nominated as primary, plus the
measured autocorrelation of each comparison, precisely because an earlier
attempt to pick "the more trustworthy" one turned out to be indefensible (see
"Things a future agent should not redo" below).

This is Phase 0's own pre-registered expected outcome for SPI-3 (`PROJECT_SPEC.md`
§0.1 Problem 2: lag-only local variables cannot forecast 3 months out — that is
what Phase 1/2's C3S ensemble ingestion and the fuller feature set are for). It
was **not** pre-registered for SPI-1 — `PROJECT_SPEC.md` §2.1 says Tier 1 "should
reach meaningful skill," and that assumption is now open, not confirmed. This is
flagged as an open decision below, not smoothed over.

## What's been built (Phase 0, tasks T0-T8)

| Task | What | Key artefact |
|---|---|---|
| T0 | Data access check | `reports/data_access.json` |
| T1 | Analysis grid (2,820 cells, CHIRPS 0.05° lattice) | `data/interim/grid_cells.csv` |
| T2 | CHIRPS precipitation export | feeds `panel_monthly.parquet` |
| T3 | ERA5-Land climate export | feeds `panel_monthly.parquet` |
| T4 | Panel assembly | `data/processed/panel_monthly.parquet` |
| T5 | SPI-1/SPI-3 computation | same panel, + `spi1_mm_per_unit`/`spi3_mm_per_unit` |
| T6 | Four baselines | `data/processed/baselines_monthly.parquet` |
| T7 | XGBoost training | `data/processed/predictions.parquet` |
| T8 | Skill table | `reports/skill_table.md`, `reports/metrics_*.json` |

Full column-level documentation: `docs/data_dictionary.md`. Full chronological
log of every task, every bug found, every fix, in the task-log format PLAN →
PRE-MORTEM → IMPLEMENT → ASSERT → LOG: `reports/phase0_log.md` (long; read the
last ~500 lines for the T8 audit rounds, not the whole thing, unless you need
the T1-T4 data provenance history).

Run anything with `python -m src.<module>` — see the `Makefile` (just fixed,
see below) for the exact chain. **`make` itself is not installed on this dev
machine** — commands must be run directly (`python -m src.data.build_panel`
etc.) until Doğa installs it or confirms that's not needed.

## Things a future agent should not redo

- **Do not re-run a full-pipeline skeptic audit from scratch.** Two rounds
  already happened (full-scope, then a diff-scoped follow-up) and both are
  resolved. If you change `src/models/baselines.py`, `src/features/build.py`,
  `src/models/train.py`, or `src/eval/skill.py` again, scope a new skeptic
  audit to **the diff since the last one**, not the whole pipeline — a
  full-scope run costs ~115K tokens; a diff-scoped one is a fraction of that.
- **Do not re-derive "which baseline shape is right" for persistence.** It's
  settled: a hard 0/1 forecast is wrong (Brier worst-case by construction);
  the calibrated version lives in `persistence_probability_forecast()` and is
  documented with its own history of two real bugs found and fixed (an
  AUC=1.0 leak, then a fit-boundary overrun) in `docs/data_dictionary.md` §4.
- **Do not re-add a "which significance test is more trustworthy" rule.** One
  was added (told to trust Wilcoxon over the t-test under positive
  autocorrelation) and then withdrawn after a second audit found it
  statistically indefensible **and** the only thing propping up the project's
  one positive claim. All three tests (t-test, Wilcoxon, sign) are now
  reported with no primary — keep it that way unless a real, checked-per-row
  justification exists, not an assumed one.
- **Do not trust "it ran without an error" as verification for anything new.**
  Every step in this project asserts an invariant about its own output. Follow
  that pattern; `docs/working_protocol.md` has the full PLAN → PRE-MORTEM →
  STOP → IMPLEMENT → ASSERT → LOG → COMMIT → REPORT sequence.

## Open decisions waiting on Doğa (not on an agent)

1. **Tier 1's success criterion.** SPI-1 @ +1 month doesn't clearly beat
   climatology, but isn't clearly beaten either — it's statistically
   indistinguishable at n≈47. Before Phase 1's richer feature set
   (MODIS NDVI, SPEI, depth-weighted soil moisture) gets re-evaluated, decide:
   which test (t-test / Wilcoxon / sign) and what p-threshold counts as "Tier 1
   has skill" going forward? This is a definitional call, not a coding task.
   See `reports/phase0_log.md`'s last "§7 boşluğu" entries for the full
   argument.
2. **`make` is not installed on this machine.** Install it (choco/scoop/WSL),
   or confirm direct `python -m ...` invocation is fine going forward.
3. **CDS API token.** Needed for C3S seasonal ensemble ingestion (Tier 2's
   actual predictor, per `PROJECT_SPEC.md` §0.1 Problem 2's fix). Blocks the
   C3S-dependent part of Phase 1 and all of Tier 2's real evaluation.
4. **MGM station comparison** (precip + temperature validation) and the
   **official DSİ basin boundary** — both logged as Phase 0 "list B" items in
   `reports/phase0_log.md`, don't block Phase 0/1 but should happen before the
   model card is finalised (Phase 3).

## What's next (in order)

1. Doğa resolves the `make` question and, when ready, gets a CDS token.
2. Finish Phase 1's CDS-independent remainder per `PROJECT_SPEC.md` §6: the
   missing-data audit (`reports/panel_integrity.json` exists from T4 — check
   whether it satisfies "missing-data audit complete" as a Phase 1 deliverable
   or needs extending).
3. CDS ingestion once the token exists, then the rest of Phase 1's gate:
   `make data` reproduces the panel from scratch (already proven true for the
   local/non-CDS steps — see the `1f151b2` commit message), every column
   documented (mostly done, extend for any new CDS columns).
4. Phase 2 (feature/index engine — SPEI, MODIS, anomalies) per `PROJECT_SPEC.md`
   §6, then Phase 3 (full modelling + evaluation, the phase whose gate is the
   project's real scientific verdict).

## Where to find things

- `CLAUDE.md` — the rules that override default behaviour, read first
- `PROJECT_SPEC.md` — the design, the four corrected problems, the phase gates
- `docs/data_dictionary.md` — every column, every artefact file, with biases
- `docs/working_protocol.md` — the step sequence for any new piece of work
- `.claude/skills/failure-modes/SKILL.md` — every mistake made and generalised,
  read before any new data step or evaluation code
- `reports/phase0_log.md` — the full append-only history, in order
- `reports/skill_table.md` — the current headline result
- `AGENT_WORKFLOW.md` — which subagent for which phase, and why only one at a time
