"""Reusable, conservative v0.5.3 pipeline; CSV, Excel and JSON audit outputs."""
from __future__ import annotations
import hashlib
import json
import logging
from dataclasses import asdict
from pathlib import Path
import numpy as np
import pandas as pd
from .config import Config
from .data_contracts import GROUP, item_mapping, attach_mapping, connectivity, trajectory_keys, chronological_split, require
from .preprocessing import clean_production_data, clean_planner_data
from .hybrid_effect import fit_hybrid_effect
from .validation import _predict_from_effects
from .evaluation import regression_metrics
from .qc_pipeline import reconstruct_qc, recovery_trajectories, recovery_groups, reconstruct_touch
from .scoring import technical_complexity

LOG = logging.getLogger(__name__)
ID_TYPES = {c:"string" for c in ["Reference","WO","Worker","Worker ID","InitialWorker","Item Number","Item Number (Size Adjusted)","QualityOrderId","EventID"]}

FOLDER_DATASETS = {
    "Production": ("01_Production", "Production"),
    "Planner Skills": ("02_Planner_Skills", "Planner Skills"),
    "Item Mapping": ("03_Item_Mapping", "Item Mapping"),
    "QC Tickets": ("04_QC_Tickets", "QC Tickets"),
    "Touch Events": ("05_Touch_Events", "Touch Events"),
    "Engineering Factors": ("06_Engineering_Factors", "Engineering Factors"),
    "Pilot Log": ("07_Pilot_Log", "Pilot Log"),
    "Reference Master": ("08_Reference_Master", "Reference Master"),
    "Item Master": ("09_Item_Master", "Item Master"),
    "Worker Master": ("10_Worker_Master", "Worker Master"),
}


def read_table(path):
    return pd.read_csv(path,dtype=ID_TYPES) if Path(path).suffix.lower()==".csv" else pd.read_excel(path,dtype=ID_TYPES)


def discover_input_files(input_dir):
    """Return all supported data files under each named input folder.

    Files beginning with ``~$`` are Excel lock files and are ignored. Multiple
    files in one folder are intentionally combined to support gradual drops.
    """
    base = Path(input_dir)
    discovered = {}
    for dataset, aliases in FOLDER_DATASETS.items():
        folder = next((base / alias for alias in aliases if (base / alias).is_dir()), None)
        if folder is None:
            discovered[dataset] = []
            continue
        discovered[dataset] = sorted(
            p for p in folder.iterdir()
            if p.is_file() and not p.name.startswith("~$")
            and p.suffix.lower() in {".xlsx", ".xls", ".csv"}
        )
    return discovered


def read_dataset_files(paths, sheet_name):
    """Read and concatenate a dataset's files while preserving source rows."""
    frames = []
    for path in paths:
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(path, dtype=ID_TYPES)
        else:
            workbook = pd.ExcelFile(path)
            selected = sheet_name if sheet_name in workbook.sheet_names else workbook.sheet_names[0]
            frame = pd.read_excel(path, sheet_name=selected, dtype=ID_TYPES)
        frame = frame.dropna(how="all")
        if not frame.empty:
            frame["SourceFile"] = path.name
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def load_inputs(config, template=None):
    sources = {}
    if template:
        sources = pd.read_excel(template, sheet_name=None,dtype=ID_TYPES)
        return {k: v.dropna(how="all") for k,v in sources.items()}
    if not config.input_dir or not Path(config.input_dir).is_dir():
        raise FileNotFoundError(f"Input folder does not exist: {config.input_dir}. Create it with python -m pipeline.create_folder_templates")
    discovered = discover_input_files(config.input_dir)
    for dataset, paths in discovered.items():
        if paths:
            sources[dataset] = read_dataset_files(paths, dataset)
    return sources


def input_source_paths(config, template=None):
    """List files used by a run for manifest hashing and audit."""
    if template:
        return [Path(template)]
    if not config.input_dir or not Path(config.input_dir).is_dir():
        raise FileNotFoundError(f"Input folder does not exist: {config.input_dir}")
    return [path for paths in discover_input_files(config.input_dir).values() for path in paths]


def _normalise_production_aliases(frame):
    """Accept the plain-language form labels while keeping canonical model names."""
    out = frame.copy()
    aliases = {
        "Quantity Doing": "Qty Doing",
        "Actual Hours": "Total Actual Hours",
        "Item number": "Item Number",
    }
    for source, target in aliases.items():
        if source in out.columns and target not in out.columns:
            out = out.rename(columns={source: target})
    return out


