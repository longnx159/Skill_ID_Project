"""Planner-adjusted QC challengers with WO-disjoint, frozen temporal validation.

Official Planner values are read-only. The existing Rasch exports stay canonical.
Posterior intervals are conditional on the model and retrospective-skill policy.
"""
from __future__ import annotations

import itertools
import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit
from scipy.stats import rankdata

from .data_contracts import GROUP, connectivity, require
from .preprocessing import clean_planner_data
from .quality_model import SkillScaler, fit_quality_candidate, predict_quality
from .rasch_experiments import split_wo_time, fit_candidate, predict, metrics, paired_bootstrap
from .run_reporting import atomic_json
from .semi_scope import excluded_semi_mask

VERSION = "planner-quality-v1.0"
BASELINE = "rasch-current-v053"
VERIFIED_DATE = pd.Timestamp("2026-08-03")
LOG = logging.getLogger(__name__)
# Explicit conservative statistical gates, versioned before looking at test results.
POLICY = dict(rhat_max=1.01, ess_min=200, min_test_wos=30,
              calibration_gap_max=.02, ece_max=.03, planner_coverage_min=.8,
              rank_correlation_lower_min=.7, network_adequate_fraction_min=.9,
              min_group_wos=10, min_segment_wos=20,
              retrospective_loss_tolerance=.01)


def prepare_rounds(rounds, production, planner_raw):
    require(rounds, ["WO", "RoundNo", "Process", GROUP, "PassQty", "InspectedQty", "QC_Start", "QC_Stop"], "Planner QC")
    if rounds.duplicated(["WO", "RoundNo"]).any():
        raise ValueError("Duplicate WO + RoundNo observations")
    q = rounds.drop(columns=["Worker", "Workers", "InitialWorker"], errors="ignore").copy()
    p = production.dropna(subset=["Reference", "RoundNo", "Worker"]).copy()
    p = p.loc[p.RoundNo.ge(1) & p.RoundNo.mod(1).eq(0)]
    # Count everyone in the round before matching item/process: mismatches cannot
    # make a multi-worker round look single-worker.
    links = p.groupby(["Reference", "RoundNo"]).agg(
        Workers=("Worker", lambda s: tuple(sorted(set(s.astype(str))))),
        ProductionProcesses=("Process", lambda s: tuple(sorted(set(s.astype(str))))),
        ProductionItems=("Item Number", lambda s: tuple(sorted(set(s.astype(str)))))).reset_index().rename(columns={"Reference": "WO"})
    q = q.merge(links, on=["WO", "RoundNo"], how="left", validate="one_to_one")
    q["Workers"] = q.Workers.map(lambda x: x if isinstance(x, tuple) else ())
    q["WorkersInRound"] = q.Workers.map(len)
    matches = q.apply(lambda r: isinstance(r.ProductionProcesses, tuple) and
                     r.ProductionProcesses == (str(r.Process),) and
                     ("Item Number" not in q or r["Item Number"] in r.ProductionItems), axis=1)
    q["Attribution"] = np.select([q.WorkersInRound.gt(1), q.WorkersInRound.eq(1) & matches], ["team", "single"], default="unknown")
    q["Worker"] = q.Workers.map(lambda x: x[0] if len(x) == 1 else pd.NA)
    q.loc[~q.Attribution.eq("single"), "Worker"] = pd.NA
    planner = clean_planner_data(planner_raw)
    q = q.merge(planner.rename(columns={"Worker ID": "Worker"})[["Worker", "Process", "Planner Verified Skill Level"]],
                on=["Worker", "Process"], how="left", validate="many_to_one")
    q["CertifiedSkill"] = q["Planner Verified Skill Level"]
    q["PlannerSkillStatus"] = np.select([~q.Attribution.eq("single"), q.CertifiedSkill.isna()],
        ["NO_SINGLE_PRODUCTION_WORKER", "MISSING_PLANNER_SKILL"], default="VERIFIED_PLANNER_0_10")
    q["PlannerVerificationDate"] = VERIFIED_DATE
    q["RetrospectivePlanner"] = q.CertifiedSkill.notna() & pd.to_datetime(q.QC_Start).lt(VERIFIED_DATE)
    q["Period"] = np.where(pd.to_datetime(q.QC_Start).lt(VERIFIED_DATE), "PRE_VERIFICATION", "POST_VERIFICATION")
    q["Branch"] = np.where(q.RoundNo.eq(1), "FIRST_PASS", "REWORK")
    excluded = excluded_semi_mask(q.get("Item Number", q[GROUP])) | excluded_semi_mask(q[GROUP])
    q["Eligibility"] = np.select([excluded, q.Attribution.eq("team"), q.Attribution.eq("unknown")],
        ["EXCLUDED_SEMI_SCOPE", "AUDIT_ONLY_MULTIPLE_WORKERS", "AUDIT_ONLY_NO_ROUND_WORKER"], default="ELIGIBLE")
    n, y = q.InspectedQty.to_numpy(float), q.PassQty.to_numpy(float)
    if not (np.isfinite(n).all() and np.isfinite(y).all() and (n > 0).all() and
            (y >= 0).all() and (y <= n).all() and (n % 1 == 0).all() and (y % 1 == 0).all()):
        raise ValueError("QC requires valid reconciled integer quantities")
    # One split across every process and branch, including audit-only rounds.
    q, boundaries = split_wo_time(q)
    return q.drop(columns=["ProductionProcesses", "ProductionItems"]), planner, boundaries


