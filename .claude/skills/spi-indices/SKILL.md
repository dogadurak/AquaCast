---
name: spi-indices
description: Correct computation of SPI, SPEI and standardised anomalies for drought analysis. Use whenever computing, validating or debugging a drought index, or when choosing a reference period.
---

# Drought index computation

SPI failures are silent. A wrong implementation returns plausible numbers and no
error, and every downstream result inherits the mistake. Validate before trusting.

## SPI, correctly

1. Aggregate precipitation over the accumulation window (k months, rolling sum).
2. Fit a gamma distribution **per cell, per calendar month** - seasonality means a
   single fit across all months is wrong.
3. Handle zero precipitation explicitly. The gamma distribution is undefined at
   zero, so use the mixed distribution: `H(x) = q + (1-q) * G(x)` where `q` is the
   probability of zero. Skipping this biases arid-month values, which in a drought
   study is exactly where accuracy matters.
4. Transform the cumulative probability to the standard normal quantile.

## Rules that are not optional

- **Fit parameters on the training period only.** Fitting on the full record leaks
  test-period statistics into training. State the reference period everywhere.
- **State the reference period in every output and figure.** SPI values are
  meaningless without it; 1991-2020 is the current WMO normal.
- **Minimum record length: 30 years for stable fits.** With 25 years, say so as a
  limitation rather than pretending otherwise.
- **Accumulation window vs forecast lead.** SPI-k at lead L < k overlaps the
  observed period by (k - L) months. Never forecast such a pair without the
  known-accumulation baseline.

## SPEI

SPEI replaces precipitation with (precipitation - PET) and fits a log-logistic
distribution, not gamma. Use Hargreaves PET when only temperature is available;
Penman-Monteith when radiation, wind and humidity are available (ERA5-Land provides
them). Do not mix PET methods within one study.

## Validation, before anything downstream

Compare against the `climate_indices` package or published Copernicus GDO values for
the same cells and months. Agreement within a small tolerance, or find out why not.