def enrich_production_from_master(production, reference_master=None, item_master=None, worker_master=None):
    """Attach master attributes to the five-column Production entry form.

    The public folder form accepts only Reference, Worker, Item Number, Qty Doing
    and Total Actual Hours. Legacy inline master columns remain accepted only for
    compatibility with historical fixtures; a new five-column folder file needs
    the three master datasets.
    """
    out = _normalise_production_aliases(production)
    required_entry = ["Reference", "Worker", "Item Number", "Qty Doing", "Total Actual Hours"]
    require(out, required_entry, "Production entry form")
    reference_master = reference_master if reference_master is not None else pd.DataFrame()
    item_master = item_master if item_master is not None else pd.DataFrame()
    worker_master = worker_master if worker_master is not None else pd.DataFrame()
    legacy_columns = {"Process", "RAF Month", "Customer Name", "Product Type", "Material", "Name"}
    has_legacy = legacy_columns.issubset(out.columns)
    if reference_master.empty and item_master.empty and worker_master.empty and has_legacy:
        return out
    if reference_master.empty:
        raise ValueError("Reference Master is required for RAF Month, Customer Name and Product Type")
    if item_master.empty:
        raise ValueError("Item Master is required for Size Adjusted group, Process and Material")
    if worker_master.empty:
        raise ValueError("Worker Master is required for Worker Name")

    def clean_key(frame, col):
        frame = frame.copy()
        frame[col] = frame[col].astype("string").str.strip()
        return frame

    ref = clean_key(reference_master, "Reference")
    require(ref, ["Reference", "RAF Month", "Customer Name", "Product Type"], "Reference Master")
    if ref.duplicated("Reference").any():
        raise ValueError("Reference Master has duplicate Reference keys")
    item = clean_key(item_master, "Item Number")
    require(item, ["Item Number", "Item Number (Size Adjusted)", "Process", "Material"], "Item Master")
    if item.duplicated("Item Number").any():
        raise ValueError("Item Master has duplicate Item Number keys")
    worker = clean_key(worker_master, "Worker")
    require(worker, ["Worker", "Name"], "Worker Master")
    if worker.duplicated("Worker").any():
        raise ValueError("Worker Master has duplicate Worker keys")

    out = out.merge(ref[["Reference", "RAF Month", "Customer Name", "Product Type"]], on="Reference", how="left", validate="many_to_one", suffixes=("", "_Master"))
    out = out.merge(item[["Item Number", "Item Number (Size Adjusted)", "Process", "Material"]], on="Item Number", how="left", validate="many_to_one", suffixes=("", "_Master"))
    out = out.merge(worker[["Worker", "Name"]], on="Worker", how="left", validate="many_to_one", suffixes=("", "_Master"))
    required_master = ["RAF Month", "Customer Name", "Product Type", "Item Number (Size Adjusted)", "Process", "Material", "Name"]
    missing_rows = out[required_master].isna().any(axis=1)
    if missing_rows.any():
        raise ValueError(f"Master data missing for {int(missing_rows.sum())} Production rows")
    return out


def stamp(frame, config, cutoff, status="Diagnostic Only"):
    out = frame.copy()
    out["Model Version"] = config.model_version
    out["Source Cutoff"] = str(cutoff)
    out["Approval Status"] = status
    if "Evidence N" not in out:
        out["Evidence N"] = out.get("QCEvidenceN", out.get("WOs", out.get("GroupEvidenceN", out.get("Worker Records", np.nan))))
    if "Confidence / Interval" not in out:
        out["Confidence / Interval"] = "Unavailable / not validated"
    if "Extrapolation Flag" not in out:
        out["Extrapolation Flag"] = out.get("ExtrapolationFlag", "Not assessed")
    if "Data Quality Status" not in out:
        out["Data Quality Status"] = "See Data Quality and Go Live Gates"
    return out


