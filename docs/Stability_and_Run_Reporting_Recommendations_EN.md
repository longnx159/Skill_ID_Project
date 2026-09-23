# Skill ID: Stability and Run Reporting Recommendations

Review date: 19 September 2026  
Scope: Current implementation plans, pipeline source, saved core outputs, and the September 16 BOM distribution update.  
Deliverable status: Recommendations and reporting specification; automatic reporting has not been implemented by this review.

Implementation follow-up: the core operational/reporting changes are now implemented in `0.5.3-pilot.2`. See [RUN_OPERATIONS.md](RUN_OPERATIONS.md) for commands, output semantics, verification, and the statistical/optional-workflow recommendations that remain open. The assessment below is the original pre-implementation review.

## Executive recommendation

Prioritize trustworthy run packaging, consistent configuration, and explicit model eligibility before further model expansion. The pipeline already preserves round-level attribution, separates rework, exports source/code hashes, and retains production approval gates. Its principal operational weakness is that a completed command does not yet produce one complete, unambiguous, human-readable run record.

Every execution should produce an English summary covering execution status, data reconciliation, model health, changes from a comparable previous run, and required actions. Execution success and permission to use model results for production decisions must be separate fields.

## Verified current position

These are observations from existing artifacts, not results of a new full production run.

| Evidence | Verified observation | Implication |
|---|---|---|
| Current automated tests | `python -B -m unittest discover -s tests -q`: 24 tests passed; unclosed Excel-file ResourceWarnings appeared | Core regression checks pass, but file lifecycle handling needs attention |
| `outputs/latest/run_manifest.json` | 23,265 retained production rows; data cutoff 2026-09-14 09:41:57; diagnostic-only status | Use the saved manifest rather than the implementation plan's older 21,933-row figure |
| Saved data-quality table | 24,892 input rows; 23,721 after basic filters; 24 duplicate rows and 432 unmapped rows quarantined | In this saved run, 23,721 - 24 - 432 = 23,265; future summaries must account for overlapping exception reasons |
| Saved QC outputs | 17,330 rounds; 9,043 first-round records; 357 rework groups | Count each table at its own grain; worker-link rows are not independent QC rounds |
| Saved time models | All five process fits have `converged=true` | The implementation plan's Stone Setting nonconvergence statement is outdated for this artifact set |
| Saved rework groups | Sanding has `Rasch_Converged=false`; the other four processes have true flags | Rework model health must be reported separately from time and first-pass model health |
| Core output directory | Canonical SKU CSV/workbook and `_new` versions coexist with different modification times | A consumer can read an older file while believing it belongs to the current manifest |
| Source comparison | All code files listed in the saved core manifest match their current hashes | This checks listed code only; it does not verify unchanged inputs, unlisted scripts, or output integrity |
| September 16 BOM distribution manifest | 7,939 unique SemiBOMs; 7,789 usable; 150 excluded; 6,297 matched to Item Master (80.84%) | Report BOM validity and mapping coverage independently; 1,492 usable SemiBOMs remain unmapped |

The saved time holdout WAPE values are approximately 51.5% for Bright Cut, 61.7% for Polishing, 72.0% for Sanding, 49.3% for Soldering, and 76.7% for Stone Setting. These describe the saved evaluation cohorts. No approved acceptance threshold was identified, so convergence alone must not imply acceptable predictive performance. RMSE and MAE in the current validation implementation are calculated on log time; WAPE is a ratio calculated from minutes.

## Prioritized changes

