# Rasch data-use comparison

Run the experiment from the project directory:

```powershell
python -B -m pipeline.rasch_experiments --input-dir input_data --output outputs/rasch_experiments
```

Requires the core environment plus SciPy (tested with SciPy 1.18.0). The experiment creates a new run directory with frozen input files, logs, an English summary, structured results, predictions, split assignments, and fitted model parameters. It does not overwrite the core model or its successful-run pointer.

## Candidates

| Candidate | Eligible training data | Outcome weight | Purpose |
|---|---|---|---|
| legacy_1000 | Single-worker WO-rounds | Inspected pieces | Current estimator benchmark |
| legacy_5000 | Single-worker WO-rounds | Inspected pieces | Isolate the effect of increasing iterations |
| ridge_single_pieces | Single-worker WO-rounds | Inspected pieces | Stable penalized worker/group logistic model |
| ridge_single_capped | Single-worker WO-rounds | Pieces capped at the training 90th percentile | Reduce domination by large batches |
| ridge_single_equal_round | Single-worker WO-rounds | Equal total weight per round | Sensitivity to within-batch dependence and quantity imbalance |
| ridge_expanded_pieces | All valid WO-rounds | Inspected pieces | Explore additional team/unknown-attribution evidence |
| ridge_expanded_equal_round | All valid WO-rounds | Equal total weight per round | Combined coverage and batch-weight sensitivity |
| group_only_all | All valid WO-rounds | Inspected pieces | Group/round benchmark without worker ability claims |

Penalized models minimize binomial negative log likelihood plus a quadratic effect penalty. Group and worker effects use penalties 0.1, 1, or 10; the intercept has a weak proper penalty to keep complete separation finite. Solver convergence requires optimizer success and a maximum gradient per training observation below 1e-5. This estimates regularized conditional effects; it is not marginal-likelihood estimation or posterior uncertainty certification.

Expanded models keep exactly one outcome for each WO-round. A known team's contribution is the equally weighted mean of its workers' logit effects, with a separate team indicator. Unknown-worker observations contribute to group/round effects plus an unknown-attribution indicator, but never to an invented worker identity. These are experimental assumptions, not measured per-worker quantities. Team and unknown cohorts are reported separately from the common single-worker evaluation cohort.

## Validation design

1. Read only the selected `input_data` source. Keep the existing July 2026 QC exclusion. No root-level QC file is automatically substituted.
2. Retain production duplicates/unmapped exclusions and require a valid round for worker attribution. Match on WO, round, Item, and Process. No QC inspector fallback.
3. Use separate first-pass and rework models for each Process.
4. Split each Process by distinct QC-start dates into approximately 60% training, 20% validation, and 20% test periods. Whole-WO spans use earliest start/latest completion across all rounds. WOs crossing a boundary are embargoed.
5. Fit each candidate on training only. Select regularization and nominate the candidate with the lowest piece-weighted log-loss on the same single-worker validation cohort, considering converged fits only.
6. Refit each frozen specification on train plus validation, without embargoed WOs. Score the untouched test once. Report all/single/team/unknown cohorts. Do not retune from test results.
7. Compute paired WO-cluster bootstrap intervals (500 resamples, seed 42) for the nominated candidate's common-test log-loss difference versus the 1,000-iteration legacy estimator. Intervals condition on fitted models and omit model-selection/refitting uncertainty.

At least 10 training rounds, 5 common single-worker validation rounds, and some test observations are required to run a branch. These are permissive diagnostic execution minima, not evidence that a model is well calibrated or that a small test is conclusive. Bootstrap intervals require at least 10 held-out WOs.

## Interpretation

The primary metric is piece-weighted log-loss. The comparison also retains equal-round log-loss, Bernoulli piece Brier score, round pass-rate RMSE, and observed versus predicted pass rates. These metrics use different denominators and must not be treated as interchangeable.

The expanded candidate's extra rows can improve group-level outcome prediction without establishing individual worker skill. Unknown attribution can be systematically associated with new dates, processes, or items. More rows alone do not resolve this confounding. Frozen unseen workers/groups use zero latent effects; this is a fallback prediction, not calibrated cold-start uncertainty.

The experiment does not use Planner scores, BOM, or engineering factors. Retrospective production assignment availability remains a limit for prospective worker assignment. One temporal split, conditional bootstrap intervals, and numerical convergence do not establish measurement invariance, causal ability, future assignment performance, or approval to publish final complexity.

Method references: [Stan's Rasch and identifiability discussion](https://mc-stan.org/docs/stan-users-guide/regression.html) and [SciPy L-BFGS-B convergence controls](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-lbfgsb.html).
