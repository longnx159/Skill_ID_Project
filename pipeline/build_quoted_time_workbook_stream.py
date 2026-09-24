"""Stream the quoted-time diagnostic report to Excel.

The preferred Artifact Tool exceeded its Node heap on the full QC/ticket
workbook in this project. This renderer uses the same bounded-memory fallback.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook

from .build_semi_detail_workbook_stream import _sheet


def _rows(path: Path, columns: list[str]):
    frame = pd.read_csv(path, dtype={c: str for c in ("WO", "SemiBOM", "SemiItem", "QuoteItem", "Worker") if c in columns}, low_memory=False)
    absent = set(columns) - set(frame)
    if absent:
        raise ValueError(f"{path.name} lacks {sorted(absent)}")
    def convert(value):
        if pd.isna(value):
            return None
        return value.item() if isinstance(value, np.generic) else value
    return [[convert(value) for value in row] for row in frame[columns].itertuples(index=False, name=None)]


def build(run: Path):
    summary = json.loads((run / "run_summary.json").read_text(encoding="utf-8"))
    if summary["execution_status"] != "SUCCEEDED_WITH_WARNINGS":
        raise ValueError("Only completed diagnostic runs can be exported")
    a = run / "artifacts"
    validation = pd.read_csv(a / "time_validation.csv")
    main = validation.loc[validation.PB.eq("ALL")]
    wb = Workbook(write_only=True)
    rows = [["Metric", "Value"],
            ["Run ID", summary["run_id"]], ["Execution", summary["execution_status"]],
            ["Decision status", summary["decision_status"]],
            ["Time scope", summary["time_scope"]], ["Unit", summary["unit"]],
            ["Positive Semi quotes", summary["cohort"]["semi_quotes_positive"]],
            ["Legacy 2025 eligible reference rows", summary["legacy_2025"]["eligible_quote_reference_rows"]],
            ["Material Design source SemiBOMs", summary["material_design_source"]["selected_semi_boms"]],
            ["Selected legacy quote-prior weight", summary["selected_legacy_prior_weight"]],
            ["Eligible WO rounds", summary["cohort"]["eligible_rounds"]],
            ["Predicted Semi and branch rows", summary["semi_branch_predictions"]],
            ["Predicted Semi codes", summary["semi_prediction_codes"]],
            ["Selected quote model", summary["selected_quote_candidate"]],
            ["Preferred by tuning", summary["preferred_by_tuning"]],
            ["Test quote WAPE", float(main.loc[(main.Window.eq("TEST")) & main.Candidate.eq("QUOTE_JOINT"), "WAPE"].iloc[0])],
            ["Test quote without legacy WAPE", float(main.loc[(main.Window.eq("TEST")) & main.Candidate.eq("QUOTE_NO_LEGACY"), "WAPE"].iloc[0])],
            ["Test no-quote WAPE", float(main.loc[(main.Window.eq("TEST")) & main.Candidate.eq("NO_QUOTE_JOINT"), "WAPE"].iloc[0])],
            ["Test 90% prediction interval coverage", float(main.loc[(main.Window.eq("TEST")) & main.Candidate.eq("QUOTE_JOINT"), "PredictionInterval90Coverage"].iloc[0])],
            ["Bootstrap refits", summary["bootstrap_refits"]]]
    _sheet(wb, "Summary", "Quoted time calibration", "Diagnostic allocated Final time. Quality and time confidence are separate.", rows[0], rows[1:])
    sheets = [
        ("Semi time", "semi_time_predictions.csv", ["SemiBOM", "SemiItem", "Process", "ProcessSource", "Branch", "TimeModelStatus", "QuotedMinutesPerSemi", "QuoteStatus", "QuoteSourceRows", "QualityScore", "MaterialDesignSourceScore", "StoneScore", "DifficultyCoverage", "DifficultyScore", "WorkContentMinutes", "TechnicalDifficultyMinutes", "ProductionEffortMinutes", "WorkerEffectMinutes", "PredictedMinutes", "EstimateLower90", "EstimateUpper90", "EstimatePrecisionWithin20Pct", "CalibrationWithin20Pct", "PredictionLower90", "PredictionUpper90", "UnseenGroup", "PredictionBasis"]),
        ("Time observations", "time_observations.csv", ["WO", "RoundNo", "Branch", "SemiBOM", "SemiItem", "Process", "ProcessSource", "Worker", "Date", "Split", "GoodCW", "AllocatedHours", "OriginHours", "IdleHours", "ActualMinutes", "QuotedMinutesPerSemi", "QualityScore", "MaterialDesignSourceScore", "StoneScore", "DifficultyScore", "WorkContentMinutes", "TechnicalDifficultyMinutes", "ProductionEffortMinutes", "WorkerEffectMinutes", "PredictedMinutes", "ResidualMinutes", "PredictionLower90", "PredictionUpper90", "UnseenGroup", "UnseenWorker"]),
        ("Quote effects", "quote_effects.csv", ["PB", "QuoteElasticity", "Lower90", "Upper90", "TrainingRounds", "Interpretation"]),
        ("Validation", "time_validation.csv", ["Window", "Candidate", "PB", "N", "LogRMSE", "WAPE", "Within20Pct", "PredictionInterval90Coverage"]),
        ("Time calibration", "time_calibration.csv", ["PB", "CalibrationN", "LogRadius90", "CalibrationWithin20Pct", "IntervalSource"]),
        ("Quote source", "quote_source_audit.csv", ["SemiBOM", "QuoteItem", "SourceMinutes", "SourceRow", "QuoteStatus"]),
        ("Material source", "material_design_source_audit.csv", ["SourceRow", "Semi Item", "Semi BOM Item", "Material", "Product Type", "Process", "Material Score", "Design Score", "Process Score", "Material Design Process", "SelectionStatus"]),
        ("Time exclusions", "time_source_audit.csv", ["WO", "RoundNo", "Branch", "Worker", "ItemNumber", "SemiBOM", "ProcessSource", "AllocatedHours", "OriginHours", "IdleHours", "GoodCW", "Date", "Exclusion"]),
        ("Legacy 2025 source", "legacy_2025_source_audit.csv", ["SourceRow", "Reference", "Worker", "Item Number", "SemiBOM", "Process", "CurrentProcess", "RAFMonth", "QtyDoing", "TotalActualHours", "AggregateMinutesPerQty", "QuotedMinutesPerSemi", "Exclusion"]),
        ("Legacy quote prior", "legacy_2025_quote_reference.csv", ["Process", "ReferenceQuoteElasticity", "Eligible2025Rows", "Scope"]),
        ("QC fit health", "quality_fit_health.csv", ["Process", "Branch", "Cutoff", "Rounds", "Converged", "LatestQC"]),
    ]
    notes = {
        "Semi time": "One row per Semi and round branch. Missing process mapping or model remains blank. Minutes per final OK for that branch.",
        "Time observations": "One row per eligible WO-round. Actual is Final allocated hours divided by final GoodCW; no double allocation.",
        "Quote effects": "Log-time elasticity for quoted minutes, shrunk by process and branch. This is not a convex-blend weight.",
        "Validation": "Tuning selected the model; calibration set the interval; test was held out. WAPE is an error fraction.",
        "Time calibration": "Shrunk historical hit rate within 20% and the log radius for future allocated-time prediction intervals.",
        "Quote source": "Raw quote rows. Zero and conflicts remain visible and are not used as positive quote values.",
        "Material source": "Engineering 0–10 factor source. The selected product-type context enters Technical Difficulty; quote remains Work Content only.",
        "Time exclusions": "All source WO-rounds with a reason when excluded. Blank Exclusion means eligible.",
        "Legacy 2025 source": "Historical aggregate hours per Qty Doing. Only eligible 2025 rows inform a quote-slope reference; no round or Final-hour claim.",
        "Legacy quote prior": "Historical quote elasticity by Process, used only when a positive prior weight wins 2026 tuning.",
        "QC fit health": "Quality features were trained only on QC before each time cutoff.",
    }
    for title, filename, columns in sheets:
        records = _rows(a / filename, columns)
        _sheet(wb, title, title, notes[title], columns, records)
        del records
    definitions = [["Field", "Meaning"],
                   ["ActualMinutes", "60 × sum Final allocated hours for one WO-round / GoodCW final OK units. Includes allocated Idle."],
                   ["WorkContentMinutes", "Reference-worker predicted minutes from process/branch, quote and residual Semi-group effects, before explicit difficulty score effect."],
                   ["TechnicalDifficultyMinutes", "Incremental fitted difficulty component in minute space. May be negative relative to reference; model components are a convention."],
                   ["ProductionEffortMinutes", "Work Content plus Technical Difficulty."],
                   ["WorkerEffectMinutes", "Difference between prediction for observed worker and reference-worker Production Effort."],
                   ["ResidualMinutes", "Observed ActualMinutes minus PredictedMinutes."],
                   ["QuoteElasticity", "Approximate percent change in fitted time per 1% change in quoted minutes, conditional on other terms. Not a blend percentage."],
                   ["Legacy quote prior", "2025 Total Actual Hours / Qty Doing informs quote slope only. A 2026 Final-time tuning window selects its prior weight; 2025 hours are not mixed into Final hours."],
                   ["EstimatePrecisionWithin20Pct", "Share of WO-cluster bootstrap model refits within ±20% of the fitted Semi/branch estimate. Diagnostic model stability."],
                   ["CalibrationWithin20Pct", "Shrunk historical share of allocated-time observations within ±20% of the predicted minutes."],
                   ["PredictionLower90/Upper90", "Calibrated interval for one future allocated-time observation, based on absolute log errors of a later calibration window."],
                   ["QualityScore", "80% first-pass + 20% rework Rasch-style score refitted with QC before the training cutoff. Missing when either branch is unavailable."],
                   ["DifficultyCoverage", "40% Quality + 20% Material Design Process + 10% Stone when available. Missing factors reduce coverage; Part/Mechanism and Learning remain unavailable."],
                   ["TimeModelStatus", "DIAGNOSTIC_ALLOCATED_TIME for modeled rows; other statuses explain missing predictions."],
                   ["ProcessSource", "A missing/unmapped Semi report Process can be filled from Item Master for the same SemiItem. Existing conflicting Process mappings are excluded."],
                   ["Time scope", "Final = Origin + Idle in source; response is allocated time per final OK, not pure touch time."],
                   ["Temporal limitation", "Current quotes, Material Design and Stone lack effective dates; holdout results are conditional on these current snapshots."],
                   ["Score confidence", "The existing Semi difficulty % confident is separate from all time estimate and prediction uncertainty in this workbook."],
                   ["Prediction branches", "First pass and Rework are separate conditions. They cannot be added without a rework frequency/trajectory model."]]
    _sheet(wb, "Definitions", "Definitions and limitations", "English audit definitions for this run.", definitions[0], definitions[1:])
    output = run / "quoted_time_calibration.xlsx"
    wb.save(output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    print(build(parser.parse_args().run.resolve()))
