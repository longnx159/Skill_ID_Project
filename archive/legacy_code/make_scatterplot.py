"""Create a presentation-ready Planner versus Worker Ability scatterplot."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    pass

LOGGER = logging.getLogger(__name__)


def create_scatterplot(
    output_dir: Path = Path("output"),
    workers: pd.DataFrame | None = None,
    planner: pd.DataFrame | None = None,
    raw: pd.DataFrame | None = None,
) -> Path:
    """Create one scatterplot per process.

    Parameters
    ----------
    output_dir:
        Directory to write PNG files into.
    workers:
        Worker capability library (output of the pipeline). When *None*,
        falls back to reading ``worker_scores.xlsx`` from *output_dir*.
    planner:
        Cleaned planner DataFrame. When *None*, falls back to reading
        the planner workbook from disk.
    raw:
        Raw production DataFrame, used only to look up worker names and
        active departments. When *None*, falls back to file discovery.
    """
    import matplotlib.pyplot as plt

    # ------------------------------------------------------------------
    # Resolve DataFrames — prefer parameters, fall back to disk
    # ------------------------------------------------------------------
    if workers is None:
        scores_path = output_dir / "worker_scores.xlsx"
        LOGGER.info("Loading worker scores from %s", scores_path)
        workers = pd.read_excel(scores_path)

    if planner is None:
        LOGGER.info("Loading planner from disk (fallback)")
        planner = pd.read_excel("Verified Skill Level - Planner.xlsx")

    # Enrich planner with names / active-department filter from raw data
    if raw is not None and "Name" in raw.columns:
        raw_names = (
            raw[["Worker", "Name", "Department"]]
            .dropna(subset=["Worker", "Name"])
            .drop_duplicates("Worker")
            .rename(columns={"Worker": "Worker ID"})
        )
        active_ids = raw_names.loc[
            raw_names["Department"].notna()
            & raw_names["Department"].astype(str).str.strip().ne(""),
            "Worker ID",
        ].drop_duplicates()
        planner = planner[planner["Worker ID"].isin(active_ids)].copy()
        planner = planner.merge(
            raw_names, on="Worker ID", how="left", suffixes=("", "_raw")
        )
        planner["Name"] = (
            planner
            .get("Name", pd.Series(index=planner.index, dtype="string"))
            .fillna(planner.get("Name_raw"))
        )
        if "Name_raw" in planner.columns:
            planner = planner.drop(columns=["Name_raw"])
    elif raw is None:
        # Legacy fallback: discover raw workbook on disk
        raw_candidates = list(Path(".").glob("Raw*.xlsx"))
        if raw_candidates:
            raw_path = raw_candidates[0]
            LOGGER.info("Loading raw names from %s (fallback)", raw_path)
            raw_names = pd.read_excel(
                raw_path, usecols=["Worker", "Name", "Department"]
            )
            active_ids = raw_names.loc[
                raw_names["Department"].notna()
                & raw_names["Department"].astype(str).str.strip().ne(""),
                "Worker",
            ].drop_duplicates()
            raw_names = (
                raw_names.dropna(subset=["Worker", "Name"])
                .drop_duplicates("Worker")
                .rename(columns={"Worker": "Worker ID"})
            )
            planner = planner[
                planner["Worker ID"].isin(active_ids)
            ].copy()
            planner = planner.merge(
                raw_names, on="Worker ID", how="left", suffixes=("", "_raw")
            )
            planner["Name"] = (
                planner
                .get(
                    "Name",
                    pd.Series(index=planner.index, dtype="string"),
                )
                .fillna(planner.get("Name_raw"))
            )
            if "Name_raw" in planner.columns:
                planner = planner.drop(columns=["Name_raw"])

    # ------------------------------------------------------------------
    # Identify the score column
    # ------------------------------------------------------------------
    score_col = next(
        (
            c
            for c in [
                "Hybrid Worker Ability",
                "Fixed Worker Ability",
                "Capability Score",
                "Capability Score (0-10)",
            ]
            if c in workers.columns
        ),
        None,
    )
    if score_col is None:
        raise ValueError(
            "worker scores have no recognized capability score column"
        )

    score_columns = (
        ["Worker", "Process", score_col]
        if "Process" in workers.columns
        else ["Worker", score_col]
    )
    scores = workers[score_columns].rename(columns={"Worker": "Worker ID"})

    if "Name" not in planner.columns:
        planner["Name"] = planner["Worker ID"]

    join_columns = (
        ["Worker ID", "Process"]
        if "Process" in scores.columns
        else ["Worker ID"]
    )
    merged = planner.merge(scores, on=join_columns, how="inner").dropna(
        subset=[score_col, "Planner Verified Skill Level"]
    )

    # ------------------------------------------------------------------
    # Generate one chart per process
    # ------------------------------------------------------------------
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    for process, group in merged.groupby("Process", dropna=False):
        process_name = str(process) if pd.notna(process) else "Unknown"
        safe_name = (
            re.sub(r"[^A-Za-z0-9]+", "_", process_name)
            .strip("_")
            .lower()
            or "unknown"
        )

        fig, ax = plt.subplots(figsize=(9, 7))
        ax.scatter(
            group[score_col],
            group["Planner Verified Skill Level"],
            s=52,
            alpha=0.75,
            color="#2f78b7",
            edgecolor="white",
            linewidth=0.5,
        )

        for _, row in group.iterrows():
            worker_name = (
                str(row["Name"]) if pd.notna(row["Name"]) else "Unknown"
            )
            worker_id = str(row["Worker ID"])
            ax.annotate(
                f"{worker_name} — {worker_id}",
                (row[score_col], row["Planner Verified Skill Level"]),
                xytext=(3, 3),
                textcoords="offset points",
                fontsize=5.5,
                alpha=0.78,
            )

        if len(group) >= 2 and group[score_col].nunique() > 1:
            slope, intercept = np.polyfit(
                group[score_col],
                group["Planner Verified Skill Level"],
                1,
            )
            x = np.linspace(
                group[score_col].min(), group[score_col].max(), 100
            )
            ax.plot(
                x,
                slope * x + intercept,
                color="#222222",
                linewidth=2,
                label="Trend line",
            )
            r = group[score_col].corr(
                group["Planner Verified Skill Level"]
            )
            annotation = (
                f"Pearson r = {r:.2f}\nWorkers = {len(group):,}"
            )
        else:
            annotation = f"Workers = {len(group):,}"

        ax.text(
            0.03,
            0.96,
            annotation,
            transform=ax.transAxes,
            va="top",
            bbox={
                "facecolor": "white",
                "alpha": 0.88,
                "edgecolor": "#cccccc",
            },
        )
        ax.set_title(
            f"{process_name}: Planner Skill vs Worker Ability",
            fontsize=15,
            weight="bold",
        )
        ax.set_xlabel("Model Worker Ability (higher = faster performance)")
        ax.set_ylabel("Planner Verified Skill Level")
        ax.grid(alpha=0.2)
        if len(group) >= 2 and group[score_col].nunique() > 1:
            ax.legend(frameon=True)
        fig.tight_layout()

        path = output_dir / f"planner_vs_ability_{safe_name}.png"
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        paths.append(path)

    return paths[0] if paths else output_dir / "planner_vs_ability.png"


if __name__ == "__main__":
    print(create_scatterplot())
