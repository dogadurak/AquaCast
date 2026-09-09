---
name: failure-modes
description: Failure types already caught, or nearly missed, in this project. Read before writing any design decision, data step, or evaluation code.
---

# Failure modes seen in this project

This file is cumulative. Every time a miss is caught, the entry lands here so it
costs once instead of every time. Adding an entry is part of the fix, not optional
follow-up.

Each entry is **SYMPTOM** (how it looks) / **MECHANISM** (why it happens) /
**DEFENCE** (what gets asserted).

The entries divide into two classes, and the class decides how much to worry:

- **Silent corruption** — no error, tests pass, result is wrong. The dangerous class.
- **Rework** — costs a day, but you can see it. Acceptable risk.

Make silent corruption impossible. Accept rework.

---

## 1. SPI accumulation window overlaps the forecast lead
**Class:** silent corruption

- **SYMPTOM:** R² of 0.6–0.8 at a long lead, far better than published seasonal
  forecast skill. Feels like a breakthrough.
- **MECHANISM:** SPI-*k* at month *t* accumulates *t-k+1 … t*. Forecasting SPI-*k*
  at lead *L < k* means *(k - L)* of the *k* months are already observed at forecast
  time. The model reproduces the known part; none of that is forecast skill.
- **DEFENCE:** `tests/test_leakage.py::test_no_target_predictor_overlap` asserts
  `lead >= k` for every configured (target, lead) pair. The known-accumulation
  baseline exists as the control for any pair that does overlap.

## 2. Reference period intersects held-out data
**Class:** silent corruption

- **SYMPTOM:** Everything looks normal. Anomalies are plausible. Test scores are
  mildly optimistic in a way nothing flags.
- **MECHANISM:** Climatology means, SPI gamma parameters and scalers fitted over a
  period that includes validation or test months push held-out statistics into
  training. The draft spec did exactly this: it named the 1991–2020 WMO normal
  while training ended in 2016, so the period both exceeded the training window and
  overlapped validation (2018–2020).
- **DEFENCE:** `tests/test_leakage.py::test_baseline_periods_exclude_val_and_test`
  reads the periods from `config/data.yaml` and asserts no intersection with any
  non-train split. Periods are never hardcoded in code.

## 3. Metrics pooled across spatially autocorrelated rows
**Class:** silent corruption

- **SYMPTOM:** Very tight confidence intervals. A metric that looks well-determined
  on ~1.15 million rows.
- **MECHANISM:** Neighbouring cells in the same month are nearly identical. The
  effective sample size is closer to the number of months (~540) than the number of
  rows. Pooling inflates confidence by more than an order of magnitude.
- **DEFENCE:** Compute metrics per forecast date, then aggregate across dates. Never
  a single pooled figure. Spatially blocked CV as a robustness check.

## 4. `getInfo` / `computeFeatures` truncates silently
**Class:** silent corruption

- **SYMPTOM:** The export "succeeds". A year file exists. Nothing errors anywhere.
  The model trains on 9 months of that year instead of 12.
- **MECHANISM:** When a result exceeds a size limit, Earth Engine sometimes returns
  a *partial* result rather than raising. Nothing downstream can distinguish a short
  month from a month that genuinely had fewer cells.
- **DEFENCE:** Assert the expected row count after every fetch — `n_cells × n_months`
  — and assert the set of distinct dates matches the requested months. Keep request
  granularity small (one month, ~2,130 features) so limits are never approached.
  Use paginated `ee.data.computeFeatures`, not raw `.getInfo()`.

## 5. A half-written file becomes permanent through resume logic
**Class:** silent corruption

- **SYMPTOM:** A rerun reports "skipping 1994, already on disk". The 1994 file has
  been wrong since the night the connection dropped, and will never be refetched.
- **MECHANISM:** "Skip what exists" resume logic plus a non-atomic write. Any crash
  mid-write leaves a plausible-looking truncated file that the resume logic then
  protects forever.
- **DEFENCE:** Write to a temporary file, validate the invariant, then atomically
  rename. On any validation failure delete the partial file and raise. A file only
  exists at its final path if it already passed its assertions.

## 6. Negative timestamps on Windows
**Class:** rework (but presented as a blocker, so it can stop a project dead)

