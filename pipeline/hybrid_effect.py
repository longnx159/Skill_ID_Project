"""Gaussian random-worker / fixed-item aggregate-time diagnostic using EM.

Worker effects are integrated in the likelihood. Conditional worker uncertainty
does not include uncertainty in item effects or fitted variance parameters.
"""
from __future__ import annotations
import time
import numpy as np
import pandas as pd


def fit_hybrid_effect(df: pd.DataFrame,max_iter=500,tol=1e-7):
    start=time.perf_counter()
    y=df.log_time.to_numpy(float)
    if not len(y) or not np.isfinite(y).all():
        raise ValueError("Time model requires finite, nonempty log_time")
    workers,wi=np.unique(df.Worker.astype(str),return_inverse=True)
    items,ii=np.unique(df["Item Number"].astype(str),return_inverse=True)
    quantity=pd.to_numeric(df.get("Qty Doing",pd.Series(1.,index=df.index)),errors="coerce").to_numpy(float)
    if not np.isfinite(quantity).all() or (quantity<=0).any():
        raise ValueError("Time-model reliability quantities must be positive and finite")
    # Provisional reliability convention: square-root quantity, normalized to
    # unit mean. This is a precision assumption, not a worker performance bonus.
    weight=np.sqrt(quantity)
    weight/=weight.mean()
    ww=np.bincount(wi,weights=weight,minlength=len(workers))
    iw=np.bincount(ii,weights=weight,minlength=len(items))
    mu=float(np.average(y,weights=weight))
    item=np.zeros(len(items))
    worker=np.zeros(len(workers))
    sigma2=max(float(np.average((y-mu)**2,weights=weight)),1e-8)
    tau2=max(sigma2*.1,1e-8)
    old_ll=-np.inf
    converged=False
    for iteration in range(max_iter):
        # E: exact posterior random intercept, conditional on current fixed terms.
        posterior_var=1/(1/tau2+ww/sigma2)
        residual=y-mu-item[ii]
        worker=posterior_var*np.bincount(wi,weights=weight*residual,minlength=len(workers))/sigma2
        # M: update fixed Item effects, weighted intercept, variance components.
        raw_item=np.bincount(ii,weights=weight*(y-worker[wi]),minlength=len(items))/iw
        mu=float(np.average(raw_item,weights=iw))
        item=raw_item-mu
        residual=y-mu-item[ii]-worker[wi]
        sigma2=max(float(np.mean(weight*(residual**2+posterior_var[wi]))),1e-10)
        tau2=max(float(np.mean(worker**2+posterior_var)),1e-10)
        # Exact marginal likelihood via random-intercept block determinant lemma.
        marginal_residual=y-mu-item[ii]
        sums=np.bincount(wi,weights=weight*marginal_residual,minlength=len(workers))
        logdet=np.log(sigma2/weight).sum()+np.log1p(tau2*ww/sigma2).sum()
        quad=(weight*marginal_residual**2).sum()/sigma2-(tau2*sums**2/(sigma2*(sigma2+tau2*ww))).sum()
        ll=float(-.5*(len(y)*np.log(2*np.pi)+logdet+quad))
        if iteration>1 and abs(ll-old_ll)<=tol*(1+abs(old_ll)):
            converged=True
            break
        old_ll=ll
    posterior_var=1/(1/tau2+ww/sigma2)
    worker=posterior_var*np.bincount(wi,weights=weight*(y-mu-item[ii]),minlength=len(workers))/sigma2
    prediction=mu+item[ii]+worker[wi]
    residual=y-prediction
    se=np.sqrt(posterior_var)
    item_var=float(np.average(item**2,weights=iw))
    total=tau2+item_var+sigma2
    sst=float(((y-y.mean())**2).sum())
    k=len(items)+2  # fixed group means plus two variance components
    return {"status":"ok","estimator":"Gaussian random-intercept EM (diagnostic)","intercept":mu,
        "worker_scores":pd.DataFrame({"Worker":workers,"Hybrid Worker Effect":worker,"Hybrid Worker Ability":-worker,
            "Hybrid Ability Lower 95%":-worker-1.96*se,"Hybrid Ability Upper 95%":-worker+1.96*se,
            "Hybrid Ability SE":se,"Worker Records":np.bincount(wi,minlength=len(workers))}),
        "item_scores":pd.DataFrame({"Item Number":items,"Hybrid Item FE":item}),
        "predictions":pd.Series(prediction,index=df.index),
        "metrics":{"RMSE":float(np.sqrt(np.mean(residual**2))),"MAE":float(np.mean(np.abs(residual))),"R2":1-float((residual**2).sum())/sst if sst else np.nan},
        "AIC":-2*ll+2*k,"BIC":-2*ll+np.log(len(y))*k,
        "variance_components":pd.DataFrame({"Component":["Worker random effect","Item fixed effects","Residual"],"Variance":[tau2,item_var,sigma2],"Share":[tau2/total,item_var/total,sigma2/total]}),
        "runtime_seconds":time.perf_counter()-start,"iterations":iteration+1,"converged":converged,
        "log_likelihood":ll,"interval_method":"Conditional Gaussian worker posterior; diagnostic only"}
