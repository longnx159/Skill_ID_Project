"""Validate and reconcile the fixed Material/Design/Process source score.

The source is an engineering calculation, not a fitted model or an approved
final Semi factor. Duplicate FG contexts are resolved only by the Item Master
product type; unresolved conflicts remain unavailable with an audit status.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED = ["Semi Item", "Semi BOM Item", "Name", "FG Item", "Material", "Product Type",
            "Process", "Material Score", "Design Score", "Process Score", "Material Design Process"]
SCORE_COLUMNS = ["Material Score", "Design Score", "Process Score", "Material Design Process"]
TYPE_ALIASES = {"Neck": "Necklace", "Brace": "Bracelet", "Accesso": "Accessory",
                "Pin, Br": "Pin/Brooch"}


def _type(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return TYPE_ALIASES.get(text, text)


def read_material_design(path: Path, semis: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    source = pd.read_excel(path, dtype={"Semi Item": str, "Semi BOM Item": str, "FG Item": str})
    missing = set(REQUIRED) - set(source.columns)
    if missing:
        raise ValueError(f"Material Design Process source missing columns: {sorted(missing)}")
    if semis.SemiBOM.duplicated().any():
        raise ValueError("SemiBOM keys must be unique for material reconciliation")
    source["SourceRow"] = np.arange(2, len(source) + 2)
    for col in ["Semi Item", "Semi BOM Item", "Process", "Product Type"]:
        source[col] = source[col].astype("string").str.strip()
    for col in SCORE_COLUMNS:
        source[col] = pd.to_numeric(source[col], errors="coerce")
    invalid = source[SCORE_COLUMNS].isna().any(axis=1) | source[SCORE_COLUMNS].lt(0).any(axis=1) | source[SCORE_COLUMNS].gt(10).any(axis=1)
    if invalid.any():
        raise ValueError(f"{int(invalid.sum())} Material Design Process rows have invalid 0–10 scores")
    expected = .4 * source["Material Score"] + .4 * source["Design Score"] + .2 * source["Process Score"]
    if (expected - source["Material Design Process"]).abs().gt(1e-7).any():
        raise ValueError("Material Design Process composite disagrees with 40/40/20 source components")
    source = source.merge(semis[["SemiBOM", "SemiItem", "Process", "Product Type"]].rename(
        columns={"Process": "SemiProcess", "Product Type": "SemiProductType"}),
        left_on="Semi BOM Item", right_on="SemiBOM", how="left", validate="many_to_one")
    source["SelectionStatus"] = "OUTSIDE_BOM_SCOPE"
    selected = []
    for semi_bom, group in source.loc[source.SemiBOM.notna()].groupby("SemiBOM", sort=False):
        valid = group.loc[group["Semi Item"].eq(group.SemiItem) & group.Process.eq(group.SemiProcess)]
        if valid.empty:
            source.loc[group.index, "SelectionStatus"] = "ITEM_OR_PROCESS_MISMATCH"
            continue
        type_match = valid["Product Type"].map(_type).eq(valid.SemiProductType.map(_type))
        matched = valid.loc[type_match]
        if matched.empty:
            source.loc[group.index, "SelectionStatus"] = "PRODUCT_TYPE_MISMATCH"
            continue
        if len(matched) != 1:
            source.loc[group.index, "SelectionStatus"] = "CONFLICTING_MATCHED_CONTEXTS"
            continue
        chosen = matched.iloc[0]
        source.loc[group.index, "SelectionStatus"] = "NOT_SELECTED_CONTEXT"
        source.loc[chosen.name, "SelectionStatus"] = "SELECTED_PRODUCT_TYPE" if len(group) > 1 else "SELECTED_UNIQUE"
        selected.append({"SemiBOM": semi_bom,
                         "MaterialSourceScore": float(chosen["Material Score"]),
                         "DesignSourceScore": float(chosen["Design Score"]),
                         "ProcessSourceScore": float(chosen["Process Score"]),
                         "MaterialDesignSourceScore": float(chosen["Material Design Process"]),
                         "MaterialDesignSourceStatus": source.loc[chosen.name, "SelectionStatus"],
                         "MaterialDesignSourceRow": int(chosen.SourceRow),
                         "MaterialDesignSourceMaterial": chosen.Material,
                         "MaterialDesignSourceProductType": chosen["Product Type"],
                         "MaterialDesignSourceProcess": chosen.Process})
    result = pd.DataFrame(selected, columns=["SemiBOM", "MaterialSourceScore", "DesignSourceScore",
                                              "ProcessSourceScore", "MaterialDesignSourceScore",
                                              "MaterialDesignSourceStatus", "MaterialDesignSourceRow",
                                              "MaterialDesignSourceMaterial", "MaterialDesignSourceProductType",
                                              "MaterialDesignSourceProcess"])
    counts = {"source_rows": len(source), "unique_source_semi_boms": int(source["Semi BOM Item"].nunique()),
              "selected_semi_boms": len(result), "selection_status": source.SelectionStatus.value_counts().to_dict(),
              "missing_semi_boms": int((~semis.SemiBOM.isin(result.SemiBOM)).sum())}
    return result, source, counts
