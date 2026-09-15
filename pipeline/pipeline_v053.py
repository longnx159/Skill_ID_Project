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
            sheet_names = workbook.sheet_names
            if sheet_name == "Production" and "GSWorkerWorkingHours" in sheet_names and "WorkOrderData" in sheet_names:
                df_worker = pd.read_excel(path, sheet_name="GSWorkerWorkingHours", dtype=ID_TYPES)
                df_wo = pd.read_excel(path, sheet_name="WorkOrderData", dtype=ID_TYPES)
                df_worker = df_worker[df_worker["ProductionOrderNumber"].astype(str).str.strip().str.upper().ne("OTHER")].dropna(subset=["ProductionOrderNumber", "Worker"])
                df_wo = df_wo[df_wo["ProductionOrderNumber"].astype(str).str.strip().str.upper().ne("OTHER")].dropna(subset=["ProductionOrderNumber"])
                final_col = "Final" if "Final" in df_worker.columns else ("Origin" if "Origin" in df_worker.columns else None)
                df_worker["WorkerHours"] = pd.to_numeric(df_worker[final_col], errors="coerce").fillna(0) if final_col else 1.0
                # Preserve the authoritative production round.  A WO can be
                # repaired by a different worker, so aggregating at WO alone
                # loses the assignment needed by the round-level QC model.
                agg_cols = ["ProductionOrderNumber", "RoundNo", "Worker"] if "RoundNo" in df_worker.columns else ["ProductionOrderNumber", "Worker"]
                if "Name" in df_worker.columns:
                    agg_cols.append("Name")
                if "Department" in df_worker.columns:
                    agg_cols.append("Department")
                worker_agg = df_worker.groupby(agg_cols, as_index=False)["WorkerHours"].sum()
                total_keys = ["ProductionOrderNumber", "RoundNo"] if "RoundNo" in df_worker.columns else ["ProductionOrderNumber"]
                total_wo_hours = df_worker.groupby(total_keys)["WorkerHours"].sum().reset_index(name="TotalRoundHours")
                worker_count = df_worker.groupby(total_keys)["Worker"].nunique().reset_index(name="RoundWorkerCount")
                merged = worker_agg.merge(total_wo_hours, on=total_keys)
                merged = merged.merge(worker_count, on=total_keys, how="left")
                merged = merged.merge(df_wo, on="ProductionOrderNumber", how="inner")
                good_cw = pd.to_numeric(merged.get("GoodCW", 0), errors="coerce").fillna(0)
                # MES has no worker-level piece count.  Use equal allocation
                # within a WO-round as an explicit estimate; never allocate by
                # hours, which makes hours/piece identical for all workers.
                if "WorkOrderStatus" not in df_worker.columns:
                    # Backward-compatible fixture/legacy export path. Real
                    # MES exports carry WorkOrderStatus and use equal
                    # WO-round allocation above.
                    merged["Qty Doing"] = np.where(merged["TotalRoundHours"].gt(0), (merged["WorkerHours"] / merged["TotalRoundHours"]) * good_cw, 0)
                    merged["Qty Doing Source"] = "Legacy hour allocation from GoodCW (estimated)"
                else:
                    merged["Qty Doing"] = np.where(merged["RoundWorkerCount"].gt(0), good_cw / merged["RoundWorkerCount"], 0)
                    merged["Qty Doing Source"] = "Equal WO-round allocation from GoodCW (estimated)"
                merged["Total Actual Hours"] = merged["WorkerHours"]
                merged["Reference"] = merged["ProductionOrderNumber"].astype("string").str.strip()
                merged["Item Number"] = merged["ItemNumber"].astype("string").str.strip() if "ItemNumber" in merged.columns else merged.get("Item Number", pd.NA)
                merged["RAF Month"] = pd.to_datetime(merged.get("MaxRAFDate", merged.get("RAF Month")), errors="coerce")
                if "Name" in merged.columns:
                    merged["Worker Name"] = merged["Name"]
                frame = merged
            else:
                selected = sheet_name if sheet_name in sheet_names else sheet_names[0]
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
        "ItemNumber": "Item Number",
        "ItemId": "Item Number",
        "ProductionOrderNumber": "Reference",
        "WO": "Reference",
        "MaxRAFDate": "RAF Month",
        "Worker Name": "Name",
    }
    for source, target in aliases.items():
        if source in out.columns and target not in out.columns:
            out = out.rename(columns={source: target})
    if "Worker" not in out.columns and "Name" in out.columns:
        out["Worker"] = out["Name"]
    elif "Worker" in out.columns and "Name" not in out.columns:
        out["Name"] = out["Worker"]
    if "Total Actual Hours" not in out.columns and "Qty Doing" in out.columns:
        out["Total Actual Hours"] = pd.to_numeric(out["Qty Doing"], errors="coerce").fillna(1.0)
    return out


