# Model card - AquaCast

Filled in during Phase 3. Every number here must trace to a `reports/metrics_*.json`.

Sections below marked **[decided]** are settled and carry no pending numbers.
Sections marked **[pending]** are placeholders until the phase that produces them.

## Intended use
*[pending - Phase 3]*

## Training data and period
*[pending - Phase 1/3]*

### Reference periods for anomalies and SPI **[decided]**

Anomalies and SPI gamma parameters are fitted on two reference periods, defined
once in `config/data.yaml`:

| Reference period | Span | Applies to |
|---|---|---|
| `baseline_precip_era5` | 1981-2016 (36 yr) | precipitation, T2m, PET, soil water, SPI-1/3/6/12, SPEI-3/6, `sm_anom` |
| `baseline_modis` | 2001-2016 (16 yr) | NDVI, ET, LST, `ndvi_anom`, `lst_anom` |

Neither period intersects validation (2018-2020) or test (2022-2025).

**Why not the 1991-2020 WMO normal.** The draft specification named it. It cannot
be used here: training ends in 2016, so 1991-2020 is not a subset of the training
window, and it overlaps the validation years. Anomalies computed against it would
carry held-out statistics into training. The correction is enforced by
`tests/test_leakage.py::test_baseline_periods_exclude_val_and_test`.

### Known limitations of these reference periods **[decided]**

1. **A 1981 start makes recent anomalies read drier.** The period includes
   pre-warming years, so present-day values are standardised against a cooler
   baseline than a 1991-2020 or 1995-2024 normal would provide. This is not an
   error - a longer record gives a more stable gamma fit, and 36 years clears the
   WMO-recommended 30-year minimum - but the resulting anomalies are *not*
   comparable to products published against a recent normal, and a drying signal in
   the anomaly series partly reflects the baseline choice rather than the forecast.
   Any figure or table of anomalies must name its reference period.

2. **MODIS-derived anomalies rest on 16 years, not 30.** MODIS begins in 2000.
   Sixteen years gives roughly 16 samples per cell per calendar month, which makes
   `ndvi_anom` and `lst_anom` noisier than the precipitation-derived indices,
   particularly in the tails - which is where drought lives. Stated here rather
   than worked around; there is no more data to be had.

3. **The two periods are not interchangeable.** A comparison between, say,
   `sm_anom` and `ndvi_anom` compares deviations from two different baselines.
   Do not read their difference as a physical signal.

## Baselines and measured skill
*[pending - Phase 0 produces the first skill table, Phase 3 the final one]*

## Where the model has no skill
*[pending - Phase 3]*

## Known limitations
*[pending - Phase 3; the reference-period limitations above carry forward]*

## Data provenance
*[pending - Phase 1]*
