---
name: gee-export
description: Google Earth Engine export patterns, quota management and pitfalls. Use when writing or debugging any GEE export, or when an export times out or exceeds quota.
---

# Earth Engine exports

## Quota

Noncommercial tiers: Community 150 EECU-hours/month, Contributor 1,000. A basin-scale
monthly export fits comfortably if chunked; a single whole-record job will not.

## Which export route

**Default: direct paginated fetch.** `ee.data.computeFeatures` with a page size,
written straight to `data/raw/`. The panel is small enough (2,130 cells per month)
that this works, and it keeps the pipeline reproducible by one command - `make` can
rebuild everything with no human stepping through Google Drive.

**Fallback: `Export.table.toDrive`.** Use when a request hits the interactive compute
limit - "User memory limit exceeded" or "Computation timed out" that chunking cannot
resolve. Batch export jobs get a far larger compute budget than interactive calls, at
the cost of a manual download step and a pipeline that no longer rebuilds in one
command. Expect to need it in Phase 1 if 1 km MODIS layers are aggregated per cell;
that decision is open until it is measured, not assumed either way.

Never a client-side loop calling `getInfo()` per cell. That is the classic way to
turn a five-minute job into an hour and a quota overrun.

## Rules

- **Chunk by year for files, by month for requests.** One file per year, twelve
  requests to build it. A whole year in one request (~25,600 features) approaches
  size limits; a month (~2,130) does not. File granularity and request granularity
  are separate decisions and should not be collapsed.
- **Assert the row count after every fetch.** `n_cells x n_months`, plus the set of
  distinct dates. See the silent-truncation entry below - this is the single most
  important line of defence in the whole export.
- **Write atomically.** Temp file, validate, rename. Delete the temp file on any
  failure. A resume that skips existing files will otherwise protect a truncated file
  forever.
- **Retry with exponential backoff.** GEE returns 429 and 5xx transiently; that is
  normal operation, not failure. Do not give up on the first attempt, and do not
  retry a deterministic error forever either - distinguish them.
- **Reduce server-side.** `reduceRegions` / `sampleRegions` over the analysis grid.
- **Set `scale` and `crs` explicitly** on every reducer and export. Defaults silently
  reproject and the result is wrong at the edges. In this project the correct target
  is the CHIRPS projection object itself, not a metric scale - passing `scale=5566`
  would resample the precipitation grid this project deliberately leaves untouched.
- **Export tables, not rasters.** The pipeline consumes a monthly panel; never
  download GeoTIFFs.
- **`tileScale`** raises to 4 or 8 when hitting memory errors, at some speed cost.
- **Monthly compositing:** build the month list explicitly and map over it; do not
  rely on `.filterDate` inside a client-side loop.
- **Masking:** apply the land-cover and basin masks before reduction, not after.

## Silent truncation - the one that does real damage

`getInfo` and `computeFeatures` can return a **partial result without raising** when
a size limit is hit. The export appears to succeed, the year file exists, nothing
errors anywhere, and the model trains on nine months of that year instead of twelve.
Nothing downstream can tell a short month from a month that genuinely had fewer cells.

Defences, all three together:

1. Keep requests small enough that limits are never approached (one month at a time).
2. Assert the expected row count and the expected set of dates before the file is
   considered written.
3. Write atomically, so a failed assertion leaves no file behind for resume logic to
   trust later.

## Heavy reductions on 10 m data

Aggregating 10 m WorldCover to the analysis grid across a whole basin exceeds the
interactive memory limit. A regular subsample - reproject the binary mask to 100 m
nearest-neighbour, then `reduceResolution` to the analysis grid - gives ~3,100
samples per cell, standard error under 1%, at a fraction of the cost. It is an
unbiased estimator of the same quantity, and it is worth saying so explicitly in the
data dictionary rather than presenting it as a full aggregation.

## Debugging

- "Computation timed out" -> chunk smaller, raise tileScale
- "User memory limit exceeded" -> raise tileScale, reduce band count per job,
  subsample a high-resolution input, or fall back to a batch Drive export
- Empty results -> check `filterBounds` geometry CRS and that the collection actually
  covers the AOI dates
- Fewer rows than expected -> assume silent truncation, not a data gap, until proved
  otherwise
