# Data dictionary

Every column the pipeline produces is documented here with units, source, native
resolution, and known biases. A column that is not documented here does not exist
as far as the rest of the pipeline is concerned.

Status: **T1 complete.** Panel columns (`data/processed/panel_monthly.parquet`)
are filled in at T4.

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

**Bias against the official climatology — the first number of the CHIRPS comparison.**

| Quantity | Value |
|---|---|
| CHIRPS v3 basin-mean annual total, 1981–2025 | **463.1 mm** |
| Published basin-mean annual total (SYGM, Konya Havzası Tanıtım) | **417 mm** |
| CHIRPS bias | **+11.1%** |

The same ministry report gives the basin area as 4,980,534 ha = 49,805 km², matching
the official area in §1.3 — so both figures describe the same delineation. A positive
bias is the documented behaviour of CHIRPS over Türkiye, and this is its magnitude for
this basin. It is a result, not only an assertion.

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

*Filled in at T4.* Schema is defined in `CLAUDE.md`. Notes already fixed:

- The panel spans **1981–2025** while MODIS columns begin in **2001**. Rows for
  1981–2000 are kept with MODIS columns null and `ndvi_available`, `et_available`,
  `lst_available` false. They are not dropped: they enable the Phase 3 ablation of a
  precipitation-only model on 36 years against a full-feature model on 16.
- Reference periods for anomalies and SPI are `baseline_precip_era5` (1981–2016) and
  `baseline_modis` (2001–2016). The 1991–2020 WMO normal is **not** used — it
  overlaps validation. See `PROJECT_SPEC.md` §4.2.
- A 1981 reference start includes pre-warming years, so recent anomalies read drier
  than against a recent normal. Correct, but stated wherever anomalies appear.
