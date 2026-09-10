"""T5 - SPI-1 and SPI-3, fit on the reference period, applied to the whole series.

FIT PERIOD vs APPLICATION PERIOD, and why they are different arguments, not a
naming convention. SPI standardises precipitation against a distribution fitted per
(cell, calendar month). Fitting on the full 1981-2025 record would let validation
(2018-2020) and test (2022-2025) statistics leak into the parameters used to score
those very periods - the leak this project's leakage tests exist to catch.

`climate_indices.indices.spi()` makes the split structural rather than a discipline
to remember: `calibration_year_initial`/`calibration_year_final` are separate,
required arguments from `data_start_year`, so fitting on the wrong window is a
different call, not a mistake inside one call. This module never computes its own
gamma parameters for that reason - it calls the library once per (cell, target) with
the reference period pinned to `config/data.yaml`'s `baseline_precip_era5`
(1981-2016), and applies the result to the full input series (1981-2025).

SENSITIVITY, not a threshold. See docs/spi_reliability_note.md: the standard
zero-frequency reliability criterion inverts on this basin because CHIRPS's
low-amount bias erases the symptom it looks for. What we can measure instead is how
many millimetres separate SPI 0 from SPI -1 at each (cell, calendar month), from the
SAME reference-period fit. That measurement is stored - `spi1_mm_per_unit`,
`spi3_mm_per_unit` - and reliability is reported binned by it (config
`spi_reliability.report_bins_mm`), never gated by a threshold frozen into the panel.

Run:  python -m src.features.spi
"""

from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import gamma as gamma_dist, norm

from src.data.gee_io import ROOT, atomic_write, load_config, provenance, report

PANEL = ROOT / "data" / "processed" / "panel_monthly.parquet"
VALIDATION_JSON = ROOT / "reports" / "spi_validation.json"

PLAUSIBLE_SPI_RANGE = (-4.0, 4.0)


# --------------------------------------------------------------------------
# reference-period gamma fit - one function, used for SPI itself and for the
# sensitivity measurement, so the two can never see different parameters.
# --------------------------------------------------------------------------
def fit_gamma_params(
    reference_values: np.ndarray,
) -> tuple[float, float, float] | None:
    """(q, shape, scale) of the mixed distribution, fit on REFERENCE data only.

    `reference_values` must already be restricted to one (cell, calendar month)
    within the fit period - restricting it is the caller's job, done once, in
    `_reference_slice`, so every consumer of this function sees the same window.
    """
    v = reference_values[~np.isnan(reference_values)]
    if len(v) < 5:
        return None
    q = float((v == 0).mean())
    nz = v[v > 0]
    if len(nz) < 5:
        return None
    shape, _, scale = gamma_dist.fit(nz, floc=0)
    if not (shape > 0 and scale > 0):
        return None
    return q, float(shape), float(scale)


def mm_per_spi_unit(params: tuple[float, float, float] | None) -> float:
    """mm separating SPI=0 from SPI=-1 under this cell-month's fitted distribution.

    The measured sensitivity that replaces the inverted zero-frequency criterion -
    see docs/spi_reliability_note.md. Uses the SAME (q, shape, scale) that produced
    the SPI values themselves, so the two can never disagree about which fit applies.
    """
    if params is None:
        return float("nan")
    q, shape, scale = params

    def value_at(spi: float) -> float:
        p = norm.cdf(spi)
        if p <= q:
            return 0.0
        return float(gamma_dist.ppf((p - q) / (1 - q), shape, loc=0, scale=scale))

    return value_at(0.0) - value_at(-1.0)


# --------------------------------------------------------------------------
def build_series_grid(
    panel: pd.DataFrame, value_col: str, start_year: int, end_year: int
) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    """cell_id-major matrix of shape (n_cells, n_years*12), gap-free from Jan start_year.

    `climate_indices.indices.spi` reshapes its 1-D input to (n_years, 12) under
    monthly periodicity, so a cell's series must start in January with no missing
    months - this function fails loudly rather than silently misaligning months if
    that is not true.
    """
    full = pd.DataFrame({
        "date": pd.date_range(f"{start_year}-01-01", f"{end_year}-12-01", freq="MS")
    })
    n_months = len(full)
    if n_months % 12:
        raise AssertionError(f"expected a whole number of years, got {n_months} months")

    cell_ids = np.sort(panel["cell_id"].unique())
    wide = (
        panel.pivot(index="cell_id", columns="date", values=value_col)
        .reindex(index=cell_ids, columns=full["date"])
    )
    if wide.isna().any().any():
        missing = int(wide.isna().sum().sum())
        raise AssertionError(
            f"{missing} missing (cell, month) values in {value_col} between "
            f"{start_year}-01 and {end_year}-12 - the input must be gap-free for "
            "reshape-based SPI computation"
        )
    return cell_ids, full["date"].to_numpy(), wide.to_numpy()