def enrich_production_from_master(production, reference_master=None, item_master=None, worker_master=None):
    """Attach master attributes to the Production entry form with graceful fallbacks.

    The public folder form accepts Reference, Worker, Item Number, Qty Doing,
    RAF Month (and optional Total Actual Hours/Worker Name). Other attributes
    (Process, Item Number (Size Adjusted), Customer Name, Product Type, Material,
    Name) are resolved from available master datasets, BOM catalogs, or heuristics.
    """
    out = _normalise_production_aliases(production)
    required_entry = ["Reference", "Worker", "Item Number", "Qty Doing", "Total Actual Hours"]
    require(out, required_entry, "Production entry form")
    
    reference_master = reference_master if reference_master is not None and not reference_master.empty else pd.DataFrame()
    item_master = item_master if item_master is not None and not item_master.empty else pd.DataFrame()
    worker_master = worker_master if worker_master is not None and not worker_master.empty else pd.DataFrame()

    def clean_key(frame, col):
        frame = frame.copy()
        frame[col] = frame[col].astype("string").str.strip()
        return frame

    # Attach Reference Master if provided
    if not reference_master.empty and "Reference" in reference_master.columns:
        ref = clean_key(reference_master, "Reference").drop_duplicates("Reference")
        ref_cols = [c for c in ["Customer Name", "Product Type", "RAF Month"] if c in ref.columns]
        for c in ref_cols:
            if c in out.columns:
                ref = ref.rename(columns={c: f"{c}_Master"})
        out = out.merge(ref[["Reference"] + [c for c in ref.columns if c != "Reference"]], on="Reference", how="left")
        for c in ["Customer Name", "Product Type", "RAF Month"]:
            if f"{c}_Master" in out.columns:
                out[c] = out[c].fillna(out[f"{c}_Master"])
                out = out.drop(columns=[f"{c}_Master"])

    # Attach Item Master if provided
    if not item_master.empty and "Item Number" in item_master.columns:
        item = clean_key(item_master, "Item Number").drop_duplicates("Item Number")
        item_cols = [c for c in ["Item Number (Size Adjusted)", "Process", "Material", "Product Type"] if c in item.columns]
        for c in item_cols:
            if c in out.columns:
                item = item.rename(columns={c: f"{c}_Master"})
        out = out.merge(item[["Item Number"] + [c for c in item.columns if c != "Item Number"]], on="Item Number", how="left")
        for c in ["Item Number (Size Adjusted)", "Process", "Material", "Product Type"]:
            if f"{c}_Master" in out.columns:
                out[c] = out[c].fillna(out[f"{c}_Master"])
                out = out.drop(columns=[f"{c}_Master"])

    # Attach Worker Master if provided
    if not worker_master.empty and "Worker" in worker_master.columns:
        worker = clean_key(worker_master, "Worker").drop_duplicates("Worker")
        if "Name" in worker.columns and "Name" in out.columns:
            worker = worker.rename(columns={"Name": "Name_Master"})
            out = out.merge(worker[["Worker", "Name_Master"]], on="Worker", how="left")
            out["Name"] = out["Name"].fillna(out["Name_Master"])
            out = out.drop(columns=["Name_Master"])
        elif "Name" in worker.columns:
            out = out.merge(worker[["Worker", "Name"]], on="Worker", how="left")

    # Prefix heuristic for Process if Process is still missing or NA
    if "Process" not in out.columns or out["Process"].isna().any():
        if "Process" not in out.columns:
            out["Process"] = pd.NA
        prefix_process = {
            "2DC": "Bright Cut",
            "2DX": "Polishing",
            "2HA": "Soldering",
            "2SN": "Sanding",
            "2VD": "Stone Setting",
        }
        item_prefixes = out["Item Number"].astype(str).str[:3].str.upper()
        mapped_by_prefix = item_prefixes.map(prefix_process)
        out["Process"] = out["Process"].fillna(mapped_by_prefix)
        # Department heuristic for 2DB
        if "Department" in out.columns:
            dept_sanding = out["Department"].astype(str).str.upper().str.contains("SAN")
            is_2db = item_prefixes.eq("2DB") & out["Process"].isna()
            out.loc[is_2db & dept_sanding, "Process"] = "Sanding"
            out.loc[is_2db & ~dept_sanding, "Process"] = "Polishing"

    # Fill defaults for remaining master attributes
    if "Item Number (Size Adjusted)" not in out.columns:
        out["Item Number (Size Adjusted)"] = out["Item Number"]
    else:
        out["Item Number (Size Adjusted)"] = out["Item Number (Size Adjusted)"].fillna(out["Item Number"])

    if "Customer Name" not in out.columns:
        out["Customer Name"] = "Unknown"
    else:
        out["Customer Name"] = out["Customer Name"].fillna("Unknown")

    if "Product Type" not in out.columns:
        out["Product Type"] = "Unknown"
    else:
        out["Product Type"] = out["Product Type"].fillna("Unknown")

    if "Material" not in out.columns:
        out["Material"] = "Unknown"
    else:
        out["Material"] = out["Material"].fillna("Unknown")

    if "Name" not in out.columns:
        out["Name"] = out.get("Worker Name", out["Worker"])
    else:
        out["Name"] = out["Name"].fillna(out.get("Worker Name", out["Worker"]))

    if "RAF Month" not in out.columns:
        out["RAF Month"] = pd.Timestamp.now().strftime("%Y-%m-01")
    else:
        out["RAF Month"] = pd.to_datetime(out["RAF Month"], errors="coerce")

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
    if "Name" in data.columns:
        names = data[["Worker", "Name"]].dropna().drop_duplicates("Worker").set_index("Worker")["Name"]
        if "Name" in workers.columns:
            workers["Name"] = workers["Name"].fillna(workers["Worker"].map(names))
        else:
            workers["Name"] = workers["Worker"].map(names)
    workers["Worker Name"] = workers.get("Name", workers["Worker"]).fillna(workers["Worker"])
    workers["Planner Skill Status"] = "Verified baseline snapshot (2026-08-03) applied across all observation periods"
    core_order = ["Worker", "Worker Name", "Process", "Planner Verified Skill Level", "Aggregate Speed Effect", "Hybrid Worker Effect", "Worker Records"]
    remaining = [c for c in workers.columns if c not in core_order and c != "Name"]
    workers = workers[[c for c in core_order if c in workers.columns] + remaining]
    return items, workers, pd.DataFrame(metrics), network, saved_models


