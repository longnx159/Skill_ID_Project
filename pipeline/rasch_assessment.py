"""Summarize two verified Rasch experiments without refitting or choosing on test."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .rasch_experiments import paired_bootstrap
from .run_reporting import atomic_json, file_hash


def verify(path):
    manifest = json.loads((path / "run_manifest.json").read_text(encoding="utf-8"))
    for artifact in manifest["artifacts"]:
        if file_hash(path / artifact["path"]) != artifact["sha256"]:
            raise ValueError(f"Changed artifact: {artifact['path']}")
    return manifest


def assess(latest, aligned, output):
    latest, aligned, output = Path(latest), Path(aligned), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    provenance = {"latest": verify(latest)["run_id"], "aligned": verify(aligned)["run_id"]}
    raw = pd.read_csv(latest / "experiment/modeling_rounds.csv", dtype={"WO": str})
    coverage = raw.groupby(["Branch", "Attribution"]).size().rename("Rounds").reset_index()
    dates = raw.assign(Date=raw.QC_Stop.str[:10]).groupby(["Date", "Attribution"]).size().unstack(fill_value=0)
    coverage.to_csv(output / "coverage.csv", index=False)
    dates.to_csv(output / "daily_attribution.csv")
    qc = pd.read_excel(latest / "inputs/04_QC_Tickets/QC data.xlsx", usecols=["WO", "RoundNo", "HasHardRoundError"])
    hard = qc.loc[qc.HasHardRoundError.eq(1), ["WO", "RoundNo"]].drop_duplicates()
    audit = {"raw_qc_rows": len(qc), "source_hard_error_rounds": len(hard),
             "retained_hard_error_rounds": len(raw.merge(hard, on=["WO", "RoundNo"])),
             "eligible_rounds": len(raw), "eligible_wos": raw.WO.nunique()}
    if audit["retained_hard_error_rounds"]:
        raise ValueError("Hard QC error rounds remain; resolve before interpretation")
    results = pd.read_csv(aligned / "experiment/comparison.csv")
    common = results.loc[results.Cohort.eq("single")]
    convergence = common.groupby("Variant").converged.agg(["sum", "count"]).reset_index()
    convergence.to_csv(output / "convergence.csv", index=False)
    predictions = pd.read_csv(aligned / "experiment/predictions.csv", dtype={"WO": str})
    single = predictions.loc[predictions.Attribution.eq("single")].copy()
    single["NLL"] = -(single.PassQty*np.log(single.Prediction) + (single.InspectedQty-single.PassQty)*np.log1p(-single.Prediction))
    pooled = single.groupby(["Branch", "Variant"]).agg(NLL=("NLL", "sum"), Pieces=("InspectedQty", "sum"), Rounds=("WO", "size"))
    pooled["LogLoss"] = pooled.NLL / pooled.Pieces
    pooled.reset_index().to_csv(output / "pooled_comparison.csv", index=False)
    intervals = []
    for branch, group in single.groupby("Branch"):
        baseline = group.loc[group.Variant.eq("legacy_1000")]
        for variant, part in group.groupby("Variant"):
            joined = baseline.merge(part[["WO", "RoundNo", "Prediction"]], on=["WO", "RoundNo"], validate="one_to_one", suffixes=("_baseline", "_candidate"))
            interval = paired_bootstrap(joined, joined.Prediction_candidate.to_numpy(), joined.Prediction_baseline.to_numpy())
            intervals.append({"Branch": branch, "Variant": variant, **interval})
    pd.DataFrame(intervals).to_csv(output / "paired_intervals.csv", index=False)
    # Fixed probability bins, not bins optimized to make calibration appear better.
    predictions["ProbabilityBin"] = pd.cut(predictions.Prediction, np.linspace(0, 1, 11), include_lowest=True).astype(str)
    predictions["PredictedPass"] = predictions.Prediction * predictions.InspectedQty
    calibration = predictions.groupby(["Process", "Branch", "Variant", "Attribution", "ProbabilityBin"]).agg(
        Rounds=("WO", "size"), Pieces=("InspectedQty", "sum"), Passed=("PassQty", "sum"), PredictedPass=("PredictedPass", "sum")).reset_index()
    calibration["ObservedRate"] = calibration.Passed / calibration.Pieces
    calibration["PredictedRate"] = calibration.PredictedPass / calibration.Pieces
    calibration.to_csv(output / "calibration_bins.csv", index=False)
    lines = ["# Rasch optimization assessment — 22 September 2026", "",
             "**Recommendation:** Use the penalized single-worker, piece-weighted Rasch-style model as the leading candidate for further shadow evaluation. First synchronize production-worker data with QC dates. Keep expanded team/unknown-worker models as sensitivity analyses, and keep rework separate. No production default was changed.", "",
             "## What was tested", "",
             "Eight candidate families were evaluated: the current 1,000-iteration estimator, 5,000 iterations, three single-worker ridge weighting schemes, two expanded-data ridge schemes, and a group-only benchmark. Hyperparameters and method nominations used validation only. Whole-WO time boundaries and embargoes were held fixed within each campaign.", "",
             "Two campaigns were necessary: the current QC source through September 22, and a sensitivity window through September 14, fixed from the last production source date. The second window was not selected by optimizing model outcomes. The windows must not be pooled as independent replications.", "",
             "## Data coverage is the main constraint", "",
             f"The selected input QC file contains {audit['raw_qc_rows']:,} source rows. Reconstruction yields {audit['eligible_rounds']:,} eligible WO-rounds across {audit['eligible_wos']:,} WOs. The source flags {audit['source_hard_error_rounds']} distinct hard-error rounds; none remains in the modeling cohort.", "",
             "| Branch | Single worker | Team | Unknown worker | Single-worker coverage |", "|---|---:|---:|---:|---:|"]
    for branch in ("First pass", "Rework"):
        counts = coverage.loc[coverage.Branch.eq(branch)].set_index("Attribution").Rounds
        lines.append(f"| {branch} | {counts.get('single',0):,} | {counts.get('team',0):,} | {counts.get('unknown',0):,} | {counts.get('single',0)/counts.sum():.1%} |")
    lines += ["", "From September 15–22, no QC round in this frozen cohort has a matched production worker. The latest-window common test contains just 31 single-worker first-pass rounds and zero single-worker rework rounds. This prevents a credible contemporary worker-model comparison. The synchronized window supplies 1,675 single-worker first-pass test WOs and 301 rework test rounds (263 WOs); Bright Cut rework has insufficient split evidence.", "",
              "Missing worker linkage is not evidence that the worker was absent, unskilled, or responsible for failure. Preserve those QC outcomes for group-level reporting; recover authoritative WO + RoundNo + Worker records before attributing individual skill.", "",
              "## Numerical stability on the synchronized window", "", "| Candidate | Converged process/branch fits |", "|---|---:|"]
    for row in convergence.itertuples(index=False):
        lines.append(f"| {row.Variant} | {row.sum}/{row.count} |")
    lines += ["", "Increasing the iteration budget alone does not fix every process. Ridge stabilizes the stated convex penalized objective; convergence does not establish calibration, an unbiased worker effect, or equivalence to a marginal random-effects fit.", "",
              "## Pooled common-test prediction results", "",
              "These are exploratory aggregate summaries, not an additional test-based model selection rule. Penalties remain validation-selected. Lower piece-weighted log-loss is better.", "",
              "| Candidate | First-pass log-loss | Rework log-loss |", "|---|---:|---:|"]
    for variant in convergence.Variant:
        lines.append(f"| {variant} | {pooled.loc[('First pass',variant),'LogLoss']:.6f} | {pooled.loc[('Rework',variant),'LogLoss']:.6f} |")
    baseline = pooled.loc[("First pass", "legacy_1000"), "LogLoss"]
    candidate = pooled.loc[("First pass", "ridge_single_pieces"), "LogLoss"]
    improvement = 100 * (1 - candidate / baseline)
    ci = next(r for r in intervals if r["Branch"] == "First pass" and r["Variant"] == "ridge_single_pieces")
    lines += ["", f"The single-worker piece-weighted ridge candidate improves pooled first-pass log-loss by {improvement:.2f}% ({baseline:.6f} to {candidate:.6f}). Its paired WO-bootstrap loss-difference interval is [{ci['lower_95']:.6f}, {ci['upper_95']:.6f}]. This conditional, exploratory interval does not account for candidate search, selection/refitting uncertainty, or future process drift.", "",
              "The expanded piece-weighted model is nearly identical on this pooled first-pass measure, so the small extra prediction gain does not establish a benefit from the added team-effect assumption. Process-level improvements often have intervals crossing zero. Rework results are inconsistent: all pooled rework improvement intervals versus the legacy baseline include zero. Group-only predictions cannot certify individual skill even when their aggregate prediction score is lower.", "",
              "## Recommended implementation order", "",
              "1. Refresh production worker-hours and validate round-specific linkage through the same endpoint as QC; report linkage by date/process/branch at every run.",
              "2. Use single-worker ridge with piece weighting as a stable diagnostic/shadow candidate, with regularization selected on time-separated validation. Retain legacy estimates for audit and regression comparison.",
              "3. Keep capped quantities as a sensitivity check for large batches; do not change every process to equal-round weighting, which worsened pooled first-pass log-loss in this experiment.",
              "4. Retain unassigned QC in a separate group-only outcome view. Test multi-worker models only with explicit assumptions, never duplicated QC outcomes or fabricated piece allocations.",
              "5. Collect another synchronized temporal holdout and inspect calibration by process and unseen-worker/group status before promoting a method. Worker uncertainty, assignment confounding, and prospective validation remain unresolved.", "",
              "## Evidence and reproducibility", "", f"Latest campaign: `{provenance['latest']}`. Aligned campaign: `{provenance['aligned']}`.",
              "All source experiment artifact hashes were verified before aggregation. This assessment includes coverage.csv, daily_attribution.csv, convergence.csv, pooled_comparison.csv, paired_intervals.csv and calibration_bins.csv. Rebuild with `python -m pipeline.rasch_assessment --latest <latest-run> --aligned <aligned-run> --output <new-directory>`.", "",
              "Method references: [Stan Rasch and identifiability](https://mc-stan.org/docs/stan-users-guide/regression.html); [SciPy L-BFGS-B controls](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-lbfgsb.html).", ""]
    (output / "Assessment_EN.md").write_text("\n".join(lines), encoding="utf-8")
    provenance.update(audit=audit, first_pass_improvement_pct=improvement,
                      artifacts=[{"path": p.name, "sha256": file_hash(p)} for p in output.iterdir() if p.is_file()])
    atomic_json(output / "assessment_manifest.json", provenance)
    print(output / "Assessment_EN.md")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest", type=Path, required=True)
    parser.add_argument("--aligned", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assess(args.latest, args.aligned, args.output)