def posterior_diagnostics(model):
    import arviz as az
    names = list(model["posterior"])
    summary = az.summary(model["trace"], var_names=names, round_to="none")
    rhat = float(summary.r_hat.max())
    ess = float(summary.ess_bulk.min())
    divergences = int(np.asarray(model["trace"].sample_stats["diverging"]).sum())
    stats = model["trace"].sample_stats
    depth = int(np.asarray(stats["reached_max_treedepth"]).sum()) if "reached_max_treedepth" in stats else 0
    passed = np.isfinite(rhat) and np.isfinite(ess) and rhat <= POLICY["rhat_max"] and ess >= POLICY["ess_min"] and divergences == 0 and depth == 0
    return dict(Converged=bool(passed), RhatMax=rhat, ESSMin=ess, Divergences=divergences, MaxTreeDepthHits=depth), summary


def actual_worker_network(frame):
    """Anchors are verified workers who actually made each Semi, never skill=5."""
    network = connectivity(frame)
    for i, row in network.iterrows():
        g = frame.loc[frame[GROUP].eq(row[GROUP])]
        verified = g.loc[g.CertifiedSkill.notna()]
        network.loc[i, "AnchorAvailability"] = not verified.empty
        network.loc[i, "VerifiedAnchorWorkers"] = verified.Worker.nunique()
        network.loc[i, "ActualAnchorSkillMin"] = verified.CertifiedSkill.min()
        network.loc[i, "ActualAnchorSkillMax"] = verified.CertifiedSkill.max()
        network.loc[i, "ExtrapolationFlag"] = verified.empty
        network.loc[i, "ConnectivityStatus"] = "Pilot Network Evidence" if (
            row.ComponentSize >= 30 and g.Worker.nunique() >= 2 and verified.Worker.nunique() >= 2
            and row.GroupsPerWorkerMean >= 2) else "WeakNetwork"
    return network


def calibration(data, probabilities):
    if data.empty:
        return {}, pd.DataFrame()
    d = data[["WO", "PassQty", "InspectedQty"]].copy()
    d["Prediction"] = np.asarray(probabilities)
    d["Bin"] = np.minimum((d.Prediction * 10).astype(int), 9)
    d["ExpectedPass"] = d.Prediction * d.InspectedQty
    bins = d.groupby("Bin").agg(WOs=("WO", "nunique"), Pieces=("InspectedQty", "sum"), Passed=("PassQty", "sum"), Expected=("ExpectedPass", "sum")).reset_index()
    bins["Observed"] = bins.Passed / bins.Pieces
    bins["Predicted"] = bins.Expected / bins.Pieces
    ece = float(np.average(abs(bins.Observed - bins.Predicted), weights=bins.Pieces))
    gap = float(abs(d.PassQty.sum() - d.ExpectedPass.sum()) / d.InspectedQty.sum())
    return dict(CalibrationGap=gap, ECE=ece), bins


def intervals(values):
    return float(np.mean(values)), float(np.quantile(values, .025)), float(np.quantile(values, .975))


