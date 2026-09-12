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


def attach_asof_skill(first_round, planner):
    """A future/current undated Planner snapshot cannot become a historical feature."""
    require(planner,["Worker ID","Process","Planner Verified Skill Level","EffectiveFrom"],"Quality-model Planner data")
    p=planner.rename(columns={"Worker ID":"Worker","Planner Verified Skill Level":"CertifiedSkill"}).copy()
    p["EffectiveFrom"]=pd.to_datetime(p.EffectiveFrom,errors="coerce")
    out=first_round.merge(p[["Worker","Process","CertifiedSkill","EffectiveFrom"]],on=["Worker","Process"],how="left",validate="many_to_one")
    asof=out.EffectiveFrom.notna() & out.EffectiveFrom.le(out.QC_Start)
    out.loc[~asof,"CertifiedSkill"]=np.nan
    out["SkillAsOfStatus"]=np.where(asof,"Dated snapshot available at QC start","Missing historical skill")
    return out


def fit_quality_candidate(train, likelihood="beta_binomial", missing_skill="observed", draws=1000, tune=1000, chains=4, seed=42):
    """Fit process-specific noncentered worker/group effects using Train only.

    likelihood: beta_binomial or wo_random_effect (never both).
    missing_skill: observed (complete-case candidate A) or hierarchical (B).
    Priors are provisional; comparison and sensitivity review remain required.
    """
    require(train,["WO","Worker",GROUP,"Process","PassQty","InspectedQty","CertifiedSkill","QC_Start"],"Quality training")
    if likelihood not in ("beta_binomial","wo_random_effect") or missing_skill not in ("observed","hierarchical"):
        raise ValueError("Unknown quality candidate")
    if train.Process.nunique()!=1 or train.WO.duplicated().any():
        raise ValueError("Fit one Process and one first-round row per WO")
    if train.Worker.isna().any():
        raise ValueError("Explicit initial worker attribution required")
    # Mandatory sequencing: diagnostic output exists before importing/fitting GLMM.
    network=connectivity(train)
    scale=SkillScaler.fit(train.CertifiedSkill)
    frame=train.dropna(subset=["CertifiedSkill"]).copy() if missing_skill=="observed" else train.copy()
    if frame.empty:
        raise ValueError("No observed historical skills for quality fitting")
    workers=sorted(frame.Worker.unique())
    groups=sorted(frame[GROUP].unique())
    wi=pd.Categorical(frame.Worker,categories=workers).codes
    gi=pd.Categorical(frame[GROUP],categories=groups).codes
    y=frame.PassQty.to_numpy(dtype=float)
    n=frame.InspectedQty.to_numpy(dtype=float)
    if not (np.isfinite(y).all() and np.isfinite(n).all() and (y>=0).all() and (n>0).all() and (y<=n).all() and (y%1==0).all() and (n%1==0).all()):
        raise ValueError("Quality likelihood requires reconciled integer piece counts")
    try:
        import pymc as pm
    except ImportError as exc:
        raise RuntimeError("Optional quality candidates require: python -m pip install -r requirements-full.txt") from exc
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
            eta=eta+pm.Normal("wo_z",0,1,shape=len(frame))*wo_sd
            pm.Binomial("outcome",n=n.astype(int),p=pm.math.sigmoid(eta),observed=y.astype(int))
        else:
            phi=pm.LogNormal("phi",mu=np.log(20),sigma=1.5)
            prob=pm.math.sigmoid(eta)
            pm.BetaBinomial("outcome",n=n.astype(int),alpha=prob*phi,beta=(1-prob)*phi,observed=y.astype(int))
        trace=pm.sample(draws=draws,tune=tune,chains=chains,cores=1,random_seed=seed,target_accept=.95,
            return_inferencedata=True,idata_kwargs={"log_likelihood":True})
    posterior={}
    for name in ["alpha","beta","u","v","worker_sd","group_sd","wo_sd","phi"]:
        if name in trace.posterior:
            value=np.asarray(trace.posterior[name])
            posterior[name]=value.reshape((-1,)+value.shape[2:])
    return {"posterior":posterior,"trace":trace,"workers":workers,"groups":groups,"scaler":scale,
        "likelihood":likelihood,"missing_skill":missing_skill,"network":network,
        "training_wos":frozenset(frame.WO),"training_last_date":frame.QC_Start.max(),
        "status":"Pilot Provisional; validation and approvals pending"}


def predict_quality(model,test,seed=42):
    """Frozen Train parameters; marginalize unseen entity and WO uncertainty."""
    if set(test.WO)&model["training_wos"]:
        raise ValueError("Evaluation WO was used for fitting")
    rng=np.random.default_rng(seed)
    posterior=model["posterior"]
    x=model["scaler"].transform(test.CertifiedSkill)
    # Candidate comparison uses exactly the same observed-skill test WOs.
    if not np.isfinite(x).all():
        raise ValueError("Use a common observed historical-skill test cohort for candidate comparison")
    eta=posterior["alpha"][:,None]+posterior["beta"][:,None]*x[None,:]
    unknown_worker=~test.Worker.isin(model["workers"])
    unknown_group=~test[GROUP].isin(model["groups"])
    for column,labels,effect,sd in [("Worker",model["workers"],"u","worker_sd"),(GROUP,model["groups"],"v","group_sd")]:
        for value in test[column].unique():
            positions=np.flatnonzero(test[column].eq(value))
            samples=posterior[effect][:,labels.index(value)] if value in labels else rng.normal(0,posterior[sd])
            eta[:,positions]+=samples[:,None]
    if model["likelihood"]=="wo_random_effect":
        eta+=rng.normal(size=eta.shape)*posterior["wo_sd"][:,None]
    probabilities=1/(1+np.exp(-np.clip(eta,-700,700)))
    out=test[["WO","Worker",GROUP,"Process","PassQty","InspectedQty"]].copy()
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