def fit_time_models(data, planner, config=None):
    """Aggregate time diagnostic only. Real WOs used for temporal evaluation."""
    config = config or Config()
    data = data.merge(planner.rename(columns={"Worker ID":"Worker", "Planner Verified Skill Level":"CertifiedSkill"})[["Worker", "Process", "CertifiedSkill"]], on=["Worker","Process"], how="left", validate="many_to_one")
    # Complete network diagnostics first, before any estimator is invoked.
    network = connectivity(data)
    item_rows, worker_rows, metrics, saved_models = [], [], [], {}
    for process, part in data.groupby("Process"):
        LOG.info("Fitting aggregate time diagnostic: %s (%d rows)", process, len(part))
        frame = part.copy()
        frame["Original Item Number"] = frame["Item Number"]
        frame["Item Number"] = frame[GROUP]
        model = fit_hybrid_effect(frame,max_iter=config.time_max_iter,tol=config.time_tolerance)
        if not model.get("converged"):
            LOG.warning("%s did not converge; scores remain diagnostic", process)
        residual = frame.log_time-model["predictions"]
        smear = float(np.exp(residual.clip(-30,30)).mean())
        items = model["item_scores"].rename(columns={"Item Number": GROUP, "Hybrid Item FE":"Aggregate Time Group Effect"})
        items["Process"] = process
        items["Estimated aggregate minutes per final OK"] = 60*np.exp(model["intercept"]+items["Aggregate Time Group Effect"])*smear
        items["Time Interpretation"] = "Historical aggregate effort including rework; assignment-conditional"
        items["Model Converged"] = bool(model["converged"])
        items = items.merge(network[network.Process.eq(process)], on=["Process",GROUP], validate="one_to_one")
        # No relative time expectation for weak components: keep the raw effect inspectable.
        items.loc[items.ConnectivityStatus.eq("WeakNetwork"), "Estimated aggregate minutes per final OK"] = np.nan
        item_rows.append(items)
        workers = model["worker_scores"].rename(columns={"Hybrid Worker Ability":"Aggregate Speed Effect"})
        workers["Process"] = process
        worker_rows.append(workers)
        frame["TrajectoryKey"], frame["WOEligible"] = trajectory_keys(frame)
        eligible = frame[frame.WOEligible]
        train, test, embargo = chronological_split(eligible, "RAF Month", "TrajectoryKey") if len(eligible) else (frame.iloc[:0],)*3
        record = {"Process": process, "Validation": "WO chronological aggregate-time holdout", "Training N": len(train), "Test N": len(test), "Embargo N": len(embargo), "Unlinked N": int((~frame.WOEligible).sum()), "Status":"Insufficient Evidence"}
        if len(train)>1 and len(test)>0 and train.Worker.nunique()>1:
            fitted = fit_hybrid_effect(train,max_iter=config.time_max_iter,tol=config.time_tolerance)
            predictions = _predict_from_effects(fitted, test)
            residual_train = train.log_time-fitted["predictions"]
            smear_train = float(np.exp(residual_train.clip(-30,30)).mean())
            actual_minutes = 60*np.exp(test.log_time)
            predicted_minutes = 60*np.exp(predictions)*smear_train
            record.update(regression_metrics(test.log_time, predictions))
            record.update({"WAPE minutes": float((actual_minutes-predicted_minutes).abs().sum()/actual_minutes.sum()),
                "Status":"Diagnostic Only" if fitted["converged"] else "Nonconverged diagnostic",
                "Train Last Month": str(train["RAF Month"].max()), "Test First Month":str(test["RAF Month"].min()),
                "Unseen Worker N":int((~test.Worker.isin(train.Worker)).sum()), "Unseen Group N":int((~test[GROUP].isin(train[GROUP])).sum())})
        metrics.append(record)
        saved_models[process] = {"intercept": model["intercept"], "smearing_factor":smear, "unit":"hours per final OK",
            "status":"Diagnostic Only", "converged":bool(model["converged"]),
            "worker_effects":model["worker_scores"].set_index("Worker")["Hybrid Worker Effect"].to_dict(),
            "group_effects":model["item_scores"].set_index("Item Number")["Hybrid Item FE"].to_dict()}
    items = pd.concat(item_rows, ignore_index=True) if item_rows else pd.DataFrame()
    workers = pd.concat(worker_rows, ignore_index=True) if worker_rows else pd.DataFrame(columns=["Worker","Process"])
    # Preserve every official Planner score including workers absent from production.
    workers = workers.merge(planner.rename(columns={"Worker ID":"Worker"}), on=["Worker","Process"], how="outer", validate="one_to_one")
    workers["Planner Skill Status"] = "Current snapshot; effective date / approval history not verified"
    return items, workers, pd.DataFrame(metrics), network, saved_models


