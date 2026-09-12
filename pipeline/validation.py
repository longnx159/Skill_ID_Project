"""Cross-validation, adjusted R-squared, and planner validation."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from collections.abc import Callable

import numpy as np
import pandas as pd

from .evaluation import compare_planner, regression_metrics

LOGGER = logging.getLogger(__name__)

# Type alias for model fitter functions
ModelFitter = Callable[[pd.DataFrame], dict]


def adjusted_r2(r2: float, n: int, parameters: int) -> float:
    """Calculate adjusted R-squared with a safe small-sample rule."""
    if n <= parameters + 1 or pd.isna(r2):
        return np.nan
    return float(1 - (1 - r2) * (n - 1) / (n - parameters - 1))


def _predict_from_effects(
    result: dict,
    test: pd.DataFrame,
) -> pd.Series:
    """Predict held-out rows from fitted item/worker effects with mean fallback."""
    worker_scores = result["worker_scores"].set_index("Worker")
    item_scores = result["item_scores"].set_index("Item Number")
    worker_col = next(
        (c for c in worker_scores if "Effect" in c), None
    )
    item_col = next((c for c in item_scores if "FE" in c), None)
    mu = float(result.get("intercept", 0.0))
    w = (
        test["Worker"].map(worker_scores[worker_col]).fillna(0)
        if worker_col
        else 0
    )
    i = (
        test["Item Number"].map(item_scores[item_col]).fillna(0)
        if item_col
        else 0
    )
    return mu + w + i


def cross_validate_effect_model(
    df: pd.DataFrame,
    fitter: ModelFitter,
    folds: int = 3,
    seed: int = 42,
    evaluation_workers: set[str] | None = None,
) -> dict:
    """Evaluate a model while scoring only Planner-evaluated workers."""
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(df))
    fold_ids = np.empty(len(df), dtype=int)
    fold_ids[order] = np.arange(len(df)) % folds

    rows: list[dict] = []
    for fold in range(folds):
        train = df.iloc[fold_ids != fold]
        test = df.iloc[fold_ids == fold]
        result = fitter(train)
        if result is None or result.get("status", "ok") != "ok":
            continue
        if evaluation_workers is not None:
            test = test[
                test["Worker"].astype(str).isin(evaluation_workers)
            ]
        if len(test) == 0:
            continue
        predictions = _predict_from_effects(result, test)
        metrics = regression_metrics(test["log_time"], predictions)
        metrics["Fold"] = fold + 1
        metrics["N"] = len(test)
        rows.append(metrics)

    frame = pd.DataFrame(rows)
    if frame.empty:
        LOGGER.warning("Cross-validation: all folds failed or empty")
        return {"status": "failed", "folds": frame}

    summary = {
        key: float(frame[key].mean()) for key in ["RMSE", "MAE", "R2"]
    }
    summary["Adjusted R2"] = adjusted_r2(
        summary["R2"], int(frame["N"].sum()), 2
    )
    LOGGER.info(
        "CV complete: %d folds, RMSE=%.4f, R2=%.4f",
        len(rows),
        summary["RMSE"],
        summary["R2"],
    )
    return {"status": "ok", "folds": frame, "summary": summary}


def planner_validation(
    worker_library: pd.DataFrame,
    planner: pd.DataFrame,
) -> pd.DataFrame:
    """Compare standardized capability with Planner Skill by process."""
    score_col = "Capability Score"
    rows: list[pd.DataFrame] = []

    for process, scores in worker_library.groupby("Process", dropna=False):
        subset = planner[planner["Process"].eq(process)].copy()
        result = compare_planner(
            scores[["Worker", score_col]], subset, score_col
        )
        rows.append(result)

    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
