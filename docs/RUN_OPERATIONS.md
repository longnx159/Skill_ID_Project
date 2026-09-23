# Skill ID run operations — 0.5.3-pilot.2

## Run and read the report

From the project directory:

```powershell
.\run_pipeline.ps1 -InputDir input_data
```

Equivalent Python command:

```powershell
python -B -m pipeline.main --input-dir input_data --output outputs/runs
```

The command prints the exact English report path. `--output` now means a root directory, not a reusable result directory. Each run writes into a unique child. The Python API returns that child as `result["output_dir"]`.

```text
outputs/runs/
  latest_successful.json
  run_<timestamp>_<suffix>/
    run_summary.md
    run_summary.json
    run_manifest.json
    run.log
    inputs/                  # frozen source copies
    artifacts/               # successful data export
      Skill_ID_Ket_qua_chay_thu.xlsx
      time_models.json
      <result tables>.csv
```

During export the folder is named `artifacts.partial`. A failed run may retain partial files, or exported files if report finalization failed. The completion manifest and exit code determine success, not the presence of an Excel file. The `latest_successful.json` pointer is written atomically only after finalization succeeds. Prior output folders and open workbooks are not overwritten.

## Input and model policy

- CLI, PowerShell, and Python API retain all production months by default. `--exclude-month=2026-07` explicitly excludes that production month.
- QC separately excludes source month July 2026 by default. The source timestamp is `CreatedDateTime` when supplied, otherwise canonical `QC_Start`. `--qc-exclude-month=` disables this exclusion. Later rows for the same WO remain subject to the existing round-reconciliation rules.
- Source times are interpreted as local Asia/Saigon time. Explicit timezone-aware cutoff values are converted to local time before comparison. A date-only cutoff means midnight, not end of day.
- Inputs are discovered once and copied to the run directory. Original and copied bytes are checked during copying. Subsequent source edits do not change a run's snapshot. Snapshots consume disk space; retention is a separate operational decision.
- Conflicting master keys fail validation. Unmatched MES WO joins are retained in `Input join exceptions`, then excluded by ordinary eligibility filters. Raw row counts can therefore exceed older runs that silently discarded these rows in an inner join.
- Unknown/invalid production rounds remain unknown and cannot supply worker-level QC attribution. Neither an unmatched first-round worker nor a multiple-worker round falls back to a QC inspector or the whole-WO primary worker.
- Missing hours and dates are not fabricated. MES worker hours require `Final` or `Origin`.
- First-pass and rework convergence fields are named separately. Both branches explicitly report calibration as `NOT_VALIDATED` and decision eligibility as `BLOCKED`. Numerical estimates remain diagnostic; final complexity and quality approval gates remain in place.

## Summary and comparisons

Every started run writes a JSON status checkpoint. Recoverable failures write an English report with the failed stage and error. Unwritable output storage or invalid CLI/configuration arguments can prevent report creation; the command reports these errors on stderr.

Successful runs add a `Run Summary` sheet based on the same summary object used for Markdown/JSON. Workbook table row counts and artifact hashes are checked/recorded during finalization. These are structural checks, not Excel Desktop rendering validation.

The summary includes unique production quarantine totals, QC attribution and FPY, model health by process/branch, validation metrics, network status counts, and remaining go-live gates. Absent optional inputs are unavailable rather than fabricated zeros. Run timestamps use UTC offsets; source timezone is recorded separately. Duration measures start through data export and explicitly excludes report/workbook-summary finalization.

The immediately preceding successful run in the same root is the baseline. Exact source hashes, code hashes, effective settings, and runtime versions must agree for direct numerical comparison. Changed cohorts or methods are marked `NOT_DIRECTLY_COMPARABLE`, with reasons. Comparable runs report row, FPY percentage-point, WAPE ratio, and warning differences. This intentionally conservative policy does not claim a valid trend from changing input populations.

## Failure and interruption recovery

The process returns zero for a completed diagnostic run, including completion with warnings; failed execution returns nonzero. The PowerShell wrapper propagates failure. `Ctrl+C` is recorded as `INTERRUPTED` with exit code 130 when Python can handle the interruption.

After a hard termination, finalize abandoned records with:

```powershell
python -B -m pipeline.main --output outputs/runs --recover-interrupted
```

Recovery checks the recorded local host and process ID. Active processes and records from another host are left unchanged. A reused live PID is conservatively treated as active. Recovery does not resume partial computation or update the successful-run pointer. Rerun the original command to create a fresh run.

## Verification and remaining scope

The regression suite covers successful repeated runs and manifest integrity, missing/corrupt input, source mutation, workbook/export failure, model failure, report-finalization failure, interruption recovery, conflicting WO master keys, consistent defaults, unknown round attribution, exclusion policy, and nonconverged score labels.

Verification on 19 September 2026: **39 tests passed**. The production-data run `run_20260919T014243_896177Z_b157c09a` completed with warnings, retained 23,265 production rows, and reconstructed 17,330 QC rounds. All 33 manifested output artifacts passed a subsequent SHA-256 check. Its report is under `outputs/runs/<run_id>/run_summary.md`. All five first-pass Rasch fits and the Sanding rework fit remained nonconverged and blocked for decision use. All five aggregate time fits converged. These statuses describe that run, not a claim of model certification.

```powershell
python -B -m unittest discover -s tests -q
```

The environment lock records the versions used for verification; a new clean installation has not been independently tested. Core dependency versions and code hashes are recorded per run. The runner rejects code changes detected during execution.

This implementation delivers the operational/reporting changes. Estimator replacement, posterior-variance correction, holdout calibration, uncertainty certification, approved performance thresholds, and engineering/business approval remain separate statistical and operational work. Increasing an iteration limit is not used as a substitute for those checks.

BOM feature extraction, Semi distribution reporting, Stone scoring, and optional Bayesian candidates retain their separate entry points. The core summary marks BOM/Stone as `NOT_RUN`; it does not import historical outputs or imply those workflows were executed. The untracked Stone/Semi scripts were not rewritten by this change. Integrating their scoring rules and approvals into the shared runner remains future work.
