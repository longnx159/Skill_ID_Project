# Rasch optimization assessment — 22 September 2026

**Recommendation:** Use the penalized single-worker, piece-weighted Rasch-style model as the leading candidate for further shadow evaluation. First synchronize production-worker data with QC dates. Keep expanded team/unknown-worker models as sensitivity analyses, and keep rework separate. No production default was changed.

## What was tested

Eight candidate families were evaluated: the current 1,000-iteration estimator, 5,000 iterations, three single-worker ridge weighting schemes, two expanded-data ridge schemes, and a group-only benchmark. Hyperparameters and method nominations used validation only. Whole-WO time boundaries and embargoes were held fixed within each campaign.

Two campaigns were necessary: the current QC source through September 22, and a sensitivity window through September 14, fixed from the last production source date. The second window was not selected by optimizing model outcomes. The windows must not be pooled as independent replications.

## Data coverage is the main constraint

The selected input QC file contains 30,152 source rows. Reconstruction yields 21,708 eligible WO-rounds across 11,222 WOs. The source flags 10 distinct hard-error rounds; none remains in the modeling cohort.

| Branch | Single worker | Team | Unknown worker | Single-worker coverage |
|---|---:|---:|---:|---:|
| First pass | 8,567 | 63 | 2,592 | 76.3% |
| Rework | 1,605 | 13 | 8,868 | 15.3% |

From September 15–22, no QC round in this frozen cohort has a matched production worker. The latest-window common test contains just 31 single-worker first-pass rounds and zero single-worker rework rounds. This prevents a credible contemporary worker-model comparison. The synchronized window supplies 1,675 single-worker first-pass test WOs and 301 rework test rounds (263 WOs); Bright Cut rework has insufficient split evidence.

Missing worker linkage is not evidence that the worker was absent, unskilled, or responsible for failure. Preserve those QC outcomes for group-level reporting; recover authoritative WO + RoundNo + Worker records before attributing individual skill.

## Numerical stability on the synchronized window

| Candidate | Converged process/branch fits |
|---|---:|
| group_only_all | 9/9 |
| legacy_1000 | 3/9 |
| legacy_5000 | 7/9 |
| ridge_expanded_equal_round | 9/9 |
| ridge_expanded_pieces | 9/9 |
| ridge_single_capped | 9/9 |
| ridge_single_equal_round | 9/9 |
| ridge_single_pieces | 9/9 |

Increasing the iteration budget alone does not fix every process. Ridge stabilizes the stated convex penalized objective; convergence does not establish calibration, an unbiased worker effect, or equivalence to a marginal random-effects fit.

## Pooled common-test prediction results

These are exploratory aggregate summaries, not an additional test-based model selection rule. Penalties remain validation-selected. Lower piece-weighted log-loss is better.

| Candidate | First-pass log-loss | Rework log-loss |
|---|---:|---:|
| group_only_all | 0.447836 | 0.613115 |
| legacy_1000 | 0.446862 | 0.658763 |
| legacy_5000 | 0.446867 | 0.658896 |
| ridge_expanded_equal_round | 0.457531 | 0.633522 |
| ridge_expanded_pieces | 0.436689 | 0.641417 |
| ridge_single_capped | 0.439109 | 0.652313 |
| ridge_single_equal_round | 0.458016 | 0.645218 |
| ridge_single_pieces | 0.436704 | 0.652502 |

The single-worker piece-weighted ridge candidate improves pooled first-pass log-loss by 2.27% (0.446862 to 0.436704). Its paired WO-bootstrap loss-difference interval is [-0.021864, -0.000418]. This conditional, exploratory interval does not account for candidate search, selection/refitting uncertainty, or future process drift.

The expanded piece-weighted model is nearly identical on this pooled first-pass measure, so the small extra prediction gain does not establish a benefit from the added team-effect assumption. Process-level improvements often have intervals crossing zero. Rework results are inconsistent: all pooled rework improvement intervals versus the legacy baseline include zero. Group-only predictions cannot certify individual skill even when their aggregate prediction score is lower.

## Recommended implementation order

1. Refresh production worker-hours and validate round-specific linkage through the same endpoint as QC; report linkage by date/process/branch at every run.
2. Use single-worker ridge with piece weighting as a stable diagnostic/shadow candidate, with regularization selected on time-separated validation. Retain legacy estimates for audit and regression comparison.
3. Keep capped quantities as a sensitivity check for large batches; do not change every process to equal-round weighting, which worsened pooled first-pass log-loss in this experiment.
4. Retain unassigned QC in a separate group-only outcome view. Test multi-worker models only with explicit assumptions, never duplicated QC outcomes or fabricated piece allocations.
5. Collect another synchronized temporal holdout and inspect calibration by process and unseen-worker/group status before promoting a method. Worker uncertainty, assignment confounding, and prospective validation remain unresolved.

## Evidence and reproducibility

Latest campaign: `run_20260922T110034_324937Z_9c4bc2b2`. Aligned campaign: `run_20260922T135300_052233Z_05af0aec`.
All source experiment artifact hashes were verified before aggregation. This assessment includes coverage.csv, daily_attribution.csv, convergence.csv, pooled_comparison.csv, paired_intervals.csv and calibration_bins.csv. Rebuild with `python -m pipeline.rasch_assessment --latest <latest-run> --aligned <aligned-run> --output <new-directory>`.

Method references: [Stan Rasch and identifiability](https://mc-stan.org/docs/stan-users-guide/regression.html); [SciPy L-BFGS-B controls](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-lbfgsb.html).
