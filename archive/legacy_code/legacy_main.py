"""Process-specific statistical decision-support pipeline."""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING
from collections.abc import Callable

import numpy as np
import pandas as pd

from config import Config
from loader import load_workbooks
from preprocessing import clean_planner_data, clean_production_data
from fixed_effect import fit_two_way_fixed_effect
from hybrid_effect import fit_hybrid_effect
from bayesian_model import fit_bayesian_model
from evaluation import regression_metrics
from normalization import item_confidence, minmax_score, worker_confidence
from report import write_master_reports
from stability import item_stability
from validation import cross_validate_effect_model, planner_validation
from visualization import generate_visualizations
from make_scatterplot import create_scatterplot

LOGGER = logging.getLogger(__name__)

# Type alias for model fitter functions used by stability / validation
ModelFitter = Callable[[pd.DataFrame], dict]


def _fixed_adapter(frame: pd.DataFrame) -> dict:
    """Adapt Model A output to the common model result interface."""
    result = fit_two_way_fixed_effect(frame)
    worker_scores = result.worker_effects.rename(
        columns={"Worker FE": "Fixed Worker Effect"}
    )
    item_scores = result.item_effects.rename(
        columns={"Item FE": "Fixed Item FE"}
    )
    return {
        "status": "ok",
        "intercept": result.intercept,
        "worker_scores": worker_scores,
        "item_scores": item_scores,
        "predictions": result.observations["fixed_prediction"],
        "observations": result.observations,
        "metrics": regression_metrics(
            frame["log_time"],
            result.observations["fixed_prediction"],
        ),
        "converged": result.converged,
    }


def _fit_process_models(
    data: pd.DataFrame,
    planner: pd.DataFrame,
    config: Config,
) -> dict[str, dict]:
    """Fit completely independent Model A/B/C systems for each Process."""
    results: dict[str, dict] = {}

    for process, frame in data.groupby("Process", dropna=False):
        LOGGER.info("Fitting models for Process: %s (%d rows)", process, len(frame))
        try:
            results[str(process)] = _fit_single_process(
                process, frame, planner, config
            )
        except Exception:
            LOGGER.exception(
                "Process %s failed — skipping to next process", process
            )

    return results


def _fit_single_process(
    process: str,
    frame: pd.DataFrame,
    planner: pd.DataFrame,
    config: Config,
) -> dict:
    """Fit all model variants for one process and return results dict."""
    evaluation_workers = set(
        planner.loc[
            planner["Process"].eq(process), "Worker ID"
        ].astype(str)
    )
    evaluation_mask = (
        frame["Worker"].astype(str).isin(evaluation_workers)
    )

    # --- Model A: Fixed effects ---
    start = time.perf_counter()
    fixed = _fixed_adapter(frame)
    fixed["runtime_seconds"] = time.perf_counter() - start
    fixed["evaluation_workers"] = len(evaluation_workers)
    if evaluation_mask.any():
        fixed["metrics"] = regression_metrics(
            frame.loc[evaluation_mask, "log_time"],
            fixed["predictions"].loc[evaluation_mask],
        )
    else:
        fixed["metrics"] = {}

    # --- Model B: Hybrid ---
    hybrid = fit_hybrid_effect(frame)
    if hybrid.get("status") == "ok":
        hybrid["evaluation_workers"] = len(evaluation_workers)
        if evaluation_mask.any():
            hybrid["metrics"] = regression_metrics(
                frame.loc[evaluation_mask, "log_time"],
                hybrid["predictions"].loc[evaluation_mask],
            )
        else:
            hybrid["metrics"] = {}

    # --- Model C: Bayesian ---
    n_rows = len(frame)
    n_items = frame["Item Number"].nunique()
    if (
        n_rows <= config.max_bayesian_rows
        and n_items <= config.max_bayesian_items
    ):
        bayes = fit_bayesian_model(
            frame,
            config.bayes_chains,
            config.bayes_warmup,
            config.bayes_draws,
        )
    else:
        bayes = {
            "status": "skipped",
            "reason": (
                f"not feasible for {n_rows:,} rows "
                f"and {n_items:,} items"
            ),
        }

    # --- Model selection & cross-validation ---
    preferred = hybrid if hybrid.get("status") == "ok" else fixed
    fitter = (
        fit_hybrid_effect
        if hybrid.get("status") == "ok"
        else _fixed_adapter
    )

    cv_a = cross_validate_effect_model(
        frame,
        _fixed_adapter,
        config.cv_folds,
        evaluation_workers=evaluation_workers,
    )
    cv_b = (
        cross_validate_effect_model(
            frame,
            fit_hybrid_effect,
            config.cv_folds,
            evaluation_workers=evaluation_workers,
        )
        if hybrid.get("status") == "ok"
        else {"status": "failed"}
    )

    stability = item_stability(
        frame, fitter, config.stability_repetitions
    )

    return {
        "data": frame,
        "fixed": fixed,
        "hybrid": hybrid,
        "bayesian": bayes,
        "preferred": preferred,
        "cv_fixed": cv_a,
        "cv_hybrid": cv_b,
        "stability": stability,
        "evaluation_workers": len(evaluation_workers),
    }


