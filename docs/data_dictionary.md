# Data dictionary

Every column the pipeline produces is documented here with units, source, native
resolution, and known biases. A column that is not documented here does not exist
as far as the rest of the pipeline is concerned.

Status: **Phase 0 (T0-T8) complete.** §1-2 (grid, CHIRPS, ERA5-Land, resolution)
written at T1-T3. §3 (panel) filled in at T4, extended at T5 (SPI). §4
(`baselines_monthly.parquet`) and §5 (`predictions.parquet`) added at T6-T8, when
those files started existing as pipeline outputs in their own right - per this
file's own rule above, a column not documented here does not exist, and neither
did these two files until now despite being read directly by anyone checking the
skill table's numbers.

---

## 1. Analysis grid — `data/interim/grid_cells.csv`, `data/interim/grid.geojson`

Produced by `python -m src.data.grid`. 2,820 cells.

| Column | Type | Units | Meaning |
|---|---|---|---|
| `cell_id` | int64 | — | Stable cell identifier, `i * 100000 + j`, where `i`, `j` are CHIRPS lattice indices. Derived from coordinates, never from row order, so it is identical on every run and safe to join on. |
| `lon`, `lat` | float64 | degrees, EPSG:4326 | Cell **centre**, not corner. |
| `i`, `j` | int64 | — | CHIRPS lattice indices, read from the collection's own `crs_transform` at runtime. |
| `crop_frac_2021` | float64 | fraction, 0–1 | Share of the cell that is cropland or rangeland **as of the 2021 WorldCover epoch**. See §1.2. |
| `in_hydrobasins` | bool | — | Cell centre falls inside the HydroBASINS L5 polygon. See §1.3. |
| `in_akarcay_lobe` | bool | — | Cell centre falls inside HydroSHEDS L6 sink `MAIN_BAS 2060086420`, the lobe that accounts for the excess area. See §1.3. |

`grid.geojson` carries the same fields with the cell's 0.05° square as geometry,
for mapping.

### 1.1 Why the grid is what it is

The analysis grid is the **CHIRPS 0.05° lattice itself** — not a metric 5 km grid.
Reprojecting onto a metric grid would resample precipitation, and SPI, the primary
forecast target, is computed from precipitation. See `PROJECT_SPEC.md` §2.3.

Lattice parameters are read from `crs_transform` at runtime rather than hardcoded:
`EPSG:4326`, origin `(-180, 60)`, step `0.05000000074505806`, nominal scale 5,566 m.
Hardcoding them would test the assumption against itself, and a wrong origin off by
a whole multiple of the step would pass silently.

### 1.2 `crop_frac_2021` — the epoch is in the name, deliberately

**Source:** ESA WorldCover v200, classes 30 (grassland) and 40 (cropland), 10 m.

**How it is computed:** the binary class mask is reprojected to a regular 100 m grid
and averaged onto the analysis grid — roughly 3,100 samples per cell, an unbiased
estimator of the fraction with a standard error under 1%. A full 10 m aggregation is
not possible: it needs ~308,000 input pixels per output pixel against
`reduceResolution`'s 65,536 ceiling. The estimator is stated here rather than
presented as a full aggregation.

**Limitation — a single epoch across a 45-year panel.** WorldCover v200 maps 2021
only, while the panel spans 1981–2025. Applying it throughout assumes land cover
held still for 45 years. In this basin that assumption is specifically wrong:
irrigated agriculture expanded substantially over exactly this period, and that
expansion is among the causes of the water stress being studied. A cell that was
rangeland in 1985 enters the analysis because it is cropland in 2021.

The mask is nonetheless kept static — a time-varying mask would make cells appear
and disappear and break panel consistency. The defence is naming: the column is
`crop_frac_2021`, never `crop_frac`, so it cannot be read as a timeless property.

**Threshold sensitivity.** Cell counts at 0.2 / 0.3 / 0.5 are 2,279 / 2,256 / 2,130.
The result is insensitive to the threshold because the basin is overwhelmingly
cropland and rangeland. 0.5 is used — "the majority of the cell" — as the statement
easiest to defend. The threshold is applied at analysis time, never at export time.

