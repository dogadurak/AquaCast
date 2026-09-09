# AquaCast — Basin-Scale Drought Forecasting with Honest Skill Reporting

**Pilot region:** Konya Closed Basin, Türkiye (~50,000 km², endorheic, Central Anatolia)
**Status:** specification v1.0 — supersedes the earlier draft spec
**One-line pitch:** An open, reproducible drought early-warning system that fuses dynamical seasonal forecasts with satellite land-surface state, and reports its own predictive skill honestly at every lead time and every grid cell.

---

## 0. Why this spec exists

An earlier AI-generated spec proposed predicting SPI-3 at +1, +3 and +6 months from lagged local variables (precipitation, temperature, soil moisture, NDVI) using XGBoost. That framing is attractive but contains four failure modes that would invalidate the results. This document keeps what was sound and fixes what was not.

### 0.1 The four problems being corrected

**Problem 1 — Overlapping accumulation windows create fake skill.**
SPI-*k* at month *t* is computed from precipitation accumulated over months *t-k+1 … t*. Forecasting SPI-6 at lead +3 therefore means predicting a quantity of which **three of six months are already observed** at forecast time. A model reproduces this trivially and reports R² ≈ 0.6–0.8, none of which is forecast skill. The same trap applies to SPI-3 at lead +1 (two of three months known) and SPI-12 at every lead below 12.

*Fix:* every forecast target is evaluated against a **known-accumulation baseline** — a model given only the already-observed portion of the accumulation window plus climatology for the unknown portion. The reported headline metric is the *skill score relative to that baseline*, not raw R². A model that cannot beat it has no skill, whatever its R² says. Additionally, report the strictly non-overlapping case (SPI-3 at lead ≥ 3) separately as the honest seasonal test.

**Problem 2 — Mid-latitude precipitation is not predictable from local lagged variables at 3–6 months.**
Land-surface memory (soil moisture, vegetation) carries real information for roughly 1–2 months. Beyond that, drought evolution is dominated by atmospheric circulation, which local history does not encode. A purely lag-based model at +3/+6 will converge to climatology plus SPI autocorrelation — and the autocorrelation contribution is exactly the artifact described in Problem 1.

*Fix:* the seasonal tier ingests **C3S multi-system seasonal forecast ensembles** (up to 6 months lead, hindcasts from 1993) as predictors. The ML layer does what ML is genuinely good at here: bias correction, spatial downscaling, and translating ensemble spread into calibrated probabilities. This mirrors how operational systems (JRC GDO, national services) actually work, and it is the difference between a toy and a defensible system.

**Problem 3 — Spatial autocorrelation inflates every metric.**
Pooling ~2,000 grid cells × ~300 months gives ~600,000 rows, but neighbouring cells during the same month are nearly identical. Effective sample size is closer to the number of months than the number of rows. Random or purely temporal splits therefore report metrics that will not reproduce operationally.

*Fix:* evaluation is **blocked in time and reported per time step**. Metrics are aggregated across forecast dates, not across rows. A spatially blocked cross-validation variant is run as a robustness check.

**Problem 4 — Two datasets in the original spec cannot support the training record.**
SMAP soil moisture begins April 2015 (~11 years of monthly data) and Sentinel-2 begins 2015–2017. Neither can anchor a 20+ year training record.

*Fix:* ERA5-Land volumetric soil water (1950–present) is the soil-moisture training source; MODIS MOD13 (2000–present) is the NDVI training source. SMAP and Sentinel-2 are retained for validation and high-resolution visualisation only.

### 0.2 What this buys the project

The verification layer is not overhead — it is the contribution. "We built a drought forecast" is a crowded claim. "We built a drought forecast and published exactly where, when, and by how much it beats climatology, including where it does not" is a rarer and more credible one, and it is the kind of thing that survives scrutiny from a thesis committee, a graduate admissions reviewer, or an engineer at a GIS company.

---

## 1. Problem statement

The Konya Closed Basin is Türkiye's largest endorheic basin and one of its most water-stressed. Irrigated agriculture dominates water demand, groundwater abstraction has driven long-term storage decline, and precipitation is highly variable between years. Existing public drought information for the basin is either coarse (continental products at 0.25–1°) or retrospective (maps of what already happened).

The operational question this project answers is narrow and deliberately so:

> For each ~1 km agricultural grid cell in the Konya Closed Basin, what is the probability that drought conditions will be moderate or worse in the coming 1 and 3 months — and how much should that probability be trusted, given the model's measured skill at that location and lead time?