- **SYMPTOM:** A working CORE dataset reported as unresolvable, with a bare
  `OSError` and no message. Looks like the dataset is unavailable.
- **MECHANISM:** ERA5-Land starts in 1950, so `system:time_start` is a negative
  epoch value. On Windows both `datetime.fromtimestamp` and `utcfromtimestamp`
  delegate to the platform `gmtime`, which raises `OSError [Errno 22]` on negative
  input.
- **DEFENCE:** Format epoch values with arithmetic — `EPOCH + timedelta(ms)` — never
  the platform converters. And never swallow an exception message down to its class
  name: the bare `OSError` is what hid this.

## 7. Resolution inflation
**Class:** rework, but a credibility failure if it ships

- **SYMPTOM:** A crisp 1 km drought map. It looks like the most professional output
  in the project.
- **MECHANISM:** Interpolating 9 km ERA5-Land or 5.5 km CHIRPS onto a 1 km grid
  produces 1 km *pixels* carrying 9 km *information*. The map asserts a precision
  the data does not have, and a reviewer who knows the input resolutions will see it
  immediately.
- **DEFENCE:** The modelling grid is the CHIRPS 0.05° lattice, and every forecast,
  baseline and skill metric lives there. Native-resolution observation layers stay
  separate from forecast layers. Every layer states its true resolution in the UI
  and the model card. `config/data.yaml` `grid.resolution_mismatch` records what
  each column actually carries.

## 8. A dataset resolves green while being unusable
**Class:** silent corruption of a conclusion, not of data

- **SYMPTOM:** `[ OK ] GEE terrestrial_water_storage` — the check passes, so the
  variable goes into the plan.
- **MECHANISM:** The availability probe confirmed the asset exists and returned
  images, but its record ended in 2017-05, seven years before the test period. An
  asset can be present, non-empty, and still cover none of the years that matter.
- **DEFENCE:** Availability is not coverage. Check the record end against the study
  period explicitly and downgrade the status when it falls short. Exempt genuinely
  static products by an explicit flag, never by silence.

## 9. Console UI translating an identifier
**Class:** rework

- **SYMPTOM:** An ID copied from a web console does not resolve, or resolves to the
  wrong resource.
- **MECHANISM:** A localised console can render display names in the user's
  language, and a translated or auto-localised string can be copied instead of the
  literal identifier.
- **DEFENCE:** Take identifiers from the URL or the API response, never from
  translated UI chrome, and echo the ID back for confirmation before depending on it.

## 10. The tautological assertion
**Class:** silent corruption of the verification layer itself — the worst kind

- **SYMPTOM:** An assertion that has never failed and never will. It reads like
  rigour. Example actually written in this project: "assert the basin area is within
  1% of 58,374 km²" — where 58,374 was measured from that same polygon minutes
  earlier.
- **MECHANISM:** Measuring a quantity, then asserting the quantity equals the
  measurement. The check compares a value to itself, so it passes under every
  possible state of the world, including a completely wrong polygon. Writing the
  assertion after seeing the number makes this almost automatic.
- **DEFENCE:** Every assertion must be able to name a state of the world in which it
  fails. If none exists, it is decoration. Validate against an **independent** source
  — published figures, a reference implementation, a physical constraint — not
  against your own prior output. And when the independent source disagrees, the rule
  is *report the discrepancy*, not *assert and move on*.

## 11. A single-epoch auxiliary layer applied to a multi-epoch panel
**Class:** silent corruption

- **SYMPTOM:** Nothing. Every row has a plausible mask value and the panel is
  internally consistent.
- **MECHANISM:** ESA WorldCover v200 maps one year, 2021. Applying it across a
  1981–2025 panel asserts that land cover held still for 45 years. In the Konya basin
  it emphatically did not: irrigated agriculture expanded substantially over exactly
  this period, and that expansion is among the causes of the water crisis being
  studied. A cell that was rangeland in 1985 enters the panel because it is cropland
  in 2021.