def compute_spi(
    values: np.ndarray,  # (n_cells, n_months), Jan start_year .. Dec end_year
    start_year: int,
    end_year: int,
    fit_start_year: int,
    fit_end_year: int,
    scale: int,
) -> tuple[np.ndarray, np.ndarray]:
    """SPI-`scale` per cell, fit on [fit_start_year, fit_end_year], applied to the whole row.

    Also returns mm-per-unit sensitivity, computed from the SAME fit as the SPI
    values - see mm_per_spi_unit.
    """
    from climate_indices import compute, indices

    n_cells, n_months = values.shape
    n_years = n_months // 12
    spi_out = np.full_like(values, np.nan, dtype=float)
    sens_out = np.full((n_cells, 12), np.nan, dtype=float)

    accumulated = values if scale == 1 else _rolling_sum(values, scale)

    reshaped = accumulated.reshape(n_cells, n_years, 12)
    fit_slice = reshaped[:, fit_start_year - start_year: fit_end_year - start_year + 1, :]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for c in range(n_cells):
            row = accumulated[c]
            if np.isnan(row).all():
                continue
            spi_out[c] = indices.spi(
                row,
                scale=1,  # accumulation already applied by _rolling_sum
                distribution=indices.Distribution.gamma,
                data_start_year=start_year,
                calibration_year_initial=fit_start_year,
                calibration_year_final=fit_end_year,
                periodicity=compute.Periodicity.monthly,
            )
            for m in range(12):
                params = fit_gamma_params(fit_slice[c, :, m])
                sens_out[c, m] = mm_per_spi_unit(params)

    return spi_out, sens_out


def _rolling_sum(values: np.ndarray, k: int) -> np.ndarray:
    """k-month trailing sum per row; first k-1 entries are NaN (accumulation incomplete).

    rolling[:, i] = csum[:, i] - csum[:, i-k], with csum[:, i-k] treated as 0 for
    i < k. Shifting csum right by k columns (zero-padded) gives that subtrahend in
    one array of the SAME width as csum, so no second slice is needed - the earlier
    version sliced both operands independently and their widths disagreed by k.
    """
    n_rows, n_cols = values.shape
    csum = np.cumsum(values, axis=1)
    csum_shifted = np.concatenate([np.zeros((n_rows, k)), csum[:, :-k]], axis=1)
    rolling = csum - csum_shifted
    rolling[:, : k - 1] = np.nan
    return rolling


