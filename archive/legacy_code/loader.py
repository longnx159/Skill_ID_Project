"""Excel input loading and schema normalization."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

LOGGER = logging.getLogger(__name__)


def _find_workbook(path: Path, keywords: tuple[str, ...]) -> Path:
    """Resolve an input path, allowing Unicode-safe keyword discovery."""
    if path.exists():
        return path
    for candidate in Path.cwd().glob("*.xlsx"):
        if all(
            k.casefold() in candidate.name.casefold() for k in keywords
        ):
            return candidate
    raise FileNotFoundError(f"Could not locate workbook {path!s}")


def load_workbooks(
    raw_path: Path,
    planner_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load raw production and planner verification workbooks."""
    raw = _find_workbook(raw_path, ("Raw",))
    planner = _find_workbook(planner_path, ("Verified", "Planner"))
    LOGGER.info("Loading raw data from %s", raw)
    LOGGER.info("Loading planner data from %s", planner)
    raw_df = pd.read_excel(raw)
    planner_df = pd.read_excel(planner)
    return raw_df, planner_df
