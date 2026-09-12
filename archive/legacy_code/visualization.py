"""Optional matplotlib visualizations."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)


def generate_visualizations(
    worker_scores: pd.DataFrame,
    observations: pd.DataFrame,
    planner: pd.DataFrame,
    bayesian: dict,
    output_dir: Path,
) -> None:
    """Generate the requested plots when matplotlib is installed."""
    try:
        import matplotlib.pyplot as plt
        from statistics import NormalDist
    except ImportError:
        LOGGER.warning("matplotlib is not installed; skipping plots")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    score = "Fixed Worker Ability"

    # --- Histograms ---
    histogram_specs = [
        (
            "Worker ability histogram",
            worker_scores[score],
            "worker_ability_histogram.png",
        ),
        (
            "Residual histogram",
            observations["fixed_residual"],
            "residual_histogram.png",
        ),
    ]
    for title, values, filename in histogram_specs:
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.hist(values.dropna(), bins=30, edgecolor="white")
        ax.set_title(title)
        fig.tight_layout()
        fig.savefig(output_dir / filename, dpi=150)
        plt.close(fig)

    # --- QQ plot ---
    # Planner-vs-ability plots are generated exclusively per Process by
    # make_scatterplot.create_scatterplot; do not create an aggregate chart.
    residuals = (
        observations["fixed_residual"]
        .dropna()
        .sort_values()
        .to_numpy()
    )
    n = len(residuals)
    if n:
        theoretical = np.array(
            [NormalDist().inv_cdf((i + 0.5) / n) for i in range(n)]
        )
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.scatter(theoretical, residuals)
        ax.set(
            xlabel="Theoretical normal quantiles",
            ylabel="Residual quantiles",
            title="Residual QQ plot",
        )
        fig.tight_layout()
        fig.savefig(output_dir / "residual_qq.png", dpi=150)
        plt.close(fig)

    # --- Worker ranking charts (per Process) ---
    ranking = worker_scores.copy()
    if "Worker ID" in planner.columns:
        if "Department" in planner.columns:
            active_ids = planner.loc[
                planner["Department"].notna()
                & planner["Department"].astype(str).str.strip().ne(""),
                "Worker ID",
            ].drop_duplicates()
            ranking = ranking[
                ranking["Worker"].isin(active_ids)
            ].copy()

        if "Name" in planner.columns:
            names = (
                planner[["Worker ID", "Name"]]
                .drop_duplicates("Worker ID")
                .rename(columns={"Worker ID": "Worker"})
            )
        else:
            names = (
                planner[["Worker ID"]]
                .drop_duplicates("Worker ID")
                .rename(columns={"Worker ID": "Worker"})
            )
        ranking = ranking.merge(names, on="Worker", how="left")

    ranking["Display Name"] = ranking.apply(
        lambda row: f"{row.get('Name', 'Unknown')} — {row['Worker']}",
        axis=1,
    )

    ranking_groups = (
        ranking.groupby("Process", dropna=False)
        if "Process" in ranking.columns
        else [(None, ranking)]
    )

    for process, process_frame in ranking_groups:
        safe_process = (
            ""
            if process is None or pd.isna(process)
            else "_" + str(process).lower().replace(" ", "_")
        )
        top = (
            process_frame.sort_values(score, ascending=False)
            .head(50)
            .sort_values(score)
        )
        bottom = (
            process_frame.sort_values(score, ascending=True)
            .head(50)
            .sort_values(score, ascending=False)
        )

        label = f" - {process}" if process else ""
        plots = [
            (
                top,
                f"Top 50 Worker Capability{label}",
                f"top_50_worker_ranking{safe_process}.png",
            ),
            (
                bottom,
                f"Bottom 50 Worker Capability{label}",
                f"bottom_50_worker_ranking{safe_process}.png",
            ),
        ]

        for frame, title, filename in plots:
            fig, ax = plt.subplots(figsize=(11, 13))
            ax.barh(
                frame["Display Name"], frame[score], color="#2f78b7"
            )
            ax.set_title(title)
            ax.set_xlabel(
                "Worker Capability (higher = faster performance)"
            )
            ax.grid(axis="x", alpha=0.2)
            fig.tight_layout()
            fig.savefig(output_dir / filename, dpi=150)
            plt.close(fig)

    # --- Bayesian posterior (informational only) ---
    if (
        isinstance(bayesian, dict)
        and bayesian.get("status") == "ok"
        and not bayesian["worker_scores"].empty
    ):
        LOGGER.info(
            "Bayesian posterior interval plot requires ArviZ "
            "variable metadata; posterior summaries were exported"
        )