Non-goals: this project does not attempt to outperform ECMWF's dynamical seasonal forecasts, does not model groundwater physically, and does not produce irrigation prescriptions.

---

## 2. System design

### 2.1 Two forecast tiers, presented differently

The system splits into two tiers because their skill characteristics are fundamentally different, and blurring them is the most common way drought-forecast projects mislead their users.

**Tier 1 — Nowcast and +1 month (deterministic, high confidence).**
Driven by observed land-surface state: ERA5-Land soil moisture, MODIS NDVI anomaly, MODIS LST, ET/PET ratio, and precipitation deficit to date. This tier answers "where is agricultural drought developing right now, and where will it still be next month." Land-surface memory makes this genuinely predictable. This tier should reach meaningful skill and is the product's reliable core.

**Tier 2 — Seasonal +3 months (probabilistic, skill-conditioned).**
Driven by C3S seasonal ensemble precipitation and temperature, post-processed with ML and combined with initial land-surface state. Output is a **probability** of SPI-3 falling below a drought threshold, never a point estimate. Every probability is displayed alongside the cell's measured Brier Skill Score against climatology. Where BSS ≤ 0, the interface says so explicitly rather than showing a colour.

A +6 month tier is explicitly **out of scope for v1**. It can be added only if Tier 2 demonstrates positive skill first.

### 2.2 Architecture

The single most important architectural decision: **all raster reduction happens in Google Earth Engine; nothing downstream ever touches a raster.** GEE exports a tidy monthly panel (grid cell × month × variable) as Parquet/CSV. That table is small — roughly 2,000 cells × 300 months × ~20 variables — so the entire ML and serving stack operates on a file that fits comfortably in memory. This removes the need for a raster store, a tiling server, and most of the data engineering the original spec implied.

```
Google Earth Engine  ──► monthly panel (Parquet, ~50 MB)
   CHIRPS v3, ERA5-Land, MOD13, MOD16, MOD11,          │
   ESA WorldCover, SRTM                                 │
                                                        ▼
Copernicus CDS  ─────► C3S seasonal ensemble ──► feature builder
   (ERA5-Land, SEAS multi-system)                       │
                                                        ▼
                                           SPI / SPEI / anomaly engine
                                                        │
                                                        ▼
                                    XGBoost  +  baselines  +  skill evaluation
                                                        │
                                                        ▼
                                    forecast GeoJSON + skill GeoJSON + metrics.json
                                                        │
                                                        ▼
                                    FastAPI (reads files, no DB in v1)
                                                        │
                                                        ▼
                                    MapLibre GL + Plotly dashboard
```

PostGIS is deferred to v2 and added only when there is a concrete need (multi-basin, user accounts, or history queries). In v1 it is complexity without benefit.

### 2.3 Grid definition

Analysis grid: 1 km, aligned to the MODIS sinusoidal grid to avoid resampling the highest-resolution input. All coarser inputs (CHIRPS ~5.5 km, ERA5-Land ~9 km, C3S ~1°) are bilinearly resampled onto it, with the resulting resolution mismatch documented — a 1 km map built from 9 km inputs must not be presented as 1 km information. Cells are masked to cropland and rangeland classes from ESA WorldCover; urban, water and bare rock are excluded.

Basin boundary: official Konya Closed Basin boundary from DSİ if obtainable; HydroBASINS level 5 as documented fallback.

---

## 3. Data

Every dataset below was checked for availability, licence and record length before this spec was written. `scripts/check_data_access.py` re-verifies all of it against your own credentials, and must pass before Phase 1 begins.