def _item_library(
    process_results: dict[str, dict],
) -> pd.DataFrame:
    """Build the primary Semi Difficulty Library keyed by Process and Item."""
    outputs: list[pd.DataFrame] = []

    for process, result in process_results.items():
        frame = result["data"]
        model = result["preferred"]
        scores = model["item_scores"].copy()
        effect_col = next(c for c in scores.columns if "FE" in c)
        scores = scores.rename(columns={effect_col: "Raw Difficulty Effect"})

        agg: dict = {
            "Worker": "nunique",
            "log_time": "size",
            "Material": "first",
            "Product Type": "first",
            "Process": "first",
        }
        if "Customer Name" in frame:
            agg["Customer Name"] = "first"

        meta = (
            frame.groupby("Item Number", as_index=False)
            .agg(agg)
            .rename(
                columns={
                    "Worker": "Number of Different Workers",
                    "log_time": "Number of Production Records",
                    "Customer Name": "Customer",
                }
            )
        )

        out = scores.merge(meta, on="Item Number", how="left")
        out["Process"] = process
        out["Difficulty Score"] = minmax_score(
            out["Raw Difficulty Effect"], higher_is_better=True
        ).round(3)
        out["Model SE"] = frame["log_time"].std() / np.sqrt(
            out["Number of Production Records"].clip(lower=1)
        )
        intercept = float(
            model.get("intercept", frame["log_time"].mean())
        )
        out["Estimated Standard Time"] = np.exp(
            intercept + out["Raw Difficulty Effect"]
        )
        out = out.merge(result["stability"], on="Item Number", how="left")
        out = item_confidence(out, float(frame["log_time"].std()))

        keep_cols = [
            "Process",
            "Item Number",
            "Difficulty Score",
            "Raw Difficulty Effect",
            "Confidence Score",
            "Confidence",
            "Difficulty Stability Index",
            "Bootstrap SD",
            "Number of Production Records",
            "Number of Different Workers",
            "Material",
            "Product Type",
            "Customer",
            "Estimated Standard Time",
        ]
        outputs.append(out[keep_cols])

    return pd.concat(outputs, ignore_index=True)


