"""Export one auditable diagnostic row per SemiBOM from BOM and core run data.

The command never manufactures a final score from a nonconverged or unapproved
model. It includes excluded SemiBOMs with an explicit blocked status.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import uuid

import pandas as pd

from .run_reporting import atomic_json, file_hash
from .semi_scope import EXCLUDED_SEMI_PREFIXES, EXCLUDED_BOM_SUFFIXES, EXCLUDED_STATUS, excluded_semi_mask, semi_scope_rule


BOM_COLUMNS = [
    "MechanicalAssemblyPartCountPCS", "MechanicalAssemblyPartSKUCount",
    "StoneCount", "StoneSKUCount", "StoneTypeCount",
    "KnownStoneWeightGram", "MaterialGroupCount",
]
MODEL_COLUMNS = [
    "Estimated aggregate minutes per final OK", "Model Converged",
    "Time Interpretation", "ObservedFPY", "PassQty1", "InspectedQty1",
    "QCEvidenceN", "Quality Status", "FirstPass_Fit_Status",
    "FirstPass_Calibration_Status", "FirstPass_Decision_Eligibility",
    "Rework_Fit_Status", "Rework_Calibration_Status",
    "Rework_Decision_Eligibility", "Final Technical Complexity",
    "Approval Status", "Source Cutoff",
]


def _read_csv(path: Path, ids: dict[str, str]) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    return pd.read_csv(path, dtype=ids, low_memory=False)


def _require(frame: pd.DataFrame, columns: set[str], source: Path) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"{source} is missing required columns: {sorted(missing)}")


def build_item_rows(features: pd.DataFrame, inputs: pd.DataFrame, model: pd.DataFrame,
                    item_master: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per unique SemiBOM; joins by item with process agreement."""
    _require(features, {"SemiBOM", "SemiItem", "SemiName", "SourceFile", "FG BOM", "Status"}, Path("semi_bom_features.csv"))
    _require(inputs, {"SemiBOM", "SemiItem", "Process", "Material", "Product Type", *BOM_COLUMNS}, Path("semi_complexity_inputs.csv"))
    _require(model, {"Item Number", "Process", *MODEL_COLUMNS}, Path("Do kho SKU.csv"))
    for frame, fields in ((features, ["SemiBOM", "SemiItem"]), (inputs, ["SemiBOM", "SemiItem"]), (model, ["Item Number"])):
        for field in fields:
            frame[field] = frame[field].astype("string").str.strip()
    if features.SemiBOM.isna().any() or features.SemiBOM.eq("").any():
        raise ValueError("BOM features contain blank SemiBOM identifiers")
    if inputs.SemiBOM.duplicated().any() or model["Item Number"].duplicated().any():
        raise ValueError("Input or model item keys are not unique")
    statuses = features.groupby("SemiBOM").Status.agg(lambda s: "BOM structure usable" if s.eq("BOM structure usable").any() else str(s.iloc[0]))
    context_count = features.groupby("SemiBOM").size().rename("ContextCount")
    representative = (features.assign(_usable=features.Status.eq("BOM structure usable"))
        .sort_values(["SemiBOM", "_usable", "SourceFile", "FG BOM"], ascending=[True, False, True, True], kind="stable")
        .drop_duplicates("SemiBOM", keep="first")[["SemiBOM", "SemiItem", "SemiName", "SourceFile", "FG BOM"]])
    representative = representative.join(statuses.rename("BOMStatus"), on="SemiBOM").join(context_count, on="SemiBOM")
    detail = inputs[["SemiBOM", "SemiItem", "Process", "Material", "Product Type", *BOM_COLUMNS]].copy()
    detail = detail.rename(columns={"SemiItem": "_DetailSemiItem"})
    report = representative.merge(detail, on="SemiBOM", how="left", validate="one_to_one")
    mismatch = report._DetailSemiItem.notna() & report.SemiItem.ne(report._DetailSemiItem)
    if mismatch.any():
        raise ValueError("SemiItem differs between BOM features and distribution input")
    missing_detail = report.BOMStatus.eq("BOM structure usable") & report._DetailSemiItem.isna()
    extra_detail = report.BOMStatus.ne("BOM structure usable") & report._DetailSemiItem.notna()
    if missing_detail.any() or extra_detail.any():
        raise ValueError("BOM eligibility and item input population do not reconcile")
    report = report.drop(columns="_DetailSemiItem")
    model_detail = model[["Item Number", "Process", *MODEL_COLUMNS]].rename(columns={
        "Process": "ModelProcess",
        "Estimated aggregate minutes per final OK": "EstimatedMinutesPerFinalOK_Diagnostic",
        "Model Converged": "TimeModelConverged",
        "Time Interpretation": "TimeInterpretation",
        "Approval Status": "ModelApprovalStatus",
        "Final Technical Complexity": "_ModelFinalTechnicalComplexity",
        "Source Cutoff": "ModelSourceCutoff",
    })
    report = report.merge(model_detail, left_on="SemiItem", right_on="Item Number", how="left", validate="many_to_one")
    if item_master is not None:
        _require(item_master, {"Item Number", "Product Type"}, Path("Item_Master.xlsx"))
        item_master = item_master.copy()
        item_master["Item Number"] = item_master["Item Number"].astype("string").str.strip()
        if item_master["Item Number"].duplicated().any():
            raise ValueError("Item Master item keys are not unique")
        product_type = item_master.set_index("Item Number")["Product Type"]
        missing_type = report["Product Type"].isna()
        report.loc[missing_type, "Product Type"] = report.loc[missing_type, "SemiItem"].map(product_type)
    has_model = report["Item Number"].notna()
    process_match = has_model & report.Process.eq(report.ModelProcess).fillna(False)
    # A process mismatch must not borrow quality or time evidence from another process.
    for column in model_detail.columns.difference(["Item Number", "ModelProcess"]):
        report.loc[has_model & ~process_match, column] = pd.NA
    report["ModelLinkStatus"] = "MATCHED"
    report.loc[~has_model, "ModelLinkStatus"] = "NO_MODEL_ITEM"
    report.loc[has_model & ~process_match, "ModelLinkStatus"] = "PROCESS_MISMATCH"
    blocked_bom = report.BOMStatus.ne("BOM structure usable")
    # A blocked BOM still has an item identity. Show its mapped process for
    # reconciliation, while keeping all model evidence and scores blocked.
    blocked_process = blocked_bom & report.Process.isna() & report.ModelProcess.notna()
    report.loc[blocked_process, "Process"] = report.loc[blocked_process, "ModelProcess"]
    for column in model_detail.columns.difference(["Item Number"]):
        report.loc[blocked_bom, column] = pd.NA
    report.loc[blocked_bom, "ModelLinkStatus"] = "NOT_EVALUATED_BOM_BLOCKED"
    report["ReportStatus"] = "DIAGNOSTIC_ONLY"
    report.loc[~has_model, "ReportStatus"] = "NO_MODEL_ITEM"
    report.loc[has_model & ~process_match, "ReportStatus"] = "PROCESS_MISMATCH"
    report.loc[report.Process.eq("Unmapped"), "ReportStatus"] = "ITEM_MASTER_UNMAPPED"
    report.loc[blocked_bom, "ReportStatus"] = "BOM_BLOCKED"
    excluded_scope = excluded_semi_mask(report.SemiItem, report.SemiBOM)
    report["SemiScopeStatus"] = "IN_SCOPE"
    report.loc[excluded_scope, "SemiScopeStatus"] = EXCLUDED_STATUS
    report["SemiScopeRule"] = semi_scope_rule(report.SemiItem, report.SemiBOM)
    report.loc[excluded_scope, "ReportStatus"] = EXCLUDED_STATUS
    report.loc[excluded_scope, "ModelLinkStatus"] = "NOT_EVALUATED_EXCLUDED_SCOPE"
    eligible_score = (
        report.ReportStatus.eq("DIAGNOSTIC_ONLY")
        & report.ModelApprovalStatus.eq("Approved").fillna(False)
        & report.FirstPass_Decision_Eligibility.eq("ELIGIBLE").fillna(False)
        & pd.to_numeric(report._ModelFinalTechnicalComplexity, errors="coerce").notna()
    )
    report["FinalTechnicalComplexity"] = pd.to_numeric(report._ModelFinalTechnicalComplexity, errors="coerce").where(eligible_score)
    report.loc[eligible_score, "ReportStatus"] = "APPROVED"
    report = report.drop(columns=["Item Number", "_ModelFinalTechnicalComplexity"])
    first = ["SemiBOM", "SemiItem", "SemiName", "SemiScopeStatus", "SemiScopeRule", "ReportStatus", "FinalTechnicalComplexity",
             "BOMStatus", "ModelLinkStatus", "Process", "Material", "Product Type", "ContextCount",
             "SourceFile", "FG BOM", *BOM_COLUMNS]
    report = report[first + [c for c in report.columns if c not in first]].sort_values("SemiBOM", kind="stable")
    if len(report) != features.SemiBOM.nunique() or report.SemiBOM.duplicated().any():
        raise ValueError("SemiBOM report does not reconcile to one row per item")
    return report.reset_index(drop=True)


