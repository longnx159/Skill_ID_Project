"""Prepare an auditable Semi/Stone/QC/Rasch Excel workbook.

Run: python -m pipeline.semi_detail_workbook --semi-report PATH --core-run PATH
The XLSX renderer is pipeline/build_semi_detail_workbook_stream.py.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

import pandas as pd

from .run_reporting import atomic_json, file_hash
from .rasch_semi_estimate import estimate_quality
from .quoted_inputs import read_bom_quotes
from .material_design_inputs import read_material_design
from .part_mechanism_inputs import read_part_mechanism
from .learning_curve import learning_from_core_run
from .preprocessing import clean_planner_data


ROOT = Path(__file__).resolve().parents[1]
STONE = ROOT / "input_data/06_Engineering_Factors/Stone/Semi Stone Score.xlsx"
MATERIAL_DESIGN = ROOT / "input_data/06_Engineering_Factors/Material Design Process/Material Design Process Score.xlsx"
PART_MECHANISM = ROOT / "input_data/06_Engineering_Factors/Part Quantity, Mechanism/Part & Mechanism Score.xlsx"
QC = ROOT / "input_data/04_QC_Tickets/QC data.xlsx"
QUOTED = ROOT / "input_data/08_Quoted Hours/Quoted Hours.xlsx"
EXPERIMENT_ROOT = ROOT / "outputs/rasch_experiments"
WORKER_VALIDATION = ROOT / "input_data/worker_score_validation.json"
PLANNER = ROOT / "input_data/02_Planner_Skills/Worker Skill Verified by Planner 20260803.xlsx"


def wo_summary(rounds: pd.DataFrame, workers: pd.DataFrame, planner: pd.DataFrame) -> pd.DataFrame:
    """First-round quantities once per WO; never sum repeated worker/QC rows."""
    first = rounds.loc[rounds.RoundNo.eq(1)].copy()
    _unique(first, ["WO"], "first-round WO")
    attribution = workers.loc[workers.RoundNo.eq(1) & workers.Worker.notna()].copy()
    attribution["Worker"] = attribution.Worker.astype("string").str.strip()
    attribution = attribution.loc[attribution.Worker.ne("")]
    names = attribution.groupby(["WO", "Process"]).Worker.agg(lambda x: "; ".join(sorted(set(x)))).rename("ProductionWorkers")
    first = first.merge(names, on=["WO", "Process"], how="left", validate="one_to_one")
    first["Worker"] = first.ProductionWorkers.where(~first.ProductionWorkers.str.contains(";", na=False))
    skills = clean_planner_data(planner).rename(columns={"Worker ID": "Worker", "Planner Verified Skill Level": "Verified Skill"})
    first = first.merge(skills[["Worker", "Process", "Verified Skill"]], on=["Worker", "Process"], how="left", validate="many_to_one")
    first["First QC Date"] = pd.to_datetime(first.QC_Start, errors="coerce").dt.strftime("%Y-%m-%d")
    first["FPY"] = first.PassQty.div(first.InspectedQty.where(first.InspectedQty.gt(0)))
    first = first.rename(columns={"Item Number": "Semi", "PassQty": "Pass", "FailQty": "Fail", "InspectedQty": "Total Quantity"})
    return first[["WO", "Semi", "ProductionWorkers", "Process", "First QC Date", "Pass", "Fail", "Total Quantity", "FPY", "Verified Skill"]].sort_values("WO", kind="stable")


def worker_validation(core_run: Path) -> dict:
    """User acceptance applies only to the exact worker estimates reviewed."""
    if not WORKER_VALIDATION.is_file():
        return {}
    record = json.loads(WORKER_VALIDATION.read_text(encoding="utf-8"))
    expected = record.get("source_sha256", {})
    names = ["Rasch first pass workers.csv", "Rasch rework workers.csv"]
    if record.get("status") != "USER_VALIDATED" or set(expected) != set(names):
        return {}
    if any(file_hash(core_run / "artifacts" / name) != expected[name] for name in names):
        return {}
    return record


def _csv(path: Path, **ids: str) -> pd.DataFrame:
    return pd.read_csv(path, dtype=ids, low_memory=False)


def _unique(frame: pd.DataFrame, keys: list[str], name: str) -> None:
    if frame.duplicated(keys).any():
        raise ValueError(f"Duplicate {name} key: {keys}")


def _json_rows(frame: pd.DataFrame, path: Path) -> None:
    # pandas handles numpy scalars, NaN and dates consistently as JSON null/ISO.
    path.write_text(frame.to_json(orient="values", date_format="iso", force_ascii=False), encoding="utf-8")


def _quotes(path: Path, keys: set[str]) -> pd.DataFrame:
    source = pd.read_excel(path, dtype={"SemiBOM": str}) if path.suffix.lower() in {".xlsx", ".xls"} else pd.read_csv(path, dtype={"SemiBOM": str})
    if "SemiBOM" not in source:
        raise ValueError("Quote source needs SemiBOM column")
    if not ({"QuotedMinutes", "QuotedHours"} & set(source.columns)):
        raise ValueError("Quote source needs QuotedMinutes or QuotedHours column")
    source["SemiBOM"] = source["SemiBOM"].astype("string").str.strip()
    source = source.loc[source.SemiBOM.notna() & source.SemiBOM.ne("")].copy()
    _unique(source, ["SemiBOM"], "quoted SemiBOM")
    unknown = set(source.SemiBOM) - keys
    if unknown:
        raise ValueError(f"Quote source has {len(unknown)} unknown SemiBOMs (example: {sorted(unknown)[0]})")
    minutes = pd.to_numeric(source["QuotedMinutes"], errors="coerce") if "QuotedMinutes" in source else pd.Series(float("nan"), index=source.index)
    hours = pd.to_numeric(source["QuotedHours"], errors="coerce") if "QuotedHours" in source else pd.Series(float("nan"), index=source.index)
    if (minutes.notna() & hours.notna()).any():
        raise ValueError("Each SemiBOM must supply minutes or hours, not both")
    if minutes.lt(0).any() or hours.lt(0).any():
        raise ValueError("Quoted time cannot be negative")
    bad = (source.get("QuotedMinutes", pd.Series(index=source.index)).notna() & minutes.isna()) | (source.get("QuotedHours", pd.Series(index=source.index)).notna() & hours.isna())
    if bad.any():
        raise ValueError("Quoted time contains non-numeric values")
    source["QuotedMinutesPerSemi"] = minutes.fillna(hours * 60)
    source["QuoteInputUnit"] = ""
    source.loc[minutes.notna(), "QuoteInputUnit"] = "MINUTES"
    source.loc[hours.notna(), "QuoteInputUnit"] = "HOURS_CONVERTED_X60"
    source["QuoteBasis"] = "PER_SEMI_UNIT"
    return source[["SemiBOM", "QuotedMinutesPerSemi", "QuoteInputUnit", "QuoteBasis"]]


def prepare(semi_report: Path, core_run: Path, stone_path: Path, qc_path: Path, destination: Path, quoted_path: Path | None = None, experiment_run: Path | None = None, material_path: Path = MATERIAL_DESIGN, part_path: Path = PART_MECHANISM) -> dict:
    artifacts = core_run / "artifacts"
    semi = _csv(semi_report, SemiBOM=str, SemiItem=str)
    _unique(semi, ["SemiBOM"], "SemiBOM")
    stone = pd.read_excel(stone_path, dtype={"BOM item number": str, "FG BOM Number": str})
    stone = stone.loc[stone["BOM item number"].astype("string").str.startswith("2", na=False)].copy()
    stone["BOM item number"] = stone["BOM item number"].str.strip()
    stone["Final Semi Stone Score"] = pd.to_numeric(stone["Final Semi Stone Score"], errors="coerce")
    conflict = stone.groupby("BOM item number")["Final Semi Stone Score"].nunique(dropna=False)
    if conflict.gt(1).any():
        raise ValueError(f"Stone scores conflict across FG contexts for {int(conflict.gt(1).sum())} SemiBOMs")
    stone_summary = stone.groupby("BOM item number", as_index=False).agg(
        StoneSourceScore=("Final Semi Stone Score", "first"),
        StoneFGContexts=("FG BOM Number", "nunique"),
        StoneSourceRows=("BOM item number", "size"),
    ).rename(columns={"BOM item number": "SemiBOM"})
    semi = semi.merge(stone_summary, on="SemiBOM", how="left", validate="one_to_one")
    material_scores, material_source, material_counts = read_material_design(material_path, semi)
    semi = semi.merge(material_scores, on="SemiBOM", how="left", validate="one_to_one")
    semi["MaterialDesignSourceStatus"] = semi.MaterialDesignSourceStatus.fillna("MISSING_SOURCE")
    part_scores, part_source, part_counts = read_part_mechanism(part_path, semi)
    semi = semi.merge(part_scores, on="SemiBOM", how="left", validate="one_to_one")
    semi["PartMechanismEvidenceStatus"] = semi.PartMechanismEvidenceStatus.fillna("MISSING_SOURCE")
    quoted_path = quoted_path if quoted_path and quoted_path.is_file() else None
    if quoted_path:
        if set(pd.read_excel(quoted_path, nrows=0).columns) >= {"BOM item number", "BOM number", "Minutes"}:
            normalized, quote_audit = read_bom_quotes(quoted_path, semi)
            semi = semi.merge(normalized, on="SemiBOM", how="left", validate="one_to_one")
        else:
            quote_audit = pd.DataFrame()
            semi = semi.merge(_quotes(quoted_path, set(semi.SemiBOM)), on="SemiBOM", how="left", validate="one_to_one")
    else:
        semi["QuotedMinutesPerSemi"] = pd.NA
        semi["QuoteInputUnit"] = pd.NA
        semi["QuoteBasis"] = pd.NA
    if "QuoteStatus" not in semi:
        semi["QuoteStatus"] = "MISSING"
    semi["QuoteStatus"] = semi["QuoteStatus"].fillna("MISSING")
    semi.loc[semi.QuotedMinutesPerSemi.notna(), "QuoteStatus"] = "SUPPLIED"
    model = _csv(artifacts / "Do kho SKU.csv", **{"Item Number": str, "SizeAdjustedGroup": str})
    _unique(model, ["Item Number"], "model item")
    model_fields = ["Item Number", "SizeAdjustedGroup", "FPY_Rasch_Difficulty", "FirstPass_Rasch_Converged", "Confidence / Interval"]
    semi = semi.merge(model[model_fields].rename(columns={"FPY_Rasch_Difficulty": "RaschGroupDifficulty_Diagnostic"}), left_on="SemiItem", right_on="Item Number", how="left", validate="many_to_one")
    match = semi["Process"].eq(semi["ModelProcess"]).fillna(False)
    for col in ["SizeAdjustedGroup", "RaschGroupDifficulty_Diagnostic", "FirstPass_Rasch_Converged", "Confidence / Interval"]:
        semi.loc[~match, col] = pd.NA
    learning, learning_pairs, learning_audit = learning_from_core_run(core_run)
    semi = semi.merge(learning, on=["Process", "SizeAdjustedGroup"], how="left", validate="many_to_one")
    semi["LearningSourceStatus"] = semi.LearningSourceStatus.fillna("NO_ELIGIBLE_WORKER_ITEM_TRAJECTORY")
    semi["LearningConfidenceStatus"] = semi.LearningConfidenceStatus.fillna("NOT_ESTIMATED")
    if experiment_run:
        quality = estimate_quality(experiment_run, ROOT)
        semi = semi.merge(quality, on=["Process", "SizeAdjustedGroup"], how="left", validate="many_to_one")
    else:
        quality = pd.DataFrame()
        for col in ["QualityFactor_Diagnostic", "RaschConfidencePct", "RaschInterval90Lower", "RaschInterval90Upper", "RaschConfidenceStatus", "QualityModelSource", "QualityFirstPassRounds", "QualityReworkRounds"]:
            semi[col] = pd.NA
    # Overlay with Planner-primary blended score (80% Planner + 20% old Rasch)
    planner_primary_csv = core_run / "planner_primary" / "Planner primary Quality.csv"
    if planner_primary_csv.is_file():
        planner_q = pd.read_csv(planner_primary_csv, dtype={"SizeAdjustedGroup": str})
        planner_blend = planner_q[["Process", "SizeAdjustedGroup", "Quality", "BlendStatus"]].copy()
        planner_blend = planner_blend.rename(columns={"Quality": "_BlendQuality", "BlendStatus": "_BlendStatus"})
        semi = semi.merge(planner_blend, on=["Process", "SizeAdjustedGroup"], how="left", validate="many_to_one")
        has_blend = semi["_BlendQuality"].notna()
        semi.loc[has_blend, "QualityFactor_Diagnostic"] = semi.loc[has_blend, "_BlendQuality"]
        semi.loc[has_blend, "QualityModelSource"] = semi.loc[has_blend, "_BlendStatus"].map(
            lambda s: f"PLANNER_RASCH_BLEND ({s})")
        semi.drop(columns=["_BlendQuality", "_BlendStatus"], inplace=True)
    # The selected core run has no approved engineering factors; source Stone is evidence, not an approved factor.
    semi["QualityFactor_Approved"] = pd.NA
    semi["PartMechanismFactor_Approved"] = pd.NA
    semi["MaterialDesignFactor_Approved"] = pd.NA
    semi["StoneFactor_Approved"] = pd.NA
    semi["LearningFactor_Approved"] = pd.NA
    semi["RaschConfidenceStatus"] = semi["RaschConfidenceStatus"].fillna("NOT_ESTIMATED")
    semi["DifficultyStatus"] = semi["ReportStatus"].where(semi["ReportStatus"].ne("DIAGNOSTIC_ONLY"), "BLOCKED_RASCH_AND_FACTORS")
    semi_cols = ["SemiBOM", "SemiItem", "SizeAdjustedGroup", "SemiName", "Process", "SemiScopeStatus", "SemiScopeRule", "DifficultyStatus", "QualityFactor_Diagnostic", "QualityFactor_Approved", "PartMechanismFactor_Approved", "MaterialDesignFactor_Approved", "StoneFactor_Approved", "LearningFactor_Approved", "FinalTechnicalComplexity", "Material", "MaterialSourceScore", "DesignSourceScore", "ProcessSourceScore", "MaterialDesignSourceScore", "MaterialDesignSourceStatus", "MaterialDesignSourceRow", "MaterialDesignSourceMaterial", "MaterialDesignSourceProductType", "MaterialDesignSourceProcess", "PartMechanismSourceScore", "PartMechanismPhysicalPartCount", "PartMechanismAssemblyType", "PartMechanismFunctionClass", "PartMechanismPartScore", "PartMechanismAssemblyScore", "PartMechanismBonus", "PartMechanismSourceRow", "PartMechanismEvidenceStatus", "StoneSourceScore", "StoneFGContexts", "StoneSourceRows", "LearningSourceScore", "LearningEarlyRatio", "LearningMiddleRatio", "LearningLateRatio", "LearningL1", "LearningL2", "LearningL3", "LearningConfidencePct", "LearningInterval90Lower", "LearningInterval90Upper", "LearningConfidenceStatus", "LearningSourceStatus", "LearningTrajectoryN", "LearningWON", "LearningSpanDays", "MechanicalAssemblyPartCountPCS", "MechanicalAssemblyPartSKUCount", "StoneCount", "StoneSKUCount", "KnownStoneWeightGram", "MaterialGroupCount", "ObservedFPY", "PassQty1", "InspectedQty1", "QCEvidenceN", "RaschGroupDifficulty_Diagnostic", "RaschConfidencePct", "RaschInterval90Lower", "RaschInterval90Upper", "RaschConfidenceStatus", "QualityModelSource", "QualityFirstPassRounds", "QualityReworkRounds", "FirstPass_Rasch_Converged", "FirstPass_Calibration_Status", "FirstPass_Decision_Eligibility", "QuotedMinutesPerSemi", "QuoteBasis", "QuoteInputUnit", "QuoteStatus", "EstimatedMinutesPerFinalOK_Diagnostic", "BOMStatus", "ModelLinkStatus", "ContextCount", "SourceFile", "FG BOM"]
    semi_cols.extend(col for col in ("QuoteItem", "QuoteSourceRows") if col in semi)
    semi_out = semi[semi_cols].copy().sort_values("SemiBOM", kind="stable")
    stone_cols = ["BOM item number", "FG BOM Number", "FG item number", "Process", "Process Group", "FG Had Stone?", "Wax Setting", "FG Stone Score", "Semi Stone Score", "Final Semi Stone Score", "Total Qty in BOM", "Level"]
    stone_out = stone[stone_cols].rename(columns={"BOM item number": "SemiBOM", "FG BOM Number": "FGBOM"}).sort_values(["SemiBOM", "FGBOM"], kind="stable")

    rounds = _csv(artifacts / "QC rounds.csv", WO=str, **{"Item Number": str, "SizeAdjustedGroup": str})
    workers = _csv(artifacts / "QC round workers.csv", WO=str, Worker=str, **{"Item Number": str})
    _unique(rounds, ["WO", "RoundNo"], "QC round")
    qc = pd.read_excel(qc_path, dtype={"WO": str, "QualityOrderId": str, "ItemId": str, "QCWorkerWrkCtrId": str})
    status_path = artifacts / "Work order status audit.csv"
    excluded_work_orders = set()
    if status_path.is_file():
        order_status = _csv(status_path, ProductionOrderNumber=str)
        excluded_work_orders = set(order_status.loc[order_status.AnalysisStatus.eq("EXCLUDED_NOT_COMPLETE"), "ProductionOrderNumber"].dropna())
        qc = qc.loc[~qc.WO.astype("string").str.strip().isin(excluded_work_orders)].copy()
    _unique(qc, ["QualityOrderId"], "quality order")
    qc = qc.merge(rounds[["WO", "RoundNo", "Item Number", "SizeAdjustedGroup", "Process", "PassQty", "FailQty", "InspectedQty", "Disposition"]], on=["WO", "RoundNo"], how="left", validate="many_to_one", indicator="_round_link")
    qc["RoundLinkStatus"] = qc["_round_link"].map({"both": "MATCHED_CORE_ROUND", "left_only": "NOT_IN_CORE_ROUNDS"}).astype(str)
    qc["ItemMatchStatus"] = "NOT_LINKED"
    linked = qc["_round_link"].eq("both")
    qc.loc[linked, "ItemMatchStatus"] = "MATCHED"
    qc.loc[linked & qc["ItemId"].ne(qc["Item Number"]), "ItemMatchStatus"] = "ITEM_MISMATCH"
    qc["RoundFPY"] = (pd.to_numeric(qc["PassQty"], errors="coerce") / pd.to_numeric(qc["InspectedQty"], errors="coerce")).where(qc["RoundNo"].eq(1) & qc["InspectedQty"].gt(0) & qc["ItemMatchStatus"].eq("MATCHED"))
    fp_denom = pd.to_numeric(qc["FirstPassQty"], errors="coerce").fillna(0) + pd.to_numeric(qc["FirstFailQty"], errors="coerce").fillna(0)
    qc["TicketSnapshotFPY"] = (pd.to_numeric(qc["FirstPassQty"], errors="coerce") / fp_denom).where(qc["RoundNo"].eq(1) & fp_denom.gt(0))
    ticket_cols = ["QualityOrderId", "WO", "RoundNo", "ItemId", "Item Number", "Process", "SizeAdjustedGroup", "QCStatus", "QCQty", "RoundPassQty", "RoundFailQty", "RoundActualQty", "FirstPassQty", "FirstFailQty", "TicketSnapshotFPY", "RoundFPY", "PassQty", "FailQty", "InspectedQty", "FirstPassTicketFlag", "FirstFailTicketFlag", "QCWorkerWrkCtrId", "QCWorkerName", "Disposition", "RoundLinkStatus", "ItemMatchStatus", "IsRoundValid", "HasHardRoundError", "CreatedDateTime"]
    ticket_out = qc[ticket_cols].sort_values(["WO", "RoundNo", "QualityOrderId"], kind="stable")

    first = _csv(artifacts / "Rasch first pass workers.csv", Worker=str)
    rework = _csv(artifacts / "Rasch rework workers.csv", Worker=str)
    first["Branch"] = "FIRST_PASS"
    rework["Branch"] = "REWORK"
    ability = pd.concat([first, rework], ignore_index=True)
    _unique(ability, ["Process", "Worker", "Branch"], "Rasch worker")
    ability["CalibrationStatus"] = "NOT_VALIDATED"
    ability["DecisionEligibility"] = "BLOCKED"
    validation = worker_validation(core_run)
    ability["StatisticalCalibrationStatus"] = "NOT_VALIDATED"
    ability["ValidationBasis"] = "NO_USER_VALIDATION_RECORDED"
    if validation:
        ability["CalibrationStatus"] = "USER_VALIDATED"
        ability["DecisionEligibility"] = "ELIGIBLE_USER_VALIDATED"
        ability["ValidationBasis"] = validation["id"]
    ability_out = ability[["Branch", "Process", "Worker", "Rasch_Worker_Effect", "Rasch_Worker_WOs", "CalibrationStatus", "DecisionEligibility", "StatisticalCalibrationStatus", "ValidationBasis"]].sort_values(["Branch", "Process", "Worker"], kind="stable")
    worker_core = workers[["WO", "RoundNo", "Worker", "Worker Name", "Hours", "QtyDoing", "WorkersInRound", "WorkerAttributionStatus", "Process"]].copy()
    ticket_workers = qc[["QualityOrderId", "WO", "RoundNo", "Process", "RoundFPY", "RoundLinkStatus"]].merge(worker_core.drop(columns="Process"), on=["WO", "RoundNo"], how="left", validate="many_to_many")
    ticket_workers["Branch"] = ticket_workers["RoundNo"].map(lambda n: "FIRST_PASS" if n == 1 else "REWORK")
    ticket_workers = ticket_workers.merge(ability[["Process", "Worker", "Branch", "Rasch_Worker_Effect", "Rasch_Worker_WOs", "CalibrationStatus", "DecisionEligibility"]], on=["Process", "Worker", "Branch"], how="left", validate="many_to_one")
    ticket_workers["WorkerScoreStatus"] = "NO_FITTED_EFFECT"
    ticket_workers.loc[ticket_workers["Rasch_Worker_Effect"].notna(), "WorkerScoreStatus"] = "DIAGNOSTIC_ONLY"
    if validation:
        ticket_workers.loc[ticket_workers["Rasch_Worker_Effect"].notna(), "WorkerScoreStatus"] = "USER_VALIDATED"
    ticket_workers.loc[ticket_workers["Worker"].isna(), "WorkerScoreStatus"] = "NO_ATTRIBUTED_PRODUCTION_WORKER"
    ticket_worker_cols = ["QualityOrderId", "WO", "RoundNo", "Branch", "Process", "Worker", "Worker Name", "Hours", "QtyDoing", "WorkersInRound", "WorkerAttributionStatus", "RoundFPY", "Rasch_Worker_Effect", "Rasch_Worker_WOs", "WorkerScoreStatus", "CalibrationStatus"]
    ticket_worker_out = ticket_workers[ticket_worker_cols].sort_values(["WO", "RoundNo", "QualityOrderId", "Worker"], kind="stable")

    sheets = {
        "WO Summary": wo_summary(rounds.loc[~rounds.WO.isin(excluded_work_orders)], workers, pd.read_excel(PLANNER)),
        "Semi difficulty": semi_out,
        "Part Mechanism source": part_source,
        "Material Design source": material_source,
        "Learning source": learning,
        "Learning trajectories": learning_pairs,
        "Stone source": stone_out,
        "QC tickets": ticket_out,
        "Ticket workers": ticket_worker_out,
        "Rasch workers": ability_out,
    }
    if quoted_path and not quote_audit.empty:
        sheets["Quote source"] = quote_audit
    destination.mkdir(parents=True, exist_ok=False)
    semi[["SemiBOM", "SemiItem", "SemiName"]].assign(QuotedMinutes="").to_csv(destination / "quoted_minutes_input_template.csv", index=False, encoding="utf-8-sig")
    for name, frame in sheets.items():
        _json_rows(frame, destination / f"{name}.json")
    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "semi_boms": len(semi_out),
        "excluded_semi_scope": int(semi_out.SemiScopeStatus.eq("EXCLUDED_SEMI_SCOPE").sum()),
        "semi_with_stone_source_score": int(semi_out.StoneSourceScore.notna().sum()),
        "semi_with_part_mechanism_source_score": int(semi_out.PartMechanismSourceScore.notna().sum()),
        "part_mechanism_source": part_counts,
        "semi_with_material_design_source_score": int(semi_out.MaterialDesignSourceScore.notna().sum()),
        "material_design_source": material_counts,
        "learning_source": learning_audit,
        "semi_with_learning_source_score": int(semi_out.LearningSourceScore.notna().sum()),
        "in_scope_semi_with_learning_score": int((semi_out.LearningSourceScore.notna() & semi_out.SemiScopeStatus.eq("IN_SCOPE")).sum()),
        "semi_without_stone_source_score": int(semi_out.StoneSourceScore.isna().sum()),
        "semi_with_quoted_minutes": int(semi_out.QuotedMinutesPerSemi.notna().sum()),
        "quote_status_counts": semi.QuoteStatus.value_counts().to_dict(),
        "estimated_quality_groups": len(quality),
        "quality_skipped_branches": quality.attrs.get("skipped_branches", []),
        "semi_with_diagnostic_quality_estimate": int(semi_out.QualityFactor_Diagnostic.notna().sum()),
        "stone_source_rows": len(stone_out),
        "qc_tickets": len(ticket_out),
        "excluded_not_complete_work_orders": len(excluded_work_orders),
        "qc_tickets_linked_to_core_rounds": int(linked.sum()),
        "qc_tickets_with_round_fpy": int(ticket_out.RoundFPY.notna().sum()),
        "qc_tickets_with_snapshot_fpy": int(ticket_out.TicketSnapshotFPY.notna().sum()),
        "ticket_worker_rows": len(ticket_worker_out),
        "rasch_worker_effects": len(ability_out),
        "worker_score_validation": validation,
        "wo_summary_rows": len(sheets["WO Summary"]),
        "wo_summary_planner_source": {"path": str(PLANNER), "sha256": file_hash(PLANNER)},
        "approved_final_difficulty_rows": int(semi_out.FinalTechnicalComplexity.notna().sum()),
        "rasch_confidence_pct_rows": int(semi_out.RaschConfidencePct.notna().sum()),
        "experiment_run_id": experiment_run.name if experiment_run else None,
        "source_sha256": {str(p.relative_to(ROOT)): file_hash(p) for p in [semi_report, stone_path, material_path, part_path, qc_path, artifacts / "QC rounds.csv", artifacts / "QC round workers.csv", artifacts / "Rasch first pass workers.csv", artifacts / "Rasch rework workers.csv", artifacts / "Do kho SKU.csv", *([quoted_path] if quoted_path else []), *([experiment_run / "run_summary.json", experiment_run / "experiment/modeling_rounds.csv"] if experiment_run else [])]},
        "sheet_columns": {name: list(frame.columns) for name, frame in sheets.items()},
    }
    (destination / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def finalize(destination: Path, manifest: dict, workbook: Path, output_root: Path) -> Path:
    if not workbook.is_file():
        raise FileNotFoundError(workbook)
    summary = {**manifest, "execution_status": "SUCCEEDED_WITH_WARNINGS",
               "decision_status": "DIAGNOSTIC_ONLY", "run_id": destination.name,
               "workbook": workbook.name, "workbook_sha256": file_hash(workbook)}
    atomic_json(destination / "manifest.json", summary)
    atomic_json(destination / "run_summary.json", summary)
    quote = summary["quote_status_counts"]
    lines = ["# Semi difficulty and source detail", "",
             f"Run: `{destination.name}`. Execution: **SUCCEEDED_WITH_WARNINGS**. Decision: **DIAGNOSTIC_ONLY**.", "",
             "## Coverage", "",
             f"- SemiBOMs: {summary['semi_boms']:,}; diagnostic quality estimates: {summary['semi_with_diagnostic_quality_estimate']:,}; approved final difficulty scores: {summary['approved_final_difficulty_rows']:,}.",
             f"- Excluded from Semi scoring by code rule: {summary['excluded_semi_scope']:,}; rows remain in the workbook for BOM reconciliation.",
             f"- Stone source scores: {summary['semi_with_stone_source_score']:,}; valid quoted minutes per Semi: {summary['semi_with_quoted_minutes']:,}.",
             f"- Part & Mechanism source scores: {summary['semi_with_part_mechanism_source_score']:,}; incomplete component detail: {summary['part_mechanism_source']['incomplete_component_detail']:,}.",
             f"- Material/Design/Process source scores: {summary['semi_with_material_design_source_score']:,}; source conflicts and exclusions remain in Material Design source.",
             f"- Learning source estimates: {summary['in_scope_semi_with_learning_score']:,} in-scope SemiBOM scores from {summary['learning_source']['scored_groups']:,} repeated-production groups; {summary['semi_with_learning_source_score']:,} source-linked rows including excluded scope. Missing histories stay blank.",
             f"- Quote gaps: {quote.get('MISSING', 0):,} missing, {quote.get('NONPOSITIVE_QUOTE', 0):,} nonpositive, {quote.get('CONFLICTING_QUOTE', 0):,} with conflicting values.",
             f"- QC tickets: {summary['qc_tickets']:,}; ticket-worker detail rows: {summary['ticket_worker_rows']:,}.", "",
             f"- Work orders excluded because status is not Complete: {summary['excluded_not_complete_work_orders']:,}.", "",
             f"- Quality branches without an eligible penalized fit: {summary['quality_skipped_branches']}.", "",
             "## Interpretation", "",
             ("Worker scores: USER_VALIDATED; ELIGIBLE_USER_VALIDATED. User acceptance applies to the exact reviewed first-pass and rework worker files. Statistical calibration is tracked separately. Validation record: " + summary["worker_score_validation"]["id"] + ".") if summary.get("worker_score_validation") else "Worker scores: no matching user validation record.",
             "The SKU Semi Score sheet preserves one row per SemiBOM. Excluded code patterns carry no factor or total score. Raw FPY is shown for context on in-scope rows; the 40% quality factor uses the QC/Rasch estimate. Provisional Learning uses repeated first-round production histories where supported. Quality and Learning each have their own conditional precision; overall confidence is a separate completeness-adjusted index. No final technical difficulty score is approved unless the core model explicitly releases one.",
             "Quoted minutes are an input to the separate Work Content time calibration only; they do not enter the Semi difficulty factors, Total Score10 or Semi confidence.",
             "The Excel workbook, run_summary.json and manifest.json retain the result, counts and source hashes for audit.", "",
             f"Workbook: `{workbook.name}` (SHA-256 `{summary['workbook_sha256']}`).", ""]
    report = destination / "run_summary.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    atomic_json(output_root.resolve() / "latest_successful.json", {"run_id": destination.name})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semi-report", type=Path, required=True)
    parser.add_argument("--core-run", type=Path, required=True)
    parser.add_argument("--stone", type=Path, default=STONE)
    parser.add_argument("--material-design", type=Path, default=MATERIAL_DESIGN)
    parser.add_argument("--part-mechanism", type=Path, default=PART_MECHANISM)
    parser.add_argument("--qc", type=Path, default=QC)
    parser.add_argument("--quoted", type=Path, help=f"Optional XLSX/CSV with SemiBOM and QuotedMinutes or QuotedHours; default checks {QUOTED}")
    parser.add_argument("--rasch-experiment", type=Path, help="Completed selected-model experiment; default is outputs/rasch_experiments/latest_experiment.json")
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs/semi_detail_workbooks")
    args = parser.parse_args()
    destination = args.output_root / (datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%S_%fZ_") + uuid.uuid4().hex[:8])
    quoted = args.quoted.resolve() if args.quoted else QUOTED if QUOTED.is_file() else None
    if args.quoted and not quoted.is_file():
        raise FileNotFoundError(quoted)
    if args.rasch_experiment:
        experiment_run = args.rasch_experiment.resolve()
    else:
        pointer = json.loads((EXPERIMENT_ROOT / "latest_experiment.json").read_text(encoding="utf-8"))
        experiment_run = EXPERIMENT_ROOT / pointer["run_id"]
    manifest = prepare(args.semi_report.resolve(), args.core_run.resolve(), args.stone.resolve(), args.qc.resolve(), destination.resolve(), quoted, experiment_run, args.material_design.resolve(), args.part_mechanism.resolve())
    print(json.dumps({"destination": str(destination), **{k: v for k, v in manifest.items() if k not in {"source_sha256", "sheet_columns"}}}, ensure_ascii=True))
    # The preferred Artifact Tool renderer runs out of heap on the complete
    # million-cell export; stream the reconciled rows to one XLSX instead.
    from .build_semi_detail_workbook_stream import build
    workbook = build(destination)
    print(workbook, flush=True)
    print(finalize(destination, manifest, workbook, args.output_root), flush=True)


if __name__ == "__main__":
    main()
