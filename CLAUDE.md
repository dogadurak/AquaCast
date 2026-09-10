# CLAUDE.md — AquaCast

Read `PROJECT_SPEC.md` before writing any code. This file contains the rules that override default behaviour.

## What this project is

A drought forecasting system for the Konya Closed Basin whose distinguishing feature is **honest skill measurement**. Producing a forecast is easy; proving it beats climatology is the actual work. Optimise every decision for defensible results, not for impressive-looking metrics.

## Non-negotiable rules

1. **Never report a metric without its baseline.** Any R², MAE or AUC printed, logged, or written to a report must appear next to the corresponding climatology, persistence, and known-accumulation baseline values, plus the skill score against each. A bare metric is a bug.

2. **Never let a forecast target overlap its predictor window.** SPI-*k* accumulates *k* months. Forecasting SPI-6 at lead +3 means three of six months are already observed and the result is meaningless. Approved target/lead pairs are in `PROJECT_SPEC.md` §4.1. Adding a new pair requires explicitly demonstrating no overlap.

3. **Never compute climatology or normalisation statistics using held-out data.** The reference periods live in `config/data.yaml` under `climatology`, and there are two because MODIS does not reach as far back as CHIRPS/ERA5-Land: `baseline_precip_era5` (1981–2016) and `baseline_modis` (2001–2016). Both end where training ends. The 1991–2020 WMO normal named in the draft spec is **not** usable here — it is not a subset of the training window and it overlaps validation (2018–2020). Anomalies, gamma-fit parameters for SPI, and scalers are fitted on the reference period and applied unchanged to validation and test. Enforced by `tests/test_leakage.py::test_baseline_periods_exclude_val_and_test`.

4. **Never pool metrics across all rows.** Compute per forecast date, then aggregate. ~600,000 rows represent roughly 300 effective time steps; pooling inflates confidence by more than an order of magnitude.

5. **Never present a layer at a resolution finer than its source.** Forecast at the resolution the physics supports; observe at the resolution the sensor provides. The modelling grid is the CHIRPS 0.05° lattice itself — every forecast, every baseline and every skill metric lives there, Tier 1 and Tier 2 alike. Precipitation is never resampled. ERA5-Land arrives bilinearly and carries 9 km information whatever the cell size says. MODIS NDVI/LST stay at native 1 km as monitoring layers only, and are aggregated to the analysis grid as **mean and standard deviation** before entering the model, so within-cell heterogeneity survives. GRACE is basin-aggregate only — its ~300 km native resolution covers the basin in one or two effective pixels, so any pixel-level GRACE map is a misrepresentation. Every layer states its true resolution in the UI and the model card. See `PROJECT_SPEC.md` §2.3 and the `grid` block in `config/data.yaml`.

6. **Never assume a live MODIS feed.** MODIS ends in late 2026 / early 2027. All vegetation and ET access goes through the source abstraction in `src/data/vegetation.py` with MODIS and VIIRS implementations.

7. **No new infrastructure without a stated need.** No PostGIS, no Docker Compose stack, no Next.js, no message queue, no tile server in v1. The panel is a Parquet file that fits in memory. If you believe a component is needed, say why in the PR description and wait for approval.

8. **Phase gates are hard stops.** Do not begin the next phase until the current gate passes. Frontend work before Phase 3's gate is out of order.

## Karar protokolü

Before asking me a question or choosing an approach, write this out for each option — short, two or three bullets:

1. **PRE-MORTEM:** "It is six months from now and this decision turned out wrong. Why?"
2. Which errors under this option are **silent** — producing a wrong result with no error message? If there are none, say that explicitly too.
3. What does reversing this decision cost? Cheap, choose fast. Expensive, stop.

Every step that produces data must assert at least one invariant claiming its output is correct. **"It ran and did not error" is not verification.** Expected row count, expected date range, expected null fraction — whichever fits.

Keep assumptions visible: list everything you could not verify as an **open assumption**, and check it the moment it becomes verifiable.

Not all misses are equal, and the difference decides how much to worry:

- **Silent-corruption class** — truncated data, leakage, a wrong baseline period. No error, tests pass, the result is wrong. This is the only dangerous class, and the most expensive one for a portfolio project: if a reviewer finds one, confidence in the whole project goes.
- **Rework class** — wrong grid, wrong export route. Annoying, costs a day, but *visible*. You notice and you fix it.

The goal is not "miss nothing". The goal is: make the silent-corruption class impossible, and accept the rework risk.

Read `.claude/skills/failure-modes/SKILL.md` before any design decision, data step, or evaluation code. When I point out something you missed, do not just fix it — **add it to that skill**, so I never have to say the same thing twice.

## Data contract

The canonical dataset is a single monthly panel. Every module reads and writes this schema; do not invent column names.

**The contract is versioned by phase.** A column that is not in the current phase's
list is not in the panel — the panel and this contract must never disagree, because a
contract silently departed from stops being a contract. Moving a column between
sections is a deliberate edit, made when the column actually lands.