def _worker_library(
    process_results: dict[str, dict],
    planner: pd.DataFrame,
) -> pd.DataFrame:
    """Build the Worker Capability Library keyed by Worker and Process."""
    outputs: list[pd.DataFrame] = []

    for process, result in process_results.items():
        frame = result["data"]
        model = result["preferred"]
        scores = model["worker_scores"].copy()
        effect_col = next(c for c in scores.columns if "Effect" in c)
        ability_col = next(
            (
                c
                for c in scores.columns
                if "Ability" in c
                and "Lower" not in c
                and "Upper" not in c
            ),
            None,
        )
        scores["Process"] = process
        scores["Raw Capability Effect"] = scores[effect_col]
        scores["_capability_raw"] = (
            scores[ability_col] if ability_col else -scores[effect_col]
        )

        counts = (
            frame.groupby("Worker")
            .agg(
                **{
                    "Number of Records": ("log_time", "size"),
                    "Number of Different Items": ("Item Number", "nunique"),
                }
            )
            .reset_index()
        )
        out = scores.merge(counts, on="Worker", how="left")
        out["Capability Score"] = minmax_score(
            out["_capability_raw"], higher_is_better=True
        ).round(3)

        # Merge planner skill data
        p = planner[planner["Process"].eq(process)].copy()
        p = (
            p.groupby("Worker ID", as_index=False)[
                "Planner Verified Skill Level"
            ]
            .mean()
            .rename(
                columns={
                    "Worker ID": "Worker",
                    "Planner Verified Skill Level": "Planner Skill",
                }
            )
        )
        p["Planner Skill (0-10)"] = minmax_score(
            p["Planner Skill"], higher_is_better=True
        ).round(3)
        out = out.merge(p, on="Worker", how="left")
        out["Difference"] = (
            out["Capability Score"] - out["Planner Skill (0-10)"]
        )
        out["Model SE"] = scores.get(
            "Hybrid Ability SE",
            pd.Series(np.nan, index=scores.index),
        )
        out = worker_confidence(out, float(frame["log_time"].std()))

        # Flag outliers (|z| >= 2)
        out["Outlier Flag"] = False
        sd = out["Difference"].std(ddof=1)
        if sd and np.isfinite(sd):
            z = (out["Difference"] - out["Difference"].mean()).abs() / sd
            out["Outlier Flag"] = (z >= 2).fillna(False)

        keep_cols = [
            "Worker",
            "Process",
            "Capability Score",
            "Raw Capability Effect",
            "Planner Skill",
            "Planner Skill (0-10)",
            "Difference",
            "Confidence Score",
            "Confidence",
            "Outlier Flag",
            "Number of Records",
            "Number of Different Items",
        ]
        outputs.append(out[keep_cols])

    return pd.concat(outputs, ignore_index=True)