def write_outputs(output, tables, manifest, models):
    from .workbook_io import write_result_workbook
    output.mkdir(parents=True, exist_ok=True)
    for sheet, frame in tables.items():
        frame.to_csv(output/f"{sheet}.csv", index=False, encoding="utf-8-sig")
    write_result_workbook(output/"Skill_ID_Ket_qua_chay_thu.xlsx", tables)
    (output/"run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (output/"time_models.json").write_text(json.dumps(models, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def run_pipeline(config, template=None):
    inputs = load_inputs(config, template)
    raw = inputs.get("Production", pd.DataFrame())
    raw = enrich_production_from_master(raw,
        inputs.get("Reference Master", pd.DataFrame()),
        inputs.get("Item Master", pd.DataFrame()),
        inputs.get("Worker Master", pd.DataFrame()))
    planner_raw = inputs.get("Planner Skills", pd.DataFrame())
    require(raw, ["Worker", "Item Number", "Qty Doing", "Total Actual Hours", "RAF Month", "Process"], "Production")
    mapping_raw = inputs.get("Item Mapping", pd.DataFrame())
    item_master = inputs.get("Item Master", pd.DataFrame())
    mapping = item_mapping(item_master if not item_master.empty else (mapping_raw if not mapping_raw.empty else raw))
    planner = clean_planner_data(planner_raw)
    data = clean_production_data(raw, config.incomplete_month)
    data = attach_mapping(data, mapping)
    data["SourceRow"] = data.get("SourceRow", data.index+2)
    if config.source_cutoff:
        cutoff = pd.Timestamp(config.source_cutoff)
        data = data[data["RAF Month"].le(cutoff)].copy()
    else:
        cutoff = pd.to_datetime(raw["RAF Month"], errors="coerce").max()
        qc_input = inputs.get("QC Tickets", pd.DataFrame())
        if "QC_Stop" in qc_input:
            qc_latest = pd.to_datetime(qc_input.QC_Stop, errors="coerce").max()
            if pd.notna(qc_latest) and (pd.isna(cutoff) or qc_latest>cutoff):
                cutoff = qc_latest
    quality = []
    quality.append({"Check":"Production input rows", "N":len(raw), "Status":"Observed"})
    quality.append({"Check":"Production retained after basic filters", "N":len(data), "Status":"Observed; latest month retained unless explicitly excluded"})
    keys = ["Reference","Worker","Item Number","RAF Month"]
    duplicate = data.duplicated(keys, keep=False) if "Reference" in data else pd.Series(False,index=data.index)
    unassigned = data.Process.isna() | data.Process.isin(["", "Unknown"])
    exceptions = data.loc[duplicate | unassigned].copy()
    exceptions["Reason"] = np.where(duplicate.loc[exceptions.index], "Duplicate production key", "Exact Item Process unavailable")
    quality += [{"Check":"Duplicate production rows quarantined", "N":int(duplicate.sum()), "Status":"Exception" if duplicate.any() else "Valid"},
                {"Check":"Unmapped production rows quarantined", "N":int(unassigned.sum()), "Status":"Exception" if unassigned.any() else "Valid"}]
    data = data.loc[~duplicate & ~unassigned].reset_index(drop=True)
    if data.empty:
        raise ValueError("No eligible production rows. Fill Production and Planner Skills in the input template.")
    time_items, workers, validation, network, models = fit_time_models(data, planner, config)
    item_output = mapping.merge(time_items, on=["Process",GROUP], how="left", validate="many_to_one")
    item_output["FPY_Rasch_Difficulty"] = np.nan
    item_output["FPY_Raw_Difficulty"] = np.nan
    item_output["QualityDifficulty"] = np.nan
    item_output["Final Technical Complexity"] = np.nan
    item_output["Quality Status"] = "Insufficient Evidence: QC not supplied"
    tables = {}
    qc = inputs.get("QC Tickets", pd.DataFrame())
    rounds = pd.DataFrame()
    if not qc.empty:
        rounds, first, qc_exceptions = reconstruct_qc(qc, mapping, cutoff)
        tables["QC can kiem"] = qc_exceptions
        tables["WO vong dau"] = first
        tables["QC rounds"] = rounds
        trajectories = recovery_trajectories(rounds, cutoff)
        tables["QC hanh trinh"] = trajectories
        recovered = recovery_groups(trajectories)
        tables["Recovery Semi"] = recovered
        if not first.empty:
            aggregate = first.groupby(["Process",GROUP], as_index=False).agg(PassQty1=("PassQty","sum"), InspectedQty1=("InspectedQty","sum"), QCEvidenceN=("WO","nunique"))
            aggregate["ObservedFPY"] = aggregate.PassQty1/aggregate.InspectedQty1
            tables["FPY Semi"] = aggregate
            for sheet, key in [("FPY cong doan", "Process"), ("FPY thang", "QCMonth")]:
                first["QCMonth"] = first.QC_Start.dt.strftime("%Y-%m")
                f = first.groupby(key, as_index=False).agg(PassQty1=("PassQty","sum"), InspectedQty1=("InspectedQty","sum"), WOs=("WO","nunique"))
                f["ObservedFPY"] = f.PassQty1/f.InspectedQty1
                tables[sheet] = f
            item_output = item_output.merge(aggregate, on=["Process",GROUP], how="left", validate="many_to_one")
            item_output["FPY_Raw_Difficulty"] = 10*(1-item_output.ObservedFPY)
            item_output["Quality Status"] = np.where(item_output.ObservedFPY.notna(), "Raw FPY fallback; uncalibrated assignment-conditional", "Insufficient Evidence: no eligible QC")
        else:
            item_output["Quality Status"] = "Insufficient Evidence: no eligible QC"
    touch = inputs.get("Touch Events", pd.DataFrame())
    if not touch.empty:
        if config.source_cutoff:
            touch = touch[pd.to_datetime(touch.Worker_Stop,errors="coerce").le(cutoff)]
        tables["Touch reconstruction"] = reconstruct_touch(touch, rounds)
    factors = inputs.get("Engineering Factors", pd.DataFrame())
    if not factors.empty:
        calculated = technical_complexity(factors)
        # Even complete approved rubrics cannot bypass the unvalidated quality model gate.
        calculated = calculated.rename(columns={"Final Technical Complexity":"Approved Factor Weighted Sum"})
        item_output = item_output.merge(calculated, on=["Item Number","Process"], how="left", validate="one_to_one")
        tables["Checklist cham diem"] = factors
    gates = [
        ("Aggregate time diagnostic", "Available", "Includes rework; cannot be called clean cycle time"),
        ("QC reconstruction", "Available" if len(rounds) else "Missing eligible QC", "Requires canonical ticket schema; full July-WO exclusion"),
        ("Quality model calibration", "Not validated", "Beta-binomial / WO random effect candidates require real QC and holdout validation"),
        ("Planner history", "Not verified", "Effective-dated skill, approver and version required before go-live"),
        ("Clean touch-time model", "Not validated", "Timestamp coverage, first-pass quantity attribution and WAPE acceptance required"),
        ("Recovery weighting", "Not calibrated", "80/20 is a pilot assumption; no automatic weight redistribution"),
        ("Engineering factors", "Pending validation", "All five approved factors with evidence; size and rubric gates"),
        ("Matching", "Unavailable", "Calibration, certification, confidence, capacity and Planner review required"),
        ("Scrap", "InDevelopment / NotAvailable", "Missing ScrapQty stays blank"),
        ("Pilot approval", "Pending", "Power analysis and Planner, Engineering, QC and IT decisions remain external")]
    tables = {"Do kho SKU": stamp(item_output,config,cutoff), "Worker capability":stamp(workers,config,cutoff),
        "Model Validation":validation, "Connectivity":network, "Data Quality":pd.DataFrame(quality),
        "Production exceptions":exceptions, "Go Live Gates":pd.DataFrame(gates,columns=["Gate","Status","Requirement"]), **tables}
    for name in ["FPY Semi", "FPY cong doan", "FPY thang", "QC hanh trinh", "Recovery Semi"]:
        if name in tables:
            tables[name] = stamp(tables[name],config,cutoff)
    for name in ["QC can kiem", "WO vong dau", "QC rounds", "QC hanh trinh", "Recovery Semi", "FPY Semi", "FPY cong doan", "FPY thang", "Touch reconstruction", "Checklist cham diem"]:
        tables.setdefault(name,pd.DataFrame({"Status":["Unavailable: required input not supplied"]}))
    # Canonical views remain visibly unavailable instead of invented data.
    for name, reason in {"Ghep tho Semi":"No calibrated matching model or approved assignment gates", "BOM bang chung":"BOM not supplied / version not approved", "Phieu cham pilot":"Prospective pilot has not run", "WO chua noi":"See Production exceptions and QC can kiem for source-specific exceptions"}.items():
        tables[name] = pd.DataFrame({"Status":["Unavailable"], "Reason":[reason]})
    paths = input_source_paths(config, template)
    manifest = {"model_version":config.model_version,"configuration":asdict(config),"cutoff":str(cutoff),
        "sources":[{"path":str(p.resolve()),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
        "retained_production_rows":len(data),"status":"Diagnostic Only; production gates incomplete",
        "scaling":"Planner raw 0-10 retained; time scores are latent effects, not skill levels",
        "time_validation":"Real WO chronological holdout; DUMMY references excluded from validation; spanning WOs embargoed"}
    import platform
    import openpyxl
    manifest["runtime"] = {"python":platform.python_version(),"pandas":pd.__version__,"numpy":np.__version__,"openpyxl":openpyxl.__version__}
    manifest["code_sha256"] = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob("*.py")}
    write_outputs(config.output_dir,tables,manifest,models)
    LOG.info("Wrote %s",config.output_dir/"Skill_ID_Ket_qua_chay_thu.xlsx")
    return {"tables":tables,"data":data,"manifest":manifest,"models":models}
