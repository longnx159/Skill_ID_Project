# Rasch assessment after the production refresh

22 September 2026. Status: **DIAGNOSTIC ONLY**.

The refreshed production workbook now has a maximum RAF date of 22 September. All eight Rasch alternatives were rerun from frozen `input_data` sources. Keep the single-worker, piece-weighted ridge method as the leading shadow-evaluation candidate. Its numerical convergence and held-out prediction improved relative to the legacy estimator, but rework attribution remains sparse and the refreshed export also removed previously available worker links.

## Source coverage and linkage

The new export contains 78,785 worker records and 75,767 work-order records. The eligible QC cohort still contains 21,708 WO-rounds. Its WO-round keys, pass/inspected quantities, QC dates, item identifiers, and processes match the earlier full-window campaign exactly. Raw workbook hashes changed for Production, QC Tickets, and Engineering Factors; engineering factors are not used by these experiments.

| Branch | Single worker | Team | Unknown worker | Single-worker coverage |
|---|---:|---:|---:|---:|
| First pass | 9,936 | 73 | 1,213 | 88.54% |
| Rework | 1,885 | 15 | 8,586 | 17.98% |

The refresh resolves 1,795 previously unknown round assignments: 1,783 single-worker and 12 team assignments. However, 134 formerly single-worker rounds now have unknown attribution. Of those, 133 lack the corresponding WO-round-worker record in the refreshed worker export; 132 lack an item/date match in the refreshed work-order data. These counts overlap. The remaining case requires further attribution-filter investigation; no worker was guessed or restored from an older export.

For QC completed during September 15–22, 1,127 rounds now have one worker and four have a known team, compared with no linked rounds in the earlier snapshot. Another 2,705 of those 3,836 recent QC rounds remain unassigned. A matching maximum production date does not establish complete worker-round coverage.

**High-priority data issue:** reconcile removed historical records and the missing rework assignments against the authoritative export. Do not interpret missing linkage as worker absence or poor skill. `lost_link_audit.csv` contains the local reconciliation keys; aggregate evidence is in `coverage.csv`, `daily_attribution.csv`, and `attribution_transitions.csv`.

## Numerical stability

| Candidate | Converged process/branch fits |
|---|---:|
| Legacy, 1,000 iterations | 4/10 |
| Legacy, 5,000 iterations | 6/10 |
| Each of the five ridge variants | 10/10 |
| Group-only benchmark | 10/10 |

Increasing iterations alone still fails to resolve every branch. Numerical convergence does not establish worker-effect calibration or production eligibility.

## Common single-worker held-out results

First-pass comparisons use the same 1,281 WO-rounds and 19,257 inspected pieces across all eight alternatives. Rework comparisons use 211 rounds, 177 WOs, and 2,847 pieces. Lower piece-weighted log-loss is better.

| Variant | First-pass log-loss | Rework log-loss |
|---|---:|---:|
| legacy_1000 | 0.565694 | 0.636022 |
| legacy_5000 | 0.565694 | 0.636168 |
| ridge_single_pieces | 0.523850 | 0.605611 |
| ridge_single_capped | 0.536823 | 0.605252 |
| ridge_single_equal_round | 0.567856 | 0.592981 |
| ridge_expanded_pieces | 0.523566 | 0.601051 |
| ridge_expanded_equal_round | 0.561935 | 0.590681 |
| group_only_all | 0.540213 | 0.601283 |

The prespecified single-worker, piece-weighted ridge candidate reduces pooled first-pass log-loss by **7.40%** versus legacy_1000. Its paired WO-bootstrap loss-difference interval is **[-0.082073, -0.013303]**. Expanded piece weighting gives a very similar score and still relies on an assumed team effect.

Several pooled rework intervals now exclude zero, including single-worker piece weighting at [-0.062962, -0.000536]. This is stronger exploratory evidence than the previous campaign, but is based on sparse linked rework data: Bright Cut and Soldering each have only two single-worker test rounds, and Stone Setting has six. Do not promote a universal rework method from these aggregates.

Penalties and process/branch nominations used validation only. The pooled table is descriptive and was not used to retune parameters. Intervals use 500 whole-WO resamples with seed 42, conditional on fitted models; they do not correct for candidate search, refitting uncertainty, or future drift. The reused temporal window is not an independent prospective replication. The old 2.27% and new 7.40% improvements have different evaluation populations and must not be read as a direct improvement caused solely by refreshing production.

## Actions

1. Reconcile historical export deletions and missing rework worker-round records before expanding individual skill interpretation.
2. Continue single-worker piece-weighted ridge in shadow evaluation; retain capped exposure as a batch-size sensitivity check.
3. Keep team and unknown-worker outcomes available for aggregate reporting, with no fabricated per-worker allocation.
4. Validate calibration and unseen-worker/group behavior on a new synchronized prospective window before promotion. Keep first-pass and rework separate.

## Reproducibility and verification

New campaign: `run_20260922T141612_236215Z_1f94bd79`.
Previous full-window campaign: `run_20260922T110034_324937Z_9c4bc2b2`.

All 90 new campaign artifact hashes and every frozen source hash were verified. The previous campaign artifact hashes were also checked before aggregation. The new campaign includes its English `run_summary.md`, machine-readable summary, split assignments, predictions, tuning results, fitted model metadata, and source snapshots. Core model defaults and the core successful-run pointer were not changed.

Rebuild the source audit from the repository root with `python -B deliverables/rasch_refresh_20260922/audit_refresh.py`, then aggregate verified predictions with `python -B -m deliverables.rasch_refresh_20260922.summarize_results`. This dated narrative is reviewed separately from those computed evidence files.

The inline sources view was reduced from 443,237 bytes to a small HTML fragment without JavaScript dependencies. Its disclosure interactions were verified in a sandboxed browser preview. The original MCP timeout does not establish its precise cause; a host-side RPC failure could still recur independently of the fragment.
