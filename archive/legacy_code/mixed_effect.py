"""Linear mixed-effect model with optimizer retries."""
import logging
import time
import pandas as pd
from evaluation import regression_metrics

LOGGER = logging.getLogger(__name__)


def fit_mixed_effect(df: pd.DataFrame) -> dict:
    """Fit statsmodels MixedLM and retry lbfgs, bfgs, powell, and cg."""
    try:
        import statsmodels.formula.api as smf
    except ImportError:
        return {"status": "skipped", "reason": "statsmodels is not installed"}
    start = time.perf_counter()
    data = df.copy()
    data["Item_Number"] = data["Item Number"].astype(str)
    formula = "log_time ~ C(Material) + C(Quality_Product_Type)"
    data["Quality_Product_Type"] = data["Product Type"].astype(str)
    model = smf.mixedlm(formula, data, groups=data["Worker"], vc_formula={"Item": "0 + C(Item_Number)"}, re_formula="1")
    result = None; errors = []
    for method in ("lbfgs", "bfgs", "powell", "cg"):
        try:
            result = model.fit(reml=False, method=method, maxiter=1000, disp=False)
            if result.converged:
                break
        except Exception as exc:  # pragma: no cover - version-specific statsmodels failures
            errors.append(f"{method}: {exc}")
    if result is None:
        return {"status": "failed", "reason": "; ".join(errors)}
    pred = result.fittedvalues
    metrics = regression_metrics(data["log_time"], pred)
    workers = pd.DataFrame({"Worker": list(result.random_effects), "Mixed Worker Effect": [float(v.iloc[0]) for v in result.random_effects.values()]})
    return {"status": "ok", "result": result, "worker_scores": workers, "predictions": pred, "metrics": metrics, "AIC": result.aic, "BIC": result.bic, "variance_components": pd.DataFrame({"Component": ["Worker", "Residual"], "Variance": [float(result.cov_re.iloc[0, 0]), float(result.scale)]}), "runtime_seconds": time.perf_counter() - start}

