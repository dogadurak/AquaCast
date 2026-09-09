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
