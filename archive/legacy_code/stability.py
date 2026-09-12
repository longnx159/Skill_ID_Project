"""Repeated-history stability analysis for static item difficulty."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from collections.abc import Callable

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)

# Type alias for model fitter functions
ModelFitter = Callable[[pd.DataFrame], dict]


def item_stability(
    df: pd.DataFrame,
    fitter: ModelFitter,
    repetitions: int = 10,
    seed: int = 42,
) -> pd.DataFrame:
    """Bootstrap item effects and return a 0-100 stability index per item."""
    rng = np.random.default_rng(seed)
    effects: list[pd.Series] = []

    for rep in range(repetitions):
        sample = df.iloc[rng.integers(0, len(df), len(df))]
        result = fitter(sample)
        if result.get("status") == "ok":
            frame = result["item_scores"].set_index("Item Number")
            col = next(c for c in frame.columns if "FE" in c)
            effects.append(frame[col].rename(len(effects)))

    if not effects:
        LOGGER.warning(
            "Stability: all %d bootstrap repetitions failed", repetitions
        )
        return pd.DataFrame(
            columns=[
                "Item Number",
                "Difficulty Stability Index",
                "Bootstrap SD",
            ]
        )

    matrix = pd.concat(effects, axis=1)
    sd = matrix.std(axis=1, ddof=1).fillna(0)
    scale = max(float(sd.quantile(0.95)), 1e-8)
    stability_index = (100 * (1 - sd / scale)).clip(0, 100).round(2)

    LOGGER.info(
        "Stability: %d/%d reps succeeded, %d items, mean index=%.1f",
        len(effects),
        repetitions,
        len(matrix),
        stability_index.mean(),
    )

    return pd.DataFrame({
        "Item Number": matrix.index.to_numpy(),
        "Bootstrap SD": sd.to_numpy(),
        "Difficulty Stability Index": stability_index.to_numpy(),
    }).reset_index(drop=True)