def write_outputs(output, tables, manifest, models):
    from .workbook_io import write_result_workbook
    output.mkdir(parents=True, exist_ok=True)
    for sheet, frame in tables.items():
        csv_path = output / f"{sheet}.csv"
        try:
            frame.to_csv(csv_path, index=False, encoding="utf-8-sig")
        except PermissionError:
            fallback = output / f"{sheet}_new.csv"
            LOG.warning("Permission denied writing %s (file open in Excel). Saved to %s", csv_path.name, fallback.name)
            frame.to_csv(fallback, index=False, encoding="utf-8-sig")
    xlsx_path = output / "Skill_ID_Ket_qua_chay_thu.xlsx"
    try:
        write_result_workbook(xlsx_path, tables)
    except PermissionError:
        fallback_xlsx = output / "Skill_ID_Ket_qua_chay_thu_new.xlsx"
        LOG.warning("Permission denied writing %s (file open in Excel). Saved to %s", xlsx_path.name, fallback_xlsx.name)
        write_result_workbook(fallback_xlsx, tables)
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
    item_master = inputs.get("Item Master", pd.DataFrame())
    mapping_raw = inputs.get("Item Mapping", pd.DataFrame())
    if not item_master.empty and not mapping_raw.empty:
        combined_items = pd.concat([mapping_raw, item_master], ignore_index=True)
        combined_items = combined_items.drop_duplicates(subset=["Item Number"], keep="last")
        mapping_source = combined_items
    elif not item_master.empty:
        mapping_source = item_master
    elif not mapping_raw.empty:
        mapping_source = mapping_raw
    else:
        mapping_source = raw.loc[raw["Process"].ne("Unknown") & raw["Process"].notna()]
    mapping = item_mapping(mapping_source)
    planner = clean_planner_data(planner_raw)
    data = clean_production_data(raw, config.incomplete_month)
    data = attach_mapping(data, mapping)
    if "RoundNo" not in data.columns:
        data["RoundNo"] = 1
    data["RoundNo"] = pd.to_numeric(data["RoundNo"], errors="coerce")
    data["SourceRow"] = data.get("SourceRow", data.index+2)
    if config.source_cutoff:
        cutoff = pd.Timestamp(config.source_cutoff)
        data = data[data["RAF Month"].le(cutoff)].copy()
    else:
        cutoff = pd.to_datetime(raw["RAF Month"], errors="coerce").max()
        qc_input = inputs.get("QC Tickets", pd.DataFrame())
        for qcol in ["QC_Stop", "ValidatedDateTime", "CreatedDateTime"]:
            if qcol in qc_input.columns:
                qc_latest = pd.to_datetime(qc_input[qcol], errors="coerce").max()
                if pd.notna(qc_latest) and (pd.isna(cutoff) or qc_latest > cutoff):
                    cutoff = qc_latest
    quality = []
    quality.append({"Check":"Production input rows", "N":len(raw), "Status":"Observed"})
    quality.append({"Check":"Production retained after basic filters", "N":len(data), "Status":"Observed; latest month retained unless explicitly excluded"})
    # RoundNo is part of the production grain. A worker can legitimately have
    # separate entries for the same WO/item across first pass and rework.
    keys = ["Reference","Worker","Item Number","RAF Month","RoundNo"]
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
        # Worker attribution is performed at WO + RoundNo.  A round with more
        # than one worker stays in the round output but is excluded from
        # individual Rasch attribution until worker-level quantities exist.
        worker_round = (data.dropna(subset=["Reference", "RoundNo", "Worker"])
                        .groupby(["Reference", "RoundNo", "Worker"], as_index=False)
                        .agg(Hours=("Total Actual Hours", "sum"),
                             QtyDoing=("Qty Doing", "sum"),
                             **({"Worker Name": ("Name", "first")} if "Name" in data.columns else {})))
        if "Worker Name" not in worker_round.columns:
            worker_round["Worker Name"] = pd.NA
        worker_counts = worker_round.groupby(["Reference", "RoundNo"])["Worker"].nunique().rename("WorkersInRound").reset_index()
        worker_round = worker_round.merge(worker_counts, on=["Reference", "RoundNo"], validate="many_to_one")
        round_links = rounds.merge(worker_round.rename(columns={"Reference":"WO"}), on=["WO", "RoundNo"], how="left", validate="one_to_many") if not rounds.empty else pd.DataFrame()
        if not round_links.empty:
            round_links["WorkerAttributionStatus"] = np.where(round_links.Worker.isna(), "No production round match",
                np.where(round_links.WorkersInRound.eq(1), "Single worker in WO-round", "Multiple workers in WO-round"))
            tables_round_links = round_links
        else:
            tables_round_links = pd.DataFrame()
        if not first.empty:
            initial = worker_round.loc[worker_round.RoundNo.eq(1)].copy()
            initial = initial.loc[initial.WorkersInRound.eq(1)].drop_duplicates("Reference")
            first = first.merge(initial[["Reference", "Worker", "Hours", "Worker Name"]].rename(columns={"Reference":"WO", "Worker":"ProductionWorker", "Hours":"Round1WorkerHours"}), on="WO", how="left")
            first["Worker"] = first["ProductionWorker"].fillna(first.get("Worker"))
            first["AttributionStatus"] = np.where(first.ProductionWorker.notna(), "Single production worker in RoundNo=1", "Missing or multiple production workers in RoundNo=1")
            first = first.drop(columns=["ProductionWorker"], errors="ignore")
            # Attach Planner Verified Skill Level from baseline snapshot (applied across all observation periods)
            if not planner.empty and "Worker ID" in planner.columns and "Planner Verified Skill Level" in planner.columns:
                p_skill = planner.rename(columns={"Worker ID": "Worker"})[["Worker", "Process", "Planner Verified Skill Level"]].drop_duplicates(["Worker", "Process"])
                first = first.merge(p_skill, on=["Worker", "Process"], how="left")
        tables["QC can kiem"] = qc_exceptions
        tables["WO vong dau"] = first
        tables["QC rounds"] = rounds
        tables["QC round workers"] = tables_round_links
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
            # Fit fast Rasch IRT model using production workers
            from .rasch_quality import fit_rasch_quality, fit_rasch_rework
            rasch_result = fit_rasch_quality(first, data)
            rasch_groups = rasch_result["group_difficulty"]
            if not rasch_groups.empty:
                rasch_merge = rasch_groups[["Process", "SizeAdjustedGroup", "FPY_Rasch_Difficulty", "Rasch_Converged"]].copy()
                rasch_merge = rasch_merge.rename(columns={"SizeAdjustedGroup": GROUP})
                item_output = item_output.drop(columns=["FPY_Rasch_Difficulty"], errors="ignore")
                item_output = item_output.merge(rasch_merge[["Process", GROUP, "FPY_Rasch_Difficulty"]], on=["Process", GROUP], how="left")
                has_rasch = item_output["FPY_Rasch_Difficulty"].notna()
                has_raw = item_output["ObservedFPY"].notna()
                item_output["Quality Status"] = np.where(
                    has_rasch, "Rasch IRT calibrated; assignment-conditional",
                    np.where(has_raw, "Raw FPY fallback; uncalibrated assignment-conditional",
                             "Insufficient Evidence: no eligible QC"))
            else:
                item_output["Quality Status"] = np.where(item_output.ObservedFPY.notna(), "Raw FPY fallback; uncalibrated assignment-conditional", "Insufficient Evidence: no eligible QC")
            # Rework Rasch is a separate diagnostic branch.  It only uses
            # WO-rounds with one matched production worker, avoiding whole-WO
            # primary-worker substitution.
            rework_result = fit_rasch_rework(rounds, data)
            if not rework_result["group_difficulty"].empty:
                rg = rework_result["group_difficulty"].rename(columns={"SizeAdjustedGroup": GROUP})
                rg = rg.rename(columns={"FPY_Rasch_Difficulty":"Rework_Rasch_Difficulty"})
                item_output = item_output.merge(rg[["Process", GROUP, "Rework_Rasch_Difficulty", "Rasch_Evidence_N", "Rasch_Converged"]], on=["Process", GROUP], how="left", suffixes=("", "_Rework"))
                tables["Rasch rework groups"] = rg
                tables["Rasch rework workers"] = rework_result["worker_effects"]
                tables["Rasch rework rounds"] = rework_result["round_effects"]
            else:
                tables["Rasch rework groups"] = pd.DataFrame()
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
        ("QC reconstruction", "Available" if len(rounds) else "Missing eligible QC", "Uses WO + RoundNo, row-level July CreatedDateTime exclusion and cumulative snapshot reconciliation"),
        ("Quality model calibration", "Not validated", "Beta-binomial / WO random effect candidates require real QC and holdout validation"),
        ("Planner history", "Baseline snapshot applied", "2026-08-03 verified skill applied as baseline for all observation periods"),
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
    for name in ["QC can kiem", "WO vong dau", "QC rounds", "QC round workers", "Rasch rework groups", "Rasch rework workers", "Rasch rework rounds", "QC hanh trinh", "Recovery Semi", "FPY Semi", "FPY cong doan", "FPY thang", "Touch reconstruction", "Checklist cham diem"]:
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