| Priority | Finding and evidence | Recommendation | Acceptance criterion |
|---|---|---|---|
| P0 | `write_outputs()` writes directly into a reusable folder and falls back to `_new` names when files are locked | Create a unique run directory, write artifacts into staging, validate them, then publish a completion manifest. Update a small `latest_successful` pointer only after successful finalization. Record exact paths, sizes, and hashes | A locked workbook or interrupted export cannot mix two runs or change the pointer to an incomplete run |
| P0 | `Config.incomplete_month` defaults to July 2026, while the CLI explicitly defaults to no production-month exclusion; QC also has separate hard-coded July rules | Establish one explicit configuration contract for production exclusion, QC timestamp policy, cutoff, and timezone. Pass it consistently through CLI, wrapper, and Python API; print effective settings in the report | Equivalent settings produce identical eligible cohorts through each entry point; later rounds remain eligible under the approved July QC policy |
| P0 | First-pass Rasch convergence is selected but omitted from the final merge; any non-null score receives a “calibrated” label | Export branch-specific diagnostics and use separate `fit_status`, `calibration_status`, and `decision_eligibility` fields. Retain raw estimates for audit, but exclude failed/unvalidated estimates from decision-facing scores | A deliberately nonconverged fit cannot be labelled calibrated or production eligible; first-pass and rework flags cannot be confused |
| P0 | The manifest is written at the end; the CLI handles only selected input errors | Create run identity and an initial status before ingestion. Persist stage timings, warnings, exception category, and exit code. Finalize a failure summary when a recoverable exception occurs; mark stale unfinished runs as interrupted on a later check | Missing input, corrupt workbook, fitting exception, and export failure each leave an intelligible run record and nonzero failure exit code. If the output location is unwritable, report that failure to stderr |
| P1 | `pd.ExcelFile(path)` is created without an explicit close; tests emit ResourceWarnings | Use context managers for workbook readers and reuse the open reader for sheet reads | Repeated ingestion releases handles; source files can be moved or reopened after reading; file-handle warnings are investigated and resolved |
| P1 | Multiple input files are concatenated; some MES merges lack explicit cardinality checks; missing RoundNo defaults to 1 | Preflight schemas, unique master keys, identifiers, dates, units, and round availability. Record join cardinality and unmatched counts. Make legacy round assumptions explicit and exclude uncertain round attribution from worker QC estimates | Duplicate master keys cannot multiply production rows; ambiguous rounds remain visible and never become silently certified first-pass records |
| P1 | Source hashes are calculated after processing; rediscovery can include files changed during a run | Freeze the input file list at startup and read immutable snapshots, or verify hashes before and after reading and reject changes | The manifest identifies the exact bytes consumed; a changed input cannot silently produce a valid run |
| P1 | Rasch variance updates use mean squared effects without posterior variance; convergence uses parameter change alone | Review the estimator against a validated reference on controlled fixtures. Record objective behavior, final delta, iteration count, boundary variance, evidence size, and network coverage. Diagnose weak identification before increasing iterations | Numerical convergence, estimator agreement, uncertainty, and holdout calibration have distinct evidence; nonconvergence never disappears through relabelling |
| P1 | Requirements contain open-ended lower bounds; `.xls` is accepted but an appropriate reader dependency is not declared in core requirements | Maintain a tested environment lock and preflight supported formats/readers. Record dependency versions and configuration hash | A clean environment can reproduce the documented test/run workflow; unsupported formats fail before model fitting |
| P1 | The 2026-08-03 Planner snapshot is deliberately applied retrospectively | Preserve the agreed baseline policy, but label it explicitly and separate retrospective baseline diagnostics from evaluation using information available at the historical decision date | Reports disclose snapshot date and interpretation; retrospective baseline results are not presented as historically available skill evidence |
| P2 | BOM summaries and Stone scoring use separate execution paths; the Stone script contains fixed local paths | Introduce a shared run manifest/report contract and parameterized paths for optional stages, with independent stage status. Version BOM definitions, scoring rules, and input lineage | Missing optional inputs produce `NOT_RUN` with reasons; BOM/Stone diagnostic results cannot silently become approved final complexity |
| P2 | Plans and validation notes contain superseded counts and status statements | Keep one maintained implementation status document and link numerical claims to immutable run IDs. Generate run facts directly from finalized artifacts | Each quoted count, fit status, and metric can be traced to a specific run |

P0 means resolve before relying on unattended recurring runs. P1 strengthens repeatability and model interpretation. P2 improves maintainability and integration. These priorities are recommendations, not existing acceptance policy.

## Reporting contract for every execution

