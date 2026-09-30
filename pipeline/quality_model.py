"""Optional Bayesian v0.5.3 quality candidates; never grants production approval.

PyMC is optional. This module deliberately does not substitute the historical
Gaussian time model for a first-pass quality model.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from .data_contracts import GROUP, connectivity, require


@dataclass(frozen=True)
class SkillScaler:
    sd: float

    @classmethod
    def fit(cls, training_skill):
        skill=pd.to_numeric(training_skill,errors="coerce").dropna()
        sd=float(skill.std(ddof=1))
        if not np.isfinite(sd) or sd<=0:
            raise ValueError("Training skill variation is insufficient to estimate a skill slope")
        return cls(sd)

    def transform(self, skill):
        return (np.asarray(skill,dtype=float)-5.0)/self.sd


def attach_asof_skill(first_round, planner, allow_baseline_prior=True):
    """Attach Planner skill. When no prior historical skill data exists before EffectiveFrom,
    the verified baseline snapshot is used for prior records."""
    require(planner,["Worker ID","Process","Planner Verified Skill Level","EffectiveFrom"],"Quality-model Planner data")
    p=planner.rename(columns={"Worker ID":"Worker","Planner Verified Skill Level":"CertifiedSkill"}).copy()
    p["EffectiveFrom"]=pd.to_datetime(p.EffectiveFrom,errors="coerce")
    out=first_round.merge(p[["Worker","Process","CertifiedSkill","EffectiveFrom"]],on=["Worker","Process"],how="left",validate="many_to_one")
    has_skill = out["CertifiedSkill"].notna()
    asof = out.EffectiveFrom.notna() & out.EffectiveFrom.le(out.QC_Start)
    if not allow_baseline_prior:
        out.loc[~asof,"CertifiedSkill"]=np.nan
        out["SkillAsOfStatus"]=np.where(asof,"Dated snapshot available at QC start","Missing historical skill")
    else:
        out["SkillAsOfStatus"]=np.where(asof,"Dated snapshot available at QC start",
            np.where(has_skill, "Baseline snapshot applied (prior to verification date)", "Missing historical skill"))
    return out


def fit_quality_candidate(train, likelihood="beta_binomial", missing_skill="observed", draws=1000, tune=1000, chains=4, seed=42, scaler=None, compile_mode=None):
    """Fit process-specific noncentered worker/group effects using Train only.

    likelihood: beta_binomial or wo_random_effect (never both).
    missing_skill: observed (complete-case candidate A) or hierarchical (B).
    Priors are provisional; comparison and sensitivity review remain required.
    """
    require(train,["WO","Worker",GROUP,"Process","PassQty","InspectedQty","CertifiedSkill","QC_Start"],"Quality training")
    if likelihood not in ("beta_binomial","wo_random_effect") or missing_skill not in ("observed","hierarchical"):
        raise ValueError("Unknown quality candidate")
    keys = ["WO", "RoundNo"] if "RoundNo" in train else ["WO"]
    if train.Process.nunique()!=1 or train.duplicated(keys).any():
        raise ValueError("Fit one Process and one row per WO-round")
    if "RoundNo" in train and train.RoundNo.eq(1).any() and train.RoundNo.ge(2).any():
        raise ValueError("FIRST_PASS and REWORK must be fitted separately")
    if train.Worker.isna().any():
        raise ValueError("Explicit initial worker attribution required")
    # Mandatory sequencing: diagnostic output exists before importing/fitting GLMM.
    scale=scaler or SkillScaler.fit(train.CertifiedSkill)
    frame=train.dropna(subset=["CertifiedSkill"]).copy() if missing_skill=="observed" else train.copy()
    if frame.empty:
        raise ValueError("No observed historical skills for quality fitting")
    network=connectivity(frame)
    workers=sorted(frame.Worker.unique())
    groups=sorted(frame[GROUP].unique())
    wi=pd.Categorical(frame.Worker,categories=workers).codes
    gi=pd.Categorical(frame[GROUP],categories=groups).codes
    y=frame.PassQty.to_numpy(dtype=float)
    n=frame.InspectedQty.to_numpy(dtype=float)
    if not (np.isfinite(y).all() and np.isfinite(n).all() and (y>=0).all() and (n>0).all() and (y<=n).all() and (y%1==0).all() and (n%1==0).all()):
        raise ValueError("Quality likelihood requires reconciled integer piece counts")
    try:
        import os
        from pathlib import Path
        # Keep compiler caches inside the workspace (including sandboxed runs).
        flags = os.environ.get("PYTENSOR_FLAGS", "")
        if "base_compiledir=" not in flags:
            cache = (Path.cwd() / "outputs" / ".planner-pytensor-cache").resolve()
            cache.mkdir(parents=True, exist_ok=True)
            os.environ["PYTENSOR_FLAGS"] = (flags + "," if flags else "") + "base_compiledir=" + cache.as_posix()
        import pymc as pm
    except ImportError as exc:
        raise RuntimeError("Optional quality candidates require: python -m pip install -r requirements-full.txt") from exc
    miss_workers = []
    wo_labels = sorted(frame.WO.unique())
    wo_index = pd.Categorical(frame.WO, categories=wo_labels).codes
    with pm.Model(coords={"worker":workers,"group":groups}) as model:
        alpha=pm.Normal("alpha",mu=0,sigma=2.5)
        beta=pm.Normal("beta",mu=0,sigma=1.5)
        worker_sd=pm.HalfNormal("worker_sd",sigma=1)
        group_sd=pm.HalfNormal("group_sd",sigma=1)
        u=pm.Deterministic("u",pm.Normal("worker_z",0,1,dims="worker")*worker_sd,dims="worker")
        v=pm.Deterministic("v",pm.Normal("group_z",0,1,dims="group")*group_sd,dims="group")
        skill=frame.CertifiedSkill.to_numpy(float)
        x=scale.transform(skill)
        if missing_skill=="hierarchical" and np.isnan(skill).any():
            # Integrates unknown skills, rather than silently mean-imputing them.
            miss_workers=sorted(frame.loc[frame.CertifiedSkill.isna(),"Worker"].unique())
            skill_mu=pm.TruncatedNormal("missing_skill_mu",mu=5,sigma=2,lower=0,upper=10)
            skill_sd=pm.HalfNormal("missing_skill_sd",sigma=2)
            latent=pm.TruncatedNormal("missing_skill",mu=skill_mu,sigma=skill_sd,lower=0,upper=10,shape=len(miss_workers))
            import pytensor.tensor as pt
            x=pt.as_tensor_variable(np.nan_to_num(x,nan=0))
            rows=np.flatnonzero(np.isnan(skill))
            codes=pd.Categorical(frame.iloc[rows].Worker,categories=miss_workers).codes
            x=pt.set_subtensor(x[rows],(latent[codes]-5)/scale.sd)
        eta=alpha+beta*x+u[wi]+v[gi]
        if likelihood=="wo_random_effect":
            wo_sd=pm.HalfNormal("wo_sd",sigma=1)
            # All rework rounds in one trajectory share a WO effect.
            eta=eta+pm.Normal("wo_z",0,1,shape=len(wo_labels))[wo_index]*wo_sd
            pm.Binomial("outcome",n=n.astype(int),p=pm.math.sigmoid(eta),observed=y.astype(int))
        else:
            phi=pm.LogNormal("phi",mu=np.log(20),sigma=1.5)
            prob=pm.math.sigmoid(eta)
            pm.BetaBinomial("outcome",n=n.astype(int),alpha=prob*phi,beta=(1-prob)*phi,observed=y.astype(int))
        trace=pm.sample(draws=draws,tune=tune,chains=chains,cores=1,random_seed=seed,target_accept=.95,
            nuts_sampler="pymc", progressbar=False,
            compile_kwargs={"mode": compile_mode} if compile_mode else {},
            return_inferencedata=True,idata_kwargs={"log_likelihood":False})
    posterior={}
    for name in ["alpha","beta","u","v","worker_sd","group_sd","wo_sd","phi","missing_skill", "missing_skill_mu", "missing_skill_sd"]:
        if name in trace.posterior:
            value=np.asarray(trace.posterior[name])
            posterior[name]=value.reshape((-1,)+value.shape[2:])
    return {"posterior":posterior,"trace":trace,"workers":workers,"groups":groups,"scaler":scale,
        "likelihood":likelihood,"missing_skill":missing_skill,"missing_workers":miss_workers,"network":network,
        "training_wos":frozenset(frame.WO),"training_last_date":frame.QC_Start.max(),
        "status":"Pilot Provisional; validation and approvals pending"}


def predict_quality(model,test,seed=42):
    """Frozen Train parameters; marginalize unseen entity and WO uncertainty."""
    if set(test.WO)&model["training_wos"]:
        raise ValueError("Evaluation WO was used for fitting")
    rng=np.random.default_rng(seed)
    posterior=model["posterior"]
    x=model["scaler"].transform(test.CertifiedSkill)
    if not np.isfinite(x).all() and model.get("missing_skill") != "hierarchical":
        raise ValueError("Use a common observed historical-skill test cohort for candidate comparison")
    xx=np.broadcast_to(x, (len(posterior["alpha"]),len(test))).copy()
    if np.isnan(x).any():
        from scipy.stats import truncnorm
        mu=posterior.get("missing_skill_mu",np.full(len(xx),5.))
        sd=posterior.get("missing_skill_sd",np.full(len(xx),2.))
        for worker in test.loc[test.CertifiedSkill.isna(),"Worker"].unique():
            positions=np.flatnonzero(test.Worker.eq(worker) & test.CertifiedSkill.isna())
            if worker in model.get("missing_workers",[]):
                latent=posterior["missing_skill"][:,model["missing_workers"].index(worker)]
            else:
                latent=truncnorm.rvs((0-mu)/sd,(10-mu)/sd,loc=mu,scale=sd,random_state=rng)
            xx[:,positions]=((latent-5)/model["scaler"].sd)[:,None]
    eta=posterior["alpha"][:,None]+posterior["beta"][:,None]*xx
    unknown_worker=~test.Worker.isin(model["workers"])
    unknown_group=~test[GROUP].isin(model["groups"])
    for column,labels,effect,sd in [("Worker",model["workers"],"u","worker_sd"),(GROUP,model["groups"],"v","group_sd")]:
        for value in test[column].unique():
            positions=np.flatnonzero(test[column].eq(value))
            samples=posterior[effect][:,labels.index(value)] if value in labels else rng.normal(0,posterior[sd])
            eta[:,positions]+=samples[:,None]
    if model["likelihood"]=="wo_random_effect":
        for wo in test.WO.unique():
            positions=np.flatnonzero(test.WO.eq(wo))
            eta[:,positions]+=(rng.normal(size=len(eta))*posterior["wo_sd"])[:,None]
    probabilities=1/(1+np.exp(-np.clip(eta,-700,700)))
    out=test[[c for c in ["WO","RoundNo","Worker",GROUP,"Process","PassQty","InspectedQty", "PlannerSkillStatus", "RetrospectivePlanner", "CertifiedSkill", "Branch"] if c in test]].copy()
    out["PredictedFPY"]=probabilities.mean(axis=0)
    out["Lower05FPY"],out["Upper95FPY"]=np.quantile(probabilities,[.05,.95],axis=0)
    out["UnseenWorker"]=unknown_worker.to_numpy()
    out["UnseenGroup"]=unknown_group.to_numpy()
    return out


def quality_metrics(prediction):
    y=prediction.PassQty.to_numpy(float)
    n=prediction.InspectedQty.to_numpy(float)
    p=np.clip(prediction.PredictedFPY.to_numpy(float),1e-12,1-1e-12)
    return {"WO N":len(prediction),"Piece N":float(n.sum()),
        "Piece Log Loss":float(-(y*np.log(p)+(n-y)*np.log1p(-p)).sum()/n.sum()),
        "Piece Brier":float((y*(1-p)**2+(n-y)*p**2).sum()/n.sum()),
        "ObservedFPY":float(y.sum()/n.sum()),"PredictedFPY":float((n*p).sum()/n.sum())}
