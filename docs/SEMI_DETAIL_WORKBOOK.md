# Semi, Stone, QC and Rasch detail workbook

The workbook command joins the completed SemiBOM report, the completed core
run, the QC tickets in `input_data/04_QC_Tickets/QC data.xlsx`, the Stone
workbook, and `input_data/06_Engineering_Factors/Material Design Process/Material Design Process Score.xlsx`. It preserves
one row per SemiBOM and one row per QC `QualityOrderId`; worker attribution is
listed separately at ticket × production worker grain.

Run from the repository root:

```powershell
python -B -m pipeline.semi_detail_workbook `
  --semi-report 'outputs/semi_item_reports/<run_id>/semi_item_report.csv' `
  --core-run 'outputs/runs/<run_id>'
```

The result is `outputs/semi_detail_workbooks/<run_id>/semi_rasch_stone_detail.xlsx`.
Its first data sheet, `SKU Semi Score`, contains the requested Semi score columns plus two separate confidence columns and a scope status:
SKU / Semi, Process, the five weighted factors, Total Score10,
Contribute/10, % contribute, First Pass Yield Summary, FPY 40% confident,
% confident overall, and Semi scope status.
`Contribute/10` sums available displayed factor estimates without
renormalizing, including provisional QC-model Quality, Material Design Process
and Stone source scores;
`% contribute` is their available weight, not a Rasch confidence percentage.
`Total Score10 = Contribute/10 ÷ % contribute` when at least one factor is
available, so missing factors are skipped and the observed weights are
normalized back to 0–10. It is a **partial, provisional score** whenever
coverage is below 100% or model/factor approval is pending. It remains blank
when no factor is available.
The core scoring gate also requires a validated confidence percentage for
Quality and any other factor marked `MODEL_ESTIMATE`; a model score without
that evidence cannot become the separately approved final Semi score.
The `First Pass Yield (40%)` header follows the requested presentation;
under the confirmed specification its Quality estimate includes modeled
first-pass and rework trajectories within that 40%. Raw observed FPY appears
only in the summary column, never as the 40% factor.
`FPY 40% confident` applies only to the modeled 40% Quality factor; it is
blank when that factor or its matching precision is unavailable. `% confident
overall` is a **completeness-adjusted index**:
`% contribute × min(confidence of each included fitted factor)`. Fixed-only
rows begin at 100% before the missing-weight reduction. An included fitted
factor without its own confidence makes this field blank. Currently Quality
is the only fitted factor with a numeric score. For example, Quality
confidence of 60% plus a Stone source score yields 50% weight coverage and
30% overall confidence, while FPY 40% confident stays 60%. This index is not a calibrated probability that the
partial `Total Score10` is correct. The unchanged Quality precision (the
conditional probability of being within ±1 Quality point) appears in `Factor
provenance` and `Semi difficulty` for audit. A later fitted factor must have
its own confidence before contributing to the index.
Codes beginning with 2GC, 2XI, 2WA, 2DU, 2EP, 2GD, 2GH, 2VS, 2TD, 2XD,
2DG, 2ME,
3, or 9, and Semi/BOM codes ending -01 or -02, remain in the workbook with
`EXCLUDED_SEMI_SCOPE`. Their factor scores, total score and confidence are
blank. The suffix rule reflects likely outsourced items, not verified supplier
classification.
Its run directory also contains `manifest.json` with source hashes and a
`quoted_minutes_input_template.csv` listing all SemiBOMs.

## Add quoted time

The current `input_data/08_Quoted Hours/Quoted Hours.xlsx` is read by default:
`BOM number` joins `SemiBOM`, and `Minutes` already means minutes for one
Semi. Rows with zero/negative minutes or conflicting duplicate quotes remain
in the `Quote source` audit sheet and are not used as positive inputs. The
time calibration and its separate uncertainty are described in
`docs/QUOTED_TIME_MODEL.md`.

Alternatively, use the supplied template or create an XLSX/CSV keyed by `SemiBOM`. Supply
**one** numeric column, either `QuotedMinutes` or `QuotedHours`. The command
converts hours to minutes (`QuotedHours * 60`), rejects duplicate/unknown
SemiBOMs, conflicting units, negative values and nonnumeric values, and
places the result in `QuotedMinutesPerSemi` with `QuoteBasis=PER_SEMI_UNIT`.
Extra descriptive columns from the template are accepted. Pass an alternative
file with `--quoted 'path/to/file.xlsx'` explicitly.

Example:

```csv
SemiBOM,QuotedMinutes
2CM151020024010100Z,15.5
```

Quoted time is a planning input for Work Content. It does not directly change
Rasch difficulty or the approved technical-complexity score. The report does
not subtract the model's minutes per final OK from the quote because those
measures can include different rework and quantity bases.

## Interpretation

| Component | Current method | Statistical `% confident` |
| --- | --- | --- |
| Quality 40% | Rasch-style first-pass and rework models fitted to QC WO rounds | Conditional estimate available for modeled groups |
| Part & Mechanism 25% | Engineering/BOM rubric; approved score pending | Not applicable to a fixed rubric value |
| Material Design Process 20% | Source calculation: 40% Material + 40% Design + 20% Process on 0–10 scales; provisional until approved | Not applicable to a fixed source calculation |
| Stone 10% | Specification-derived source calculation; factor approval pending | Not applicable to a fixed source calculation |
| Learning 5% | Ramp-up time/effort model not yet fitted | Required if this factor is estimated from production trajectories |

Quoted minutes per Semi are a supplied planning input. Worker Effect and the
minute adjustment from difficulty belong to the separate production-time
model; both need their own uncertainty when fitted and must not inherit the
Rasch Quality percentage.

- `StoneSourceScore` is the new workbook's `Final Semi Stone Score`, joined on
  its `BOM item number`. Multiple FG contexts may reference the same Semi;
  the command rejects conflicting scores and retains all original contexts
  on `Stone source`.
- `MaterialDesignSourceScore` joins by Semi BOM Item, Semi Item and Process.
  If the workbook has multiple FG contexts for one Semi, the selected row must
  match the Item Master product type. All rows and selection statuses remain
  in `Material Design source`. This source score can appear in the provisional
  20% column, while `MaterialDesignFactor_Approved` stays blank.
- `TicketSnapshotFPY` uses this QC ticket's first-pass quantities when the
  denominator is positive. Ticket quantities can be cumulative snapshots.
  `RoundFPY` is calculated from the selected core WO first round and is
  repeated on its tickets; do not sum repeated ticket rows as new inspections.
- Production workers come from the `WO + RoundNo` core join. The QC inspector
  is a separate source column. Rasch worker effects are process/branch-level
  diagnostic logits, not individual ticket scores.
- `FinalTechnicalComplexity` stays blank when the core model or
  engineering-factor approval gates are unmet. Blank does not mean zero.
  The displayed provisional `% confident` omits model-selection,
  worker-effect and specification uncertainty. The engineering subfactors
  P1–P3, M1–M3, S1–S3 and L1–L3 still require approved scoring evidence
  before a final score can be released.

The large workbook is written row by row with `openpyxl` because the
preferred Artifact Tool renderer exhausted its Node heap on the full
ticket-level dataset.
