"""Prepare 2025 aggregate-hours data as a separate quoted-time reference cohort.

These rows have neither allocated Final hours nor a production RoundNo. They
can inform a quote slope prior but are never labeled first pass or rework.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


LEGACY_COLUMNS = ["Reference", "Worker", "Item Number", "Item Number (Size Adjusted)",
                  "Qty Doing", "Total Actual Hours", "RAF Month", "Process"]


def prepare_legacy_2025(path: Path, semi_inputs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    source = pd.read_excel(path, usecols=LEGACY_COLUMNS,
                           dtype={"Reference": str, "Worker": str, "Item Number": str,
                                  "Item Number (Size Adjusted)": str, "Process": str})
    source["SourceRow"] = np.arange(2, len(source) + 2)
    source["RAFMonth"] = pd.to_datetime(source["RAF Month"], errors="coerce")
    year_counts = source.RAFMonth.dt.year.value_counts(dropna=False).to_dict()
    source = source.loc[source.RAFMonth.dt.year.eq(2025)].copy()
    source["Item Number"] = source["Item Number"].astype("string").str.strip()
    source["Process"] = source.Process.astype("string").str.strip()
    source["Worker"] = source.Worker.astype("string").str.strip()
    source["QtyDoing"] = pd.to_numeric(source["Qty Doing"], errors="coerce")
    source["TotalActualHours"] = pd.to_numeric(source["Total Actual Hours"], errors="coerce")
    source["AggregateMinutesPerQty"] = 60 * source.TotalActualHours / source.QtyDoing.where(source.QtyDoing.gt(0))

    ambiguous = set(semi_inputs.loc[semi_inputs.SemiItem.duplicated(keep=False), "SemiItem"])
    unique = semi_inputs.loc[~semi_inputs.SemiItem.isin(ambiguous),
                              ["SemiBOM", "SemiItem", "Process", "SizeAdjustedGroup",
                               "QuotedMinutesPerSemi", "StoneScore", "MaterialDesignSourceScore", "ReportStatus"]].copy()
    unique = unique.rename(columns={"Process": "CurrentProcess"})
    source = source.merge(unique, left_on="Item Number", right_on="SemiItem", how="left", validate="many_to_one")
    source["Exclusion"] = ""
    checks = [
        (source["Item Number"].isin(ambiguous), "AMBIGUOUS_SEMI_ITEM"),
        (source.SemiBOM.isna(), "NO_UNIQUE_BOM_SEMI"),
        (source.ReportStatus.eq("BOM_BLOCKED"), "BOM_BLOCKED"),
        (source.ReportStatus.eq("EXCLUDED_SEMI_SCOPE"), "EXCLUDED_SEMI_SCOPE"),
        (source.Worker.isna() | source.Worker.eq(""), "MISSING_WORKER"),
        (source.CurrentProcess.isna() | source.Process.isna(), "MISSING_PROCESS"),
        (source.Process.ne(source.CurrentProcess), "PROCESS_CHANGED_OR_CONFLICTING"),
        (source.QtyDoing.le(0) | ~np.isfinite(source.QtyDoing), "INVALID_QTY"),
        (source.TotalActualHours.le(0) | ~np.isfinite(source.TotalActualHours), "INVALID_HOURS"),
        (source.QuotedMinutesPerSemi.le(0) | source.QuotedMinutesPerSemi.isna(), "NO_POSITIVE_QUOTE"),
    ]
    for bad, reason in checks:
        source.loc[bad.fillna(True) & source.Exclusion.eq(""), "Exclusion"] = reason
    usable = source.loc[source.Exclusion.eq("")].copy()
    usable["ActualMinutes"] = 60 * usable.TotalActualHours / usable.QtyDoing
    usable["LogMinutes"] = np.log(usable.ActualMinutes)
    usable["WO"] = "LEGACY2025:" + usable.SourceRow.astype(str)
    usable["Branch"] = "Legacy 2025 aggregate"
    usable["PB"] = usable.CurrentProcess + " / " + usable.Branch
    usable["GroupKey"] = usable.PB + " / " + usable.SizeAdjustedGroup.fillna(usable.SemiItem)
    usable["WorkerKey"] = usable.PB + " / " + usable.Worker
    coverage = .1 * usable.StoneScore.notna() + .2 * usable.MaterialDesignSourceScore.notna()
    usable["DifficultyScore"] = (.1 * usable.StoneScore.fillna(0) + .2 * usable.MaterialDesignSourceScore.fillna(0)).div(
        coverage.where(coverage.gt(0)))
    usable["Pattern"] = ("m" + usable.MaterialDesignSourceScore.notna().astype(int).astype(str)
                         + "_s" + usable.StoneScore.notna().astype(int).astype(str))
    usable["Date"] = usable.RAFMonth
    counts = {"all_source_rows": int(sum(year_counts.values())),
              "rows_2025": len(source), "eligible_quote_reference_rows": len(usable),
              "unique_semis": int(usable.SemiBOM.nunique()),
              "year_counts": {str(k): int(v) for k, v in year_counts.items()},
              "exclusions_2025": source.Exclusion.value_counts().to_dict(),
              "measurement": "60 * Total Actual Hours / Qty Doing; aggregate historical time, not allocated Final per round"}
    return usable.reset_index(drop=True), source.reset_index(drop=True), counts