- **DEFENCE:** Keeping the mask static is still right — a time-varying mask would
  break panel consistency and make cells appear and disappear. The defence is
  naming: the column is `crop_frac_2021`, not `crop_frac`, so the name cannot
  mislead. Recorded in `docs/data_dictionary.md` and `reports/model_card.md` as a
  limitation. Generalise: any auxiliary layer with a single epoch applied across a
  long panel carries its epoch in its column name.

## 12. Hardcoded grid constants instead of the source projection
**Class:** rework, occasionally silent

- **SYMPTOM:** A grid-alignment assertion passes, so the grid is believed correct.
- **MECHANISM:** Writing `(lon + 180 - 0.025) / 0.05` bakes in an assumed origin and
  step. The assertion then tests the assumption against itself rather than against
  the data. Worse, a wrong origin that differs from the true one by a whole multiple
  of the step still passes — so the check is silent precisely when it is wrong in the
  most plausible way. CHIRPS v3 is a new product; assuming v2's extent would be
  exactly this kind of quiet mistake.
- **DEFENCE:** Read `crs_transform` from the collection's own projection at runtime,
  derive origin and step from it, and log the derived values. Then the assertion
  tests the data, not the belief.

## 13. `reduceResolution` maxPixels ceiling
**Class:** rework (it errors loudly), but it derails a design if unanticipated

- **SYMPTOM:** "User memory limit exceeded" on what looks like a simple aggregation.
- **MECHANISM:** `reduceResolution` caps at 65,536 input pixels per output pixel.
  Aggregating 10 m WorldCover into a 0.05° (~5.5 km) cell needs ~555 × 555 ≈ 308,000
  — nearly five times over. No amount of `tileScale` fixes an arithmetic ceiling.
- **DEFENCE:** Compute the fraction at ~100 m instead: reproject the binary mask to
  100 m, then reduce to the analysis grid (~3,100 pixels per cell, comfortably under
  the cap). For a threshold comparison 100 m is far more precision than the decision
  needs; 10 m buys nothing and burns quota. Check the pixel-ratio arithmetic *before*
  writing the reduction, not after the error.

## 14. An AOI bounding box silently clipping the real geometry
**Class:** silent corruption

- **SYMPTOM:** The export runs, the grid looks sensible, and part of the study area
  is simply absent. No error, because a smaller region is a perfectly valid region.
- **MECHANISM:** A bbox written for one purpose (availability probing) gets reused as
  a spatial filter. The configured AOI bbox here starts at 31.4°E while the basin
  polygon reaches 30.0°E — a 1.4° strip that would have vanished without complaint.
- **DEFENCE:** Never filter analysis geometry by a convenience bbox. Assert that the
  authoritative geometry is fully contained in any bbox that touches it, or drop the
  bbox from that code path entirely. Bounding boxes are for probing; polygons are for
  analysis.

## 15. A threshold set at a multiple of the physical maximum
**Class:** silent corruption of the verification layer — a cousin of entry 10

- **SYMPTOM:** An assertion that passes on every run and feels like a range check.
  Written in this project: "monthly precipitation < 1000 mm". The basin's *annual*
  mean is 417 mm, so that ceiling is two and a half times a whole year's rainfall.
- **MECHANISM:** Choosing a bound that is obviously safe rather than one that is
  actually informative. Such a threshold catches only absurd failures — a unit
  confusion by three orders of magnitude — and passes every plausible one: a factor
  of two, a missing pentad, a wrong accumulation window.
- **DEFENCE:** **An assertion must fail on values that are plausible but wrong.**
  Anchor the bound to an independent published quantity and put the tolerance where
  a real error would land. Here: basin-mean *annual* total against the ministry's
  417 mm, expected 350–500 mm, which a missing pentad (−17%) would break. Ask of
  every threshold: what realistic bug does this catch? If the answer is "none",
  it is decoration.

## 16. A stitched product series read as one instrument
**Class:** silent corruption — and it imitates the very signal being studied

- **SYMPTOM:** A trend. The model appears to learn something real about climate.
- **MECHANISM:** Long satellite records are often several production lines spliced:
  CHIRPS has an ERA5-based reanalysis line and an IMERG-based near-real-time line,
  plus a final/preliminary distinction whose recent months get revised. If the line
  changes between the reference period (1981–2016 here) and the test period
  (2022–2025), anomalies are measured with one product against a baseline fitted on
  another. The systematic offset is indistinguishable from a climate signal, and
  what the model learns is the product change.