Generate `run_summary.md` in English and `run_summary.json` for machine consumption. Add an English `Run Summary` sheet to the result workbook when workbook export succeeds. Retain detailed CSVs and a persistent `run.log`. Build all summaries from the same structured summary object to prevent conflicting numbers.

Suggested execution statuses are `SUCCEEDED`, `SUCCEEDED_WITH_WARNINGS`, `FAILED`, and `INTERRUPTED`. Stage statuses additionally include `NOT_RUN`. Keep decision status separate: `DIAGNOSTIC_ONLY`, `BLOCKED`, or `APPROVED` only when actual approval evidence exists. A successful diagnostic run may still have blocked production use.

Required content:

1. **Run identity:** unique ID, start/end time with timezone, duration, code/configuration hashes, runtime versions, cutoff, exclusions, and exact source snapshot identities.
2. **Execution:** stage outcome and duration for ingestion, validation, QC reconstruction, time fitting, first-pass fitting, rework fitting, optional BOM/Stone work, and export. Identify the failed stage and retained partial artifacts.
3. **Data reconciliation:** input, retained, excluded, and quarantined populations with explicit grain and non-overlapping reconciliation totals. Report reason flags separately when they overlap. Include mapping coverage and estimated worker quantity coverage.
4. **QC integrity:** unique WOs and WO-rounds, first-pass and later-round populations, single-worker attribution coverage, ambiguous attribution, quantity mismatches, open trajectories, and missing scrap information. Aggregate FPY as total passed pieces divided by total inspected pieces, not the unweighted mean of row percentages.
5. **Model health by process and branch:** fit status, convergence diagnostics, evidence count, network weakness, train/test windows, embargo counts, unseen entities, metrics with units, calibration evidence, and decision eligibility. Missing diagnostics must say `NOT_AVAILABLE`.
6. **BOM coverage when run:** unique and usable SemiBOMs, excluded structural issues, Item Master match rate, multi-context consistency, direct mechanical part counts, and expanded material composition. Preserve the distinction between direct assembly parts and components found through child BOMs. Zero, unknown, and invalid BOM are different states.
7. **Comparison:** previous comparable successful run ID, cohort/configuration changes, row-count differences, mapping coverage changes, metric changes, and new/resolved issues. For changed cohorts or methods, label results `NOT_DIRECTLY_COMPARABLE`. Use percentage points for rate differences. The first run has `NO_BASELINE`.
8. **Actions and artifacts:** severity, evidence, recommended action, suggested responsible function, decision blocked, and exact output links. Do not invent assigned owners, deadlines, or approvals.

Do not populate report counts from placeholder “Unavailable” rows. Null is not zero. Quality scores copied from a Size Adjusted group onto multiple SKUs do not represent additional independent QC evidence.

## Proposed implementation sequence

1. Implement run lifecycle, immutable output packaging, consistent configuration, and branch-specific eligibility fields.
2. Build a shared structured summary and English renderer; integrate finalization into both successful and failed execution paths.
3. Add input snapshots, workbook lifecycle fixes, dependency locking, and comparable-run selection.
4. Extend the reporting contract to BOM/Stone stages and address estimator validation separately.

Verify with focused failure scenarios: locked output, duplicate run target, corrupt input, source mutation, duplicate master key, missing optional folders, missing RoundNo, nonconverged fit, failed export, and interruption recovery. On a fixed input snapshot, repeat runs should agree on cohorts and metrics within documented numerical tolerance; IDs and timestamps should differ. These scenarios are proposed acceptance tests, not checks completed in this review.

## Evidence and review limits

Reviewed: root and `docs/IMPLEMENTATION_PLAN.md`, README, `docs/VALIDATION_REPORT.md`, pipeline configuration/entry/export/attribution/model code, current tests, selected `outputs/latest` manifests and CSVs, and `outputs/semi_distribution_20260916_run5` brief and distribution manifest. The Stone generator was inspected only for integration/portability context, not fully audited.

The 24-test suite was rerun successfully. Existing production models and BOM data were not refitted; workbook rendering was not tested. File timestamps establish observed coexistence, not a complete transaction history. Historical output figures above should not be interpreted as a newly verified source-data population.