def rank_stability(model):
    # Actual worker Planner scores anchor the explanatory Rasch fit. This is
    # relative Semi difficulty, not failure probability for a fictional worker.
    difficulty = 10 * expit(-model["posterior"]["v"])
    if difficulty.shape[1] < 3:
        return dict(RankCorrelationLower95=np.nan, RankCorrelationMedian=np.nan), difficulty
    means = rankdata(difficulty.mean(axis=0))
    correlations = [np.corrcoef(means, rankdata(d))[0, 1] for d in difficulty[::max(1, len(difficulty)//200)]]
    return dict(RankCorrelationLower95=float(np.quantile(correlations, .025)), RankCorrelationMedian=float(np.median(correlations))), difficulty


def evaluate_segments(data, p, model_name, process, branch, train, baseline_p=None):
    d = data.copy()
    d["Probability"] = p
    counts = train.groupby(GROUP).WO.nunique()
    d["SparseSemi"] = np.where(d[GROUP].map(counts).fillna(0).lt(POLICY["min_group_wos"]), "LOW_WO", "SUFFICIENT_WO")
    d["PlannerLevel"] = d.CertifiedSkill.map(lambda v: "MISSING" if pd.isna(v) else str(v))
    if baseline_p is not None:
        d["BaselineProbability"] = baseline_p
    rows, bins = [], []
    for dimension in ["ALL", "PlannerLevel", "Worker", "SparseSemi", "Period", "PlannerSkillStatus"]:
        parts = [("ALL", d)] if dimension == "ALL" else d.groupby(dimension, dropna=False)
        for segment, part in parts:
            identity = dict(Process=process, Branch=branch, Model=model_name, Dimension=dimension, Segment=str(segment))
            cal, b = calibration(part, part.Probability)
            row = dict(**identity, WOs=part.WO.nunique(), **metrics(part, part.Probability), **cal)
            if baseline_p is not None:
                row.update({"Comparison_"+k: v for k,v in paired_bootstrap(part, part.Probability.to_numpy(), part.BaselineProbability.to_numpy()).items()})
            rows.append(row)
            if dimension in {"ALL", "Period"}:
                for key, value in identity.items():
                    b[key] = value
                bins.append(b)
    return rows, bins


def save_model(model, output, name, metadata):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    np.savez_compressed(output / (safe + "_posterior.npz"), **model["posterior"])
    atomic_json(output / (safe + "_metadata.json"), {
        **metadata, "version": VERSION, "workers": model["workers"], "groups": model["groups"],
        "missing_workers": model.get("missing_workers", []), "skill_sd_train": model["scaler"].sd,
        "training_wos": sorted(model["training_wos"]), "likelihood": model["likelihood"],
        "missing_skill": model["missing_skill"], "policy": POLICY})


def combine_quality(groups, availability=None):
    """Use 100% first pass only when no attributable rework observations exist."""
    if groups.empty:
        return pd.DataFrame()
    rows = []
    for (process, group), part in groups.groupby(["Process", GROUP]):
        r = {"Process": process, GROUP: group, "ModelVersion": VERSION}
        selected = part.loc[part.SelectedOnValidation]
        valid, approved = True, True
        rework_n = availability.get((process, group, "REWORK"), 0) if availability is not None else int(part.loc[part.Branch.eq("REWORK"), "WOs"].sum())
        fp_weight, rw_weight = (1., 0.) if rework_n == 0 else (.8, .2)
        r["FirstPassWeight"], r["ReworkWeight"] = fp_weight, rw_weight
        r["ReworkDataStatus"] = "NO_USABLE_REWORK_DATA" if rework_n == 0 else "REWORK_DATA_AVAILABLE"
        for branch, weight in [("FIRST_PASS", .8), ("REWORK", .2)]:
            b = selected.loc[selected.Branch.eq(branch)]
            row = b.iloc[0] if len(b) == 1 else None
            for field in ["Difficulty10", "Lower95", "Upper95", "WOs", "QCPieces", "Model", "Converged", "ValidationStatus"]:
                r[branch + "_" + field] = row[field] if row is not None else np.nan
            eligible = row is not None and bool(row.EstimateEligible)
            if branch == "FIRST_PASS" or rw_weight > 0:
                valid &= eligible
                approved &= row is not None and row.ValidationStatus == "PASSED_STATISTICAL_GATES"
        r["DiagnosticQuality"] = (fp_weight*r["FIRST_PASS_Difficulty10"] + rw_weight*r["REWORK_Difficulty10"] if rw_weight else r["FIRST_PASS_Difficulty10"]) if valid else np.nan
        r["Quality"] = r["DiagnosticQuality"] if valid and approved else np.nan
        # Bonferroni simultaneous bounds: each branch uses 97.5% intervals so
        # weighted endpoints cover the sum at least 95%, without independence.
        if valid:
            a = selected.loc[selected.Branch.eq("FIRST_PASS")].iloc[0]
            if rw_weight:
                b = selected.loc[selected.Branch.eq("REWORK")].iloc[0]
                r["QualityLower95"] = fp_weight*a.Lower975 + rw_weight*b.Lower975
                r["QualityUpper95"] = fp_weight*a.Upper975 + rw_weight*b.Upper975
            else:
                r["QualityLower95"], r["QualityUpper95"] = a.Lower95, a.Upper95
        else:
            r["QualityLower95"] = r["QualityUpper95"] = np.nan
        r["QualityStatus"] = "PASSED_STATISTICAL_GATES" if valid and approved else ("DIAGNOSTIC_ONLY" if valid else "MISSING_OR_INELIGIBLE_REQUIRED_BRANCH")
        rows.append(r)
    return pd.DataFrame(rows)


def run_comparison(rounds, production, planner_raw, output, sources, draws=500, tune=500, chains=4, seed=42, compile_mode="NUMBA"):
    output = Path(output)
    data, planner, boundaries = prepare_rounds(rounds, production, planner_raw)
    planner_sources = [s for s in sources if s.get("dataset") == "Planner Skills"]
    tables = {}
    audit = data.copy()
    audit["Workers"] = audit.Workers.map(lambda x: json.dumps(x))
    tables["Planner QC audit"] = audit
    tables["Planner coverage"] = data.groupby(["Process", "Branch", "Split", "Eligibility", "PlannerSkillStatus", "Period"], dropna=False).agg(
        WOs=("WO", "nunique"), Rounds=("WO", "size"), QCPieces=("InspectedQty", "sum")).reset_index()
    tables["Planner QC audit"].to_csv(output / "Planner QC audit.csv", index=False, encoding="utf-8-sig")
    comparison, predictions, segments, calibration_rows, networks = [], [], [], [], []
    workers_out, groups_out, decisions, sensitivity, rank_rows, anchors = [], [], [], [], [], []
    fit_ids = []
    for process, process_data in data.groupby("Process"):
        process_train = process_data.loc[process_data.Split.eq("train") & process_data.Eligibility.eq("ELIGIBLE")]
        try:
            scaler = SkillScaler.fit(process_train.CertifiedSkill)
        except ValueError:
            scaler = None
        for branch in ("FIRST_PASS", "REWORK"):
            part = process_data.loc[process_data.Branch.eq(branch)]
            eligible = part.loc[part.Eligibility.eq("ELIGIBLE")]
            train, validation, test = [eligible.loc[eligible.Split.eq(s)].copy() for s in ("train", "validation", "test")]
            common_val = validation.loc[validation.CertifiedSkill.notna()]
            common_test = test.loc[test.CertifiedSkill.notna()]
            base = dict(Process=process, Branch=branch, ModelVersion=VERSION)
            if scaler is None or len(train) < 10 or common_val.empty or common_test.empty:
                decisions.append({**base, "Decision": "KEEP_RASCH", "Reason": "INSUFFICIENT_TRAIN_VALIDATION_TEST_OR_SKILL_VARIATION", "TrainRounds": len(train), "TestWOs": common_test.WO.nunique()})
                continue
            LOG.info("Planner comparison %s / %s: train=%d validation=%d test=%d", process, branch, len(train), len(common_val), len(common_test))
            network = actual_worker_network(train)
            network["Branch"] = branch
            networks.append(network)
            baseline = None
            baseline_p = None
            try:
                baseline = fit_candidate(train, "legacy_1000")
                baseline_p = predict(baseline, common_test)
                detail = common_test.drop(columns=["Workers"]).copy()
                detail["Model"], detail["PredictedPassProbability"] = BASELINE, baseline_p
                predictions.append(detail)
                sr, cb = evaluate_segments(common_test, baseline_p, BASELINE, process, branch, train)
                segments.extend(sr); calibration_rows.extend(cb)
                baseline_meta = {k:v for k,v in baseline.items() if k != "legacy"}
                baseline_meta["legacy"] = {k: v.to_dict("records") if isinstance(v, pd.DataFrame) else v for k,v in baseline["legacy"].items()}
                atomic_json(output / (re.sub(r"\W", "_", process + branch) + "_rasch_baseline.json"), baseline_meta)
                comparison.append({**base, "Model": BASELINE, "Converged": baseline["converged"], "ValidationLoss": metrics(common_val, predict(baseline, common_val))["piece_log_loss"], **metrics(common_test, baseline_p)})
            except ValueError as exc:
                comparison.append({**base, "Model": BASELINE, "Converged": False, "Error": str(exc)})
            models = {}
            for missing, likelihood in itertools.product(["observed", "hierarchical"], ["beta_binomial", "wo_random_effect"]):
                name = f"{VERSION}_{missing}_{likelihood}"
                fitted_train = train.loc[train.CertifiedSkill.notna()] if missing == "observed" else train
                try:
                    LOG.info("Fitting %s %s %s", process, branch, name)
                    model = fit_quality_candidate(train, likelihood, missing, draws, tune, chains, seed, scaler=scaler, compile_mode=compile_mode)
                    model["network"] = actual_worker_network(fitted_train)
                    diagnostics, full_diagnostics = posterior_diagnostics(model)
                    vp = predict_quality(model, common_val, seed).PredictedFPY.to_numpy()
                    pred = predict_quality(model, common_test, seed)
                    p = np.clip(pred.PredictedFPY.to_numpy(), 1e-8, 1-1e-8)
                    cal, _ = calibration(common_test, p)
                    rank, difficulty = rank_stability(model)
                    row = {**base, "Model": name, "MissingSkill": missing, "Likelihood": likelihood,
                           "SkillSDTrainProcess": scaler.sd, "TrainingWOs": fitted_train.WO.nunique(),
                           "ValidationLoss": metrics(common_val, vp)["piece_log_loss"],
                           **diagnostics, **metrics(common_test, p), **cal, **rank}
                    beta = intervals(model["posterior"]["beta"])
                    row.update(Beta=beta[0], BetaLower95=beta[1], BetaUpper95=beta[2], BetaNegativeProbability=float(np.mean(model["posterior"]["beta"] < 0)))
                    if baseline_p is not None:
                        row.update({"Comparison_"+k: v for k,v in paired_bootstrap(common_test, p, baseline_p).items()})
                    comparison.append(row)
                    pred["Model"] = name
                    pred = pred.rename(columns={"PredictedFPY": "PredictedPassProbability", "Lower05FPY": "PassProbabilityLower90", "Upper95FPY": "PassProbabilityUpper90"})
                    predictions.append(pred)
                    sr, cb = evaluate_segments(common_test, p, name, process, branch, train, baseline_p)
                    segments.extend(sr); calibration_rows.extend(cb)
                    if missing == "hierarchical" and test.CertifiedSkill.isna().any():
                        unknown = test.loc[test.CertifiedSkill.isna()]
                        up = predict_quality(model, unknown, seed).rename(columns={"PredictedFPY": "PredictedPassProbability"})
                        up["Model"] = name
                        predictions.append(up)
                        sr, cb = evaluate_segments(unknown, up.PredictedPassProbability, name, process, branch, train)
                        segments.extend(sr); calibration_rows.extend(cb)
                    meta = {**base, "planner_sources": planner_sources, "split_boundaries": boundaries,
                            "validation_wos": sorted(common_val.WO.unique()), "test_wos": sorted(common_test.WO.unique()),
                            "draws": draws, "tune": tune, "chains": chains, "seed": seed, **diagnostics}
                    safe = re.sub(r"\W", "_", process + "_" + branch + "_" + name)
                    save_model(model, output, safe, meta)
                    full_diagnostics.to_csv(output / (safe + "_diagnostics.csv"))
                    for subset, frame in [("train", fitted_train), ("validation", common_val), ("test", common_test)]:
                        ids = frame[["WO", "RoundNo"]].copy()
                        ids["Process"], ids["Branch"], ids["Model"], ids["Use"] = process, branch, name, subset
                        fit_ids.append(ids)
                    models[name] = dict(model=model, row=row, validation_p=vp, predictions=p, difficulty=difficulty, training=fitted_train)
                    pd.DataFrame(comparison).to_csv(output / "Planner comparison.csv", index=False)
                except (ValueError, RuntimeError, FloatingPointError) as exc:
                    LOG.exception("Planner candidate unavailable %s %s %s", process, branch, name)
                    comparison.append({**base, "Model": name, "Converged": False, "Error": str(exc)})
            if not models:
                decisions.append({**base, "Decision": "KEEP_RASCH", "Reason": "ALL_CANDIDATES_UNAVAILABLE"})
                continue
            viable = [n for n,m in models.items() if m["row"]["Converged"]]
            pool = viable or list(models)
            best = min(pool, key=lambda n: models[n]["row"]["ValidationLoss"])
            # Prefer observed-skill Beta-Binomial if its validation difference
            # is not distinguishable from clustered comparison uncertainty.
            simplest = f"{VERSION}_observed_beta_binomial"
            if simplest in pool and best != simplest:
                diff = paired_bootstrap(common_val, models[best]["validation_p"], models[simplest]["validation_p"])
                if diff.get("upper_95", np.inf) >= 0:
                    best = simplest
            selected = models[best]
            row = selected["row"]
            # Explicit before/after verification evaluation and a fit excluding
            # retrospective observations. The original train SD remains frozen.
            post_train = train.loc[train.Period.eq("POST_VERIFICATION")]
            retrospective_ok = not train.RetrospectivePlanner.any()
            if train.RetrospectivePlanner.any() and len(post_train) >= 10 and post_train.CertifiedSkill.nunique() >= 2:
                try:
                    LOG.info("Retrospective sensitivity %s / %s", process, branch)
                    sm = fit_quality_candidate(post_train, selected["model"]["likelihood"], selected["model"]["missing_skill"], draws, tune, chains, seed+1, scaler=scaler, compile_mode=compile_mode)
                    sd, _ = posterior_diagnostics(sm)
                    sp = np.clip(predict_quality(sm, common_test, seed).PredictedFPY.to_numpy(), 1e-8, 1-1e-8)
                    delta = paired_bootstrap(common_test, sp, selected["predictions"])
                    shared = sorted(set(sm["groups"]) & set(selected["model"]["groups"]))
                    da = [selected["difficulty"][:, selected["model"]["groups"].index(g)].mean() for g in shared]
                    db = [10*expit(-sm["posterior"]["v"][:, sm["groups"].index(g)]).mean() for g in shared]
                    corr = float(np.corrcoef(rankdata(da), rankdata(db))[0,1]) if len(shared) >= 3 else np.nan
                    retrospective_ok = bool(sd["Converged"] and delta.get("upper_95", np.inf) <= POLICY["retrospective_loss_tolerance"] and corr >= POLICY["rank_correlation_lower_min"])
                    sensitivity.append({**base, "Model": best, "Status": "PASS" if retrospective_ok else "FAIL_OR_UNCERTAIN", "CommonGroups": len(shared), "RankCorrelation": corr, **sd, **delta, **metrics(common_test, sp)})
                    save_model(sm, output, process + branch + "_post_verification_sensitivity", {**base, "planner_sources": planner_sources, "test_wos": sorted(common_test.WO.unique())})
                except (ValueError, RuntimeError, FloatingPointError) as exc:
                    sensitivity.append({**base, "Status": "UNAVAILABLE", "Reason": str(exc)})
            elif train.RetrospectivePlanner.any():
                sensitivity.append({**base, "Status": "INSUFFICIENT_POST_VERIFICATION_TRAINING"})
            else:
                sensitivity.append({**base, "Status": "NO_RETROSPECTIVE_TRAINING"})
            covered = float(eligible.CertifiedSkill.notna().mean()) if len(eligible) else 0.
            net_fraction = float(network.ConnectivityStatus.eq("Pilot Network Evidence").mean()) if len(network) else 0.
            selected_segments = [s for s in segments if s["Process"] == process and s["Branch"] == branch and s["Model"] == best]
            segment_ok = all(s.get("Comparison_upper_95", np.inf) <= POLICY["retrospective_loss_tolerance"] for s in selected_segments if s["Dimension"] in {"PlannerLevel", "Worker", "SparseSemi"} and s["WOs"] >= POLICY["min_segment_wos"])
            periods = {s["Segment"]:s for s in selected_segments if s["Dimension"] == "Period"}
            period_ok = all(periods.get(p, {}).get("WOs", 0) >= POLICY["min_test_wos"] for p in ["PRE_VERIFICATION", "POST_VERIFICATION"])
            gates = dict(Convergence=row["Converged"], CommonHoldout=common_test.WO.nunique() >= POLICY["min_test_wos"],
                Improvement=row.get("Comparison_upper_95", np.inf) < 0,
                Calibration=row["CalibrationGap"] <= POLICY["calibration_gap_max"] and row["ECE"] <= POLICY["ece_max"],
                Segments=segment_ok, RankStability=row["RankCorrelationLower95"] >= POLICY["rank_correlation_lower_min"],
                PlannerCoverage=covered >= POLICY["planner_coverage_min"], Network=net_fraction >= POLICY["network_adequate_fraction_min"],
                RetrospectiveSensitivity=retrospective_ok, BeforeAfterEvidence=period_ok)
            passed = all(gates.values())
            status = "PASSED_STATISTICAL_GATES" if passed else "NOT_ACCEPTED_KEEP_RASCH"
            decisions.append({**base, "SelectedCandidate": best, "Decision": "ELIGIBLE_FOR_REPLACEMENT" if passed else "KEEP_RASCH",
                "Reason": "; ".join(k for k,v in gates.items() if not v), "PlannerCoverage": covered,
                "NetworkAdequateFraction": net_fraction, "TestWOs": common_test.WO.nunique(), **gates})
            for name, entry in models.items():
                model, fit, difficulty = entry["model"], entry["training"], entry["difficulty"]
                diag = entry["row"]
                net = model["network"].set_index(GROUP)
                ranks = np.apply_along_axis(rankdata, 1, difficulty)
                for i, group in enumerate(model["groups"]):
                    g = fit.loc[fit[GROUP].eq(group)]
                    mean, low, high = intervals(difficulty[:,i])
                    network_status = net.loc[group, "ConnectivityStatus"]
                    estimate_ok = diag["Converged"] and g.WO.nunique() >= POLICY["min_group_wos"] and network_status == "Pilot Network Evidence"
                    groups_out.append({**base, GROUP: group, "Model": name, "SelectedOnValidation": name == best,
                        "Difficulty10": mean, "Lower95": low, "Upper95": high,
                        "Lower975": float(np.quantile(difficulty[:,i], .0125)), "Upper975": float(np.quantile(difficulty[:,i], .9875)),
                        "AnchorMethod": "ACTUAL_PRODUCTION_WORKERS_WITH_VERIFIED_PLANNER", "ScoreMeaning": "RELATIVE_RASCH_DIFFICULTY_WITHIN_PROCESS",
                        "SemiGroupEffect": float(model["posterior"]["v"][:,i].mean()),
                        "VerifiedAnchorWorkers": g.loc[g.CertifiedSkill.notna(), "Worker"].nunique(), "WOs": g.WO.nunique(), "QCPieces": g.InspectedQty.sum(),
                        "Converged": diag["Converged"], "NetworkStatus": network_status, "EstimateEligible": bool(estimate_ok),
                        "ValidationStatus": status if name == best else "NOT_SELECTED", "RankLower95": float(np.quantile(ranks[:,i],.025)), "RankUpper95": float(np.quantile(ranks[:,i],.975))})
                    for worker, link in g.groupby("Worker"):
                        wi = model["workers"].index(worker)
                        official = link.CertifiedSkill.iloc[0]
                        actual_eta = model["posterior"]["alpha"] + model["posterior"]["u"][:,wi] + model["posterior"]["v"][:,i]
                        if pd.notna(official):
                            actual_eta += model["posterior"]["beta"] * (official-5)/scaler.sd
                            probability = float(expit(actual_eta).mean())
                        else:
                            probability = np.nan
                        anchors.append({**base, GROUP: group, "Worker":worker, "Model":name, "SelectedOnValidation":name==best,
                            "Planner Verified Skill Level":official, "AnchorStatus":"VERIFIED_ACTUAL_WORKER" if pd.notna(official) else "MISSING_NOT_OFFICIAL_ANCHOR",
                            "WOsUsed":link.WO.nunique(), "QCPieces":link.InspectedQty.sum(),
                            "PredictedPassProbabilityAtTypicalWO":probability})
                for i, worker in enumerate(model["workers"]):
                    w = fit.loc[fit.Worker.eq(worker)]
                    mean, low, high = intervals(model["posterior"]["u"][:,i])
                    value = w.CertifiedSkill.iloc[0]
                    workers_out.append({**base, "Worker": worker, "Model": name, "SelectedOnValidation": name == best,
                        "Planner Verified Skill Level": value, "PlannerSkillStatus": "VERIFIED_PLANNER_0_10" if pd.notna(value) else "MISSING_LATENT_MODEL_ONLY",
                        "WorkerResidual": mean, "WorkerResidualLower95": low, "WorkerResidualUpper95": high,
                        "WOsUsed": w.WO.nunique(), "RoundsUsed": len(w), "Converged": diag["Converged"], "ModelStatus": status if name == best else "NOT_SELECTED"})
                rank_rows.append({**base, "Model": name, "SelectedOnValidation": name == best,
                    **{k:diag[k] for k in ["RankCorrelationLower95", "RankCorrelationMedian"]}})
            # Checkpoint long runs without exposing partial outputs as completed.
            atomic_json(output / "planner_decisions.partial.json", decisions)
    represented = {(r["Process"],r[GROUP],r["Branch"]) for r in groups_out if r["SelectedOnValidation"]}
    for (process, group), gp in data.groupby(["Process", GROUP]):
        for branch in ["FIRST_PASS", "REWORK"]:
            if (process, group, branch) in represented:
                continue
            evidence = gp.loc[gp.Branch.eq(branch) & gp.Eligibility.eq("ELIGIBLE")]
            reason = "NO_USABLE_BRANCH_DATA" if evidence.empty else "INSUFFICIENT_MODEL_OR_TRAINING_EVIDENCE"
            if gp.Eligibility.eq("EXCLUDED_SEMI_SCOPE").all():
                reason = "EXCLUDED_SEMI_SCOPE"
            groups_out.append({"Process":process, GROUP:group, "Branch":branch, "ModelVersion":VERSION,
                "Model":"UNAVAILABLE", "SelectedOnValidation":True, "Difficulty10":np.nan,"Lower95":np.nan,"Upper95":np.nan,
                "Lower975":np.nan,"Upper975":np.nan,"WOs":0,"QCPieces":0,"AvailableWOs":evidence.WO.nunique(),
                "Converged":False,"EstimateEligible":False,"ValidationStatus":reason})
    groups = pd.DataFrame(groups_out)
    worker_results = pd.DataFrame(workers_out)
    # Keep all official Worker+Process pairs even when no fitted branch exists.
    existing = set(zip(worker_results.Worker, worker_results.Process)) if not worker_results.empty else set()
    unmodeled = []
    for r in planner.to_dict("records"):
        if (r["Worker ID"], r["Process"]) not in existing:
            unmodeled.append({"Worker": r["Worker ID"], "Process": r["Process"], "Planner Verified Skill Level": r["Planner Verified Skill Level"],
                "PlannerSkillStatus": "VERIFIED_PLANNER_0_10", "WorkerResidual": np.nan, "WOsUsed": 0, "ModelStatus": "NO_ELIGIBLE_MODEL", "ModelVersion": VERSION})
    official_pairs = set(zip(planner["Worker ID"], planner.Process))
    for worker, process in data.loc[data.Worker.notna(), ["Worker", "Process"]].drop_duplicates().itertuples(index=False, name=None):
        if (worker, process) not in existing and (worker, process) not in official_pairs:
            unmodeled.append({"Worker":worker,"Process":process,"Planner Verified Skill Level":np.nan,
                "PlannerSkillStatus":"MISSING_PLANNER_SKILL","WorkerResidual":np.nan,"WOsUsed":0,
                "ModelStatus":"NO_ELIGIBLE_MODEL","ModelVersion":VERSION})
    worker_results = pd.concat([worker_results, pd.DataFrame(unmodeled)], ignore_index=True)
    availability = data.loc[data.Eligibility.eq("ELIGIBLE")].groupby(["Process", GROUP, "Branch"]).WO.nunique().to_dict()
    tables.update({"Planner workers": worker_results, "Planner Semi branches": groups, "Planner Quality": combine_quality(groups, availability),
        "Planner comparison": pd.DataFrame(comparison), "Planner acceptance": pd.DataFrame(decisions),
        "Planner predictions": pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame(),
        "Planner segment metrics": pd.DataFrame(segments), "Planner actual worker anchors": pd.DataFrame(anchors),
        "Planner calibration": pd.concat(calibration_rows, ignore_index=True) if calibration_rows else pd.DataFrame(),
        "Planner networks": pd.concat(networks, ignore_index=True) if networks else pd.DataFrame(),
        "Planner sensitivity": pd.DataFrame(sensitivity), "Planner rank stability": pd.DataFrame(rank_rows),
        "Planner fit WO lists": pd.concat(fit_ids, ignore_index=True) if fit_ids else pd.DataFrame()})
    from importlib.metadata import version
    metadata = {"model_version": VERSION, "baseline_version": BASELINE, "planner_sources": planner_sources,
        "runtime": {name:version(name) for name in ["pymc", "arviz", "pytensor", "numba"]},
        "sampling":dict(chains=chains, draws=draws, tune=tune, seed=seed, compile_mode=compile_mode),
        "split_boundaries": boundaries, "acceptance_policy": POLICY, "canonical_model": BASELINE,
        "decision": "KEEP_RASCH" if not any(d["Decision"] == "ELIGIBLE_FOR_REPLACEMENT" for d in decisions) else "REVIEW_ELIGIBLE_BRANCHES",
        "note": "Rasch exports retained; posterior estimates do not alter official Planner scores. User update: 100% first pass when no usable rework data; otherwise 80/20. Failed rework fits are not absence of data.",
        "scaling": "(raw Planner score - 5) / SD of eligible observed-skill training rounds within Process; same frozen SD for both branches",
        "difficulty_rule": "User clarification: explanatory Rasch anchored by actual production workers. Difficulty10 = 10 * logistic(-SemiGroupEffect); relative within Process, not a reference-worker failure rate. Skill=5 only centers the regressor.",
        "uncertainty": "95% Bayesian credible intervals; provisional priors. Paired WO bootstrap intervals conditional on fitted models.",
        "decisions": decisions}
    atomic_json(output / "planner_quality_manifest.json", metadata)
    for name, table in tables.items():
        table.to_csv(output / (name + ".csv"), index=False, encoding="utf-8-sig")
    return tables, metadata
