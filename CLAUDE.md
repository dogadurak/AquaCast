# CLAUDE.md — AquaCast

Read `PROJECT_SPEC.md` before writing any code. This file contains the rules that override default behaviour.

## What this project is

A drought forecasting system for the Konya Closed Basin whose distinguishing feature is **honest skill measurement**. Producing a forecast is easy; proving it beats climatology is the actual work. Optimise every decision for defensible results, not for impressive-looking metrics.

## Non-negotiable rules

1. **Never report a metric without its baseline.** Any R², MAE or AUC printed, logged, or written to a report must appear next to the corresponding climatology, persistence, and known-accumulation baseline values, plus the skill score against each. A bare metric is a bug.

2. **Never let a forecast target overlap its predictor window.** SPI-*k* accumulates *k* months. Forecasting SPI-6 at lead +3 means three of six months are already observed and the result is meaningless. Approved target/lead pairs are in `PROJECT_SPEC.md` §4.1. Adding a new pair requires explicitly demonstrating no overlap.

3. **Never compute climatology or normalisation statistics using test-period data.** The 1991–2020 baseline must be derived from the training period only. Anomalies, gamma-fit parameters for SPI, and scalers are all fitted on train and applied to validation and test.

4. **Never pool metrics across all rows.** Compute per forecast date, then aggregate. ~600,000 rows represent roughly 300 effective time steps; pooling inflates confidence by more than an order of magnitude.

5. **Never present GRACE at grid resolution.** Its native resolution is ~300 km. Basin aggregate only.

6. **Never assume a live MODIS feed.** MODIS ends in late 2026 / early 2027. All vegetation and ET access goes through the source abstraction in `src/data/vegetation.py` with MODIS and VIIRS implementations.

7. **No new infrastructure without a stated need.** No PostGIS, no Docker Compose stack, no Next.js, no message queue, no tile server in v1. The panel is a Parquet file that fits in memory. If you believe a component is needed, say why in the PR description and wait for approval.

8. **Phase gates are hard stops.** Do not begin the next phase until the current gate passes. Frontend work before Phase 3's gate is out of order.

## Data contract

The canonical dataset is a single monthly panel. Every module reads and writes this schema; do not invent column names.

```
data/processed/panel_monthly.parquet

cell_id            int64      stable ID from the 1 km analysis grid
date               datetime   month start, UTC
lon, lat           float64    cell centroid, EPSG:4326
precip_chirps_mm   float64    CHIRPS v3 monthly total
precip_era5_mm     float64    ERA5-Land monthly total
t2m_c              float64    ERA5-Land 2 m mean temperature
pet_mm             float64    ERA5-Land potential evapotranspiration
swvl1..swvl4       float64    ERA5-Land volumetric soil water, 4 layers
ndvi               float64    MOD13A2 monthly composite, VIIRS after transition
ndvi_source        category   "MODIS" | "VIIRS"
et_mm, pet_modis_mm float64   MOD16A2GF
lst_day_c          float64    MOD11A2 daytime LST
spi_1, spi_3, spi_6, spi_12   float64   computed, train-period gamma fit
spei_3, spei_6     float64
sm_anom, ndvi_anom, lst_anom  float64   vs 1991–2020 train-period baseline
elevation_m, slope_deg, aspect_deg  float64   static
landcover          category   ESA WorldCover class
```

Rules: one row per (`cell_id`, `date`); no forward-filling across more than one month without an explicit `*_filled` flag column; all units in column names; no silent unit conversion.

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
