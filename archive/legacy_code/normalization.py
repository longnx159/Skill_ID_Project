"""Business-facing monotonic 0-10 scoring and confidence calculations."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)


def minmax_score(
    values: pd.Series,
    higher_is_better: bool = True,
) -> pd.Series:
    """Map observed values monotonically to 0-10 using observed min/max."""
    x = pd.to_numeric(values, errors="coerce")
    lo, hi = x.min(), x.max()
    if pd.isna(lo) or hi == lo:
        return pd.Series(5.0, index=values.index)
    score = 10 * (x - lo) / (hi - lo)
    return score if higher_is_better else 10 - score


def confidence_label(score: pd.Series) -> pd.Series:
    """Convert continuous confidence to transparent High/Medium/Low labels."""
    return pd.cut(
        score,
        bins=[-np.inf, 40, 70, np.inf],
        labels=["Low", "Medium", "High"],
    ).astype("string")


def item_confidence(
    items: pd.DataFrame,
    residual_sd: float,
) -> pd.DataFrame:
    """Calculate item confidence from observations, worker coverage, and uncertainty.

    Returns a **copy** with Confidence Score and Confidence columns added.
    """
    out = items.copy()
    n_col = (
        "Number of Observations"
        if "Number of Observations" in out
        else "Number of Production Records"
    )
    w_col = (
        "Number of Unique Workers"
        if "Number of Unique Workers" in out
        else "Number of Different Workers"
    )
    n = out[n_col].clip(lower=1)
    workers = out[w_col].clip(lower=1)
    uncertainty = (
        out.get("Model SE", pd.Series(residual_sd, index=out.index))
        .fillna(residual_sd)
        .clip(lower=1e-8)
    )

    score = 100 * (
        0.45 * (1 - np.exp(-n / 20))
        + 0.35 * (1 - np.exp(-workers / 5))
        + 0.20 * (1 / (1 + uncertainty / max(residual_sd, 1e-8)))
    )
    out["Confidence Score"] = score.clip(0, 100).round(2)
    out["Confidence"] = confidence_label(out["Confidence Score"])

    LOGGER.debug(
        "Item confidence: %d items, mean=%.1f",
        len(out),
        out["Confidence Score"].mean(),
    )
    return out


def worker_confidence(
    workers: pd.DataFrame,
    residual_sd: float,
) -> pd.DataFrame:
    """Calculate worker confidence from records, item coverage, and uncertainty.

    Returns a **copy** with Confidence Score and Confidence columns added.
    """
    out = workers.copy()
    n_col = (
        "Number of Observations"
        if "Number of Observations" in out
        else "Number of Records"
    )
    item_col = "Number of Different Items"
    n = out[n_col].clip(lower=1)
    items = out[item_col].clip(lower=1)
    uncertainty = (
        out.get("Model SE", pd.Series(residual_sd, index=out.index))
        .fillna(residual_sd)
        .clip(lower=1e-8)
    )

    score = 100 * (
        0.45 * (1 - np.exp(-n / 30))
        + 0.35 * (1 - np.exp(-items / 8))
        + 0.20 * (1 / (1 + uncertainty / max(residual_sd, 1e-8)))
    )
    out["Confidence Score"] = score.clip(0, 100).round(2)
    out["Confidence"] = confidence_label(out["Confidence Score"])

    LOGGER.debug(
        "Worker confidence: %d workers, mean=%.1f",
        len(out),
        out["Confidence Score"].mean(),
    )
    return out
