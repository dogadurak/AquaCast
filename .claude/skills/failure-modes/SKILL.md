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

---

## Adding an entry

When a miss is caught — by me, by the skeptic agent, or by a failing run — append it
here in the same format before moving on. If the same class of mistake could recur in
a different module, say so in the DEFENCE line. Most of these are generic GIS/ML
failure modes, not Konya-specific, so this file is worth carrying to the next project.