# --------------------------------------------------------------------------
# validation against climate_indices as the reference implementation - full
# coverage on one cell's whole series, not a spot sample. See failure-modes 24:
# do not sample when full verification is cheap, and here it is trivially cheap.
# --------------------------------------------------------------------------
def validate_against_reference(
    panel: pd.DataFrame, start_year: int, fit_start: int, fit_end: int
) -> dict[str, Any]:
    from climate_indices import compute, indices

    cell_ids, dates, precip = build_series_grid(panel, "precip_chirps_mm", start_year, 2025)
    picks = [
        cell_ids[0], cell_ids[len(cell_ids) // 2], cell_ids[-1],
    ]
    results = {}
    for cell in picks:
        idx = int(np.where(cell_ids == cell)[0][0])
        row = precip[idx]
        ours, _ = compute_spi(row[None, :], start_year, 2025, fit_start, fit_end, scale=1)
        theirs = indices.spi(
            row, scale=1, distribution=indices.Distribution.gamma,
            data_start_year=start_year, calibration_year_initial=fit_start,
            calibration_year_final=fit_end, periodicity=compute.Periodicity.monthly,
        )
        diff = np.abs(ours[0] - theirs)
        results[int(cell)] = {
            "n_months": len(theirs),
            "max_abs_diff": float(np.nanmax(diff)),
            "mean_abs_diff": float(np.nanmean(diff)),
        }
    return results


# --------------------------------------------------------------------------
def build() -> pd.DataFrame:
    config = load_config()
    baseline = config["climatology"]["baseline_precip_era5"]
    fit_start_year = int(str(baseline["start"])[:4])
    fit_end_year = int(str(baseline["end"])[:4])

    panel = pd.read_parquet(PANEL)
    panel["date"] = pd.to_datetime(panel["date"])
    start_year, end_year = panel["date"].dt.year.min(), panel["date"].dt.year.max()

    print(f"Reference period (fit): {fit_start_year}-{fit_end_year} "
          f"({fit_end_year - fit_start_year + 1} years)")
    print(f"Application period: {start_year}-{end_year}")

    cell_ids, dates, precip = build_series_grid(
        panel, "precip_chirps_mm", start_year, end_year
    )

    print("\nComputing SPI-1 ...")
    spi1, sens1 = compute_spi(precip, start_year, end_year, fit_start_year, fit_end_year, scale=1)
    print("Computing SPI-3 ...")
    spi3, sens3 = compute_spi(precip, start_year, end_year, fit_start_year, fit_end_year, scale=3)

    n_years = end_year - start_year + 1
    long = pd.DataFrame({
        "cell_id": np.repeat(cell_ids, len(dates)),
        "date": np.tile(dates, len(cell_ids)),
        "spi_1": spi1.ravel(),
        "spi_3": spi3.ravel(),
    })
    sens_df = pd.DataFrame({
        "cell_id": np.repeat(cell_ids, 12),
        "month": np.tile(np.arange(1, 13), len(cell_ids)),
        "spi1_mm_per_unit": sens1.ravel(),
        "spi3_mm_per_unit": sens3.ravel(),
    })
    long["month"] = pd.to_datetime(long["date"]).dt.month
    long = long.merge(sens_df, on=["cell_id", "month"], how="left").drop(columns="month")

    panel_out = panel.merge(long, on=["cell_id", "date"], how="left", validate="one_to_one")

    print("\nAssertions (expected -> actual):")
    ok = report("rows", len(panel), len(panel_out))
    ok &= report("duplicate keys after merge", 0,
                 int(panel_out.duplicated(["cell_id", "date"]).sum()))

    lo, hi = PLAUSIBLE_SPI_RANGE
    for col in ("spi_1", "spi_3"):
        in_range = panel_out[col].dropna().between(lo, hi).all()
        ok &= report(f"{col} within [{lo}, {hi}]", True, bool(in_range))

    # SPI-3's first 2 months of the record cannot accumulate 3 months - null there
    # is correct and expected, not a defect.
    n_cells = len(cell_ids)
    expected_null_spi3 = n_cells * 2
    actual_null_spi3 = int(panel_out["spi_3"].isna().sum())
    ok &= report("spi_3 nulls (accumulation warm-up, 2 months x n_cells)",
                 expected_null_spi3, actual_null_spi3)
    ok &= report("spi_1 nulls", 0, int(panel_out["spi_1"].isna().sum()))

    # Sanity: manually accumulate one (cell, month) and compare to the vectorised
    # rolling sum used inside compute_spi.
    sample_cell = cell_ids[len(cell_ids) // 3]
    sample_row = panel[panel["cell_id"] == sample_cell].sort_values("date")
    manual_3mo = sample_row["precip_chirps_mm"].iloc[10:13].sum()
    idx = int(np.where(cell_ids == sample_cell)[0][0])
    vectorised_3mo = _rolling_sum(precip[idx:idx + 1], 3)[0, 12]
    ok &= report("manual vs vectorised 3-month sum (spot check)",
                 round(float(manual_3mo), 6), round(float(vectorised_3mo), 6))

    print("\nValidating against climate_indices (full series, 3 cells - see failure-modes 24):")
    ref_check = validate_against_reference(panel, start_year, fit_start_year, fit_end_year)
    worst = max(r["max_abs_diff"] for r in ref_check.values())
    for cell, r in ref_check.items():
        print(f"  cell {cell}: {r['n_months']} months, max|diff| {r['max_abs_diff']:.2e}, "
              f"mean|diff| {r['mean_abs_diff']:.2e}")
    passed = worst < 1e-9
    print(f"  [{'OK      ' if passed else 'MISMATCH'}] max abs diff vs climate_indices "
          f"reference: expected < 1e-9 -> actual {worst:.2e}")
    ok &= passed

    if not ok:
        raise AssertionError(
            "T5 assertions failed - no output written. Per docs/working_protocol.md, "
            "stop and report."
        )

    atomic_write(panel_out, PANEL)
    VALIDATION_JSON.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": provenance(["src/features/spi.py", "config/data.yaml"]),
        "fit_period": [fit_start_year, fit_end_year],
        "application_period": [int(start_year), int(end_year)],
        "reference_impl_check": ref_check,
        "max_abs_diff_vs_reference": worst,
        "spi3_warmup_nulls": actual_null_spi3,
    }, indent=2), encoding="utf-8")

    print(f"\nWrote {PANEL.relative_to(ROOT)} (spi_1, spi_3, "
          f"spi1_mm_per_unit, spi3_mm_per_unit added)")
    print(f"Wrote {VALIDATION_JSON.relative_to(ROOT)}")
    return panel_out


if __name__ == "__main__":
    build()
