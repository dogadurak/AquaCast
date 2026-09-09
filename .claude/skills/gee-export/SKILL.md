---
name: gee-export
description: Google Earth Engine export patterns, quota management and pitfalls. Use when writing or debugging any GEE export, or when an export times out or exceeds quota.
---

# Earth Engine exports

## Quota

Noncommercial tiers: Community 150 EECU-hours/month, Contributor 1,000. A basin-scale
monthly export fits comfortably if chunked; a single whole-record job will not.

## Rules

- **Chunk by year.** One export task per year, named deterministically so reruns skip
  completed years.
- **Reduce server-side.** `reduceRegions` over the analysis grid, never a client-side
  loop over cells with `getInfo()` per cell - that is the most common way to turn a
  five-minute job into an hour and a quota overrun.
- **Set `scale` and `crs` explicitly** on every reducer and export. Defaults silently
  reproject and the result is wrong at the edges.
- **Export tables, not rasters.** The pipeline consumes a monthly panel. Use
  `Export.table.toDrive` with CSV; never download GeoTIFFs.
- **`tileScale`** raises to 4 or 8 when hitting memory errors, at some speed cost.
- **Monthly compositing:** build the month list explicitly and map over it; do not
  rely on `.filterDate` inside a client-side loop.
- **Masking:** apply the land-cover and basin masks before reduction, not after.

## Debugging

- "Computation timed out" -> chunk smaller, raise tileScale
- "User memory limit exceeded" -> raise tileScale, reduce band count per job
- Empty results -> check `filterBounds` geometry CRS and that the collection actually
  covers the AOI dates