def _model_reports(
    process_results: dict[str, dict],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Create process summary, validation, and model-comparison tables."""
    summaries: list[dict] = []
    comparisons: list[dict] = []
    validations: list[dict] = []

    for process, result in process_results.items():
        hybrid = result["hybrid"]
        variance = hybrid.get("variance_components", pd.DataFrame())
        share = (
            variance.set_index("Component")["Share"].to_dict()
            if not variance.empty and "Share" in variance
            else {}
        )

        model_specs = [
            (
                "Model A - Two-way Fixed Effect",
                result["fixed"],
                result["cv_fixed"],
            ),
            (
                "Model B - Hybrid Random Worker + Fixed Item",
                result["hybrid"],
                result["cv_hybrid"],
            ),
            (
                "Model C - Bayesian Hierarchical",
                result["bayesian"],
                {"status": "failed"},
            ),
        ]

        for name, model, cv in model_specs:
            metrics = model.get("metrics", {})
            cv_summary = cv.get("summary", {})
            row = {
                "Process": process,
                "Model": name,
                "Evaluation Workers": result["evaluation_workers"],
                "Status": model.get("status"),
                "Runtime": model.get("runtime_seconds"),
                "RMSE": metrics.get("RMSE"),
                "MAE": metrics.get("MAE"),
                "R2": metrics.get("R2"),
                "AIC": model.get("AIC"),
                "BIC": model.get("BIC"),
                "RMSE CV": cv_summary.get("RMSE"),
                "MAE CV": cv_summary.get("MAE"),
                "R2 CV": cv_summary.get("R2"),
                "Adjusted R2 CV": cv_summary.get("Adjusted R2"),
                "Reason": model.get("reason"),
            }
            comparisons.append(row)

            if cv.get("status") == "ok":
                validations.append({
                    "Process": process,
                    "Validation": "Cross-validation",
                    "Model": name,
                    **cv["summary"],
                })

        # Determine recommended model
        recommended = (
            "Model B - Hybrid Random Worker + Fixed Item"
            if hybrid.get("status") == "ok"
            else "Model A - Two-way Fixed Effect"
        )
        stability_val = result["stability"]
        stability_mean = (
            float(stability_val["Difficulty Stability Index"].mean())
            if not stability_val.empty
            else np.nan
        )
        summaries.append({
            "Process": process,
            "Evaluation Workers": result["evaluation_workers"],
            "Recommended Model": recommended,
            "Item Variance Share": share.get("Item fixed effects"),
            "Worker Variance Share": share.get("Worker random effect"),
            "Residual Variance Share": share.get("Residual"),
            "Difficulty Stability": stability_mean,
        })

    return (
        pd.DataFrame(summaries),
        pd.DataFrame(comparisons),
        pd.DataFrame(validations),
    )


def run_pipeline(config: Config) -> dict:
    """Run independent static models for each production Process."""
    raw, planner_raw = load_workbooks(config.raw_path, config.planner_path)
    data = clean_production_data(raw, config.incomplete_month)
    planner = clean_planner_data(planner_raw)

    process_results = _fit_process_models(data, planner, config)
    items = _item_library(process_results)
    workers = _worker_library(process_results, planner)

    process_summary, comparison, cv_validation = _model_reports(
        process_results
    )
    planner_validation_report = planner_validation(workers, planner)
    planner_validation_report.insert(
        0, "Validation", "Planner vs Capability"
    )
    validation = pd.concat(
        [cv_validation, planner_validation_report],
        ignore_index=True,
        sort=False,
    )

    reports = {
        "01_Process_Model_Summary": process_summary,
        "02_Semi_Difficulty_Library": items,
        "03_Worker_Capability_Library": workers,
        "04_Model_Validation": validation,
        "05_Model_Comparison": comparison,
    }
    write_master_reports(config.output_dir, reports)
    workers.to_excel(
        config.output_dir / "worker_scores.xlsx", index=False
    )

    # --- Visualization ---
    visual_planner = planner.copy()
    if "Name" in raw.columns:
        raw_names = (
            raw[["Worker", "Name", "Department"]]
            .dropna(subset=["Worker", "Name"])
            .drop_duplicates("Worker")
            .rename(columns={"Worker": "Worker ID"})
        )
        visual_planner = visual_planner.merge(
            raw_names, on="Worker ID", how="left", suffixes=("", "_raw")
        )
        visual_planner["Name"] = (
            visual_planner
            .get("Name", pd.Series(index=visual_planner.index, dtype="string"))
            .fillna(visual_planner.get("Name_raw"))
        )
        if "Name_raw" in visual_planner.columns:
            visual_planner = visual_planner.drop(columns=["Name_raw"])

    observations = pd.concat(
        [
            r["fixed"]["observations"][["fixed_residual"]]
            for r in process_results.values()
        ],
        ignore_index=True,
    )
    visual_workers = workers.rename(
        columns={"Capability Score": "Fixed Worker Ability"}
    )[["Worker", "Process", "Fixed Worker Ability"]]

    generate_visualizations(
        visual_workers, observations, visual_planner, {}, config.output_dir
    )
    create_scatterplot(
        config.output_dir,
        workers=workers,
        planner=visual_planner,
        raw=raw,
    )

    return {
        "data": data,
        "items": items,
        "workers": workers,
        "reports": reports,
        "process_results": process_results,
    }


def main() -> None:
    """Parse CLI arguments and execute the process-specific pipeline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=Config.raw_path)
    parser.add_argument("--planner", type=Path, default=Config.planner_path)
    parser.add_argument("--output", type=Path, default=Config.output_dir)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_pipeline(
        Config(
            raw_path=args.raw,
            planner_path=args.planner,
            output_dir=args.output,
        )
    )


if __name__ == "__main__":
    main()
