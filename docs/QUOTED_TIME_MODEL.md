# Joint calibration of quoted minutes and allocated production time

Run from the repository root:

```powershell
python -B -m pipeline.quoted_time_model `
  --quoted 'input_data/08_Quoted Hours/Quoted Hours.xlsx' `
  --legacy 'input_data/00_legacy data/Raw data gốc.xlsx' `
  --bootstrap 80
```

The command resolves the latest completed Semi report and QC experiment.
It checks that the Semi core run and QC experiment used identical Production,
QC and Item Master source hashes. Pass `--semi-report` and `--experiment-run`
to reproduce a specific pair of completed runs.

Each run creates an isolated directory under `outputs/quoted_time_runs` with
`run_summary.md`, `run_summary.json`, source hashes, frozen inputs, audit CSVs,
and `quoted_time_calibration.xlsx`. The run reports in English. A successful
execution remains `DIAGNOSTIC_ONLY` until the source and model gates are
validated.

The quote file already contains **minutes for one Semi**. `BOM number` joins
`SemiBOM`; `BOM item number` remains as a provenance cross-check. Source rows
are retained, including zeros, duplicates, and records outside the current
Semi list. Conflicting or nonpositive quote values are not used as positive
model inputs. A missing quote can still receive a prediction from other
features, but has a visible `QuoteStatus` and the model's missing-quote term.
When the Semi report has an empty or `Unmapped` Process, Item Master fills it
for the same `SemiItem` and `ProcessSource` records that decision. Conflicting
nonempty Process values are excluded and retained in the source audit.

The observed response is `60 × sum(Final allocated hours for one WO-round) /
GoodCW`. First-pass and repair rounds are fitted separately. The primary fit
uses rounds with one identified production worker; team outcomes remain in the
source audit because worker-level piece counts are unavailable. The source
identity `Final = Origin + Idle` was verified. Thus predicted minutes are
**allocated minutes per final OK for a specified round**, including allocated
Idle, not clean touch minutes. `GoodCW` is final output, so rework predictions
are not minutes per repaired/inspected piece.

The legacy workbook contributes **2025 only**. Its separate response is
`60 × Total Actual Hours / Qty Doing`; it has no `Final` allocation or RoundNo.
Rows are matched to unique BOM Semis and audited for missing quotes, process
changes and invalid measures. A regularized fit on eligible 2025 rows learns
quote elasticity, with its own aggregate-time intercept and worker/group
effects. Only that elasticity may enter the current model as a prior on its
Work Content quote slope. Its hours, intercepts, worker effects and unknown
first-pass/rework status are never pooled into the allocated-time response.
The 2026 tuning window chooses the prior weight from zero and positive
candidates; a zero winner leaves legacy as audited reference evidence only.

The model estimates the quote, available technical-difficulty score, residual
Semi-group term and worker effect **together** on log minutes. Global quote
and difficulty slopes have process/branch deviations shrunk toward them;
Semi-group and worker effects are also shrunk. This prevents adding an
unadjusted production average to quote and difficulty a second time. Quoted
minutes enter **Work Content only**. They do not enter the Semi difficulty
score, technical factor scores or Semi `% confident`. The quote coefficient
is an **elasticity** (`quote_effects.csv`), not a fixed blend
percentage. The minute decomposition in the workbook follows one reference
convention:

```text
PredictedMinutes = WorkContentMinutes
                 + TechnicalDifficultyMinutes
                 + WorkerEffectMinutes
ActualMinutes    = PredictedMinutes + ResidualMinutes
```

The components reconcile exactly on the minute scale, but their individual
causal meanings are not fully identified by observational data. The
`TechnicalDifficultyMinutes` term may be negative relative to its reference.
Because the joint fit uses log minutes, this minute increment scales with the
quote-adjusted Work Content baseline; the underlying Semi difficulty score
does not depend on quoted minutes.
Quality is the 80/20 first-pass/rework Rasch-style score fitted from QC before
each training cutoff. Material/Design/Process and Stone are current fixed
engineering source scores. Their available weights (20% and 10%) join the
40% Quality score before a technical-difficulty minute coefficient is fitted.
Part/Mechanism and Learning are not present in this time fit. The separately
approved Semi score and its `% confident` are unchanged by quote data.

WO dates define train, tuning, calibration and untouched test windows. A WO
spanning a boundary is embargoed. The tuning window chooses quote/penalty
settings against a no-quote joint baseline. The calibration window sets the
future-observation prediction interval; the test window measures its actual
coverage. Per-Semi estimate intervals come from WO-cluster bootstrap refits.
`EstimatePrecisionWithin20Pct` describes model-estimate stability, while
`CalibrationWithin20Pct` describes the historical fraction of allocated-time
observations within 20% of a prediction. Neither is the Semi difficulty
confidence percentage. The workbook retains every BOM Semi with a visible
status even where no time estimate is available. Items excluded by the Semi
prefix rule or a Semi/BOM -01/-02 suffix are kept for audit with
`EXCLUDED_SEMI_SCOPE` and are omitted from allocated-time fitting and
prediction. The suffix rule treats these as likely outsourced, not proven.

Quotes, Material/Design/Process and Stone lack effective dates, so temporal evaluation is conditional
on the **current** engineering snapshots. Before operational use, add their
effective dates, confirm the meaning of `Final`/`Idle`, resolve source-join
exceptions, and repeat evaluation on new periods. First-pass and rework
predictions are separate conditions and cannot be summed without a model for
how often rework occurs.
