# Why the standard SPI reliability criterion could not be used here

*Method-selection note. Belongs in the model card, not in the results.*

## The question

SPI at short accumulations is known to misbehave in arid regions and dry seasons.
Before computing SPI-1 and SPI-3 for the Konya basin, we needed to know whether our
approved targets — SPI-1 at +1 month and SPI-3 at +3 months — are meaningful in every
month, or only in some.

## The standard criterion, and why it does not apply

[Wu et al. (2007)](https://rmets.onlinelibrary.wiley.com/doi/10.1002/joc.1371)
describes the mechanism precisely: where zero precipitation is common, SPI at short
timescales becomes **lower-bounded and non-normally distributed**, and fails to
indicate drought. The criterion follows from the mixed distribution used to compute
SPI — with a probability of zero *q*, no SPI value below Φ⁻¹(*q*) can ever occur, so
the index is truncated from below and cannot express severe drought.

That criterion is testable, so we tested it on our reference period (1981–2016, 2,130
analysis cells):

| Month | *q* (median / max) | Implied SPI lower bound | Wu criterion |
|---|---|---|---|
| January | 0.028 / 0.111 | −1.22 | **warns** |
| April | 0.000 / 0.056 | −1.59 | **warns** |
| **July** | **0.000 / 0.000** | none | **passes** |
| **August** | **0.000 / 0.028** | −1.91 | **passes** |
| **September** | **0.000 / 0.000** | none | **passes** |
| December | 0.028 / 0.083 | −1.38 | **warns** |

The criterion clears July, August and September — the driest months of the year — and
raises concern about midwinter instead. That is the opposite of what the climate
implies, and it is not a small discrepancy. Applied without checking, it would have
given a clean bill of health to precisely the months that are broken.

## Why it inverts

CHIRPS overestimates low precipitation amounts — a documented bias over Türkiye, and
one we measured directly on this basin: in July 1990, the driest month of a dry year,
the basin **minimum** was 2.42 mm and not one of 2,820 cells recorded zero.

So the product almost never produces an exact zero in summer. *q* ≈ 0, the mixed
distribution collapses to a plain gamma fit on ~36 samples, and Wu's test finds
nothing wrong.

**The bias removes the symptom the criterion looks for, while leaving the underlying
problem in place.** A gauge series for the same basin would show many summer zeros and
the criterion would fire correctly. Ours does not, because the product has filled
those zeros with small positive numbers.

## What actually breaks, measured directly

Rather than test for zeros, we measured the quantity that matters: **how much
precipitation must change to move SPI by one unit.** Median across analysis cells,
reference period 1981–2016:

| Month | SPI-1 | SPI-3 |
|---|---|---|
| December–May | 19–25 mm | 35–46 mm |
| June | 12.9 mm | 36.0 mm |
| July | **3.3 mm** | 29.6 mm |
| **August** | **2.0 mm** | 15.9 mm |
| September | **6.1 mm** | 10.1 mm |
| October–November | 20–23 mm | 26–34 mm |

In August, **2 mm of precipitation is one full SPI unit** — the difference between
normal conditions and moderate drought. That is below the product's own floor over
this basin. Whatever SPI-1 reports for August is therefore dominated by the behaviour
of CHIRPS at small amounts, not by meteorology.

SPI-3 never approaches that regime. Its weakest month is September (the July–August–
September window), at 10.1 mm — five times more robust than SPI-1 in August, and well
above the product floor in every month.

## Consequences for the design

1. **SPI-3 at +3 months becomes the primary target.** It was already the
   non-overlapping, honest seasonal test; it is now also the only one of the two that
   is well conditioned in every month and every cell.
2. **SPI-1 at +1 month is retained as secondary**, with its skill reported **per
   calendar month** rather than pooled. Pooling would average the summer degradation
   into the robust winter months and hide it — the specific way this project is most
   likely to mislead itself.
3. **Sensitivity is stored, not thresholded.** `spi1_mm_per_unit` and
   `spi3_mm_per_unit` are panel columns, because they are measurements. Skill is
   reported **binned by sensitivity** (<3, 3–5, 5–10, >10 mm per SPI unit) so that the
   curve shows where degradation begins instead of asserting a cut point. Any binary
   flag is derived at analysis time from a threshold in `config/`, never frozen into
   the panel.

## Open

The bin edges above are descriptive, not justified by a measured uncertainty. Setting
a defensible reliability threshold requires knowing CHIRPS's actual error at low
monthly amounts over this basin, which requires station data. The MGM station
comparison already planned for ERA5 temperature and CHIRPS bias supplies that third
answer as well; the threshold should be drawn on the sensitivity curve with that
evidence rather than chosen now.

## The transferable point

The failure mode here is not "SPI is unreliable in dry seasons" — that is known. It is
that **a product's bias can erase the diagnostic that would have detected its own
unsuitability.** A criterion built on a symptom is only as good as the symptom's
survival through the processing chain. Where a standard test can be checked against a
direct measurement of the thing it is proxying for, it should be.