**Phase 0 — in `panel_monthly.parquet` now**

```
data/processed/panel_monthly.parquet

cell_id            int64      stable ID from the CHIRPS 0.05° analysis grid,
                              derived from lon/lat indices so it is reproducible
date               datetime   month start, UTC
lon, lat           float64    cell centroid, EPSG:4326
i, j               int64      CHIRPS lattice indices
in_hydrobasins     bool       cell centre inside the HydroBASINS L5 polygon
in_akarcay_lobe    bool       cell centre inside the Akarçay sub-basin
crop_frac_2021     float64    cropland/rangeland fraction, 2021 WorldCover epoch
precip_chirps_mm   float64    CHIRPS v3 monthly total
n_pentads, n_obs   int64      pentads in the collection / contributing at this pixel
precip_zero_isolated  bool    DERIVED at panel stage - artefact-like zero cluster
t2m_c              float64    ERA5-Land monthly mean temperature (DAILY_AGGR)
t2m_min_c, t2m_max_c  float64 mean of daily extremes (DAILY_AGGR, not MONTHLY_AGGR)
dewpoint_c         float64    ERA5-Land mean daily dewpoint
precip_era5_mm     float64    ERA5-Land monthly total
pet_era5_mm        float64    ERA5-Land potential evaporation — PAN evaporation,
                              a comparison column only, NOT the project's PET
pet_era5_raw_mm    float64    unflipped value, so the sign convention stays auditable
swvl1..swvl4       float64    ERA5-Land volumetric soil water, 4 layers
wind10m_ms, wind2m_ms  float64  mean of daily speeds; 2 m via the FAO-56 conversion
srad_down_mj_m2_day, net_solar_mj_m2_day, net_thermal_mj_m2_day  float64
surface_pressure_kpa  float64
era5_native_cell_id  int64    which ERA5 0.1° pixel this cell draws from
```

**Phase 1 — not in the panel yet; do not emit these as empty columns**

```
ndvi, ndvi_sd      float64    MOD13A2 monthly composite, cell mean and within-cell sd
ndvi_source        category   "MODIS" | "VIIRS"
ndvi_available     bool       false before 2001 — MODIS record does not reach back
et_mm, et_mm_sd, pet_modis_mm  float64   MOD16A2GF, cell mean and sd
et_available       bool
lst_day_c, lst_day_c_sd  float64   MOD11A2 daytime LST, cell mean and sd
lst_available      bool
elevation_m, slope_deg, aspect_deg  float64   static
landcover          category   ESA WorldCover class
```

**Phase 2 — computed from the panel, not exported into it by T4**

```
spi_1, spi_3, spi_6, spi_12   float64   train-period gamma fit
spei_3, spei_6     float64    FAO-56 Penman-Monteith ET₀, not ERA5 pev
pet_fao56_mm       float64    clamped at zero, with pet_fao56_clamped flag
sm_anom            float64    vs baseline_precip_era5 (1981–2016), depth-weighted
                              0.07·swvl1 + 0.21·swvl2 + 0.72·swvl3 — plain mean forbidden
ndvi_anom, lst_anom  float64  vs baseline_modis (2001–2016)
```

Rules: one row per (`cell_id`, `date`); no forward-filling across more than one month without an explicit `*_filled` flag column; all units in column names; no silent unit conversion.

**The panel spans 1981–2025; MODIS columns start in 2001.** Rows for 1981–2000 are kept with the MODIS columns null and their `*_available` flags false. Never drop those rows — they are the point. They enable the Phase 3 ablation that this project owes an answer to: **a precipitation-only model trained on 1981–2016 (36 years) against a full-feature model trained on 2001–2016 (16 years).** More data or more features — which wins is a reportable result in its own right, and it is not knowable in advance.

## Code conventions

- Python 3.11, type hints on every public function
- `src/` layout: `data/`, `features/`, `models/`, `eval/`, `api/`
- Configuration in `config/*.yaml` — no magic numbers in code, especially not thresholds, date ranges, or file paths
- Every stage writes an artefact to `data/` and is re-runnable independently
- `make data`, `make features`, `make train`, `make eval` — each idempotent
- Seeds fixed and logged; every metrics run writes `reports/metrics_<timestamp>.json` including the git SHA
- Tests: `pytest`. Leakage tests are not optional and live in `tests/test_leakage.py`

## Working style

- Ask before adding a dependency
- Prefer a working, boring implementation over a clever one
- When a result looks surprisingly good, treat it as a suspected leak and investigate before celebrating — this project's most likely failure is a bug that looks like success
- When you find a problem with the spec itself, say so rather than implementing around it
- Report negative results plainly; a documented "no skill at +3 months" is a legitimate and valuable outcome

## Definition of done for a modelling change

1. Metrics regenerated with all four baselines
2. `pytest tests/test_leakage.py` passes
3. `reports/metrics_<timestamp>.json` written and committed
4. The skeptic agent has reviewed the diff and its findings are resolved