| Variable | Source | Access | Record | Role |
|---|---|---|---|---|
| Precipitation | CHIRPS v3 (0.05°) | GEE, free | 1981– | SPI input, validated for monthly use over Türkiye. **Exported from 1981**, not 2001: the extra years are the `baseline_precip_era5` reference period (§4.2) |
| Precipitation, temperature, soil moisture, PET | ERA5-Land (~9 km) | GEE (`ECMWF/ERA5_LAND/MONTHLY_AGGR`) for the panel; CDS API for variables GEE does not carry | 1950– | Core predictors; SPEI input. **Exported from 1981** to match the precipitation reference period |
| Seasonal forecast ensemble | C3S seasonal monthly statistics (multi-system, ≤6 months lead) | CDS API, free w/ token | hindcast 1993– | **Tier 2 predictors** |
| NDVI | MODIS MOD13A2 (1 km, 16-day) | GEE, free | 2000– | Vegetation stress |
| NDVI continuity | VIIRS VNP13A1 | GEE, free | 2012– | Successor after MODIS shutdown |
| Evapotranspiration | MODIS MOD16A2GF | GEE, free | 2001– | ET/PET stress ratio |
| Land surface temperature | MODIS MOD11A2 | GEE, free | 2000– | Thermal stress |
| Soil moisture (satellite) | SMAP L4 (9 km) | GEE, free | 2015– | **Validation only** — record too short to train on |
| Terrestrial water storage | GRACE/GRACE-FO, or GDO TWS anomaly via WCS | GEE / WCS, free | 2002– | Basin-scale covariate only (~300 km native resolution — never a 1 km map layer) |
| Benchmark drought indicators | Copernicus GDO/EDO (SPI, CDI) via WCS | open, no registration | varies | Independent comparison |
| Land cover | ESA WorldCover v200 (10 m) | GEE, free | 2020/2021 | Cropland masking |
| Terrain | SRTM 30 m | GEE, free | static | Elevation, slope, aspect |

### 3.1 Access requirements — resolve these on day one

1. **Google Earth Engine** — free for noncommercial use but requires registering a Google Cloud project and choosing a tier. Undergraduate students fall under the Community Tier (150 EECU-hours/month); graduate students may qualify for the Contributor Tier (1,000 EECU-hours/month). A basin-scale monthly export fits well inside the Community quota if exports are chunked by year rather than requested as one job.
2. **Copernicus CDS** — free account, then a personal access token in `~/.cdsapirc`, and `cdsapi>=0.7.7`. **Licences must be accepted in the web interface per dataset** before API requests succeed; this is the single most common first-day failure. Accept them for *ERA5-Land monthly averaged data* and *Seasonal forecast monthly statistics on single levels*.
3. **CDS queueing** — seasonal forecast requests can queue for hours. Download the hindcast archive once, early, in the background, chunked by initialisation month.

### 3.2 Known data risks, and the mitigations

**MODIS decommissioning.** NASA has stated that the Terra and Aqua platforms carrying MODIS begin shutting down in late 2026 / early 2027. The historical archive remains permanently available, so *training* is unaffected — but any pipeline that assumes a live MODIS feed will break. Mitigation: the ingestion layer defines an abstract `vegetation_index` source with MODIS and VIIRS implementations behind one interface, and the VIIRS path is implemented and cross-calibrated against MODIS during the overlap period in Phase 2, not retrofitted later. Treat this as a designed-for requirement, not a footnote.

**CHIRPS over Türkiye.** CHIRPS is designed for data-sparse tropical regions. Published validation over Türkiye finds high correlation at monthly and dekadal scales — the scales this project uses — with a positive bias, overestimation of low precipitation amounts, best performance in winter, and degraded performance over complex eastern terrain. Konya is a high plateau in Central Anatolia, so this is acceptable but not free: run CHIRPS against ERA5-Land and, where obtainable, MGM station records for the basin, and report the comparison. A short, honest precipitation-product comparison is a genuine contribution and costs about two days.

**GRACE resolution.** GRACE's native resolution (~300 km) covers the entire basin in roughly one to two effective pixels. It is a valid basin-aggregate covariate and an invalid map layer. Any pixel-level GRACE visualisation is a misrepresentation.

---

## 4. Method

### 4.1 Targets

| Target | Lead | Overlap with observed data | Tier |
|---|---|---|---|
| SPI-1 | +1 month | none | 1 |
| SPI-3 | +3 months | none | 2 |
| Soil moisture anomaly | +1 month | none | 1 |
| NDVI anomaly | +1 month | none | 1 |

Targets are chosen so that **no target overlaps its own predictor window**. This is the structural fix for Problem 1: rather than merely correcting for the overlap in evaluation, the primary targets avoid it entirely. SPI-6 and SPI-12 may be produced as *monitoring* layers (current conditions) but are not forecast targets in v1.

Classification framing is preferred for the seasonal tier: P(SPI-3 < −1) — moderate drought or worse — because a calibrated probability is more useful and more honestly evaluable than a point estimate.

### 4.2 Features