### 1.3 Basin boundary — a measured, unresolved discrepancy

**Source in use:** HydroBASINS v1 level 5, `HYBAS_ID 2050085960`, the only `ENDO=2`
(endorheic sink) polygon over the AOI. `PROJECT_SPEC.md` designates this a
*documented fallback* for the official DSİ boundary.

**Published areas, from an independent source:**

| Figure | Value | Source |
|---|---|---|
| Official, prose | 49,805.34 km² | [T.C. Tarım ve Orman Bakanlığı, Su Yönetimi Genel Müdürlüğü](https://www.tarimorman.gov.tr/SYGM/Sayfalar/Detay.aspx?SayfaId=135) |
| Official, table | 50,028 km² | same page |
| Literature | ~50,000 km², some ~53,000 | various |
| **HydroBASINS L5** | **58,373.7 km²** | attribute `SUB_AREA`; geodesic recomputation from the geometry gives 58,373.9 |

HydroBASINS is therefore **+17.2%** against the prose figure, **+16.7%** against the
table. Both official figures are recorded so the project cannot silently pick the
more convenient one.

**Where the difference is — measured, not assumed.** The L5 polygon is a merge of
**nine** distinct HydroSHEDS level-6 endorheic sinks. One of them, `MAIN_BAS
2060086420` (8,096 km², spanning 30.00–31.83°E / 38.06–39.13°N), accounts for
essentially the whole excess. Excluding it gives 50,278 km²: **+0.95%** against the
prose figure and **+0.50%** against the table. Every other single sub-basin is at
least 7.5% off, so this is not one match among many.

That lobe is the Akşehir–Eber lake system — the **Akarçay closed basin**, which the
ministry lists as a *neighbour* of Konya, not part of it (published Akarçay drainage
area ~7,400 km²). HydroSHEDS derives basins from flow directions, and endorheic
basins are where that derivation is weakest: with no outlet, the boundary depends on
sink-filling choices.

An independent cross-check supports the identification. The area ratio from the
vector polygons, (58,374 − 8,096)/58,374 = 0.8613, matches the cell-count ratio from
the raster lattice, (2,395 − 334)/2,395 = 0.8605, to 0.08%. These are computed by
entirely different means.

**Status: hypothesis, not verified geometry.** The official polygon is still not in
hand — only its published area. The difference figure
(`reports/figures/basin_boundary_uncertainty_*.png`) decomposes HydroBASINS rather
than differencing it against the official boundary, and is completed when that
geometry is obtained.

**Consequence for the project.** Skill scores are unaffected in kind: the model and
every baseline are compared on the same cells. Any **basin-total** figure — area,
water volume, agricultural statistics — inherits the discrepancy and must state it.

### 1.4 Membership is a column, never a row filter

No cell is dropped at export time. The grid covers the HydroBASINS polygon plus a
one-cell (5,566 m) ring, and which cells count is decided at analysis time by
`aoi.membership_column` in `config/data.yaml`:

| Selection | Cells | Purpose |
|---|---|---|
| `in_hydrobasins` | 2,395 | as delivered by HydroBASINS |
| `in_hydrobasins AND NOT in_akarcay_lobe` | 2,061 | provisional best approximation to the official basin |
| `in_official` | — | added when the DSİ/SYGM geometry arrives |
| ring only (`NOT in_hydrobasins`) | 425 | insurance in case the official boundary reaches outside HydroBASINS |

Because the official boundary is ~17% *smaller*, it almost certainly lies inside the
exported region — so revising the boundary is a filter change, not a re-download.
The ring covers the case where it does not.

---

## 1.5 CHIRPS v3 — product continuity, bias, and what a zero means

Checked **before** the export by `python -m scripts.check_chirps_continuity`;
numbers in `reports/chirps_continuity.json`, figure in
`reports/figures/chirps_continuity_*.png`.

**Is the series one product?** CHIRPS has an ERA5-based reanalysis line and an
IMERG-based near-real-time line, plus a final/preliminary distinction. If the line
changed between the reference period (1981–2016) and the test period (2022–2025),
anomalies would be measured with one product against a baseline fitted on another,
and that offset would look exactly like a climate signal.

- **Metadata cannot settle it.** `UCSB-CHC/CHIRPS/V3/PENTAD` carries only `year`,
  `month` and `pentad` per image — no source, version or preliminary flag. So no
  provenance column can be added to the panel, and the time series is the only
  available evidence. This is itself a limitation for the model card.
- **No level shift.** Basin-mean annual totals 1981–2025 show no discontinuity; the
  12-month rolling mean holds a stable level throughout. The 2022–2025 era mean is
  low (399 mm against 463 mm overall), but that is one exceptional year, not a step:
  **2023 sits at 467 mm, above the long-term mean**, and a production change would
  move every year after the transition. 2025 (287 mm) is the driest year in the
  45-year record; the eight driest years span four decades.
- **Preliminary data — unresolved.** With no flag, whether recent months are
  preliminary cannot be determined from GEE. Recent months therefore may be revised.
  Each year file carries a manifest with `fetched_utc` so a later divergence is
  attributable rather than mysterious.

**CHIRPS against the official figure — CONTEXT, not a bias measurement.**

| Quantity | Value |
|---|---|
| CHIRPS v3 basin-mean annual total, 1981–2025 (masked, Akarçay excluded) | 449.2 mm |
| …all `in_hydrobasins` cells | 463.2 mm |
| Published figure (SYGM, Konya Havzası Tanıtım) | 417 mm |
| Ratio | +7.7% to +11.1% depending on cell population |

**This is not CHIRPS's bias, and an earlier version of this section wrongly said it
was.** The claim that both figures describe one delineation is false. The report's own
sentence reads:

> "Toplam **yağış alanı 56.554 km²** olan Konya Kapalı Havzası'nın yıllık ortalama
> yağış yüksekliği **417 mm**…"

so the 417 mm is a mean over a **56,554 km² precipitation area**, while the surface
area in the same document is 49,805 km² — 13.6% apart, and 56,554 sits nearer
HydroBASINS' 58,374 than the 50,278 it was being compared against. The report states
**no reference period** at all: no year range, no "long-term average", no attribution
to DSİ or MGM.

Two of the three comparison axes therefore fail — population and scale — and the
anchor's own uncertainty is the same size as the difference being measured, with
unknown sign. The figure is retained because it tells a reader roughly where CHIRPS
sits, and because the 14 mm spread across populations shows how much the unresolved
boundary moves it. Nothing here may be reported as bias.

**The precipitation validation PROJECT_SPEC §3.2 asks for belongs on MGM station
records**, where all three axes can be controlled: same point (the station-to-cell
mapping in `reports/station_cells.json`), same period (restrict CHIRPS to the
station's normal period), same quantity. That is the same station set already needed
for the point-based ERA5 temperature check — one dataset, two validations.

**What an exact zero means.** CHIRPS overestimates low precipitation amounts, so the
climatological dry season rarely reaches exact zero: in July 1990 — the driest month
of a dry year — the basin **minimum** was 2.42 mm across all 2,820 cells, and not one
cell recorded zero. Exact zeros instead mark exceptional months in any season: March
1990 has 2,009 cells at zero with a basin mean of 2.27 mm.

Zeros are therefore validated by the **shape of the distribution**, not by season.
Masked pixels arriving as 0 would produce an isolated spike at exactly 0.0 with a gap
above it; a genuine dry month produces a continuous ramp. Every month containing
zeros must also contain values in (0, 1) mm. Separately, a per-pixel `n_obs` band
asserts that all six pentads contributed **at every cell** — a collection-level count
of six says nothing about a pixel masked in two of them, and `sum()` would silently
return a four-pentad total.

## 1.6 ERA5-Land — soil layers, resampling, and the native-pixel column

### Soil water layers are NOT of equal thickness — a plain mean is forbidden

ERA5-Land reports volumetric soil water in four layers with very different depths:

| Column | Depth | Thickness | Share of the 0–100 cm root zone |
|---|---|---|---|
| `swvl1` | 0–7 cm | 7 cm | **0.07** |
| `swvl2` | 7–28 cm | 21 cm | **0.21** |
| `swvl3` | 28–100 cm | 72 cm | **0.72** |
| `swvl4` | 100–289 cm | 189 cm | excluded — below the root zone |

T3 exports the four raw layers unchanged, which is correct: the panel stores what
the source provides. But **any root-zone quantity derived in T5 must be depth
weighted** — `0.07·swvl1 + 0.21·swvl2 + 0.72·swvl3` — and a plain arithmetic mean of
the four layers is **forbidden**.

An unweighted mean over-weights the 7 cm skin layer by a factor of ten. That layer
responds to individual rain events within days, while the 28–100 cm layer carries
the seasonal memory that makes soil moisture predictive at +1 month. A plain mean
would therefore substitute weather noise for exactly the signal this project depends
on — and it would produce no error, only a worse model that looks fine.

Written here before the derivation exists, so that the rule precedes the code.

### Resampling: bilinear, and it is verified rather than assumed

ERA5-Land is 0.1° (~9 km); the analysis grid is 0.05°. Earth Engine's implicit
reprojection is **nearest neighbour**, which would copy each native pixel into
roughly four analysis cells: the field would look smooth and plausible while
carrying no more information than 0.1°.

The export asserts a **distinct-value ratio** per month — distinct `t2m_c` values
divided by cell count. Nearest neighbour gives ≈ 0.25; bilinear gives ≈ 1.0.
Measured: **1.000**. The threshold is 0.90.

### `era5_native_cell_id` — for effective sample size, not for joining

**756** ERA5 native pixels cover the 2,820 analysis cells, about **3.7 cells per
native pixel**. Four neighbouring analysis cells drawing on one ERA5 pixel are not
four independent observations.

The column records which native pixel each cell draws from, so Phase 3 can compute
the effective sample size for ERA5-derived features rather than counting rows. This
is difficult to reconstruct after the fact, which is why it is exported now.

### Land–sea mask: no cells are lost

ERA5-Land is a land product, so cells over Tuz Gölü, Beyşehir and Akşehir could have
arrived as no-data. Measured: **zero** no-data cells across the 2,820 — at 0.1°,
ERA5-Land classifies those cells as land. Recorded because T4 would otherwise have
had to guess, and because a future ERA5 version could change it. Nothing is filled
and nothing is dropped.

### `pet_era5_mm` is NOT the project's PET — and it is not clamped

ERA5-Land's `potential_evaporation` is **not** a potential evapotranspiration in the
FAO-56 sense. ECMWF documents it as **open-water (pan) evaporation** applied to a
hypothetical surface, and notes that "the definitions of potential and reference
evapotranspiration may vary according to the scientific application". Measured here it
runs about 1,500–1,600 mm/yr, against a typical FAO-56 ET₀ of 1,100–1,300 mm/yr for
this basin.

So it is kept as a **comparison column only**. SPEI uses the FAO-56 Penman-Monteith
ET₀ computed from the DAILY_AGGR inputs.

**The gap between the two is not a bias, and must not be reported as one.** Open-water
evaporation exceeds reference-crop evapotranspiration *by definition* — different
surface, different roughness, no stomatal resistance. Measuring 1,500–1,600 mm/yr
against 1,100–1,300 and calling ERA5 "25% high" would be comparing two different
physical quantities and reading the definition as an error. See the comparison rule at
the head of `.claude/skills/failure-modes/SKILL.md`, axis (b).

The ratio is still worth recording, because it tells a reader how far apart the two
definitions land for this basin. It is reported as **the ratio of two PET definitions,
with both definitions named**, and it belongs in the model card as the **reason for a
data choice** — *ERA5 `pev` is pan evaporation, so it was not used for SPEI; FAO-56
ET₀ was computed instead* — not as a validation result.

This is unlike the CHIRPS figure, which **is** a bias: there, satellite precipitation
and gauge precipitation are the same physical quantity over the same basin, so their
difference is measurement error rather than definition.

Because it is not the primary quantity, **it is not clamped**: `pet_era5_mm` is the
raw ERA5 value with the sign flipped, and `pet_era5_raw_mm` carries the unflipped
value so the convention stays auditable in the data itself.

**It can be slightly negative, and that is correct.** Over frozen ground in midwinter
the computed flux reverses — deposition rather than evaporation. Measured for 1983:
22 rows of 33,840 (0.065%), all in January, at cells averaging 1,481 m and −6.3 °C,
ranging −0.53 to −0.0 mm/month. The export therefore tests the **sign convention by
proportion** — an inverted convention would flip essentially every row, not 0.065% —
rather than asserting positivity row by row.

**FAO-56 ET₀ will need the same decision.** Penman-Monteith can go slightly negative
when net radiation is negative and the vapour-pressure deficit is small — winter, snow,
high albedo. FAO-56 practice is to clamp ET₀ at zero. When that column is computed it
will be clamped, with a `*_clamped` flag, and the raw value retained.

### Units and sign conventions

| Column | Source band | Conversion |
|---|---|---|
| `t2m_c`, `t2m_min_c`, `t2m_max_c` | `temperature_2m[_min/_max]` | K − 273.15 |
| `precip_era5_mm` | `total_precipitation_sum` | m × 1000 |
| `pet_era5_mm` | `potential_evaporation_sum` | m × **−1000** |
| `swvl1..4` | `volumetric_soil_water_layer_1..4` | none, m³/m³ |

ERA5 fluxes are positive **downward**, so potential evaporation arrives negative and
the sign is flipped. The raw value is kept as `pet_era5_raw_m` and the export asserts
`pet_era5_mm > 0` on every row, so the convention is tested rather than assumed.

## 2. Resolution — what each column actually carries

A 0.05° cell fed by 9 km ERA5-Land carries 9 km information. Recorded per column in
`config/data.yaml` under `grid.resolution_mismatch`, and repeated in the model card.

| Source | Native | On the analysis grid | Information content |
|---|---|---|---|
| CHIRPS v3 | 0.05° | native, never resampled | 0.05° — genuine |
| ERA5-Land | ~9 km | bilinear | 9 km |
| C3S seasonal | ~1° | bilinear | ~100 km |
| MOD13A2 / MOD11A2 / MOD16A2GF | 1 km | mean + standard deviation per cell; also served ungridded at 1 km as observation layers | 1 km, preserved both ways |
| SMAP L4 | 9 km | validation only, not a panel column | 9 km |
| GRACE MASCON_CRI | ~300 km | basin aggregate only, never a cell column | one to two effective pixels over the basin |
| ESA WorldCover | 10 m | cropland fraction per cell, static 2021 epoch | mask only |
| SRTM | 30 m | mean elevation, slope, aspect per cell | 30 m aggregated |

---

## 3. Monthly panel — `data/processed/panel_monthly.parquet`

**Full column list and dtypes are the authoritative contract in `CLAUDE.md`**
("Data contract" section, versioned by phase) — not duplicated here, so the two
documents cannot silently drift apart. This section carries only what CLAUDE.md's
contract does not: derivation notes, biases, and what each column is not.

2,820 cells × 540 months = 1,522,800 rows, one row per (`cell_id`, `date`).

- The panel spans **1981–2025** while MODIS columns begin in **2001**. Rows for
  1981–2000 are kept with MODIS columns null and `ndvi_available`, `et_available`,
  `lst_available` false. They are not dropped: they enable the Phase 3 ablation of a
  precipitation-only model on 36 years against a full-feature model on 16.
- Reference periods for anomalies and SPI are `baseline_precip_era5` (1981–2016) and
  `baseline_modis` (2001–2016). The 1991–2020 WMO normal is **not** used — it
  overlaps validation. See `PROJECT_SPEC.md` §4.2.
- A 1981 reference start includes pre-warming years, so recent anomalies read drier
  than against a recent normal. Correct, but stated wherever anomalies appear.

### 3.1 `spi_1`, `spi_3` — added at T5, gamma-fit on the reference period

Computed by `src/features/spi.py`, delegating to `climate_indices.indices.spi()`
with `calibration_year_initial`/`calibration_year_final` set to
`baseline_precip_era5` (1981–2016) as SEPARATE arguments from `data_start_year` —
the fit period and the applied-to period are never the same argument, so mixing
them is a different call, not a silently wrong default. Applied to the full
1981–2025 series once fit.

### 3.2 `spi1_mm_per_unit`, `spi3_mm_per_unit` — a measurement, not a threshold

Per (cell, calendar month): millimetres of precipitation needed to move that
column's SPI by one unit, from the same reference-period gamma fit. Exists
because the standard Wu et al. (2007) zero-frequency reliability criterion
**inverts** on this basin (see `reports/spi_reliability_note.md`): CHIRPS's
known low-amount overestimation erases the zeros that criterion looks for, so it
clears the broken summer months and flags the reliable winter ones.

Per this project's repeated pattern (`in_hydrobasins`, `crop_frac_2021`): the
MEASUREMENT is a panel column, correct and unconditional; the DECISION (which
sensitivity counts as "unreliable") lives in `config/model.yaml`'s
`spi_reliability` block, not baked into the data. Skill is reported **binned** by
this column (`report_bins_mm`), never gated by a threshold frozen into the panel.

---

## 4. Baselines — `data/processed/baselines_monthly.parquet`

Produced by `python -m src.models.baselines` (T6). 3,045,600 rows = 1,522,800
panel rows × 2 approved targets (`spi_3`, `spi_1`) — **not** filtered to the
1,823-cell analysis population; that filter is applied at scoring time
(`src/eval/skill.py`), except for one internal fit (§4.3).

`date` here is the target's own **VERIFICATION date** — the month a row's
`actual` describes — not an issue date. See §5 for why this matters and how the
two files' date conventions were confirmed to disagree on purpose.

| Column | Type | Meaning |
|---|---|---|
| `cell_id`, `date` | int64, datetime | join keys |
| `target` | str | `"spi_3"` or `"spi_1"` |
| `lead_months` | int | 3 or 1 |
| `kind` | str | `"classification"` or `"regression"` |
| `actual` | float64 | `panel[target]` at this row's own date |
| `climatology` | float64 | reference-period (cell, calendar-month) mean of `target` |
| `persistence` | float64 | `target` observed `lead_months` earlier — the value actually known at issue time |
| `known_accumulation` | float64 | identical to `climatology` for every approved pair (zero accumulation overlap — see §4.1's note in `config/model.yaml`) |
| `c3s_raw` | float64 | always null — CDS access pending, see `config/model.yaml` `c3s_raw_status` |
| `actual_prob` | float64, `spi_3` only | `(target < threshold)`, the binary drought indicator this row's date resolves to |
| `climatology_prob` | float64, `spi_3` only | empirical P(target < threshold) per (cell, calendar month), reference period |
| `persistence_prob` | float64, `spi_3` only | CALIBRATED — see §4.3, not the hard 0/1 an earlier version used |
| `known_accumulation_prob` | float64, `spi_3` only | identical to `climatology_prob`, same zero-overlap reasoning |
| `c3s_raw_prob` | float64, `spi_3` only | always null |

### 4.1 Why `known_accumulation` always equals `climatology` here

Every approved (target, lead) pair has zero accumulation overlap (`k - lead = 0`:
spi_1@+1, spi_3@+3). With nothing observed to condition on, the known-accumulation
estimator reduces exactly to climatology — by design, not a bug, and computed by
an independently-written code path specifically so the numeric match is evidence
rather than one function calling the other. Verified by
`tests/test_leakage.py::test_known_accumulation_baseline_matches_climatology_numerically`.

### 4.2 `persistence_prob` is calibrated, not a coin flip dressed as a probability

A hard 0/1 step function (today's state, carried forward) is a Brier
worst-case by construction on a ~15-25% base-rate event — using it inflated
"model beats persistence" into mostly an artefact of the baseline being
deliberately uncalibrated. Replaced with an empirically fit P(drought ahead |
drought now), estimated basin-wide (not per cell — a per-cell 2-state table would
starve some cells of both classes over 36 years) on the reference period only.

### 4.3 The ONE place a baseline's fit is population-restricted

`persistence_prob`'s fit is the only baseline computation restricted to the
1,823-cell analysis population (`in_hydrobasins & ~in_akarcay_lobe &
crop_frac_2021 >= 0.5`) rather than the full 2,820-cell panel. `climatology`
fits **per cell**, so a boundary-ring cell's own mean never reaches an analysis
cell's forecast regardless of which cells are in the input frame. `persistence`'s
calibration is a single POOLED basin-wide rate, so without this restriction the
ring's statistics leak into the number applied to every analysis cell — found
during the second skeptic audit of T8, not anticipated when the baseline was
first written. The APPLICATION (one row per panel cell) is unrestricted, per the
one-row-per-`(cell_id, date)` contract.

### 4.4 NaN means "unknown", not "not in drought"

A bare `series < threshold` reads `NaN` as `False` (pandas/numpy comparison
semantics) — silently, with no error. `persistence_prob` and its fit therefore go
through `_below_threshold()` (`src/models/baselines.py`), which keeps a missing
value missing. Before this fix, 14,100 rows in 1981's warm-up window (where the
continuous `persistence` column is correctly null) carried a real-looking
`persistence_prob` value instead of null — a silent-corruption-class bug that
never touched the test-period metrics but would have on a target with interior
gaps.

---

## 5. Predictions — `data/processed/predictions.parquet`

Produced by `python -m src.models.train` (T7). 1,545,360 rows: every
(cell, month, target) combination the model could be SCORED on across
train+validation+test (not just test), so the leakage tests and the split
assertions have train/validation rows to check too.

| Column | Type | Meaning |
|---|---|---|
| `cell_id`, `date` | int64, datetime | `date` is the forecast **ISSUE** date — see below, this is the opposite convention from §4 |
| `target`, `lead_months`, `kind` | — | same meaning as §4 |
| `actual` | float64 | the quantity `prediction` estimates: binary {0,1} for classification, raw value for regression — NOT always the raw SPI value (see 5.2) |
| `actual_raw_spi` | float64 | the raw SPI value at `date + lead_months`, kept alongside `actual` even for classification targets |
| `prediction` | float64 | XGBoost's output: `predict_proba(...)[:,1]` for classification, `predict(...)` for regression |
| `split` | str | `"train"`, `"validation"`, `"test"`, or `"none"` |

### 5.1 `date` is the ISSUE date here, the VERIFICATION date in §4 — read this before joining the two files

`predictions.parquet`'s `date` is the month the forecast was ISSUED from;
`baselines_monthly.parquet`'s `date` is the month the forecast is ABOUT. A row
with `date = 2023-01-01` and `lead_months = 3` means "issued 2023-01, verifies
2023-04" in this file, and "this row IS the verification for 2023-01" in §4's
file. Comparing the two on raw `date` silently pairs the wrong months — caught
building T8, proven empirically (shifting `predictions`' date forward by
`lead_months` reproduces §4's date-indexed series with a 45/45 exact match), and
guarded permanently by an assertion in `src/eval/skill.py` that the two files'
`actual` values agree on every date they're aligned to.

### 5.2 Why `actual` and `actual_raw_spi` are both stored

For a classification target, `actual` is the {0,1} indicator `prediction`
estimates — not the SPI value. Storing the raw SPI value in `actual` for a
classification target was a real bug caught before T8 shipped: every downstream
AUC/Brier computation would have silently scored a probability against a
continuous number. `actual_raw_spi` keeps the raw value available anyway, for
anyone who wants it, under a name that cannot be confused with the scoring
target.
