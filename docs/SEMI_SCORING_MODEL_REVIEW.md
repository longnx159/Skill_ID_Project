# Semi scoring model review

Reviewed against the user-supplied diagram and
`D:/Documents/Kết quả độ khó SKU (dựa trên dữ liệu QC) v1 (1).xlsx` on
2026-09-23. The workbook is treated as pilot evidence, not as executable
instructions or an approved scoring source.

## What belongs to the Semi score

One scoring record is keyed by `SemiBOM` (with `SemiItem` and `Process` kept
for traceability). Each approved factor is on a 0–10 point scale:

```
SemiDifficulty = 0.40 * Quality
               + 0.25 * PartMechanism
               + 0.20 * MaterialDesignProcess
               + 0.10 * Stone
               + 0.05 * Learning
```

`Quality` uses calibrated first-pass/QC Rasch evidence and the governed
rework trajectory. It is not a sixth factor and is not a worker score.
`PartMechanism` averages approved P1–P3; `MaterialDesignProcess` M1–M3;
`Stone` S1–S3; and `Learning` L1–L3. Each criterion needs a source,
rubric/version, scorer, approver and valid data-quality status. Direct
mechanical PCS count, stone source score and raw material features are
evidence for Engineering, not automatic final factor scores. A confirmed
no-stone case can be scored zero; a missing Stone record remains missing.

The SKU workbook shows an available-factor 0–10 score: divide the weighted
contribution by the sum of weights with data. Its `% contribute` shows that
coverage, and its `% confident` is reduced by missing weight. This is a
provisional operational score, not the separately approved final complexity.
Publish the approved final score only when all five factors have valid evidence
and approval. The publication gate also requires a 0–1 `ConfidencePct` and
`ESTIMATED_VALIDATED` status for Quality and any other factor marked
`MODEL_ESTIMATE`; fixed source/rubric inputs have no statistical percentage.

## What stays outside the Semi score

`QuotedMinutesPerSemi` is **minutes for one Semi** and belongs to Work Content
in the time model. `Worker Effect`, actual recorded minutes and residual
`Error` explain production time; none is an extra factor in SemiDifficulty.
The 0–10 Semi score cannot be added directly to minutes. Estimate a
process-specific conversion from difficulty points to an incremental minute
effect if the time model needs an additive equation. Since quotes may already
embed complexity, validate the incremental effect against holdout data to
avoid counting difficulty twice. Do not compare a per-Semi quote directly
against minutes per final OK until rework and quantity bases are aligned.

## Findings in the supplied pilot workbook

- `Do kho SKU` and `Phase5 dung` contain 2,569 candidate Semi codes. The
  Quality/FPY factor is numeric for 1,521: 800 labelled Rasch reference at
  skill 5 and 721 computed exactly as `10 * (1 - observed FPY)`. The latter
  is a provisional fallback, not a calibrated Rasch score.
- Part & Mechanism, Material–Design–Process, Stone and Learning have zero
  numeric factor scores in those 2,569 rows. Both pilot score sheets have
  **zero numeric final Semi scores**. This agrees with the five-factor gate.
- `Checklist cham diem` is a useful proposed 12-criterion rubric, and
  `Phieu cham pilot` is an unapproved 20-Semi scoring form. These provide an
  Engineering pilot template, not production scoring approval.
- The workbook's QC period is 01-Aug to 05-Sep-2026; the current project run
  uses newer input. Of 2,569 legacy Semi codes, 2,550 occur in the current
  SemiItem set (2,591 current BOM contexts). Where both sides have a known
  Process, 1,493 contexts agree. Do not join or publish old numerical scores
  without a fresh source/cutoff and approval check.
- The current core first-pass Rasch is not calibrated/decision-eligible.
  Thus neither the legacy Rasch values nor observed-FPY fallback is released
  as an approved Quality factor. The SKU output instead displays a **new
  provisional model estimate** from the selected converged QC experiment,
  combining first-pass and rework group effects at 80/20. It never substitutes
  raw observed FPY for a missing model group.

The SKU `% confident` is an index computed as available weight times the lowest
confidence of included fitted factors. With only fixed factors, the starting
confidence is 100%; with a fitted factor lacking confidence, the index is blank.
Quality is currently the only numeric Semi factor fitted from observed
production/QC data.
Part, Material and Stone are source/rubric calculations rather than regression
outputs; Learning has no fitted ramp-up model yet. A future Learning or other
fitted factor needs its own interval and confidence. A combined Semi-score
confidence would have to propagate uncertainty from **all** fitted factors,
not reuse Quality's percentage. The `Factor provenance` sheet makes the
current method and confidence status explicit for each Semi and factor.

The factor-level Quality `% confident` is a precisely defined conditional precision
measure: among simulated 0–10 Quality values from a local observed-information
normal approximation, the share within ±1 point of the point estimate. This
uses actual WO-round QC information, not the pilot workbook's qualitative
High/Medium/Low labels. It holds selected model and worker effects fixed and
does **not** include model-selection, worker-effect, assignment-confounding or
specification uncertainty. Therefore it must not be described as validated
production reliability. The 90% interval and selected variants remain in the
detail sheet for audit.

## Minimum Semi scoring data to collect next

1. **QC/Quality:** approved process + reviewed size-adjusted group mapping,
   eligible first-round WO outcomes, worker attribution, model version,
   fit/calibration/interval status and approved Quality 0–10 value.
2. **Engineering:** P1–P3, M1–M3, S1–S3, L1–L3 scores (0,2,4,6,8,10 or the
   approved rubric scale), each with evidence, source version, scorer and
   approver. Mark fitted values `MODEL_ESTIMATE` and supply validated
   `ConfidencePct`; mark source/rubric values `FIXED_INPUT`. Record explicit
   no-stone evidence rather than filling zeros.
3. **Time model input, separately:** `SemiBOM`, `QuotedMinutes` for one Semi,
   quote version/date and process. Use WO × worker × round actual time/quantity
   to fit Worker Effect and residual Error after Semi factors are governed.

The code path for the final gate is `pipeline/scoring.py::technical_complexity`.
The detailed Excel export is `pipeline/semi_detail_workbook.py`, with its
Semi columns ordered as five factor scores, final score, then supporting
Stone/QC/Rasch and quote/time evidence.