Per grid cell, per month *t*:
- Precipitation anomaly at lags 1–6; SPI-1, SPI-3, SPI-6, SPI-12 at *t*
- ERA5-Land soil moisture (4 layers) anomaly at lags 1–3
- NDVI anomaly at lags 1–3; ET/PET ratio at lags 1–3; LST anomaly at lags 1–2
- Static: elevation, slope, aspect, land cover class, long-term mean precipitation
- Seasonality: month-of-year encoded cyclically
- **Tier 2 only:** C3S ensemble mean and spread of forecast precipitation and temperature for the target window, plus terciles

Feature engineering rule: **anomalies, not raw values**, computed against a fixed climatological reference period calculated *only from data outside the held-out splits*, to avoid leaking validation- or test-period statistics into the normalisation.

**Reference periods (corrects the draft spec).** The draft named 1991–2020, the current WMO normal. That period cannot be used here: training ends in 2016, so 1991–2020 is not a subset of the training window, and it overlaps the validation years 2018–2020. Anomalies computed against it would carry held-out statistics into training — the exact failure §0.1 Problem 3 warns about, in a different guise. Two reference periods replace it, because MODIS does not reach as far back as the climate records:

| Reference period | Span | Applies to | Note |
|---|---|---|---|
| `baseline_precip_era5` | **1981–2016** (36 yr) | CHIRPS and ERA5-Land derived: precipitation, T2m, PET, soil water, SPI-1/3/6/12, SPEI-3/6, `sm_anom` | Above the WMO-recommended 30-year minimum for stable gamma fits. Start year is the CHIRPS record start; ERA5-Land reaches 1950 but is truncated to match so both precipitation products share one period. |
| `baseline_modis` | **2001–2016** (16 yr) | MOD13/MOD16/MOD11 derived: NDVI, ET, LST, `ndvi_anom`, `lst_anom` | Below the 30-year guidance — MODIS begins in 2000. Declared as a limitation in `docs/data_dictionary.md` and `reports/model_card.md`, not hidden. |

Neither period intersects validation (2018–2020) or test (2022–2025). The periods are defined once in `config/data.yaml` and enforced by `tests/test_leakage.py::test_baseline_periods_exclude_val_and_test`, so that this correction cannot silently regress.

Pulling precipitation back to 1981 means the CHIRPS and ERA5-Land exports cover 1981–2025 while the modelling panel still starts in 2001, where MODIS does. Only the index and anomaly fitting uses the extra years.

**Known side effect, to be stated wherever anomalies are reported.** A reference period beginning in 1981 includes pre-warming years, so recent anomalies read drier than they would against a later normal. This is not an error — the longer period is the statistically better choice — but the comparison is against a cooler baseline and must be said plainly rather than left for a reader to discover.

### 4.3 Models

Baselines first, and they are not a formality — they are the yardstick the entire project reports against:
1. **Climatology** — the long-term probability of drought for that cell and calendar month
2. **Persistence** — current SPI carried forward
3. **Known-accumulation baseline** — the observed portion of the accumulation window plus climatology for the remainder (the Problem 1 control)
4. **C3S raw ensemble** — the dynamical forecast used directly, without ML (Tier 2 only)

Then: XGBoost as primary. LightGBM as a cross-check. LSTM only if Phase 3 shows the gradient-boosted models are underfitting temporal structure — which is unlikely, and adding it before that is evidence is unjustified complexity.

### 4.4 Evaluation

Temporal split with a gap to prevent accumulation-window bleed:
```
train 2001–2016   |  gap 2017  |  validation 2018–2020  |  gap 2021  |  test 2022–2025
```
The gap years matter: with 12-month accumulation windows, adjacent train and test periods share data.

Metrics:
- Continuous targets: MAE, RMSE, R², plus **skill score vs each baseline**
- Probabilistic targets: Brier Skill Score, reliability diagram, ROC AUC
- Aggregated **per forecast date**, then summarised — never pooled across all rows
- Reported **per lead time and per land-cover class**, and mapped **per grid cell** so that spatial skill variation is visible

Robustness: spatially blocked CV as a secondary check; a permutation test on the target to confirm the pipeline reports near-zero skill on shuffled labels.

**Publication rule:** any headline claim of forecast skill must be accompanied by the baseline it beats and the margin. "R² = 0.72" alone is not a result.

---

## 5. Product

### 5.1 v1 scope (must ship)

1. **Monitoring map** — current SPI-1/3/6, soil moisture anomaly, NDVI anomaly, ET/PET, per 1 km cell
2. **Forecast map** — +1 month deterministic (Tier 1), +3 month probabilistic (Tier 2)
3. **Skill map** — per-cell BSS/skill score, with a hard visual distinction for cells with no skill
4. **Cell inspector** — click a cell: time series since 2001, current drivers via SHAP, forecast with confidence, and that cell's measured skill
5. **Model card** — a page stating training period, baselines, measured skill, known limitations, and data provenance

