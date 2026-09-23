"""Fast analytical Rasch/IRT quality difficulty estimator via EM.

Uses binomial FPY data at WO level with worker and group random effects,
fitted by Expectation-Maximisation similar to the time model in hybrid_effect.py.

Worker identity comes from production data (GSWorkerWorkingHours), NOT from
QC inspectors. Only an unambiguous production round worker is eligible.
"""
from __future__ import annotations
import logging
import numpy as np
import pandas as pd

LOG = logging.getLogger(__name__)


def _logistic(x):
    """Numerically stable logistic sigmoid."""
    x = np.clip(x, -30, 30)
    return 1.0 / (1.0 + np.exp(-x))


def fit_rasch_quality(first_round, production_data, max_iter=1000, tol=1e-5):
    """Fit Rasch IRT model to first-round QC pass/fail data.

    Parameters
    ----------
    first_round : DataFrame
        WO-level first round data with columns: WO, SizeAdjustedGroup, Process,
        PassQty, InspectedQty.
    production_data : DataFrame
        Cleaned production data with columns: Reference (=WO), Worker.
        Used only for unambiguous first-round production attribution.

    Returns
    -------
    dict with keys: group_difficulty (DataFrame), worker_effects (DataFrame),
        intercepts (dict by Process), converged (dict by Process)
    """
    if max_iter < 1 or tol <= 0:
        raise ValueError("Rasch iterations and tolerance must be positive")
    if first_round.empty or production_data.empty:
        return {"group_difficulty": pd.DataFrame(), "worker_effects": pd.DataFrame(),
                "intercepts": {}, "converged": {}}

    # Production round attribution is authoritative. An explicitly missing Worker
    # must never fall back to the whole-WO worker or a QC inspector.
    if "Worker" in first_round.columns:
        merged = first_round.copy()
        merged["ProdWorker"] = merged["Worker"]
    else:
        p = production_data.copy()
        if "RoundNo" in p:
            p = p.loc[p.RoundNo.eq(1)]
        else:
            p = p.iloc[:0]
        counts = p.groupby("Reference").Worker.nunique()
        p = p.loc[p.Reference.isin(counts[counts.eq(1)].index)]
        primary = p[["Reference", "Worker"]].drop_duplicates("Reference")
        merged = first_round.merge(primary.rename(columns={"Reference": "WO", "Worker": "ProdWorker"}), on="WO", how="left", validate="many_to_one")

    group_rows = []
    worker_rows = []
    round_rows = []
    intercepts = {}
    converged_map = {}

    for process, part in merged.groupby("Process"):
        part = part.dropna(subset=["ProdWorker"]).copy()
        if len(part) < 2:
            LOG.warning("Rasch %s: insufficient data (%d WOs with attributed workers)", process, len(part))
            continue

        pass_qty = part["PassQty"].to_numpy(float)
        inspected = part["InspectedQty"].to_numpy(float)

        workers, wi = np.unique(part["ProdWorker"].astype(str).to_numpy(dtype=str), return_inverse=True)
        groups, gi = np.unique(part["SizeAdjustedGroup"].astype(str).to_numpy(dtype=str), return_inverse=True)
        round_values = np.sort(part["RoundNo"].dropna().astype(int).unique()) if "RoundNo" in part.columns else np.array([1])
        round_map = {value: i for i, value in enumerate(round_values)}
        ri = part["RoundNo"].fillna(round_values[0]).astype(int).map(round_map).to_numpy() if "RoundNo" in part.columns else np.zeros(len(part), dtype=int)

        n_workers = len(workers)
        n_groups = len(groups)
        n_obs = len(part)

        if n_workers < 2 or n_groups < 2:
            LOG.warning("Rasch %s: need >=2 workers and >=2 groups (got %d workers, %d groups)",
                        process, n_workers, n_groups)
            continue

        LOG.info("Fitting Rasch quality model: %s (%d WOs, %d workers, %d groups)",
                 process, n_obs, n_workers, n_groups)

        # Initialize
        observed_fpy = np.clip(pass_qty.sum() / inspected.sum(), 1e-8, 1 - 1e-8)
        mu = np.log(observed_fpy / max(1 - observed_fpy, 1e-8))
        u = np.zeros(n_workers)  # worker effects
        v = np.zeros(n_groups)   # group effects (difficulty = -v)
        r = np.zeros(len(round_values))  # round effect; retained separate from item difficulty
        tau2_w = 0.5  # worker variance
        tau2_g = 0.5  # group variance

        conv = False
        for iteration in range(max_iter):
            # E-step: compute expected probabilities
            eta = mu + u[wi] + v[gi] + r[ri]
            p = _logistic(eta)

            # Working response (IRLS for logistic regression)
            wt = inspected * p * (1 - p)  # weights
            wt = np.clip(wt, 1e-8, None)
            z = eta + (pass_qty - inspected * p) / wt  # working response

            # M-step: update intercept
            mu_new = float(np.average(z - u[wi] - v[gi] - r[ri], weights=wt))

            # Vectorized worker effect updates (shrunk toward 0)
            resid_w = wt * (z - mu_new - v[gi] - r[ri])
            num_w = np.zeros(n_workers)
            den_w = np.zeros(n_workers)
            np.add.at(num_w, wi, resid_w)
            np.add.at(den_w, wi, wt)
            u_new = num_w / (den_w + 1.0 / max(tau2_w, 1e-8))

            # Vectorized group effect updates (shrunk toward 0)
            resid_g = wt * (z - mu_new - u_new[wi] - r[ri])
            num_g = np.zeros(n_groups)
            den_g = np.zeros(n_groups)
            np.add.at(num_g, gi, resid_g)
            np.add.at(den_g, gi, wt)
            v_new = num_g / (den_g + 1.0 / max(tau2_g, 1e-8))

            resid_r = wt * (z - mu_new - u_new[wi] - v_new[gi])
            num_r = np.zeros(len(round_values))
            den_r = np.zeros(len(round_values))
            np.add.at(num_r, ri, resid_r)
            np.add.at(den_r, ri, wt)
            r_new = num_r / (den_r + 1.0)

            # Update variance components
            tau2_w_new = max(float(np.mean(u_new ** 2)), 1e-8)
            tau2_g_new = max(float(np.mean(v_new ** 2)), 1e-8)

            # Check convergence on parameter changes
            delta = (abs(mu_new - mu)
                     + np.max(np.abs(u_new - u))
                     + np.max(np.abs(v_new - v))
                     + np.max(np.abs(r_new - r))
                     + abs(tau2_w_new - tau2_w)
                     + abs(tau2_g_new - tau2_g))
            mu = mu_new
            u = u_new
            v = v_new
            r = r_new
            tau2_w = tau2_w_new
            tau2_g = tau2_g_new

            if delta < tol:
                conv = True
                LOG.info("Rasch %s converged at iteration %d", process, iteration + 1)
                break

        if not conv:
            LOG.warning("Rasch %s did not converge after %d iterations (delta=%.2e)",
                        process, max_iter, delta)

        converged_map[process] = conv
        intercepts[process] = mu

        # Compute Rasch difficulty: P_ref = logistic(mu + v_j), difficulty = 10 * (1 - P_ref)
        p_ref = _logistic(mu + v)
        rasch_diff = 10.0 * (1.0 - p_ref)

        # Count evidence per group
        group_evidence = pd.Series(gi).value_counts().sort_index().to_numpy()

        for k in range(n_groups):
            group_rows.append({
                "Process": process,
                "SizeAdjustedGroup": groups[k],
                "FPY_Rasch_Difficulty": float(rasch_diff[k]),
                "Rasch_Group_Effect": float(v[k]),
                "Rasch_P_ref": float(p_ref[k]),
                "Rasch_Evidence_N": int(group_evidence[k]),
                "Rasch_Converged": conv,
                "Rasch_Iterations": iteration + 1,
                "Rasch_Final_Delta": float(delta),
                "Rasch_Worker_Variance": float(tau2_w),
                "Rasch_Group_Variance": float(tau2_g),
                "CalibrationStatus": "NOT_VALIDATED",
                "DecisionEligibility": "BLOCKED",
            })

        for j in range(n_workers):
            mask = wi == j
            worker_rows.append({
                "Process": process,
                "Worker": workers[j],
                "Rasch_Worker_Effect": float(u[j]),
                "Rasch_Worker_WOs": int(mask.sum()),
            })

        # Keep round effects visible for the rework branch; RoundNo=1 is the
        # reference level when a first-round-only fit is supplied.
        for k, value in enumerate(round_values):
            round_rows.append({"Process": process, "RoundNo": int(value),
                               "Rasch_Round_Effect": float(r[k]),
                               "Rasch_Round_Evidence_N": int((ri == k).sum()),
                               "Rasch_Converged": conv})

    return {
        "group_difficulty": pd.DataFrame(group_rows),
        "worker_effects": pd.DataFrame(worker_rows),
        "intercepts": intercepts,
        "converged": converged_map,
        "round_effects": pd.DataFrame(round_rows),
    }


