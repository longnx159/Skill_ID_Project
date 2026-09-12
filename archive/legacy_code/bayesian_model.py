"""Optional Bambi/PyMC hierarchical model."""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)


def fit_bayesian_model(
    df: pd.DataFrame,
    chains: int = 4,
    warmup: int = 1000,
    draws: int = 2000,
) -> dict:
    """Fit Bambi when available, otherwise PyMC, and return posterior summaries."""
    cache_dir = Path.cwd() / ".pytensor_cache"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        # PyTensor's config parser requires quoting paths with spaces.
        os.environ.setdefault(
            "PYTENSOR_FLAGS",
            f"compiledir='{cache_dir}',linker=py",
        )
        os.environ.setdefault(
            "NUMBA_CACHE_DIR", str(cache_dir / "numba")
        )
        (cache_dir / "numba").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        LOGGER.warning("Could not create local PyTensor cache: %s", exc)

    try:
        import bambi as bmb
    except ImportError:
        try:
            import pymc as pm  # noqa: F401
            import arviz as az  # noqa: F401
        except ImportError:
            return {
                "status": "skipped",
                "reason": "Bambi and PyMC are not installed",
            }
        return {
            "status": "skipped",
            "reason": (
                "PyMC fallback requires a Bambi-compatible formula "
                "adapter; install bambi for automatic fitting"
            ),
        }

    start = time.perf_counter()
    data = df.copy()
    data["Item"] = data["Item Number"].astype(str)
    data["Product_Type"] = data["Product Type"].astype(str)

    try:
        # Use a formula-safe column name; Q(...) is not available in
        # all formulae/Bambi versions.
        model = bmb.Model(
            "log_time ~ Material + Product_Type + (1|Worker) + (1|Item)",
            data,
        )
    except Exception as exc:
        LOGGER.exception("Bayesian model construction failed")
        return {"status": "failed", "reason": str(exc)}

    try:
        idata = model.fit(
            draws=draws,
            tune=warmup,
            chains=chains,
            cores=1,
            target_accept=0.9,
        )
    except Exception as exc:
        LOGGER.exception("Bayesian model failed")
        return {"status": "failed", "reason": str(exc)}

    posterior = idata.posterior
    worker_var = next(
        (
            v
            for v in posterior.data_vars
            if "Worker" in v and "offset" in v
        ),
        None,
    )
    item_var = next(
        (
            v
            for v in posterior.data_vars
            if "Item" in v and "offset" in v
        ),
        None,
    )

    worker = pd.DataFrame()
    item = pd.DataFrame()
    if worker_var:
        arr = posterior[worker_var].mean(dim=("chain", "draw"))
        worker = pd.DataFrame({
            "Worker": arr.coords[arr.dims[-1]].values,
            "Bayesian Worker Ability": np.asarray(arr).ravel(),
        })
    if item_var:
        arr = posterior[item_var].mean(dim=("chain", "draw"))
        item = pd.DataFrame({
            "Item Number": arr.coords[arr.dims[-1]].values,
            "Bayesian Item Difficulty": np.asarray(arr).ravel(),
        })

    return {
        "status": "ok",
        "idata": idata,
        "worker_scores": worker,
        "item_scores": item,
        "runtime_seconds": time.perf_counter() - start,
    }