Item 5 is not documentation-as-afterthought; it is a deliverable and the thing that distinguishes this project.

### 5.2 v2 and beyond (only after v1 ships)

Alerts and subscriptions, a second basin, PostGIS migration, +6 month tier, irrigation-district aggregation, Sentinel-2 high-resolution field-level views.

### 5.3 Stack

Python 3.11, `earthengine-api`, `pandas`, `xarray`, `scipy` (gamma fitting for SPI), `scikit-learn`, `xgboost`, `shap`, `geopandas`. FastAPI serving precomputed GeoJSON. Frontend: MapLibre GL JS + Plotly, vanilla or a minimal React setup — **not** a full Next.js application in v1. Deployment: static frontend plus a small API container.

The frontend rule: the map must render precomputed GeoJSON/PMTiles. No on-the-fly raster rendering, no tile server in v1.

---

## 6. Phases and gates

Each phase has a gate. Do not begin the next phase until the gate passes. The gates exist to catch the failure mode where a project accumulates infrastructure without ever establishing whether the core idea works.

**Phase 0 — Feasibility spike (3–5 days).**
Run `check_data_access.py`. Pull one variable set for the basin. Compute SPI-3. Train XGBoost for Tier 1 (+1 month) and Tier 2 (+3 months) with all four baselines. Produce a skill table.
**Gate:** a skill table exists comparing model vs all baselines, and the leakage audit passes. If Tier 2 shows no skill over climatology, the product narrows to Tier 1 plus monitoring plus an honest statement about seasonal limits — the project continues, reframed, rather than quietly reporting inflated numbers.

**Phase 1 — Data pipeline (1 week).** Reproducible GEE exports chunked by year, CDS ingestion, the monthly panel with a documented schema, a data dictionary, and integrity tests.
**Gate:** `make data` reproduces the panel from scratch; every column documented; missing-data audit complete.

**Phase 2 — Feature and index engine (1 week).** SPI/SPEI implementation validated against a reference implementation (`climate_indices` or GDO values), anomaly computation, VIIRS/MODIS cross-calibration.
**Gate:** SPI values match the reference within tolerance on a test basin; baseline-period leakage test passes.

**Phase 3 — Modelling and evaluation (1.5 weeks).** Full training, all baselines, blocked evaluation, SHAP, per-cell skill maps.
**Gate:** the skeptic agent's audit passes with no unresolved findings; metrics reproduce from a clean run.

**Phase 4 — API and precomputation (0.5 week).** FastAPI serving GeoJSON, forecast artefacts generated by a single command.
**Gate:** API returns valid GeoJSON for every layer; response times acceptable.

**Phase 5 — Frontend (1.5 weeks).** Map, inspector, skill visualisation, model card.
**Gate:** every v1 item present; no-skill cells visually unmistakable.

**Phase 6 — Documentation and release (0.5 week).** README with real numbers, model card, reproducibility instructions, screenshots.
**Gate:** a stranger can clone the repository and reproduce the metrics.

Realistic total: **6–7 weeks of focused part-time work.** Phases 0–3 are the project; 4–6 are presentation. If time runs short, ship Phases 0–3 with a static notebook report rather than an unfinished dashboard — a rigorous result with a modest interface is worth considerably more than a polished interface over unvalidated numbers.

---

## 7. Failure conditions

The project is in trouble, and must be re-scoped rather than pushed forward, if any of these hold:

- Tier 2 cannot beat climatology after C3S predictors are added *(response: narrow to Tier 1, report the negative result — a well-documented negative result is publishable and honest)*
- Reported skill collapses when the known-accumulation baseline is introduced *(response: the earlier numbers were the artifact; report corrected figures)*
- CDS seasonal data cannot be obtained within the schedule *(response: Tier 1 only for v1)*
- The frontend begins before Phase 3's gate passes *(response: stop and finish the gate)*

---

## 8. Naming

"AquaCast" is serviceable but the name is in use by other water-sector products; check before committing to it publicly. Alternatives that describe the actual differentiator — skill-aware forecasting — include **SkillCast**, **DroughtLedger**, **AridSight**, and **Konya Drought Observatory** (accurate, unglamorous, and credible for an academic audience).
