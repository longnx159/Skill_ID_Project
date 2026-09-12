"""Two-way worker/item fixed-effect estimation by alternating least squares."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

try:
    from tqdm.auto import tqdm
except ImportError:  # Keep the fixed-effect stage runnable in a minimal env.
    def tqdm(iterable, **kwargs):
        """Fallback iterator when tqdm is not installed."""
        return iterable


@dataclass
class FixedEffectResult:
    """Outputs from the two-way fixed-effect model."""

    observations: pd.DataFrame
    worker_effects: pd.DataFrame
    item_effects: pd.DataFrame
    intercept: float
    iterations: int
    converged: bool


def fit_two_way_fixed_effect(
    df: pd.DataFrame,
    max_iter: int = 100,
    tol: float = 1e-8,
) -> FixedEffectResult:
    """Fit log_time = intercept + worker effect + item effect using ALS."""
    work = df[["Worker", "Item Number", "log_time"]].copy()
    quantity = (
        pd.to_numeric(
            df.get("Qty Doing", pd.Series(1.0, index=df.index)),
            errors="coerce",
        )
        .fillna(1)
        .clip(lower=1)
    )
    work["_weight"] = np.sqrt(quantity.to_numpy())

    mu = float(work.log_time.mean())
    worker = pd.Series(0.0, index=work["Worker"].unique())
    item = pd.Series(0.0, index=work["Item Number"].unique())
    converged = False
    iteration = 0

    for iteration in tqdm(
        range(max_iter), desc="Fixed-effect ALS", leave=False
    ):
        old = np.r_[worker.values, item.values, mu]

        # Worker update
        worker_residual = (
            work["log_time"] - mu - work["Item Number"].map(item)
        )
        worker = (
            (worker_residual * work["_weight"])
            .groupby(work["Worker"])
            .sum()
            / work["_weight"].groupby(work["Worker"]).sum()
        )

        # Item update
        item_residual = (
            work["log_time"] - mu - work["Worker"].map(worker)
        )
        item = (
            (item_residual * work["_weight"])
            .groupby(work["Item Number"])
            .sum()
            / work["_weight"].groupby(work["Item Number"]).sum()
        )

        # Intercept update
        final_residual = (
            work["log_time"]
            - work["Worker"].map(worker)
            - work["Item Number"].map(item)
        )
        mu = float(
            (final_residual * work["_weight"]).sum()
            / work["_weight"].sum()
        )

        now = np.r_[worker.values, item.values, mu]
        if np.max(np.abs(now - old)) < tol:
            converged = True
            break

    pred = mu + work["Worker"].map(worker) + work["Item Number"].map(item)
    obs = df.copy()
    obs["fixed_prediction"] = pred.to_numpy()
    obs["fixed_residual"] = obs["log_time"] - obs["fixed_prediction"]

    worker_frame = (
        worker.rename("Worker FE")
        .reset_index()
        .rename(columns={"index": "Worker"})
    )
    item_frame = (
        item.rename("Item FE")
        .reset_index()
        .rename(columns={"index": "Item Number"})
    )

    return FixedEffectResult(
        obs, worker_frame, item_frame, mu, iteration + 1, converged
    )
