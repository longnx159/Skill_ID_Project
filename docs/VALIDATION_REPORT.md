# Implementation validation — v0.5.3-pilot.1

**Assessment: usable for data collection and diagnostic runs; production decisions remain blocked.**

The controlling document is `docs/Skill_ID_Project_Specification_v0.5.3.md`. The v0.5.2 document is older. The external presentation, current-production, QC, BOM and touch-event files cited by the specification were not supplied in this project.

The runtime input contract is now folder-only: `input_data/01_Production` through `input_data/07_Pilot_Log`. The public `pipeline.main` module and `run_pipeline.ps1` commands do not accept a multi-sheet workbook or separate legacy source arguments. The old multi-sheet workbook remains only as a column reference.

## Source checks

The supplied historical workbook contains 107,250 production rows, 455 workers, 3,712 Items and 2,244 Size Adjusted groups across five Processes. Dates range from May 2025 through July 2026. The Planner workbook contains 580 Worker–Process records. No conflicting Item/group mappings, cross-Process groups, duplicate production keys or duplicate Planner keys were found in these supplied files.

The core pipeline retains 106,606 production rows after filtering invalid/nonpositive hours or quantities, invalid identities/dates, and Training records. Source files are unchanged. July production remains included. Each folder-based run writes its source hashes and runtime/code versions to `run_manifest.json` in the selected output folder (for example, `outputs/<run>/run_manifest.json`).

## Material changes

- Removed automatic latest-month exclusion and preserved official Planner scores without min-max rescaling or duplicate averaging.
- Replaced random row evaluation with chronological real-WO evaluation and an embargo for trajectories spanning the cutoff. DUMMY references remain diagnostics but do not establish real-WO validation.
- Replaced unstable empirical variance updates with a Gaussian random-intercept EM diagnostic. Its marginal likelihood is independently checked against dense covariance calculations.
- Pooled by the supplied Size Adjusted mapping while preserving original Item IDs. Network diagnostics precede model fitting. Weak components and nonconvergence remain visible.
- Corrected time labels and units. Historical aggregate effort cannot claim clean first-pass touch time or calibrated quality difficulty.
- Added canonical QC reconstruction, July exclusion, quantity/round controls, observed recovery, open-WO sensitivity, missing Scrap status, and actual touch-event classification.
- Added strict factor completeness/evidence/approval checks. Final complexity and automated matching remain unpublished.
- Added the fillable template, Python runner, optional QC candidate comparison and reproducibility outputs.

## Verification

**16 automated tests pass.** Tests cover fractional quantities, latest-month retention, key/mapping checks, raw Planner skill preservation, first-pass denominators, July whole-WO exclusion, duplicate/invalid QC, future recovery exclusion, recovery edge cases, open-WO sensitivity, touch-time/idle-time separation, Process guards, SelfRework versus AssistedRescue, chronological embargo, disconnected networks, missing factors, training-only skill scaling, unseen/frozen effects, future-skill exclusion, and a filled-template end-to-end run. A dense-covariance spot check independently verifies the time-model likelihood.

The input template was opened, structurally inspected and rendered. Its instruction page was visually checked. Test input records are synthetic and isolated under `tests/_artifacts`; the delivered blank template contains no example production records.

The full historical core run completes across all five Processes. Its holdout uses training through April 2026 and evaluation from May 2026 onward. Current aggregate-time holdout WAPE is approximately 52–67% across Processes, so these time estimates should remain diagnostic. The full-history Stone Setting fit reaches the configured iteration limit; this is flagged in `Do kho SKU`, rather than described as a validated estimate. Its separately fitted holdout model converged.

## Unverified / remaining gates

- PyMC samplers were not executed: real QC inputs and the optional Bayesian dependencies are absent. Candidate equations and pure-Python leakage controls are implemented, but posterior convergence, priors, calibration, empirical coverage and predictive performance remain unverified.
- The core run uses raw FPY fallback when QC is provided; it does not promote optional candidate outputs into calibrated Rasch difficulty.
- No approved recovery maturity/closure policy, usability thresholds, quality-weight calibration, size residual tolerance, or assignment-confounding review was supplied.
- Clean-time model fitting, attributed rescue-success rates, a complete probability-based matching/ranking engine, certification/capacity integration, and prospective pilot power/ITT analysis are not implemented in this release.
- Effective dates can be collected and are enforced by the candidate model, but multiple historical Planner versions and a full approval workflow are not implemented.
- Engineering factor inputs may produce an approved weighted-sum diagnostic. They cannot bypass the unvalidated Quality factor and other production gates to publish Final Technical Complexity.

These are explicit limits of the release, not evidence that the full specification has received production approval. See README for the requirements coverage and future commands.
