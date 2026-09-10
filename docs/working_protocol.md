# Working protocol

Read this at the start of every session, together with `CLAUDE.md`,
`PROJECT_SPEC.md` and `.claude/skills/failure-modes/SKILL.md`.

Phase 0 proceeds task by task. For each task, in order:

1. **PLAN** — what will be done, which files will be touched, what artefact comes
   out at the end. Three or four sentences. No code.
2. **PRE-MORTEM** — read `.claude/skills/failure-modes/SKILL.md`. Which errors in
   *this* task would be **silent**? Which invariant will be asserted so that such an
   error gives itself away? **Write the assertion down now**, before the work.
3. **STOP** — wait for approval. No code before an explicit "tamam".
4. **IMPLEMENT.**
5. **ASSERT** — print the expected and the actual value **side by side**. "The test
   passed" is not enough; the number has to be visible. On a mismatch: delete the
   produced file, mark the task as HATA, and come back to the user.
6. **LOG** — append to `reports/phase0_log.md` in the format below. Append, never
   overwrite.
7. **COMMIT** — one commit per task, with the task code in the message
   (e.g. `T3: ERA5-Land export`).
8. **REPORT** — at most five lines: artefact, assertion result, surprise, next.

## Why step 2 comes before step 4

Writing the assertion *after* the work lets it be shaped, unconsciously, to fit
whatever came out — bending the test to make it pass. Written first, that is not
possible.

## Log format

```
## T3 — ERA5-Land export
durum: OK | HATA | KISMİ
artefakt: data/raw/era5/*.csv (45 dosya, 31 MB)
assert: beklenen 1500 x 12 = 18000 satır/yıl → gerçek 18000 ✓
süre: 12 dk
sürpriz: 1987'de 3 ay kaynakta yok, *_available flag ile işaretlendi
sonraki: T4
```

If the output of a past task is changed later, add a `REVİZE:` line to that task's
log entry. Never correct it silently.

## Scope discipline

An interesting finding is not automatically a task. During Phase 0, anything that does
not change the skill table goes on the model-card list and the work continues. The
gate is one question - does the model beat climatology, persistence and the
known-accumulation baseline - and everything the answer does not depend on can wait
until after it exists.

This is not an argument against rigour; every diagnostic run so far found something
real. It is a guard against rigour turning into a way of deferring the result, which
is a failure mode this project is specifically prone to.

## Stop conditions — stop writing code and come back to the user

- An assertion failed.
- **The result came out better than expected.** In this project the most likely
  explanation for good news is a bug. Treat it as an alarm, not a celebration.
- A design decision is needed and the spec does not answer it.
- A contradiction was found in the spec.
- The same error resisted two attempts. Do not attempt a third — ask.

## Phase 0 task list

| Task | Work | Artefact |
|---|---|---|
| T1 | Basin boundary + analysis grid (CHIRPS 0.05° lattice, cropland mask) | `data/interim/grid.geojson` + cell count |
| T2 | CHIRPS export, 1981–2025, year by year to local CSV | `data/raw/chirps/*.csv` |
| T3 | ERA5-Land export (t2m, total precipitation, swvl1–4, PET), 1981–2025 | `data/raw/era5/*.csv` |
| T4 | Panel assembly | `data/processed/panel_monthly.parquet` — assert: schema matches CLAUDE.md exactly, (cell_id, date) unique, date range complete, null report |
| T5 | SPI-1 and SPI-3, validated against `climate_indices` | assert: agreement with the reference implementation within tolerance |
| T6 | Four baselines (climatology, persistence, known-accumulation; note the absence of C3S) | assert: the known-accumulation ≡ climatology tripwire fires |
| T7 | XGBoost: SPI-1 @ +1 month, SPI-3 @ +3 months | trained models |
| T8 | Skill table + `/leakage-audit` + `/phase-gate` | `reports/skill_table.md` |

## Tooling note

`TodoWrite` is not available in this environment, so the live terminal checklist is
not possible. `reports/phase0_log.md` plus one commit per task carries the same audit
trail: if a bug surfaces three tasks later, the log says what each assertion claimed
at the time, and the commits make each step separately revertible.