- **DEFENCE:** Check before exporting, not after. Look for a per-image
  source/version property; if there is none — as with CHIRPS v3 PENTAD in GEE, which
  carries only year, month and pentad — the time series is the only evidence, so
  plot basin-mean annual totals and look for a level shift. Beware the era mean as a
  detector: one extreme year drags it and imitates a step. The discriminator is that
  a production change moves *every* year after the transition, so a single
  post-transition year at or above the long-term mean rules a level shift out.
  Record the fetch date in a manifest, because final products get reprocessed and
  the same export can return different numbers months later.

## 17. An assertion that encodes the analyst's expectation, not a property of the data
**Class:** rework — it fires loudly, but on the wrong thing

- **SYMPTOM:** A well-motivated check fails, and the instinct is that the data is
  broken. Written here: "exact-zero precipitation months should concentrate in
  July–September, because Konya summers are dry". It failed. The zeros were in March.
- **MECHANISM:** The assertion tested a belief about the region rather than a
  property that distinguishes the two outcomes. The belief was wrong for this
  product: CHIRPS overestimates low precipitation amounts, so the climatological dry
  season rarely reaches exact zero — the basin minimum in July 1990, the driest month
  of a dry year, was 2.42 mm across all 2,820 cells. Zeros mark *exceptional* months,
  not the dry season.
- **DEFENCE:** Test the mechanism that separates the outcomes, not a correlate of it.
  Masked pixels produce an isolated spike at exactly 0.0 with a gap above it; a
  genuine dry month produces a continuous ramp down to zero. So the check is: does
  every month containing zeros also contain values in (0, 1) mm? That is a property
  of the distribution, true regardless of season or region. When an assertion fails,
  ask which of the two — the expectation or the data — is being tested, before
  assuming the data lost.

## 18. Collection-level counts mistaken for per-pixel counts
**Class:** silent corruption

- **SYMPTOM:** None. The monthly total is plausible, merely too low.
- **MECHANISM:** `ImageCollection.size()` says how many images are in the window. It
  says nothing about how many contributed *at a given pixel*. `sum()` skips masked
  pixels, so a cell masked in two of six pentads gets a four-pentad total, and no
  count, range check or null check notices.
- **DEFENCE:** Carry a per-pixel `count()` band alongside the sum and assert it
  equals the expected number of observations for **every row**, not once per month.
  The collection-level check stays too — they catch different failures.

## 19. A check applied to the wrong population, or to an incommensurable quantity
**Class:** rework — a false alarm, which is expensive in a different way

- **SYMPTOM:** An assertion fails on correct data and halts a long job. Here: "monthly
  precipitation must not exceed 417 mm" stopped the export on 1981 at a value of
  720.6 mm that was entirely real.
- **MECHANISM:** Two errors compounded. The bound compared a **per-cell monthly**
  value against a **basin-mean annual** figure — incommensurable quantities, so the
  comparison was meaningless whatever number was chosen. And it was applied to the
  whole exported set including the **ring cells**, which exist only as boundary
  insurance and sit partly on the Taurus flank where 1,500–2,000 mm/year is normal.
  The offending cell was outside the basin and would have been masked out anyway.
- **DEFENCE:** Before writing a bound, state the population it describes and check
  the units match on both sides. Apply analysis-time sanity checks to the analysis
  population, not to cells deliberately carried for other reasons. And prefer a
  **cross-check between two independent computation routes** over an absolute bound:
  here, the exported per-cell values averaged over the basin reproduce the
  pre-flight's server-side basin reduction to within 0.07%, which catches an
  accumulation-window bug that no single-value ceiling would.
- False alarms are not free. They cost a 2.5-hour job and, worse, they train the
  habit of relaxing thresholds until nothing fires.

---

## Adding an entry

When a miss is caught — by me, by the skeptic agent, or by a failing run — append it
here in the same format before moving on. If the same class of mistake could recur in
a different module, say so in the DEFENCE line. Most of these are generic GIS/ML
failure modes, not Konya-specific, so this file is worth carrying to the next project.