def _resolve_core_run(run: Path | None, core_root: Path) -> Path:
    if run is not None:
        return run.resolve()
    pointer = json.loads((core_root / "latest_successful.json").read_text(encoding="utf-8"))
    return (core_root / pointer["run_id"]).resolve()


def run(semi_dir: Path, core_run: Path | None, output_root: Path, core_root: Path = Path("outputs/runs")) -> Path:
    semi_dir, output_root = semi_dir.resolve(), output_root.resolve()
    core_run = _resolve_core_run(core_run, core_root.resolve())
    core_summary = json.loads((core_run / "run_summary.json").read_text(encoding="utf-8"))
    if core_summary["execution_status"] not in {"SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"}:
        raise ValueError("Core run is not complete")
    core_manifest = json.loads((core_run / "run_manifest.json").read_text(encoding="utf-8"))
    model_path = core_run / "artifacts" / "Do kho SKU.csv"
    recorded = next((a for a in core_manifest["artifacts"] if Path(a["path"]).name == model_path.name), None)
    if recorded is None or file_hash(model_path) != recorded["sha256"]:
        raise ValueError("Core item model artifact hash is missing or changed")
    sources = {
        "semi_bom_features.csv": semi_dir / "semi_bom_features.csv",
        "semi_complexity_inputs.csv": semi_dir / "semi_complexity_inputs.csv",
        "Do kho SKU.csv": model_path,
        "Item_Master.xlsx": core_run / "inputs" / "09_Item_Master" / "Item_Master.xlsx",
    }
    master_record = next((s for s in core_summary["sources"] if s.get("dataset") == "Item Master"
                          and Path(s["path"]).name == "Item_Master.xlsx"), None)
    if master_record is None or file_hash(sources["Item_Master.xlsx"]) != master_record["sha256"]:
        raise ValueError("Core Item Master snapshot is missing or changed")
    source_hashes = {name: file_hash(path) for name, path in sources.items()}
    features = _read_csv(sources["semi_bom_features.csv"], {"SemiBOM": str, "SemiItem": str, "FG BOM": str, "SourceFile": str})
    inputs = _read_csv(sources["semi_complexity_inputs.csv"], {"SemiBOM": str, "SemiItem": str, "FG BOM": str})
    model = _read_csv(model_path, {"Item Number": str})
    item_master = pd.read_excel(sources["Item_Master.xlsx"], dtype=str)
    report = build_item_rows(features, inputs, model, item_master)
    run_id = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%S_%fZ_") + uuid.uuid4().hex[:8]
    destination = output_root / run_id
    destination.mkdir(parents=True, exist_ok=False)
    snapshots = destination / "inputs"
    snapshots.mkdir()
    for name, source in sources.items():
        target = snapshots / name
        shutil.copy2(source, target)
        if file_hash(target) != source_hashes[name]:
            raise ValueError(f"Source changed during snapshot: {source}")
    output_csv = destination / "semi_item_report.csv"
    report.to_csv(output_csv, index=False, encoding="utf-8-sig")
    status_counts = {str(k): int(v) for k, v in report.ReportStatus.value_counts().items()}
    engineering_in_core = any(source.get("dataset") == "Engineering Factors" for source in core_summary.get("sources", []))
    summary = {
        "status": "SUCCEEDED_WITH_WARNINGS" if len(report) != status_counts.get("APPROVED", 0) else "SUCCEEDED",
        "decision_status": "DIAGNOSTIC_ONLY" if status_counts.get("DIAGNOSTIC_ONLY", 0) else "NO_APPROVED_ITEMS",
        "run_id": run_id, "core_run_id": core_summary["run_id"],
        "rows": len(report), "unique_semi_boms": report.SemiBOM.nunique(),
        "engineering_factors_in_core_run": engineering_in_core,
        "status_counts": status_counts,
        "excluded_prefixes": list(EXCLUDED_SEMI_PREFIXES),
        "excluded_bom_suffixes": list(EXCLUDED_BOM_SUFFIXES),
        "excluded_scope_rows": int(excluded_semi_mask(report.SemiItem, report.SemiBOM).sum()),
        "source_hashes": source_hashes,
        "output_sha256": file_hash(output_csv),
        "definition": "One row per SemiBOM; mechanical assembly parts are direct SM_Casting/SM_ACJ PCS quantities from the selected valid BOM context",
        "limitation": "Only a model-approved, first-pass-eligible nonmissing score is released as FinalTechnicalComplexity; other model fields are diagnostic",
    }
    atomic_json(destination / "semi_item_report_summary.json", summary)
    lines = ["# Semi item report", "", f"Core run: `{core_summary['run_id']}`. Report run: `{run_id}`.", "",
             f"The CSV contains **{len(report):,} unique SemiBOMs**, one row each, including BOM-blocked items.", "",
             "| Status | SemiBOMs |", "|---|---:|"]
    lines += [f"| {status} | {count:,} |" for status, count in status_counts.items()]
    lines += ["", "Codes with listed prefixes or ending -01/-02 in the Semi or BOM identifier are kept for reconciliation but excluded from Semi scoring. The suffixes indicate likely outsourced items under the current business rule, not verified supplier status.", "",
              "`FinalTechnicalComplexity` is populated only when the core model explicitly marks an item approved and first-pass eligible. Blank means no approved score; it is not zero. Time and QC values, where present, are diagnostics.", "",
              "`MechanicalAssemblyPartCountPCS` counts only direct SM_Casting and SM_ACJ rows in PCS in a valid BOM context. Flagged BOMs retain an explicit blocked status and no complexity inputs.", "",
              "Source snapshots and SHA-256 hashes are stored in this run. The item-level source is `semi_item_report.csv`; `semi_item_report_summary.json` gives counts and checks.", ""]
    if not engineering_in_core:
        lines += ["Engineering factors were absent from the selected core run; no factor-based final technical complexity can be published from it.", ""]
    (destination / "semi_item_report_summary.md").write_text("\n".join(lines), encoding="utf-8")
    atomic_json(output_root / "latest_successful.json", {"run_id": run_id})
    print(destination / "semi_item_report_summary.md")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semi-dir", type=Path, required=True, help="Directory with semi_bom_features.csv and semi_complexity_inputs.csv")
    parser.add_argument("--core-run", type=Path, help="Completed core run; default resolves latest_successful.json")
    parser.add_argument("--core-root", type=Path, default=Path("outputs/runs"))
    parser.add_argument("--output-root", type=Path, default=Path("outputs/semi_item_reports"))
    args = parser.parse_args()
    run(args.semi_dir, args.core_run, args.output_root, args.core_root)
