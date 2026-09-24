"""Joint, partially pooled quoted-time calibration. All outputs are diagnostic.

One response per WO-round: allocated Final hours / final GoodCW units.
Quality is refitted using earlier QC only; no full-snapshot Rasch score enters
temporal evaluation. Quote, Stone and Material Design are undated engineering snapshots.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time
import uuid

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.linalg import lsmr
from scipy.special import expit

from .quoted_inputs import read_bom_quotes
from .legacy_time import prepare_legacy_2025
from .material_design_inputs import read_material_design
from .rasch_experiments import fit_candidate
from .rasch_semi_estimate import _source_check
from .run_reporting import atomic_json, file_hash

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUOTE = ROOT / "input_data/08_Quoted Hours/Quoted Hours.xlsx"
DEFAULT_LEGACY = ROOT / "input_data/00_legacy data/Raw data gốc.xlsx"
SEMI_ROOT = ROOT / "outputs/semi_item_reports"
EXPERIMENT_ROOT = ROOT / "outputs/rasch_experiments"


def latest_run(root: Path, pointer_name: str) -> Path:
    pointer = json.loads((root / pointer_name).read_text(encoding="utf-8"))
    return root / pointer["run_id"]


def prepare_time(production_path, master_path, semis, quotes, stone_path, material_path):
    workers = pd.read_excel(production_path, sheet_name="GSWorkerWorkingHours", dtype={"Worker": str, "ProductionOrderNumber": str})
    orders = pd.read_excel(production_path, sheet_name="WorkOrderData", dtype={"ProductionOrderNumber": str, "ItemNumber": str})
    master = pd.read_excel(master_path, dtype=str)
    if orders.ProductionOrderNumber.duplicated().any() or master["Item Number"].duplicated().any():
        raise ValueError("Nonunique WO or Item Master")
    for name in ("Final", "Origin", "Idle", "RoundNo"):
        workers[name] = pd.to_numeric(workers[name], errors="coerce")
    workers["DuplicateWorkerRound"] = workers.duplicated(["ProductionOrderNumber", "RoundNo", "Worker"], keep=False)
    workers["InvalidHours"] = (~np.isfinite(workers[["Final", "Origin", "Idle"]]).all(axis=1)
                               | workers[["Final", "Origin", "Idle"]].lt(0).any(axis=1))
    workers["InvalidRound"] = workers.RoundNo.isna() | workers.RoundNo.lt(1) | workers.RoundNo.mod(1).ne(0)
    workers["BranchMismatch"] = ((workers.RoundNo.eq(1) & workers.WorkOrderStatus.ne("1st Attempt"))
                                  | (workers.RoundNo.gt(1) & workers.WorkOrderStatus.ne("Repair WorkOrder")))
    workers["MissingWorker"] = workers.Worker.isna() | workers.Worker.str.strip().eq("")
    workers["HoursIdentityError"] = (workers.Final - workers.Origin - workers.Idle).abs().gt(1e-7)
    rounds = workers.groupby(["ProductionOrderNumber", "RoundNo"], dropna=False).agg(
        AllocatedHours=("Final", "sum"), OriginHours=("Origin", "sum"), IdleHours=("Idle", "sum"),
        Worker=("Worker", "first"), WorkerCount=("Worker", "nunique"),
        DuplicateWorkerRound=("DuplicateWorkerRound", "any"), InvalidHours=("InvalidHours", "any"),
        InvalidRound=("InvalidRound", "any"), BranchMismatch=("BranchMismatch", "any"),
        MissingWorker=("MissingWorker", "any"), HoursIdentityError=("HoursIdentityError", "any")).reset_index()
    rounds = rounds.rename(columns={"ProductionOrderNumber": "WO"}).merge(
        orders.rename(columns={"ProductionOrderNumber": "WO"}), on="WO", how="left", validate="many_to_one", indicator="WOJoin")
    rounds["Date"] = pd.to_datetime(rounds.MaxRAFDate, errors="coerce")
    rounds["Branch"] = np.where(rounds.RoundNo.eq(1), "First pass", "Rework")
    semi_columns = ["SemiBOM", "SemiItem", "Process", "Product Type"] + (["ReportStatus"] if "ReportStatus" in semis else [])
    q = semis[semi_columns].merge(quotes, on="SemiBOM", how="left", validate="one_to_one")
    q["QuoteStatus"] = q.QuoteStatus.fillna("MISSING")
    stone = pd.read_excel(stone_path, dtype={"BOM item number": str})
    stone = stone.rename(columns={"BOM item number": "SemiBOM", "Final Semi Stone Score": "StoneScore"})
    if stone.groupby("SemiBOM").StoneScore.nunique().gt(1).any():
        raise ValueError("Conflicting Stone scores")
    q = q.merge(stone[["SemiBOM", "StoneScore"]].drop_duplicates("SemiBOM"), on="SemiBOM", how="left", validate="one_to_one")
    material_scores, material_audit, material_counts = read_material_design(material_path, q)
    q = q.merge(material_scores, on="SemiBOM", how="left", validate="one_to_one")
    q["MaterialDesignSourceStatus"] = q.MaterialDesignSourceStatus.fillna("MISSING_SOURCE")
    master = master.rename(columns={"Item Number": "SemiItem", "Item Number (Size Adjusted)": "SizeAdjustedGroup", "Process": "MasterProcess"})
    q = q.merge(master[["SemiItem", "SizeAdjustedGroup", "MasterProcess"]], on="SemiItem", how="left", validate="many_to_one")
    q["SizeAdjustedGroup"] = q.SizeAdjustedGroup.fillna(q.SemiItem)
    incomplete_process = q.Process.isna() | q.Process.astype("string").str.strip().isin(["", "Unknown", "Unmapped"])
    master_available = q.MasterProcess.notna() & ~q.MasterProcess.astype("string").str.strip().isin(["", "Unknown", "Unmapped"])
    q["ProcessSource"] = "SEMI_REPORT"
    q.loc[incomplete_process & master_available, "Process"] = q.loc[incomplete_process & master_available, "MasterProcess"]
    q.loc[incomplete_process & master_available, "ProcessSource"] = "ITEM_MASTER_FILLED_MISSING"
    q.loc[incomplete_process & ~master_available, "ProcessSource"] = "UNRESOLVED"
    q["ProcessMismatch"] = q.Process.ne(q.MasterProcess) | q.MasterProcess.isna()
    ambiguous = set(q.loc[q.SemiItem.duplicated(False), "SemiItem"])
    unique = q.loc[~q.SemiItem.isin(ambiguous)].copy()
    rounds = rounds.merge(unique, left_on="ItemNumber", right_on="SemiItem", how="left", validate="many_to_one")
    rounds["Exclusion"] = ""
    checks = [
        (rounds.WO.str.strip().str.casefold().eq("other"), "OTHER_WO"),
        (rounds.WOJoin.ne("both"), "UNMATCHED_WO"),
        (rounds.Status.ne("Complete"), "INCOMPLETE_WO"),
        (rounds.Date.isna(), "MISSING_DATE"),
        (rounds.InvalidRound, "INVALID_ROUND"),
        (rounds.DuplicateWorkerRound, "DUPLICATE_WORKER_ROUND"),
        (rounds.InvalidHours | rounds.HoursIdentityError, "INVALID_ALLOCATED_HOURS"),
        (rounds.BranchMismatch, "BRANCH_ROUND_MISMATCH"),
        (rounds.MissingWorker | rounds.WorkerCount.ne(1), "TEAM_OR_MISSING_WORKER"),
        (rounds.ItemNumber.isin(ambiguous), "AMBIGUOUS_SEMI_BOM"),
        (rounds.SemiBOM.isna(), "NO_UNIQUE_SEMI"),
        (rounds.ReportStatus.eq("BOM_BLOCKED") if "ReportStatus" in rounds else pd.Series(False, index=rounds.index), "BOM_BLOCKED"),
        (rounds.ReportStatus.eq("EXCLUDED_SEMI_SCOPE") if "ReportStatus" in rounds else pd.Series(False, index=rounds.index), "EXCLUDED_SEMI_SCOPE"),
        (rounds.ProcessMismatch.fillna(True).astype(bool), "PROCESS_MAPPING_MISMATCH"),
        (rounds.GoodCW.le(0) | rounds.GoodCW.isna() | rounds.AllocatedHours.le(0), "NONPOSITIVE_RESPONSE"),
    ]
    for bad, reason in checks:
        rounds.loc[bad.fillna(True) & rounds.Exclusion.eq(""), "Exclusion"] = reason
    eligible = rounds.loc[rounds.Exclusion.eq("")].copy()
    eligible["ActualMinutes"] = 60 * eligible.AllocatedHours / eligible.GoodCW
    eligible["LogMinutes"] = np.log(eligible.ActualMinutes)
    eligible["PB"] = eligible.Process + " / " + eligible.Branch
    eligible["GroupKey"] = eligible.PB + " / " + eligible.SizeAdjustedGroup
    eligible["WorkerKey"] = eligible.PB + " / " + eligible.Worker
    return eligible.reset_index(drop=True), rounds, q, material_audit, material_counts


def temporal_split(data, qc):
    # Use QC-era calendar days so training can contain pre-cutoff QC evidence.
    first_qc = pd.to_datetime(qc.QC_Start).min().normalize()
    days = sorted(data.loc[data.Date.ge(first_qc), "Date"].dt.normalize().unique())
    if len(days) < 20:
        raise ValueError("Need at least 20 QC-era production dates for four temporal windows")
    cuts = [pd.Timestamp(days[int(len(days) * f)]) for f in (.50, .70, .85)]
    spans = data.groupby("WO").Date.agg(["min", "max"])
    spans["Split"] = "embargo"
    spans.loc[spans["max"].lt(cuts[0]), "Split"] = "train"
    spans.loc[spans["min"].ge(cuts[0]) & spans["max"].lt(cuts[1]), "Split"] = "tune"
    spans.loc[spans["min"].ge(cuts[1]) & spans["max"].lt(cuts[2]), "Split"] = "calibration"
    spans.loc[spans["min"].ge(cuts[2]), "Split"] = "test"
    out = data.join(spans.Split, on="WO")
    if any(not out.Split.eq(s).any() for s in ("train", "tune", "calibration", "test")):
        raise ValueError("An evaluation window is empty")
    return out, cuts


def earlier_quality(qc, cutoff, heldout_wos):
    eligible = qc.loc[pd.to_datetime(qc.QC_Stop).lt(cutoff) & ~qc.WO.isin(heldout_wos)].copy()
    eligible["Workers"] = eligible.Workers.map(lambda x: tuple(json.loads(x)) if isinstance(x, str) else x)
    rows, health = [], []
    for (process, branch), part in eligible.groupby(["Process", "Branch"]):
        part = part.loc[part.Attribution.eq("single")]
        if len(part) < 10:
            continue
        model = fit_candidate(part, "ridge_single_pieces", penalty=1.0)
        health.append({"Process": process, "Branch": branch, "Cutoff": str(cutoff), "Rounds": len(part),
                       "Converged": model["converged"], "LatestQC": str(pd.to_datetime(part.QC_Stop).max())})
        if not model["converged"]:
            continue
        beta = model["coefficients"]
        for i, name in enumerate(model["schema"]["names"]):
            if name.startswith("g:"):
                rows.append({"Process": process, "SizeAdjustedGroup": name[2:], "Branch": branch, "Score": 10 * (1 - expit(beta[0] + beta[i]))})
    if not rows:
        return pd.DataFrame(columns=["Process", "SizeAdjustedGroup", "QualityScore"]), health
    scores = pd.DataFrame(rows).pivot(index=["Process", "SizeAdjustedGroup"], columns="Branch", values="Score")
    for branch in ("First pass", "Rework"):
        if branch not in scores:
            scores[branch] = np.nan
    scores["QualityScore"] = .8 * scores["First pass"] + .2 * scores.Rework
    return scores[["QualityScore"]].dropna().reset_index(), health


def features(data, quality):
    out = data.drop(columns=["QualityScore"], errors="ignore").merge(quality, on=["Process", "SizeAdjustedGroup"], how="left", validate="many_to_one")
    out["QualityAvailable"] = out.QualityScore.notna()
    out["StoneAvailable"] = out.StoneScore.notna()
    out["MaterialAvailable"] = out.MaterialDesignSourceScore.notna()
    out["DifficultyCoverage"] = .4 * out.QualityAvailable + .2 * out.MaterialAvailable + .1 * out.StoneAvailable
    out["DifficultyScore"] = (.4 * out.QualityScore.fillna(0) + .2 * out.MaterialDesignSourceScore.fillna(0)
                              + .1 * out.StoneScore.fillna(0)).div(out.DifficultyCoverage.where(out.DifficultyCoverage.gt(0)))
    out["Pattern"] = ("q" + out.QualityAvailable.astype(int).astype(str) + "_m"
                      + out.MaterialAvailable.astype(int).astype(str) + "_s" + out.StoneAvailable.astype(int).astype(str))
    return out


def design(data, use_quote=True, schema=None):
    if schema is None:
        quote = np.log(data.QuotedMinutesPerSemi.where(data.QuotedMinutesPerSemi.gt(0)))
        schema = {"pb": sorted(data.PB.unique()), "groups": sorted(data.GroupKey.unique()),
                  "workers": sorted(data.WorkerKey.unique()), "use_quote": use_quote,
                  "qmean": float(quote.mean()) if quote.notna().any() else 0.,
                  "qscale": max(float(quote.std()) if quote.notna().sum() > 1 else 1., .1),
                  "dmean": float(data.DifficultyScore.mean()) if data.DifficultyScore.notna().any() else 0.}
        names = ["intercept:" + p for p in schema["pb"]] + ["difficulty:global"]
        names += ["difficulty:" + p for p in schema["pb"]]
        names += ["pattern:" + p for p in ("quality_only", "stone_only", "none")]
        if use_quote:
            names += ["quote:global"] + ["quote:" + p for p in schema["pb"]] + ["quote_missing"]
        names += ["group:" + p for p in schema["groups"]] + ["worker:" + p for p in schema["workers"]]
        schema["names"] = names
    lookup = {name: i for i, name in enumerate(schema["names"])}
    rr, cc, vv = [], [], []
    for n, row in enumerate(data.itertuples(index=False)):
        d = (row.DifficultyScore - schema["dmean"]) / 10 if pd.notna(row.DifficultyScore) else 0.
        entries = {"intercept:" + row.PB: 1., "difficulty:global": d, "difficulty:" + row.PB: d,
                   "pattern:" + row.Pattern: 1., "group:" + row.GroupKey: 1., "worker:" + row.WorkerKey: 1.}
        if schema["use_quote"]:
            valid_quote = pd.notna(row.QuotedMinutesPerSemi) and row.QuotedMinutesPerSemi > 0
            q = (np.log(row.QuotedMinutesPerSemi) - schema["qmean"]) / schema["qscale"] if valid_quote else 0.
            entries.update({"quote:global": q, "quote:" + row.PB: q, "quote_missing": float(not valid_quote)})
        for name, value in entries.items():
            if name in lookup and value:
                rr.append(n); cc.append(lookup[name]); vv.append(value)
    return sparse.csr_matrix((vv, (rr, cc)), shape=(len(data), len(lookup))), schema


def penalties(schema, strength):
    # Gaussian MAP partial pooling: process slopes shrink to global slopes;
    # item and worker effects shrink to zero. This is not a causal separation.
    return np.array([1e-8 if n.startswith("intercept:") else .1 if n.endswith(":global")
                     else strength * 10 if n.startswith(("quote:", "difficulty:"))
                     else strength for n in schema["names"]])


def solve(x, y, penalty, weights=None, extra_penalty=None, extra_center=None):
    scale = np.sqrt(weights) if weights is not None else np.ones(len(y))
    matrices = [x.multiply(scale[:, None]), sparse.diags(np.sqrt(penalty))]
    targets = [y * scale, np.zeros(x.shape[1])]
    if extra_penalty is not None and np.any(extra_penalty):
        matrices.append(sparse.diags(np.sqrt(extra_penalty)))
        targets.append(np.sqrt(extra_penalty) * extra_center)
    augmented = sparse.vstack(matrices, format="csr")
    fit = lsmr(augmented, np.concatenate(targets), atol=1e-8, btol=1e-8, maxiter=5000)
    if fit[1] not in (1, 2, 4, 5) or not np.isfinite(fit[0]).all():
        raise ValueError(f"Joint fit did not converge: stopping code {fit[1]}")
    return fit[0], {"stop": fit[1], "iterations": fit[2], "condition_estimate": fit[6]}


def legacy_quote_prior(model, legacy_rows):
    schema, beta = model["schema"], model["beta"]
    names = schema["names"]
    global_slope = float(beta[names.index("quote:global")] / schema["qscale"])
    by_process = {}
    for process in sorted(legacy_rows.CurrentProcess.unique()):
        pb = process + " / Legacy 2025 aggregate"
        if "quote:" + pb in names:
            by_process[process] = float(global_slope + beta[names.index("quote:" + pb)] / schema["qscale"])
    return {"global_elasticity": global_slope, "process_elasticity": by_process,
            "rows_by_process": legacy_rows.CurrentProcess.value_counts().to_dict(),
            "scope": "2025 aggregate hours per Qty Doing; quote slopes only"}


def legacy_prior_terms(schema, prior, strength):
    extra = np.zeros(len(schema["names"]))
    center = np.zeros(len(schema["names"]))
    if prior is None or strength <= 0 or not schema["use_quote"]:
        return extra, center
    for index, name in enumerate(schema["names"]):
        if name == "quote:global":
            extra[index] = strength
            center[index] = prior["global_elasticity"] * schema["qscale"]
        elif name.startswith("quote:") and name != "quote_missing":
            process = name[6:].rsplit(" / ", 1)[0]
            if process in prior["process_elasticity"]:
                extra[index] = strength
                center[index] = (prior["process_elasticity"][process] - prior["global_elasticity"]) * schema["qscale"]
    return extra, center


def fit_time(data, use_quote, strength, legacy_prior=None, legacy_strength=0.):
    x, schema = design(data, use_quote)
    extra, center = legacy_prior_terms(schema, legacy_prior, legacy_strength)
    beta, health = solve(x, data.LogMinutes.to_numpy(), penalties(schema, strength),
                         extra_penalty=extra, extra_center=center)
    residual = data.LogMinutes.to_numpy() - x @ beta
    smear = {pb: float(np.exp(residual[data.PB.eq(pb)]).mean()) for pb in schema["pb"]}
    return {"schema": schema, "beta": beta, "strength": strength, "health": health,
            "smear": smear, "legacy_prior": legacy_prior if legacy_strength > 0 else None,
            "legacy_strength": legacy_strength}


def predict_parts(model, data):
    x, _ = design(data, schema=model["schema"])
    beta = model["beta"]
    names = model["schema"]["names"]
    technical = np.array([n.startswith(("difficulty:", "pattern:")) for n in names])
    worker = np.array([n.startswith("worker:") for n in names])
    work = ~(technical | worker)
    base = np.asarray(x[:, work] @ beta[work])
    tech = np.asarray(x[:, technical] @ beta[technical])
    labor = np.asarray(x[:, worker] @ beta[worker])
    smear = data.PB.map(model["smear"]).to_numpy(float)
    baseline = np.exp(base) * smear
    effort = np.exp(base + tech) * smear
    predicted = np.exp(base + tech + labor) * smear
    return pd.DataFrame({"WorkContentMinutes": baseline, "TechnicalDifficultyMinutes": effort - baseline,
                         "ProductionEffortMinutes": effort, "WorkerEffectMinutes": predicted - effort,
                         "PredictedMinutes": predicted}, index=data.index)


def metrics(actual, predicted):
    a, p = np.asarray(actual), np.asarray(predicted)
    valid = np.isfinite(a) & np.isfinite(p) & (a > 0) & (p > 0)
    a, p = a[valid], p[valid]
    return {"N": len(a), "LogRMSE": float(np.sqrt(np.mean(np.log(a / p) ** 2))) if len(a) else None,
            "WAPE": float(np.abs(a - p).sum() / a.sum()) if len(a) else None,
            "Within20Pct": float(np.mean(np.abs(a / p - 1) <= .2)) if len(a) else None}


def uncertainty(model, train, calibration, target, bootstrap=80):
    x, _ = design(train, schema=model["schema"])
    target_x, _ = design(target, schema=model["schema"])
    wo, wi = np.unique(train.WO, return_inverse=True)
    rng = np.random.default_rng(20260923)
    draws, coeffs = [], []
    extra, center = legacy_prior_terms(model["schema"], model.get("legacy_prior"), model.get("legacy_strength", 0.))
    for _ in range(bootstrap):
        counts = np.bincount(rng.integers(0, len(wo), len(wo)), minlength=len(wo))
        beta, _ = solve(x, train.LogMinutes.to_numpy(), penalties(model["schema"], model["strength"]), counts[wi], extra, center)
        residual = train.LogMinutes.to_numpy() - x @ beta
        smear = {pb: float(np.average(np.exp(residual[train.PB.eq(pb)]), weights=counts[wi][train.PB.eq(pb)])) for pb in model["schema"]["pb"]}
        draws.append(np.exp(target_x @ beta) * target.PB.map(smear).to_numpy())
        coeffs.append(beta)
    draws, coeffs = np.asarray(draws), np.asarray(coeffs)
    center = predict_parts(model, target).PredictedMinutes.to_numpy()
    result = pd.DataFrame({"EstimateLower90": np.quantile(draws, .05, axis=0), "EstimateUpper90": np.quantile(draws, .95, axis=0),
                           "EstimatePrecisionWithin20Pct": np.mean(np.abs(draws / center - 1) <= .2, axis=0)}, index=target.index)
    cpred = predict_parts(model, calibration).PredictedMinutes.to_numpy()
    cal = calibration[["PB", "ActualMinutes"]].copy()
    cal["LogError"] = np.abs(np.log(cal.ActualMinutes / cpred))
    cal["Within20"] = np.abs(cal.ActualMinutes / cpred - 1) <= .2
    cal = cal.loc[np.isfinite(cal.LogError)]
    if len(cal) < 30:
        raise ValueError("Insufficient calibration observations")
    def q90(values):
        level = min(1., np.ceil((len(values) + 1) * .90) / len(values))
        return float(np.quantile(values, level, method="higher"))
    global_q = q90(cal.LogError)
    stats = []
    for pb in model["schema"]["pb"]:
        part = cal.loc[cal.PB.eq(pb)]
        q = max(global_q, q90(part.LogError)) if len(part) >= 30 else global_q
        within = (part.Within20.sum() + 20 * cal.Within20.mean()) / (len(part) + 20)
        stats.append({"PB": pb, "CalibrationN": len(part), "LogRadius90": q,
                      "CalibrationWithin20Pct": within, "IntervalSource": "PROCESS_BRANCH_CONSERVATIVE" if len(part) >= 30 else "POOLED"})
    stats = pd.DataFrame(stats)
    result = result.join(target[["PB"]]).merge(stats, on="PB", how="left", validate="many_to_one")
    result["PredictionLower90"] = center * np.exp(-result.LogRadius90)
    result["PredictionUpper90"] = center * np.exp(result.LogRadius90)
    return result.drop(columns="PB"), coeffs, stats


def run(args):
    started = time.perf_counter()
    run_id = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%S_%fZ_") + uuid.uuid4().hex[:8]
    dest = args.output_root.resolve() / run_id
    artifacts, frozen = dest / "artifacts", dest / "inputs"
    artifacts.mkdir(parents=True)
    frozen.mkdir()
    summary = {"run_id": run_id, "execution_status": "RUNNING", "decision_status": "DIAGNOSTIC_ONLY",
               "started_utc": datetime.now(timezone.utc).isoformat(), "sources": [],
               "time_scope": "Allocated Final hours per WO-round / final GoodCW; not pure touch time",
               "unit": "minutes per final OK per production round", "warnings": []}
    atomic_json(dest / "run_summary.json", summary)
    try:
        experiment = args.experiment_run.resolve()
        source_summary = json.loads((experiment / "run_summary.json").read_text(encoding="utf-8"))
        _source_check(source_summary, ROOT)
        semi_summary_path = args.semi_report.resolve().parent / "semi_item_report_summary.json"
        semi_summary = json.loads(semi_summary_path.read_text(encoding="utf-8"))
        if semi_summary["output_sha256"] != file_hash(args.semi_report.resolve()):
            raise ValueError("Semi item report differs from its completed run")
        core_summary_path = ROOT / "outputs/runs" / semi_summary["core_run_id"] / "run_summary.json"
        core_summary = json.loads(core_summary_path.read_text(encoding="utf-8"))
        core_sources = {(s["dataset"], Path(s["path"]).name): s["sha256"] for s in core_summary["sources"]}
        experiment_sources = {(s["dataset"], Path(s["path"]).name): s["sha256"] for s in source_summary["sources"]}
        for key in (("Production", "ProductionData.xlsx"), ("QC Tickets", "QC data.xlsx"), ("Item Master", "Item_Master.xlsx")):
            if core_sources.get(key) != experiment_sources.get(key):
                raise ValueError(f"Semi core and QC experiment use different source versions: {key}")
        exp_manifest = json.loads((experiment / "run_manifest.json").read_text(encoding="utf-8"))
        qc_file = experiment / "experiment/modeling_rounds.csv"
        hashes = {e["path"].replace("\\", "/"): e["sha256"] for e in exp_manifest["artifacts"]}
        if hashes.get("experiment/modeling_rounds.csv") != file_hash(qc_file):
            raise ValueError("QC modeling rounds differ from experiment manifest")
        paths = {"quotes.xlsx": args.quoted.resolve(), "legacy_2025_source.xlsx": args.legacy.resolve(),
                 "production.xlsx": ROOT / "input_data/01_Production/ProductionData.xlsx",
                 "master.xlsx": ROOT / "input_data/09_Item_Master/Item_Master.xlsx", "semis.csv": args.semi_report.resolve(),
                 "stone.xlsx": ROOT / "input_data/06_Engineering_Factors/Stone/Semi Stone Score.xlsx",
                 "material_design.xlsx": ROOT / "input_data/06_Engineering_Factors/Material Design Process/Material Design Process Score.xlsx",
                 "qc_rounds.csv": qc_file}
        for name, path in paths.items():
            before = file_hash(path)
            shutil.copyfile(path, frozen / name)
            if before != file_hash(frozen / name) or before != file_hash(path):
                raise ValueError(f"Source changed during snapshot: {path}")
            summary["sources"].append({"path": str(path), "snapshot": name, "sha256": before})
        summary["code_sha256"] = {p.name: file_hash(p) for p in Path(__file__).parent.glob("*.py")}
        semis = pd.read_csv(frozen / "semis.csv", dtype={"SemiBOM": str, "SemiItem": str})
        quotes, quote_audit = read_bom_quotes(frozen / "quotes.xlsx", semis)
        quote_audit.to_csv(artifacts / "quote_source_audit.csv", index=False, encoding="utf-8-sig")
        quotes.to_csv(artifacts / "normalized_quotes.csv", index=False, encoding="utf-8-sig")
        data, source_audit, semi_inputs, material_audit, material_counts = prepare_time(
            frozen / "production.xlsx", frozen / "master.xlsx", semis, quotes,
            frozen / "stone.xlsx", frozen / "material_design.xlsx")
        source_audit.to_csv(artifacts / "time_source_audit.csv", index=False, encoding="utf-8-sig")
        material_audit.to_csv(artifacts / "material_design_source_audit.csv", index=False, encoding="utf-8-sig")
        summary["material_design_source"] = material_counts
        legacy, legacy_audit, legacy_counts = prepare_legacy_2025(frozen / "legacy_2025_source.xlsx", semi_inputs)
        if len(legacy) < 100:
            raise ValueError("Too few valid 2025 legacy rows to estimate a quote reference")
        legacy_audit.to_csv(artifacts / "legacy_2025_source_audit.csv", index=False, encoding="utf-8-sig")
        legacy_model = fit_time(legacy, True, 10.)
        prior = legacy_quote_prior(legacy_model, legacy)
        pd.DataFrame([{"Process": process, "ReferenceQuoteElasticity": slope,
                       "Eligible2025Rows": prior["rows_by_process"][process],
                       "Scope": prior["scope"]} for process, slope in prior["process_elasticity"].items()]).to_csv(
                           artifacts / "legacy_2025_quote_reference.csv", index=False)
        summary["legacy_2025"] = {**legacy_counts, "reference_fit_health": legacy_model["health"],
                                  "global_quote_elasticity": prior["global_elasticity"]}
        print(json.dumps(summary["legacy_2025"], ensure_ascii=True), flush=True)
        qc = pd.read_csv(frozen / "qc_rounds.csv", dtype={"WO": str, "SizeAdjustedGroup": str}, low_memory=False)
        data, cuts = temporal_split(data, qc)
        summary["split_dates"] = dict(zip(["tune_start", "calibration_start", "test_start"], map(str, cuts)))
        summary["cohort"] = {"source_rounds": len(source_audit), "eligible_rounds": len(data), "eligible_wos": data.WO.nunique(),
                             "splits": data.Split.value_counts().to_dict(), "branches": data.Branch.value_counts().to_dict(),
                             "exclusions": source_audit.Exclusion.value_counts().to_dict(), "quote_status": quote_audit.QuoteStatus.value_counts().to_dict(),
                             "semi_quotes_positive": int(quotes.QuotedMinutesPerSemi.notna().sum()),
                             "process_sources": semi_inputs.ProcessSource.value_counts().to_dict()}
        print(json.dumps(summary["cohort"], ensure_ascii=True), flush=True)
        train_q, health1 = earlier_quality(qc, cuts[0], set(data.loc[data.Split.ne("train"), "WO"]))
        tuning_data = features(data, train_q)
        train = tuning_data.loc[tuning_data.Split.eq("train")]
        tune = tuning_data.loc[tuning_data.Split.eq("tune")]
        candidates, fitted = [], {}
        for use_quote in (False, True):
            for strength in (1., 10., 100.):
                for legacy_strength in ((0., 100., 1000.) if use_quote else (0.,)):
                    name = f"{'quote' if use_quote else 'no_quote'}_pool_{strength:g}_legacy_{legacy_strength:g}"
                    model = fit_time(train, use_quote, strength, prior, legacy_strength)
                    score = metrics(tune.ActualMinutes, predict_parts(model, tune).PredictedMinutes)
                    candidates.append({"Candidate": name, "UseQuote": use_quote, "PoolingPenalty": strength,
                                       "LegacyPriorWeight": legacy_strength, **score, **model["health"]})
                    fitted[name] = model
                    print(f"Tuning {name}: log RMSE={score['LogRMSE']:.4f}, WAPE={score['WAPE']:.3f}", flush=True)
        comparison = pd.DataFrame(candidates)
        comparison.to_csv(artifacts / "candidate_comparison.csv", index=False)
        selected = comparison.loc[comparison.UseQuote].sort_values("LogRMSE").iloc[0]
        quote_only = comparison.loc[comparison.UseQuote & comparison.LegacyPriorWeight.eq(0)].sort_values("LogRMSE").iloc[0]
        baseline = comparison.loc[~comparison.UseQuote].sort_values("LogRMSE").iloc[0]
        selected_overall = comparison.sort_values("LogRMSE").iloc[0].Candidate
        # Quote is explicitly evaluated even if the no-quote baseline wins.
        summary["selected_quote_candidate"] = selected.Candidate
        summary["selected_legacy_prior_weight"] = float(selected.LegacyPriorWeight)
        summary["best_quote_without_legacy"] = quote_only.Candidate
        summary["preferred_by_tuning"] = selected_overall
        final_q, health2 = earlier_quality(qc, cuts[1], set(data.loc[~data.Split.isin(["train", "tune"]), "WO"]))
        data = features(data, final_q)
        final_q.to_csv(artifacts / "training_only_quality.csv", index=False)
        pd.DataFrame(health1 + health2).to_csv(artifacts / "quality_fit_health.csv", index=False)
        train = data.loc[data.Split.isin(["train", "tune"])]
        calibration = data.loc[data.Split.eq("calibration")]
        test = data.loc[data.Split.eq("test")]
        model = fit_time(train, True, float(selected.PoolingPenalty), prior, float(selected.LegacyPriorWeight))
        no_legacy = fit_time(train, True, float(quote_only.PoolingPenalty))
        no_quote = fit_time(train, False, float(baseline.PoolingPenalty))
        atomic_json(artifacts / "joint_time_model.json", model)
        observations = pd.concat([data.reset_index(drop=True), predict_parts(model, data).reset_index(drop=True)], axis=1)
        observations["ResidualMinutes"] = observations.ActualMinutes - observations.PredictedMinutes
        observations["UnseenGroup"] = ~observations.GroupKey.isin(model["schema"]["groups"])
        observations["UnseenWorker"] = ~observations.WorkerKey.isin(model["schema"]["workers"])
        assert np.allclose(observations.ActualMinutes, observations.WorkContentMinutes + observations.TechnicalDifficultyMinutes + observations.WorkerEffectMinutes + observations.ResidualMinutes, equal_nan=True)
        target_all = pd.concat([semi_inputs.assign(Branch=b) for b in ("First pass", "Rework")], ignore_index=True)
        target_all["PB"] = target_all.Process + " / " + target_all.Branch
        target_all["GroupKey"] = target_all.PB + " / " + target_all.SizeAdjustedGroup
        target_all["WorkerKey"] = "REFERENCE_WORKER_ZERO"
        target_all["Worker"] = "REFERENCE_WORKER_ZERO"
        target = target_all.loc[target_all.PB.isin(model["schema"]["pb"]) & ~target_all.ProcessMismatch
                                & ~target_all.ReportStatus.isin(["BOM_BLOCKED", "EXCLUDED_SEMI_SCOPE"])].reset_index(drop=True)
        target = features(target, final_q)
        predictions = predict_parts(model, target)
        print(f"WO-cluster bootstrap: {args.bootstrap} refits; {len(target)} Semi/branch targets", flush=True)
        intervals, coeff_draws, calibration_stats = uncertainty(model, train, calibration, target, args.bootstrap)
        semi_time = pd.concat([target.reset_index(drop=True), predictions.reset_index(drop=True), intervals.reset_index(drop=True)], axis=1)
        semi_time["TimeModelStatus"] = "DIAGNOSTIC_ALLOCATED_TIME"
        semi_time["UnseenGroup"] = ~semi_time.GroupKey.isin(model["schema"]["groups"])
        semi_time["PredictionBasis"] = "REFERENCE_WORKER; TRAINING_SNAPSHOT_QC"
        missing_targets = target_all.loc[~target_all.set_index(["SemiBOM", "Branch"]).index.isin(
            target.set_index(["SemiBOM", "Branch"]).index)].copy()
        missing_targets["TimeModelStatus"] = np.select(
            [missing_targets.ReportStatus.eq("EXCLUDED_SEMI_SCOPE"),
             missing_targets.ReportStatus.eq("BOM_BLOCKED"), missing_targets.ProcessMismatch],
            ["EXCLUDED_SEMI_SCOPE", "BOM_BLOCKED", "PROCESS_MAPPING_MISMATCH"], default="NO_PROCESS_BRANCH_MODEL")
        if not missing_targets.empty:
            semi_time = pd.concat([semi_time, missing_targets.reindex(columns=semi_time.columns)], ignore_index=True)
        semi_time = semi_time.sort_values(["SemiBOM", "Branch"], kind="stable")
        semi_time.to_csv(artifacts / "semi_time_predictions.csv", index=False, encoding="utf-8-sig")
        radius = observations.PB.map(calibration_stats.set_index("PB").LogRadius90)
        observations["PredictionLower90"] = observations.PredictedMinutes * np.exp(-radius)
        observations["PredictionUpper90"] = observations.PredictedMinutes * np.exp(radius)
        observations.to_csv(artifacts / "time_observations.csv", index=False, encoding="utf-8-sig")
        validation = []
        for label, frame in [("CALIBRATION", calibration), ("TEST", test)]:
            for candidate, m in [("QUOTE_JOINT", model), ("QUOTE_NO_LEGACY", no_legacy), ("NO_QUOTE_JOINT", no_quote)]:
                predicted = predict_parts(m, frame).PredictedMinutes
                for key, indexes in [("ALL", frame.index), *list(frame.groupby("PB").groups.items())]:
                    actual, pred = frame.loc[indexes, "ActualMinutes"], predicted.loc[indexes]
                    row = {"Window": label, "Candidate": candidate, "PB": key, **metrics(actual, pred)}
                    if candidate == "QUOTE_JOINT":
                        rad = frame.loc[indexes, "PB"].map(calibration_stats.set_index("PB").LogRadius90)
                        row["PredictionInterval90Coverage"] = float(((actual >= pred * np.exp(-rad)) & (actual <= pred * np.exp(rad))).mean())
                    validation.append(row)
        validation = pd.DataFrame(validation)
        validation.to_csv(artifacts / "time_validation.csv", index=False)
        calibration_stats.to_csv(artifacts / "time_calibration.csv", index=False)
        coef = pd.DataFrame({"Term": model["schema"]["names"], "EstimateLogScale": model["beta"],
                             "Lower90": np.quantile(coeff_draws, .05, axis=0), "Upper90": np.quantile(coeff_draws, .95, axis=0)})
        coef["PrecisionWithinLog01Pct"] = np.mean(np.abs(coeff_draws - model["beta"]) <= .1, axis=0)
        coef.to_csv(artifacts / "time_coefficients.csv", index=False)
        slopes = []
        names = model["schema"]["names"]
        for pb in model["schema"]["pb"]:
            indices = [names.index("quote:global"), names.index("quote:" + pb)]
            draws = coeff_draws[:, indices].sum(axis=1) / model["schema"]["qscale"]
            slopes.append({"PB": pb, "QuoteElasticity": model["beta"][indices].sum() / model["schema"]["qscale"],
                           "Lower90": np.quantile(draws, .05), "Upper90": np.quantile(draws, .95),
                           "TrainingRounds": int(train.PB.eq(pb).sum()), "Interpretation": "Elasticity, not a percentage blend weight"})
        pd.DataFrame(slopes).to_csv(artifacts / "quote_effects.csv", index=False)
        summary["model_health"] = model["health"]
        summary["bootstrap_refits"] = args.bootstrap
        summary["time_validation"] = validation.where(validation.notna(), None).to_dict("records")
        summary["semi_branch_rows"] = len(semi_time)
        summary["semi_branch_predictions"] = int(semi_time.PredictedMinutes.notna().sum())
        summary["semi_prediction_codes"] = semi_time.loc[semi_time.PredictedMinutes.notna(), "SemiBOM"].nunique()
        summary["warnings"] = [
            "Final includes allocated Idle as requested. The response is not verified clean touch time.",
            "GoodCW is final output quantity; rework response is allocated rework minutes per final OK, not minutes per repaired/inspected piece.",
            "2025 legacy Total Actual Hours / Qty Doing has a different scope and no RoundNo. It informs only a quote-slope prior, never a first-pass or rework label.",
            "The legacy prior weight is chosen on 2026 Final-time tuning data; 2025 observations do not enter 2026 calibration or test metrics.",
            "Primary fit excludes multiworker rounds because individual piece attribution is unavailable; see source audit.",
            "Current quote, Stone and Material Design snapshots lack effective dates. Temporal results are retrospective snapshot-conditional, not as-of deployment validation.",
            "All effects are fitted jointly with Gaussian penalties. WorkContent/Technical/Worker separation is a reference convention, not causally identified effort.",
            "Bootstrap intervals hold QC features, legacy prior fit, model selection and current engineering snapshots fixed. They exclude upstream Rasch and legacy-prior uncertainty.",
            "First-pass and rework targets are separate round conditions. Do not sum their predictions without a rework probability/round-count model.",
            "Excluded Semi code prefixes and -01/-02 suffixes remain in the BOM audit but do not train or receive allocated-time predictions.",
        ]
        if selected_overall != selected.Candidate:
            summary["warnings"].append("No-quote model wins tuning; quote joint model is a sensitivity candidate, not a recommended replacement.")
        if float(selected.LegacyPriorWeight) == 0:
            summary["warnings"].append("Legacy 2025 was evaluated as a quote reference but no positive prior weight won tuning; it is not forced into the exported current-time fit.")
        for source in summary["sources"]:
            if file_hash(frozen / source["snapshot"]) != source["sha256"]:
                raise ValueError("Frozen input changed during fit")
        if summary["code_sha256"] != {p.name: file_hash(p) for p in Path(__file__).parent.glob("*.py")}:
            raise ValueError("Pipeline code changed during fit")
        summary["execution_status"] = "SUCCEEDED_WITH_WARNINGS"
        summary["duration_seconds"] = time.perf_counter() - started
        summary["artifacts"] = [{"path": str(p.relative_to(dest)), "sha256": file_hash(p)} for p in sorted(artifacts.glob("*"))]
        atomic_json(dest / "run_manifest.json", summary)
        atomic_json(dest / "run_summary.json", summary)
        lines = ["# Quoted hours and joint allocated-time calibration", "", "Status: SUCCEEDED_WITH_WARNINGS / DIAGNOSTIC_ONLY", "",
                 f"Input quote unit: minutes per Semi. Positive matched quotes: {summary['cohort']['semi_quotes_positive']:,}.",
                 f"Eligible WO-rounds: {len(data):,}; modeled Semi/branch rows: {summary['semi_branch_predictions']:,} of {len(semi_time):,}.",
                 f"Legacy 2025 aggregate reference: {len(legacy):,} eligible of {legacy_counts['rows_2025']:,} 2025 rows; selected quote-prior weight: {selected.LegacyPriorWeight:g}.",
                 f"Material Design Process source scores: {material_counts['selected_semi_boms']:,} SemiBOMs, joined by Semi BOM Item, item, process and product type.",
                 "", "## Method", "",
                 "Joint regularized log-time regression with process/branch intercepts, global quote and difficulty slopes, shrunk process/branch slope deviations, and shrunk Semi-group and worker effects. No observed-time average is added a second time. Quote is a learned Work Content covariate, not a fixed offset or a claimed convex blend weight. A separately fitted 2025 aggregate-hours quote slope can act as a validated prior; its time level and branch labels are never transferred.",
                 "", "Final allocated hours are summed once per WO-round and divided by final GoodCW. Only uniquely attributed worker rounds enter the primary fit. Quality features are refitted using QC before each training cutoff, excluding later-window WOs. Model/penalty selection uses the tuning window, intervals use a separate calibration window, and the test window is untouched.",
                 "", "## Temporal windows", "", *[f"- {k}: {v}" for k, v in summary["split_dates"].items()],
                 "", f"Preferred by tuning: **{selected_overall}**. Exported quote candidate: **{selected.Candidate}**. Best quote-only candidate without legacy: **{quote_only.Candidate}**.",
                 "", "| Window | Model | Rows | Log RMSE | WAPE | Within 20% | 90% interval coverage |", "|---|---|---:|---:|---:|---:|---:|"]
        for row in validation.loc[validation.PB.eq("ALL")].itertuples(index=False):
            coverage = f"{row.PredictionInterval90Coverage:.1%}" if pd.notna(row.PredictionInterval90Coverage) else "N/A"
            lines.append(f"| {row.Window} | {row.Candidate} | {row.N} | {row.LogRMSE:.4f} | {row.WAPE:.1%} | {row.Within20Pct:.1%} | {coverage} |")
        lines += ["", "## Interpretation and limitations", "", *["- " + w for w in summary["warnings"]], "",
                  "The per-Semi estimate precision is the fraction of fixed-design WO-bootstrap refits within ±20% of the point estimate. CalibrationWithin20Pct is a shrunk historical calibration hit rate, not the Semi difficulty confidence. Prediction intervals describe allocated time for a future observation under the snapshot assumptions, with actual coverage checked in the test window.",
                  "", "## Next actions", "", "- Review quote conflicts/zero values and time join exclusions.", "- Supply quote effective dates and validate allocation semantics before deployment.", "- Use holdout results to decide whether quote adds value; do not deploy on training fit alone.", "",
                  "Method references: [Mixed-effects models](https://www.statsmodels.org/dev/mixed_linear.html); [preventing preprocessing leakage](https://github.com/scikit-learn/scikit-learn/blob/main/doc/common_pitfalls.rst)."]
        (dest / "run_summary.md").write_text("\n".join(lines), encoding="utf-8")
        from .build_quoted_time_workbook_stream import build
        workbook = build(dest)
        summary["artifacts"].append({"path": workbook.name, "sha256": file_hash(workbook)})
        atomic_json(dest / "run_manifest.json", summary)
        atomic_json(dest / "run_summary.json", summary)
        atomic_json(args.output_root.resolve() / "latest_successful.json", {"run_id": run_id})
        print(str(dest), flush=True)
        return dest
    except BaseException as exc:
        summary.update(execution_status="FAILED", error=f"{type(exc).__name__}: {exc}", duration_seconds=time.perf_counter() - started)
        atomic_json(dest / "run_summary.json", summary)
        (dest / "run_summary.md").write_text(f"# Quoted-time calibration\n\nStatus: FAILED\n\n{summary['error']}\n", encoding="utf-8")
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quoted", type=Path, default=DEFAULT_QUOTE)
    parser.add_argument("--legacy", type=Path, default=DEFAULT_LEGACY, help="Historical workbook; only 2025 rows are considered")
    parser.add_argument("--semi-report", type=Path, help="Completed Semi report; default resolves latest_successful.json")
    parser.add_argument("--experiment-run", type=Path, help="Completed QC experiment; default resolves latest_experiment.json")
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs/quoted_time_runs")
    parser.add_argument("--bootstrap", type=int, default=80)
    args = parser.parse_args()
    if args.bootstrap < 20:
        parser.error("At least 20 bootstrap refits are required")
    if args.semi_report is None:
        args.semi_report = latest_run(SEMI_ROOT, "latest_successful.json") / "semi_item_report.csv"
    if args.experiment_run is None:
        args.experiment_run = latest_run(EXPERIMENT_ROOT, "latest_experiment.json")
    run(args)


if __name__ == "__main__":
    main()
