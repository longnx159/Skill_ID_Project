"""Reproducible, held-out comparison of diagnostic Rasch data-use alternatives.

Does not replace the production runner or certify workers. One observation is
one WO-round; team outcomes are never copied into individual-worker outcomes.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
import logging
from pathlib import Path
import time

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import minimize
from scipy.special import expit

from .config import Config
from .data_contracts import GROUP, item_mapping, attach_mapping
from .pipeline_v053 import load_inputs, enrich_production_from_master
from .preprocessing import clean_production_data
from .qc_pipeline import reconstruct_qc
from .rasch_quality import fit_rasch_quality
from .run_reporting import RunSession, atomic_json, clean_json, file_hash, utc_now

LOG = logging.getLogger(__name__)
VARIANTS = {
    "legacy_1000": ("single", "pieces", 1000),
    "legacy_5000": ("single", "pieces", 5000),
    "ridge_single_pieces": ("single", "pieces", 0),
    "ridge_single_capped": ("single", "capped", 0),
    "ridge_single_equal_round": ("single", "equal", 0),
    "ridge_expanded_pieces": ("expanded", "pieces", 0),
    "ridge_expanded_equal_round": ("expanded", "equal", 0),
    "group_only_all": ("group", "pieces", 0),
}
PENALTIES = (0.1, 1.0, 10.0)


def prepare(inputs, qc_exclude_month="2026-07"):
    raw = enrich_production_from_master(inputs["Production"], inputs.get("Reference Master"),
                                       inputs.get("Item Master"), inputs.get("Worker Master"))
    source = inputs.get("Item Master", pd.DataFrame())
    if source.empty:
        source = inputs.get("Item Mapping", pd.DataFrame())
    if source.empty:
        source = raw
    mapping = item_mapping(source)
    production = attach_mapping(clean_production_data(raw, ""), mapping)
    production["RoundNo"] = pd.to_numeric(production.get("RoundNo", pd.Series(np.nan, index=production.index)), errors="coerce")
    keys = ["Reference", "Worker", "Item Number", "RAF Month", "RoundNo"]
    valid = (~production.duplicated(keys, keep=False) & production.Process.notna()
             & ~production.Process.isin(["", "Unknown"]))
    production = production.loc[valid].copy()
    rounds, _, exceptions = reconstruct_qc(inputs["QC Tickets"], mapping, exclude_month=qc_exclude_month)
    if rounds.empty:
        raise ValueError("No eligible QC rounds")
    p = production.loc[production.RoundNo.ge(1) & production.RoundNo.mod(1).eq(0)].copy()
    # Additional item/process guards prevent cross-process worker attribution.
    link_keys = ["WO", "RoundNo", "Item Number", "Process"]
    p = p.rename(columns={"Reference": "WO"})
    workers = p.groupby(link_keys).Worker.agg(lambda x: tuple(sorted(set(x.dropna().astype(str))))).rename("Workers").reset_index()
    data = rounds.merge(workers, on=link_keys, how="left", validate="one_to_one")
    data["Workers"] = data.Workers.map(lambda x: x if isinstance(x, tuple) else ())
    data["Attribution"] = data.Workers.map(lambda x: "single" if len(x) == 1 else ("team" if len(x) > 1 else "unknown"))
    data["Branch"] = np.where(data.RoundNo.eq(1), "First pass", "Rework")
    for col in ("QC_Start", "QC_Stop"):
        data[col] = pd.to_datetime(data[col], errors="raise")
    numeric = data[["PassQty", "InspectedQty"]].to_numpy(float)
    if (not np.isfinite(numeric).all() or data.InspectedQty.le(0).any()
            or data.PassQty.lt(0).any() or data.PassQty.gt(data.InspectedQty).any()
            or data.duplicated(["WO", "RoundNo"]).any()):
        raise ValueError("Invalid/nonunique QC modeling observations")
    return data, exceptions


def split_wo_time(data):
    """60/20/20 date split; embargo WOs whose outcomes cross either boundary."""
    spans = data.groupby("WO").agg(start=("QC_Start", "min"), stop=("QC_Stop", "max"))
    days = sorted(spans.start.dt.normalize().unique())
    if len(days) < 5:
        return data.assign(Split="insufficient_dates"), {}
    c1, c2 = pd.Timestamp(days[int(len(days) * .6)]), pd.Timestamp(days[int(len(days) * .8)])
    spans["Split"] = "embargo"
    spans.loc[spans.stop.lt(c1), "Split"] = "train"
    spans.loc[spans.start.ge(c1) & spans.stop.lt(c2), "Split"] = "validation"
    spans.loc[spans.start.ge(c2), "Split"] = "test"
    return data.join(spans.Split, on="WO"), {"validation_start": str(c1), "test_start": str(c2)}


def build_design(data, mode, schema=None):
    if schema is None:
        groups = sorted(data[GROUP].astype(str).unique())
        workers = sorted({w for team in data.Workers for w in team}) if mode != "group" else []
        rounds = sorted(data.RoundNo.astype(int).unique())[1:]
        names = ["Intercept"] + ["g:" + g for g in groups] + ["w:" + w for w in workers] + [f"r:{r}" for r in rounds]
        if mode == "expanded":
            names += ["a:team", "a:unknown"]
        schema = {"names": names, "mode": mode}
    lookup = {name: i for i, name in enumerate(schema["names"])}
    rows, cols, values = [], [], []
    for row, (group, team, round_no) in enumerate(zip(data[GROUP], data.Workers, data.RoundNo)):
        entries = {"Intercept": 1., "g:" + str(group): 1., f"r:{int(round_no)}": 1.}
        if mode != "group" and team:
            # Equal membership in logit space is a sensitivity assumption, not piece attribution.
            entries.update({"w:" + w: 1. / len(team) for w in team})
        if mode == "expanded" and len(team) != 1:
            entries["a:team" if team else "a:unknown"] = 1.
        for name, value in entries.items():
            if name in lookup:
                rows.append(row); cols.append(lookup[name]); values.append(value)
    return sparse.csr_matrix((values, (rows, cols)), shape=(len(data), len(lookup))), schema


def objective(beta, x, success, exposure, penalty):
    eta = x @ beta
    loss = np.sum(exposure * np.logaddexp(0, eta) - success * eta) + .5 * np.dot(penalty * beta, beta)
    gradient = np.asarray(x.T @ (exposure * expit(eta) - success)).ravel() + penalty * beta
    return float(loss), gradient


def fit_candidate(data, variant, penalty=1.):
    start = time.perf_counter()
    mode, weighting, legacy_iter = VARIANTS[variant]
    train = data.loc[data.Attribution.eq("single")].copy() if mode == "single" else data.copy()
    if train.empty:
        raise ValueError("No eligible training observations")
    n, y = train.InspectedQty.to_numpy(float), train.PassQty.to_numpy(float)
    model = {"variant": variant, "training_rounds": len(train), "training_pieces": float(n.sum()),
             "training_wos": sorted(train.WO.unique()), "penalty": penalty, "group_count": train[GROUP].nunique()}
    if legacy_iter:
        train["Worker"] = train.Workers.map(lambda x: x[0])
        # A round key is local to the legacy fitter only; train/test splits retain original WO.
        train["WO"] = train.WO.astype(str) + ":" + train.RoundNo.astype(str)
        result = fit_rasch_quality(train, train[["WO", "Worker"]].rename(columns={"WO": "Reference"}), max_iter=legacy_iter)
        if not result["intercepts"]:
            raise ValueError("Legacy model has insufficient worker/group evidence")
        model.update(legacy=result, converged=all(result["converged"].values()),
                     iterations=int(result["group_difficulty"].Rasch_Iterations.max()),
                     final_delta=float(result["group_difficulty"].Rasch_Final_Delta.max()))
    else:
        x, schema = build_design(train, mode)
        cap = float(np.quantile(n, .9))
        effective_n = np.minimum(n, cap) if weighting == "capped" else (np.ones(len(n)) if weighting == "equal" else n)
        effective_y = y / n * effective_n
        penalties = np.full(x.shape[1], penalty)
        penalties[0] = 1e-6  # Proper weak intercept prior also handles complete separation.
        initial = np.zeros(x.shape[1])
        rate = (effective_y.sum() + .5) / (effective_n.sum() + 1)
        initial[0] = np.log(rate / (1 - rate))
        result = minimize(objective, initial, args=(x, effective_y, effective_n, penalties),
                          jac=True, method="L-BFGS-B", options={"maxiter": 2000, "ftol": 1e-12, "gtol": 1e-5, "maxls": 40})
        gradient = float(np.max(np.abs(result.jac)))
        # Require a small per-observation gradient in addition to optimizer success.
        converged = bool(result.success and np.isfinite(result.fun) and gradient / len(train) < 1e-5)
        model.update(schema=schema, coefficients=result.x, converged=converged,
                     optimizer_success=bool(result.success), optimizer_message=str(result.message),
                     iterations=int(result.nit), gradient_max=gradient, objective=float(result.fun),
                     cap=cap, effective_training_exposure=float(effective_n.sum()))
    model["runtime_seconds"] = time.perf_counter() - start
    return model


def predict(model, data):
    if "legacy" in model:
        fitted = model["legacy"]
        alpha = next(iter(fitted["intercepts"].values()))
        groups = fitted["group_difficulty"].set_index(GROUP).Rasch_Group_Effect.to_dict()
        workers = fitted["worker_effects"].set_index("Worker").Rasch_Worker_Effect.to_dict()
        rounds = fitted["round_effects"].set_index("RoundNo").Rasch_Round_Effect.to_dict()
        eta = np.array([alpha + groups.get(str(g), 0.) + (sum(workers.get(w, 0.) for w in team) / len(team) if team else 0.) + rounds.get(int(r), 0.)
                        for g, team, r in zip(data[GROUP], data.Workers, data.RoundNo)])
    else:
        x, _ = build_design(data, model["schema"]["mode"], model["schema"])
        eta = x @ model["coefficients"]
    return np.clip(expit(eta), 1e-8, 1 - 1e-8)


def metrics(data, prediction):
    if not len(data):
        return {"rounds": 0, "pieces": 0, "piece_log_loss": None, "round_log_loss": None}
    n, y = data.InspectedQty.to_numpy(float), data.PassQty.to_numpy(float)
    p = np.clip(np.asarray(prediction), 1e-8, 1 - 1e-8)
    losses = -(y * np.log(p) + (n - y) * np.log1p(-p))
    return {"rounds": len(data), "pieces": float(n.sum()), "piece_log_loss": float(losses.sum() / n.sum()),
            "round_log_loss": float(np.mean(losses / n)),
            "piece_brier": float((y * (1-p)**2 + (n-y)*p**2).sum() / n.sum()),
            "round_rate_rmse": float(np.sqrt(np.mean((y/n-p)**2))),
            "observed_pass_rate": float(y.sum()/n.sum()), "predicted_pass_rate": float(np.average(p, weights=n))}


def paired_bootstrap(data, candidate, baseline, seed=42, repetitions=500):
    """WO-cluster interval for held-out loss difference; conditional on fitted models."""
    n, y = data.InspectedQty.to_numpy(float), data.PassQty.to_numpy(float)
    def loss(p):
        return -(y * np.log(p) + (n-y) * np.log1p(-p))
    grouped = pd.DataFrame({"WO": data.WO.to_numpy(), "difference": loss(candidate)-loss(baseline), "n": n}).groupby("WO").sum()
    if len(grouped) < 10:
        return {"status": "INSUFFICIENT_WOS", "wos": len(grouped)}
    rng = np.random.default_rng(seed)
    values = grouped.to_numpy()
    draws = []
    for _ in range(repetitions):
        sample = values[rng.integers(0, len(values), len(values))]
        draws.append(sample[:, 0].sum() / sample[:, 1].sum())
    return {"status": "CONDITIONAL_DIAGNOSTIC", "wos": len(grouped),
            "loss_difference": float(grouped.difference.sum()/grouped.n.sum()),
            "lower_95": float(np.quantile(draws,.025)), "upper_95": float(np.quantile(draws,.975))}


def compare(data, output):
    rows, tuning, predictions, selected, split_rows, coverage = [], [], [], [], [], []
    for process, process_data in data.groupby("Process"):
        split, boundaries = split_wo_time(process_data)
        split_rows.append(split)
        for branch, part in split.groupby("Branch"):
            for (subset, attribution), group in part.groupby(["Split", "Attribution"]):
                coverage.append({"Process": process, "Branch": branch, "Split": subset, "Attribution": attribution,
                                 "Rounds": len(group), "Pieces": float(group.InspectedQty.sum()), "Groups": group[GROUP].nunique()})
            train, validation, test = [part.loc[part.Split.eq(name)].copy() for name in ("train", "validation", "test")]
            common_validation = validation.loc[validation.Attribution.eq("single")]
            if len(train) < 10 or len(common_validation) < 5 or not len(test):
                selected.append({"Process": process, "Branch": branch, "status": "INSUFFICIENT_SPLIT_EVIDENCE", **boundaries})
                continue
            LOG.info("Comparing %s / %s: train=%d validation=%d test=%d", process, branch, len(train), len(validation), len(test))
            choices = {}
            for variant in VARIANTS:
                trials = []
                for penalty in ((1.,) if variant.startswith("legacy") else PENALTIES):
                    try:
                        model = fit_candidate(train, variant, penalty)
                        score = metrics(common_validation, predict(model, common_validation))
                        entry = {"Process": process, "Branch": branch, "Variant": variant, "penalty": penalty,
                                 "converged": model["converged"], "training_rounds": model["training_rounds"], **score}
                        tuning.append(entry)
                        trials.append((score["piece_log_loss"], penalty, model["converged"]))
                    except (ValueError, FloatingPointError) as exc:
                        tuning.append({"Process": process, "Branch": branch, "Variant": variant, "penalty": penalty, "error": str(exc), "converged": False})
                eligible = [t for t in trials if t[2]]
                if eligible:
                    choices[variant] = min(eligible)
                elif trials:
                    choices[variant] = min(trials)  # retain failed-fit benchmark but never select it
            viable = [(v[0], name) for name,v in choices.items() if v[2]]
            winner = min(viable)[1] if viable else None
            refit = pd.concat([train, validation], ignore_index=True)
            test_predictions = {}
            for variant, (validation_loss, penalty, validation_converged) in choices.items():
                model = fit_candidate(refit, variant, penalty)
                p = predict(model, test)
                test_predictions[variant] = p
                for cohort in ("all", "single", "team", "unknown"):
                    mask = np.ones(len(test), dtype=bool) if cohort == "all" else test.Attribution.eq(cohort).to_numpy()
                    rows.append({"Process": process, "Branch": branch, "Variant": variant, "Cohort": cohort,
                                 "penalty": penalty, "validation_loss": validation_loss, "validation_converged": validation_converged,
                                 "selected_on_validation": variant == winner, "converged": model["converged"],
                                 "iterations": model["iterations"], "training_rounds": model["training_rounds"],
                                 "runtime_seconds": model["runtime_seconds"], **metrics(test.loc[mask], p[mask])})
                detail = test[["WO", "RoundNo", "Process", "Branch", GROUP, "Attribution", "PassQty", "InspectedQty", "QC_Stop"]].copy()
                detail["Variant"], detail["Prediction"] = variant, p
                predictions.append(detail)
                metadata = {k:v for k,v in model.items() if k != "legacy"}
                if "legacy" in model:
                    metadata["legacy"] = {k:v.to_dict("records") if isinstance(v,pd.DataFrame) else v for k,v in model["legacy"].items()}
                if "coefficients" in metadata:
                    metadata["coefficients"] = metadata["coefficients"].tolist()
                safe = (process + "_" + branch + "_" + variant).replace(" ", "_")
                atomic_json(output / "models" / (safe + ".json"), metadata)
            decision = {"Process": process, "Branch": branch, "selected_variant": winner,
                        "status": "DIAGNOSTIC_ONLY", "common_validation_rounds": len(common_validation),
                        "test_single_rounds": int(test.Attribution.eq("single").sum()), **boundaries}
            if winner and "legacy_1000" in test_predictions:
                mask = test.Attribution.eq("single").to_numpy()
                decision["vs_legacy_common_single"] = paired_bootstrap(test.loc[mask], test_predictions[winner][mask], test_predictions["legacy_1000"][mask])
            selected.append(decision)
            # Save progress after every process/branch, including partial work on failure.
            pd.DataFrame(rows).to_csv(output / "comparison.csv", index=False)
    tables = {"comparison": pd.DataFrame(rows), "tuning": pd.DataFrame(tuning), "coverage": pd.DataFrame(coverage),
              "predictions": pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame(),
              "split_assignments": pd.concat(split_rows, ignore_index=True)}
    for name, table in tables.items():
        table.to_csv(output / (name + ".csv"), index=False, encoding="utf-8-sig")
    return tables, selected


def run(input_dir, output_root, prepared_run=None, qc_through=None):
    if prepared_run:
        input_dir = Path(prepared_run) / "inputs"
    session = RunSession(Config(input_dir=Path(input_dir), output_dir=Path(output_root)))
    output = session.path / "experiment"
    output.mkdir()
    (output / "models").mkdir()
    try:
        frozen, template = session.call("Input snapshot", session.snapshot_inputs)
        if prepared_run:
            session.start_stage("Verified prepared cohort")
            parent = Path(prepared_run)
            parent_manifest = json.loads((parent / "run_manifest.json").read_text(encoding="utf-8"))
            if parent_manifest.get("execution_status") not in {"SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"}:
                raise ValueError("Prepared cohort must come from a completed experiment")
            for recorded_source in parent_manifest["sources"]:
                original_snapshot = parent / recorded_source["snapshot"]
                if file_hash(original_snapshot) != recorded_source["sha256"]:
                    raise ValueError(f"Prepared source snapshot changed: {recorded_source['snapshot']}")
            source = parent / "experiment" / "modeling_rounds.csv"
            recorded = next(a for a in parent_manifest["artifacts"] if a["path"].replace("\\", "/") == "experiment/modeling_rounds.csv")
            if file_hash(source) != recorded["sha256"]:
                raise ValueError("Prepared cohort hash mismatch")
            data = pd.read_csv(source, dtype={"WO": str, "Item Number": str, GROUP: str})
            data["Workers"] = data.Workers.map(lambda s: tuple(json.loads(s)))
            for column in ("QC_Start", "QC_Stop"):
                data[column] = pd.to_datetime(data[column])
            exceptions = pd.read_csv(parent / "experiment" / "qc_exceptions.csv")
            session.summary["prepared_cohort"] = {"parent_run": str(parent.resolve()), "sha256": recorded["sha256"],
                                                   "note": "Reuses the parent's QC reconstruction and attribution; no source refresh"}
            session.finish_stage()
        else:
            inputs = session.call("Input loading", load_inputs, frozen)
            data, exceptions = session.call("QC cohort preparation", prepare, inputs, frozen.qc_exclude_month)
        if qc_through:
            cutoff = pd.Timestamp(qc_through)
            original_rows = len(data)
            data = data.loc[data.QC_Stop.le(cutoff)].copy()
            session.summary["synchronized_window"] = {"qc_through": str(cutoff), "excluded_later_rounds": original_rows-len(data),
                "reason": "Sensitivity window fixed by production source coverage, not optimized against outcome scores"}
        data.assign(Workers=data.Workers.map(json.dumps)).to_csv(output / "modeling_rounds.csv", index=False, encoding="utf-8-sig")
        exceptions.to_csv(output / "qc_exceptions.csv", index=False, encoding="utf-8-sig")
        tables, selections = session.call("Candidate comparison", compare, data, output)
        session.summary.update(execution_status="SUCCEEDED_WITH_WARNINGS", decision_status="DIAGNOSTIC_ONLY", finished_at=utc_now(),
                               duration_seconds=time.perf_counter()-session.started, exit_code=0,
                               experiment="Rasch data-use alternatives", selections=selections,
                               comparison_design="60/20/20 chronological WO split within process, with trajectory embargo; penalty/variant selected on common single-worker validation piece log-loss only",
                               candidates=VARIANTS, penalties=PENALTIES, modeled_rounds=len(data),
                               used_datasets=["Production", "QC Tickets", "Item Master", "Item Mapping", "Reference Master", "Worker Master"],
                               excluded_features="Planner skill, engineering and BOM scores are not used; no historical feature availability is assumed",
                               sources_methodology=["https://mc-stan.org/docs/stan-users-guide/regression.html", "https://docs.scipy.org/doc/scipy/reference/optimize.minimize-lbfgsb.html"])
        session.checkpoint()
        write_report(session, tables, selections)
        session.log_handler.flush()
        artifacts = [p for p in session.path.rglob("*") if p.is_file() and "inputs" not in p.relative_to(session.path).parts]
        manifest = dict(session.summary)
        manifest["artifacts"] = [{"path": str(p.relative_to(session.path)), "sha256": file_hash(p), "size_bytes": p.stat().st_size} for p in artifacts]
        atomic_json(session.path / "run_manifest.json", manifest)
        atomic_json(session.root / "latest_experiment.json", {"run_id": session.run_id})
        print("Experiment report:", session.path / "run_summary.md")
        return session.path
    except BaseException as exc:
        session.logger.exception("Experiment failed")
        session.finish(error=exc)
        raise
    finally:
        session.close()


def write_report(session, tables, selections):
    coverage, results = tables["coverage"], tables["comparison"]
    lines = ["# Rasch data-use experiment", "", "Status: DIAGNOSTIC ONLY. No production model was replaced.", "",
             "Eight alternatives separate numerical stability, observation weighting, and expanded data use. Penalties (0.1, 1, 10) and the nominated method are chosen using validation only. Test outcomes are never used to tune parameters.", "",
             "## Data coverage", "", "| Branch | Attribution | Rounds |", "|---|---|---:|"]
    for (branch, attribution), part in coverage.groupby(["Branch", "Attribution"]):
        lines.append(f"| {branch} | {attribution} | {part.Rounds.sum()} |")
    lines += ["", "## Validation-selected alternatives: untouched common single-worker test", "",
              "Lower log-loss is better. The baseline can be nonconverged; it remains a descriptive benchmark. Intervals resample whole WOs and are conditional on the fitted models.", "",
              "| Process | Branch | Validation choice | Test rounds | Candidate log-loss | Legacy log-loss | Difference 95% interval |",
              "|---|---|---|---:|---:|---:|---|"]
    for row in selections:
        variant = row.get("selected_variant")
        part = results.loc[results.Process.eq(row["Process"]) & results.Branch.eq(row["Branch"]) & results.Cohort.eq("single")] if not results.empty else results
        selected = part.loc[part.Variant.eq(variant)] if len(part) else part
        baseline = part.loc[part.Variant.eq("legacy_1000")] if len(part) else part
        score = f"{selected.iloc[0].piece_log_loss:.4f}" if len(selected) and pd.notna(selected.iloc[0].piece_log_loss) else "N/A"
        old = f"{baseline.iloc[0].piece_log_loss:.4f}" if len(baseline) and pd.notna(baseline.iloc[0].piece_log_loss) else "N/A"
        ci = row.get("vs_legacy_common_single", {})
        interval = f"[{ci['lower_95']:.4f}, {ci['upper_95']:.4f}]" if "lower_95" in ci else "Insufficient evidence"
        lines.append(f"| {row['Process']} | {row['Branch']} | {variant or row['status']} | {row.get('test_single_rounds',0)} | {score} | {old} | {interval} |")
    lines += ["", "## Interpretation and safeguards", "",
              "- Single-worker candidates retain unambiguous round attribution. The legacy 5,000-iteration arm tests whether more iterations alone resolve the problem.",
              "- Penalized candidates use fixed regularization selected within training/validation. They are regularized Rasch-style logistic models, not a validated replacement for a marginal-likelihood random-effects estimator.",
              "- Capped exposure uses the training-only 90th percentile of inspected quantity. Equal-round weighting is a pseudo-likelihood sensitivity, not an ordinary piece-level binomial likelihood.",
              "- Expanded candidates keep one outcome per WO-round. Known teams use the mean of worker logit effects; unknown workers contribute only group/round and missing-attribution effects. This is an explicit experimental assumption, not measured worker piece allocation or a classical individual Rasch interpretation.",
              "- Group-only uses all valid rounds but cannot estimate worker skill. More retained rows do not automatically mean better skill evidence.",
              "- First pass and rework are modeled separately. WO trajectories never cross train, validation and test; boundary-spanning WOs are embargoed. Labels use QC completion times for training availability.",
              "- Zero worker/group effects are used for unseen entities. Inspect cohort-specific results and unseen coverage before interpreting generalization.",
              "- Worker identifiers/assignments are retrospective production records. Their historical availability at assignment time is not established. This is an outcome-model diagnostic, not a validated prospective assignment engine.",
              "- No effect-interval calibration, measurement invariance, confounding adjustment, or production approval is claimed. A single temporal split is not proof of long-term stability.",
              "", "## Reproducibility", "", "See experiment/comparison.csv, tuning.csv, coverage.csv, split_assignments.csv, predictions.csv and models/*.json. Input snapshots and source/code hashes are retained in this run. The core latest_successful pointer is unchanged.",
              "", "Methods: [Stan Rasch model and identifiability](https://mc-stan.org/docs/stan-users-guide/regression.html); [SciPy optimizer stopping criteria](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-lbfgsb.html).", ""]
    (session.path / "run_summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("input_data"))
    parser.add_argument("--output", type=Path, default=Path("outputs/rasch_experiments"))
    parser.add_argument("--prepared-run", type=Path, help="Reuse a verified experiment cohort and its frozen sources")
    parser.add_argument("--qc-through", help="Inclusive QC completion timestamp for a prespecified sensitivity window")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(args.input_dir, args.output, args.prepared_run, args.qc_through)
