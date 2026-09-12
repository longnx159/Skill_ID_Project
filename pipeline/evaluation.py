"""Model metrics, planner agreement, and outlier analysis."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)


def _rank(values: np.ndarray) -> np.ndarray:
    """Return average ranks without requiring SciPy."""
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    sorted_values = values[order]
    start = 0
    while start < len(values):
        end = start + 1
        while (
            end < len(values)
            and sorted_values[end] == sorted_values[start]
        ):
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2 + 1
        start = end
    return ranks


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    """Compute Pearson correlation for finite arrays."""
    if len(x) < 2 or np.std(x) == 0 or np.std(y) == 0:
        return np.nan
    return float(np.corrcoef(x, y)[0, 1])


def _kendall_tau(x: np.ndarray, y: np.ndarray) -> float:
    """Compute Kendall's tau-b using vectorized concordant/discordant pairs."""
    n = len(x)
    if n < 2:
        return np.nan
    # Vectorized: compute all pairwise differences via broadcasting
    dx = x[np.newaxis, :] - x[:, np.newaxis]  # (n, n) upper triangle
    dy = y[np.newaxis, :] - y[:, np.newaxis]
    # Use only upper triangle (i < j) to avoid double-counting
    mask = np.triu(np.ones((n, n), dtype=bool), k=1)
    prod = dx[mask] * dy[mask]
    concordant = int(np.sum(prod > 0))
    discordant = int(np.sum(prod < 0))
    ties_x = int(np.sum((dx[mask] == 0) & (dy[mask] != 0)))
    ties_y = int(np.sum((dx[mask] != 0) & (dy[mask] == 0)))
    denom = np.sqrt(
        (concordant + discordant + ties_x)
        * (concordant + discordant + ties_y)
    )
    return float((concordant - discordant) / denom) if denom else np.nan


def regression_metrics(
    y: pd.Series,
    pred: pd.Series,
    weights: pd.Series | None = None,
) -> dict[str, float]:
    """Return RMSE, MAE, and weighted R-squared."""
    yv = np.asarray(y, float)
    pv = np.asarray(pred, float)
    resid = yv - pv
    w = np.ones(len(yv)) if weights is None else np.asarray(weights, float)
    mean = np.average(yv, weights=w)
    ss_res = np.average(resid**2, weights=w)
    ss_tot = np.average((yv - mean) ** 2, weights=w)
    r2 = float(1 - ss_res / ss_tot) if np.any(yv != mean) else np.nan
    return {
        "RMSE": float(np.sqrt(ss_res)),
        "MAE": float(np.average(np.abs(resid), weights=w)),
        "R2": r2,
    }


def compare_planner(
    worker_scores: pd.DataFrame,
    planner: pd.DataFrame,
    score_col: str,
) -> pd.DataFrame:
    """Calculate Pearson, Spearman, Kendall, and OLS agreement by process."""
    left = worker_scores.rename(columns={"Worker": "Worker ID"})
    if "Worker ID" in left:
        merged = planner.merge(
            left[["Worker ID", score_col]], on="Worker ID", how="inner"
        )
    else:
        merged = planner.merge(left, on="Worker ID", how="inner")

    rows: list[dict] = []
    for process, g in merged.groupby("Process", dropna=False):
        x = g[score_col].astype(float)
        y = g["Planner Verified Skill Level"].astype(float)
        xv, yv = x.to_numpy(), y.to_numpy()
        pearson = _pearson(xv, yv)
        spearman = _pearson(_rank(xv), _rank(yv))
        kendall = _kendall_tau(xv, yv)
        if len(g) >= 2 and x.nunique() > 1:
            slope, intercept = np.polyfit(x, y, 1)
        else:
            slope, intercept = np.nan, np.nan
        rows.append({
            "Process": process,
            "N": len(g),
            "Pearson": pearson,
            "Spearman": spearman,
            "Kendall": kendall,
            "Slope": slope,
            "Intercept": intercept,
            "R2": pearson**2 if pd.notna(pearson) else np.nan,
        })

    return pd.DataFrame(rows)


def identify_outliers(
    worker_scores: pd.DataFrame,
    planner: pd.DataFrame,
    score_col: str,
) -> pd.DataFrame:
    """Flag large planner-model discrepancies using standardized z scores."""
    scores = (
        worker_scores.rename(columns={"Worker": "Worker ID"})[
            ["Worker ID", score_col]
        ]
        .drop_duplicates()
    )
    p = (
        planner.groupby("Worker ID", as_index=False)[
            "Planner Verified Skill Level"
        ].mean()
    )
    out = p.merge(scores, on="Worker ID", how="inner")
    out["Residual"] = out["Planner Verified Skill Level"] - out[score_col]
    sd = out["Residual"].std(ddof=1)
    if sd and np.isfinite(sd):
        out["Standardized residual"] = out["Residual"] / sd
        out["Z score"] = (
            (out["Residual"] - out["Residual"].mean()) / sd
        )
    else:
        out["Standardized residual"] = 0.0
        out["Z score"] = 0.0
    out["Flag"] = out["Z score"].abs().ge(2.0)

    LOGGER.debug(
        "Outlier analysis: %d workers, %d flagged",
        len(out),
        out["Flag"].sum(),
    )
    return out.sort_values(
        "Z score", key=lambda s: s.abs(), ascending=False
    )