def fit_rasch_rework(rounds, production_data, max_iter=1000, tol=1e-5):
    """Fit the repeated-round branch using the worker recorded in each round.

    A WO-round with multiple workers is excluded from individual attribution;
    its QC result remains available in the round-level tables.
    """
    if rounds.empty or production_data.empty or "RoundNo" not in production_data.columns:
        return {"group_difficulty": pd.DataFrame(), "worker_effects": pd.DataFrame(),
                "round_effects": pd.DataFrame(), "intercepts": {}, "converged": {}}
    p = production_data.dropna(subset=["Reference", "Worker", "RoundNo"]).copy()
    p["RoundNo"] = pd.to_numeric(p["RoundNo"], errors="coerce")
    hours = p["Total Actual Hours"] if "Total Actual Hours" in p.columns else pd.Series(0.0, index=p.index)
    p["Hours"] = pd.to_numeric(hours, errors="coerce").fillna(0)
    counts = p.groupby(["Reference", "RoundNo"])["Worker"].nunique()
    eligible = counts[counts.eq(1)].index
    p = p.set_index(["Reference", "RoundNo"])
    p = p.loc[p.index.isin(eligible)].reset_index()
    p = p.sort_values("Hours", ascending=False).drop_duplicates(["Reference", "RoundNo"])
    q = rounds.loc[rounds.RoundNo.ge(2)].copy()
    q["_key"] = q.WO.astype(str) + "|" + q.RoundNo.astype(int).astype(str)
    p["_key"] = p.Reference.astype(str) + "|" + p.RoundNo.astype(int).astype(str)
    q = q.merge(p[["_key", "Worker"]], on="_key", how="inner", validate="one_to_one")
    if q.empty:
        return {"group_difficulty": pd.DataFrame(), "worker_effects": pd.DataFrame(),
                "round_effects": pd.DataFrame(), "intercepts": {}, "converged": {}}
    q["WO"] = q["_key"]
    # Pass a keyed one-row-per-observation production frame so the shared
    # fitter does not replace the recorded WO-round worker with a whole-WO
    # primary worker.
    fit_workers = q[["WO", "Worker"]].drop_duplicates("WO").rename(columns={"WO":"Reference", "Worker":"WorkerAssigned"})
    fit_workers = fit_workers.rename(columns={"WorkerAssigned":"Worker"})
    return fit_rasch_quality(q, fit_workers, max_iter=max_iter, tol=tol)
