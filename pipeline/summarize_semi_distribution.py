"""Summarize BOM-derived Semi inputs for Material & Design analysis.

The script reads the auditable outputs from ``pipeline.bom_features`` and
joins Semi items to the Item Master.  It reports distributions only; it does
not turn the counts into an approved technical-complexity score.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


PART_BINS = [-0.1, 0, 1, 2, 4, 9, 19, 49, float("inf")]
PART_LABELS = ["0", "1", "2", "3-4", "5-9", "10-19", "20-49", "50+"]
STONE_GROUPS = {
    "Diamond": "RM_Diamond",
    "Artificial stone": "RM_Art ST",
    "Natural stone": "RM_Nat ST",
    "Pearl": "RM_Pearl",
    "Old stone (unspecified)": "RM_Old ST",
}
MECHANICAL_ASSEMBLY_GROUPS = {"SM_Casting", "SM_ACJ"}


def _required(frame: pd.DataFrame, columns: set[str], source: Path) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"{source} is missing columns: {sorted(missing)}")


def _label_missing(series: pd.Series) -> pd.Series:
    return series.fillna("Unmapped").astype(str).replace({"": "Unmapped", "nan": "Unmapped"})


def _part_distribution(series: pd.Series, metric: str, population: int) -> pd.DataFrame:
    bins = pd.cut(series, bins=PART_BINS, labels=PART_LABELS, include_lowest=True)
    counts = bins.value_counts(sort=False).reindex(PART_LABELS, fill_value=0)
    return pd.DataFrame(
        {
            "Metric": metric,
            "PartCountBin": PART_LABELS,
            "SemiCount": counts.to_numpy(),
            "ShareOfPopulationPct": (counts.to_numpy() / population * 100).round(2),
        }
    )


def _profile_by_dimension(data: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dimensions = ["Process", "Material", "Product Type"]
    for values, group in data.groupby(dimensions, dropna=False, sort=True):
        rows.append(
            {
                "Process": values[0],
                "Material": values[1],
                "Product Type": values[2],
                "SemiCount": len(group),
                "MechanicalAssemblyPartCount_Median": group["MechanicalAssemblyPartCountPCS"].median(),
                "MechanicalAssemblyPartCount_P90": group["MechanicalAssemblyPartCountPCS"].quantile(0.90),
                "MaterialGroupCount_Median": group["MaterialGroupCount"].median(),
                "MaterialGroupCount_P90": group["MaterialGroupCount"].quantile(0.90),
                "SemiWithStones": int(group["StoneCount"].gt(0).sum()),
                "SemiWithStonesPct": round(group["StoneCount"].gt(0).mean() * 100, 2),
            }
        )
    return pd.DataFrame(rows).sort_values(dimensions, kind="stable")


def _profile_each_dimension(data: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for dimension in ["Process", "Material", "Product Type"]:
        for value, group in data.groupby(dimension, dropna=False, sort=True):
            rows.append(
                {
                    "Dimension": dimension,
                    "Value": value,
                    "SemiCount": len(group),
                    "ShareOfUsableSemiPct": round(len(group) / len(data) * 100, 2),
                    "MechanicalAssemblyPartCount_Median": group["MechanicalAssemblyPartCountPCS"].median(),
                    "MechanicalAssemblyPartCount_P90": group["MechanicalAssemblyPartCountPCS"].quantile(0.90),
                    "MaterialGroupCount_Median": group["MaterialGroupCount"].median(),
                    "SemiWithStonesPct": round(group["StoneCount"].gt(0).mean() * 100, 2),
                }
            )
    return pd.DataFrame(rows).sort_values(["Dimension", "SemiCount", "Value"], ascending=[True, False, True], kind="stable")


def _direct_mechanical_parts(bom_source_dir: Path, contexts: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    frames = []
    for workbook in sorted(bom_source_dir.glob("*.xlsx")):
        if workbook.name.startswith("~$"):
            continue
        frame = pd.read_excel(
            workbook,
            dtype={
                "FG BOM number": str,
                "BOM number": str,
                "Component item number": str,
            },
        )
        _required(
            frame,
            {"FG BOM number", "BOM number", "Component item number", "Item group", "BOM quantity", "BOM unit"},
            workbook,
        )
        frame["SourceFile"] = workbook.name
        frames.append(frame)
    if not frames:
        raise ValueError(f"No BOM Excel file found in {bom_source_dir}")
    raw = pd.concat(frames, ignore_index=True)
    raw["FG BOM number"] = raw["FG BOM number"].fillna("").str.strip()
    raw["BOM number"] = raw["BOM number"].fillna("").str.strip()
    raw["Component item number"] = raw["Component item number"].fillna("").str.strip()
    raw["Item group"] = raw["Item group"].fillna("").str.strip()
    raw["BOM unit"] = raw["BOM unit"].fillna("").astype(str).str.strip().str.upper()
    raw["BOM quantity"] = pd.to_numeric(raw["BOM quantity"], errors="coerce")
    keys = ["SourceFile", "FG BOM", "SemiBOM"]
    matched = raw.merge(
        contexts,
        left_on=["SourceFile", "FG BOM number", "BOM number"],
        right_on=keys,
        how="inner",
        validate="many_to_one",
    )
    matched_contexts = matched[keys].drop_duplicates()
    expected_contexts = contexts[keys].drop_duplicates()
    if len(matched_contexts) != len(expected_contexts):
        missing = expected_contexts.merge(matched_contexts, on=keys, how="left", indicator=True)
        sample = missing.loc[missing["_merge"].eq("left_only"), "SemiBOM"].head(5).tolist()
        raise ValueError(f"Selected SemiBOM contexts are not found in the raw BOM source: {sample}")
    mechanical = matched.loc[
        matched["Item group"].isin(MECHANICAL_ASSEMBLY_GROUPS) & matched["BOM unit"].eq("PCS")
    ].copy()
    invalid_line_count = int(mechanical["BOM quantity"].isna().sum() + mechanical["BOM quantity"].le(0).sum())
    if invalid_line_count:
        raise ValueError(f"Usable BOM contexts contain {invalid_line_count} invalid mechanical assembly quantities")
    summary = mechanical.groupby("SemiBOM", as_index=False).agg(
        MechanicalAssemblyPartCountPCS=("BOM quantity", "sum"),
        MechanicalAssemblyPartSKUCount=("Component item number", "nunique"),
    )
    return summary, len(mechanical)


def run(bom_output_dir: Path, bom_source_dir: Path, item_master_path: Path, output_dir: Path) -> dict[str, object]:
    feature_path = bom_output_dir / "semi_bom_features.csv"
    part_path = bom_output_dir / "semi_part_paths.csv"
    stone_path = bom_output_dir / "semi_stone_paths.csv"
    features = pd.read_csv(feature_path, dtype={"SourceFile": str, "FG BOM": str, "SemiBOM": str, "SemiItem": str})
    parts = pd.read_csv(part_path, dtype={"SourceFile": str, "FG BOM": str, "SemiBOM": str})
    stones = pd.read_csv(stone_path, dtype={"SourceFile": str, "FG BOM": str, "SemiBOM": str})
    master = pd.read_excel(item_master_path, dtype={"Item Number": str})
    _required(features, {"SourceFile", "FG BOM", "SemiBOM", "SemiItem", "Status", "DirectPartCountPCS", "LeafPartCountPCS", "StoneCount"}, feature_path)
    _required(parts, {"SourceFile", "FG BOM", "SemiBOM", "ItemGroup"}, part_path)
    _required(stones, {"SourceFile", "FG BOM", "SemiBOM", "StoneType"}, stone_path)
    _required(master, {"Item Number", "Process", "Material", "Product Type"}, item_master_path)

    master = master[["Item Number", "Process", "Material", "Product Type"]].copy()
    master["Item Number"] = master["Item Number"].str.strip()
    ambiguity = master.groupby("Item Number")[["Process", "Material", "Product Type"]].nunique(dropna=False).max(axis=1)
    if ambiguity.gt(1).any():
        sample = ambiguity[ambiguity.gt(1)].index[:5].tolist()
        raise ValueError(f"Item Master has conflicting mappings for: {sample}")
    master = master.drop_duplicates("Item Number")

    contexts = features[["SourceFile", "FG BOM", "SemiBOM"]].copy()
    context_count = contexts.groupby("SemiBOM", as_index=False).size().rename(columns={"size": "ContextCount"})
    features = features.copy()
    features["_usable_status"] = features["Status"].eq("BOM structure usable")
    selected = (
        features.sort_values(["SemiBOM", "_usable_status", "SourceFile", "FG BOM"], ascending=[True, False, True, True], kind="stable")
        .drop_duplicates("SemiBOM", keep="first")
        .merge(context_count, on="SemiBOM", how="left", validate="one_to_one")
    )
    selected["SemiItem"] = selected["SemiItem"].str.strip()
    selected = selected.merge(master, left_on="SemiItem", right_on="Item Number", how="left", validate="many_to_one")
    for column in ["Process", "Material", "Product Type"]:
        selected[column] = _label_missing(selected[column])

    usable = selected.loc[selected["Status"].eq("BOM structure usable")].copy()
    selected_contexts = usable[["SourceFile", "FG BOM", "SemiBOM"]]
    keys = ["SourceFile", "FG BOM", "SemiBOM"]
    mechanical_parts, mechanical_line_count = _direct_mechanical_parts(bom_source_dir, selected_contexts)
    usable = usable.merge(mechanical_parts, on="SemiBOM", how="left", validate="one_to_one")
    usable["MechanicalAssemblyPartCountPCS"] = usable["MechanicalAssemblyPartCountPCS"].fillna(0)
    usable["MechanicalAssemblyPartSKUCount"] = usable["MechanicalAssemblyPartSKUCount"].fillna(0).astype(int)
    material_parts = parts.merge(selected_contexts, on=keys, how="inner", validate="many_to_one")
    material_parts = material_parts.loc[~material_parts["ItemGroup"].eq("Services"), keys + ["ItemGroup"]]
    material_stones = stones.merge(selected_contexts, on=keys, how="inner", validate="many_to_one")
    material_stones["ItemGroup"] = material_stones["StoneType"].map(STONE_GROUPS).fillna("RM_Stone_Unclassified")
    material_stones = material_stones[keys + ["ItemGroup"]]
    material_presence = pd.concat([material_parts, material_stones], ignore_index=True).drop_duplicates(keys + ["ItemGroup"])
    material_count = material_presence.groupby("SemiBOM", as_index=False).size().rename(columns={"size": "MaterialGroupCount"})
    usable = usable.merge(material_count, on="SemiBOM", how="left", validate="one_to_one")
    usable["MaterialGroupCount"] = usable["MaterialGroupCount"].fillna(0).astype(int)

    population = len(usable)
    part_distribution = pd.concat(
        [
            _part_distribution(
                usable["MechanicalAssemblyPartCountPCS"],
                "Mechanical assembly parts: SM_Casting + SM_ACJ (PCS)",
                population,
            ),
        ],
        ignore_index=True,
    )
    material_distribution = (
        material_presence.groupby("ItemGroup", as_index=False)["SemiBOM"].nunique()
        .rename(columns={"ItemGroup": "MaterialGroup", "SemiBOM": "SemiCount"})
        .sort_values(["SemiCount", "MaterialGroup"], ascending=[False, True], kind="stable")
    )
    material_distribution["ShareOfUsableSemiPct"] = (material_distribution["SemiCount"] / population * 100).round(2)
    material_count_distribution = (
        usable.groupby("MaterialGroupCount", as_index=False)["SemiBOM"].nunique()
        .rename(columns={"SemiBOM": "SemiCount"})
        .sort_values("MaterialGroupCount", kind="stable")
    )
    material_count_distribution["ShareOfUsableSemiPct"] = (material_count_distribution["SemiCount"] / population * 100).round(2)
    profile = _profile_by_dimension(usable)
    dimension_profile = _profile_each_dimension(usable)
    detail_columns = [
        "SemiBOM", "SemiItem", "SemiName", "SourceFile", "FG BOM", "Status", "ContextCount", "Process", "Material", "Product Type",
        "MechanicalAssemblyPartCountPCS", "MechanicalAssemblyPartSKUCount", "StoneCount", "StoneSKUCount", "StoneTypeCount", "KnownStoneWeightGram", "MaterialGroupCount",
    ]
    complexity_inputs = usable[detail_columns].sort_values("SemiBOM", kind="stable")

    output_dir.mkdir(parents=True, exist_ok=True)
    part_distribution.to_csv(output_dir / "semi_part_distribution.csv", index=False, encoding="utf-8-sig")
    material_distribution.to_csv(output_dir / "semi_material_group_distribution.csv", index=False, encoding="utf-8-sig")
    material_count_distribution.to_csv(output_dir / "semi_material_group_count_distribution.csv", index=False, encoding="utf-8-sig")
    profile.to_csv(output_dir / "semi_distribution_by_process_material_product_type.csv", index=False, encoding="utf-8-sig")
    dimension_profile.to_csv(output_dir / "semi_distribution_by_dimension.csv", index=False, encoding="utf-8-sig")
    complexity_inputs.to_csv(output_dir / "semi_complexity_inputs.csv", index=False, encoding="utf-8-sig")
    summary = {
        "all_unique_semi_boms": int(selected["SemiBOM"].nunique()),
        "usable_unique_semi_boms": int(population),
        "excluded_flagged_semi_boms": int(len(selected) - population),
        "semi_item_master_match_count": int(usable["Process"].ne("Unmapped").sum()),
        "semi_item_master_match_pct": round(float(usable["Process"].ne("Unmapped").mean() * 100), 2),
        "multi_context_semi_boms": int(selected["ContextCount"].gt(1).sum()),
        "mechanical_assembly_bom_lines": mechanical_line_count,
        "outputs": [
            "semi_part_distribution.csv",
            "semi_material_group_distribution.csv",
            "semi_material_group_count_distribution.csv",
            "semi_distribution_by_process_material_product_type.csv",
            "semi_distribution_by_dimension.csv",
            "semi_complexity_inputs.csv",
        ],
    }
    (output_dir / "semi_distribution_manifest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bom-output-dir", type=Path, required=True)
    parser.add_argument("--bom-source-dir", type=Path, required=True)
    parser.add_argument("--item-master", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.bom_output_dir, args.bom_source_dir, args.item_master, args.output)
