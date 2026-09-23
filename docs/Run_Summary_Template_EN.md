# Skill ID Run Summary

> Template only. Replace bracketed fields from the current run's structured summary. This file does not itself enable automatic report generation.

**Run ID:** [run_id]  
**Execution status:** [SUCCEEDED / SUCCEEDED_WITH_WARNINGS / FAILED / INTERRUPTED]  
**Decision status:** [DIAGNOSTIC_ONLY / BLOCKED / APPROVED with approval reference]  
**Started / finished:** [timestamps and timezone]  
**Duration:** [elapsed time]  
**Data cutoff:** [cutoff and timezone]  
**Production exclusions / QC policy:** [effective rules]  
**Previous comparable run:** [run_id / NO_BASELINE / NOT_DIRECTLY_COMPARABLE]

## Executive summary

[Execution outcome and the most material change.] [Data/model limitation affecting use.] [Highest-priority next action.] A successful execution does not by itself authorize worker certification, final complexity publication, or automated assignment.

## Execution by stage

| Stage | Status | Duration | Warning or failure reason |
|---|---|---|---|
| Input loading and validation | [status] | [duration] | [reason or none] |
| QC reconstruction | [status] | [duration] | [reason or none] |
| Aggregate time models | [status] | [duration] | [reason or none] |
| First-pass quality models | [status] | [duration] | [reason or none] |
| Rework quality models | [status] | [duration] | [reason or none] |
| Optional BOM / Stone stage | [status] | [duration] | [reason or none] |
| Artifact validation and export | [status] | [duration] | [reason or none] |

## Data reconciliation

| Measure | Current run | Previous comparable run | Change | Grain / denominator |
|---|---:|---:|---:|---|
| Input production rows | [N] | [N] | [delta] | Loaded production rows |
| Removed by basic filters | [N] | [N] | [delta] | Mutually exclusive removal accounting |
| Quarantined after basic filters | [N] | [N] | [delta] | Unique source records, regardless of reason count |
| Final retained production rows | [N] | [N] | [delta] | WO + RoundNo + Worker + Item + period |
| Eligible QC rounds | [N] | [N] | [delta] | Unique WO + RoundNo |
| Single-worker QC attribution | [n/N; %] | [%] | [pp] | Eligible rounds in the stated branch |
| BOM Item Master coverage, if run | [n/N; %] | [%] | [pp] | Usable unique SemiBOMs |

Reconciliation: [input = retained + mutually exclusive removals].  
Exceptions: [reason counts, overlapping reason flags identified, links to detail].  
Missing optional inputs: [datasets and affected outputs].

## Model health and validation

Repeat rows for every process and model branch. Use `NOT_AVAILABLE` for unsaved or unavailable evidence.

| Process | Branch | Fit status | Evidence N | Iterations / final delta | Validation metric and unit | Calibration status | Decision eligibility |
|---|---|---|---:|---|---|---|---|
| [process] | [Time / First pass / Rework] | [status] | [N and grain] | [values] | [metric] | [status] | [status and reason] |

Evaluation window: [training / holdout / embargo].  
Unseen workers/groups and network limitations: [counts and interpretation].  
Planner policy: [snapshot date, retrospective baseline or as-of history].  
Metric definitions: WAPE = sum absolute prediction errors / sum actual values on the stated cohort. Current time-model RMSE/MAE use log time. FPY = total first-round passed pieces / total first-round inspected pieces.  
Approved thresholds: [policy reference or NOT_DEFINED].

## Changes and required actions

| Severity | Finding | Evidence | Recommended action | Suggested responsible function |
|---|---|---|---|---|
| [level] | [finding] | [artifact/metric] | [action] | [function, unassigned unless confirmed] |

New / resolved issues: [changes from comparable run].  
Production gates still open: [actual current gates].  
Comparison limitations: [changed inputs, definitions, cohort, model, or no baseline].

## Artifacts and reproducibility

- Manifest: [exact path]
- Detailed tables / workbook: [exact finalized paths and availability]
- Persistent log: [path]
- Input snapshot / source hashes: [reference]
- Code and configuration hashes: [values]
- Runtime versions: [versions]
- Exit code: [value]

For failed runs: [failed stage, concise error, completed stages, partial artifact locations, and safe rerun instruction]. Values not computed because of failure must remain `NOT_AVAILABLE`; never replace them with zero or carry forward values from an earlier run.
