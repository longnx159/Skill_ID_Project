"""Prepare an Item Master Process coverage audit for a SemiBOM report.

Stone Process is kept as a reference suggestion only; it is never copied into
Item Master or used as a model factor by this audit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .run_reporting import file_hash
from .semi_scope import EXCLUDED_SEMI_PREFIXES, EXCLUDED_BOM_SUFFIXES, excluded_semi_mask


def prepare(semi_report: Path, item_master: Path, stone_source: Path) -> dict:
    semi = pd.read_csv(semi_report, dtype={"SemiBOM": str, "SemiItem": str}, low_memory=False)
    master = pd.read_excel(item_master, usecols=["Item Number", "Process"], dtype=str)
    stone = pd.read_excel(stone_source, usecols=["BOM item number", "Process"], dtype=str)
    for frame, key in ((semi, "SemiItem"), (master, "Item Number"), (stone, "BOM item number")):
        frame[key] = frame[key].astype("string").str.strip()
    if master["Item Number"].duplicated().any():
        raise ValueError("Duplicate Item Number in Item Master")
    if stone.groupby("BOM item number").Process.nunique().gt(1).any():
        raise ValueError("Conflicting Stone Process labels for one SemiBOM")
    missing = semi.loc[~semi.SemiItem.isin(master["Item Number"]),
                       ["SemiBOM", "SemiItem", "ReportStatus", "BOMStatus", "SemiName"]].copy()
    stone_lookup = stone[["BOM item number", "Process"]].drop_duplicates("BOM item number")
    missing = missing.merge(stone_lookup.rename(columns={"BOM item number": "SemiBOM",
                                                  "Process": "StoneProcessReference"}),
                            on="SemiBOM", how="left", validate="one_to_one")
    missing["RequiredAction"] = "Add SemiItem to Item Master and confirm Process"
    missing = missing.sort_values(["ReportStatus", "SemiBOM"], kind="stable")
    ignored = excluded_semi_mask(missing.SemiItem, missing.SemiBOM)
    missing["RequiredAction"] = missing["RequiredAction"].where(~ignored, "No Item Master addition requested for this excluded code")
    actionable = missing.loc[~ignored].copy()
    matched = semi.SemiItem.isin(master["Item Number"])
    master_process = master.set_index("Item Number").Process
    mapped_process = semi.loc[matched, "SemiItem"].map(master_process)
    if mapped_process.isna().any() or mapped_process.astype("string").str.strip().eq("").any():
        raise ValueError("A matched Item Master row has blank Process")
    return {
        "summary": {
            "semi_bom_rows": len(semi),
            "matched_item_master": int(matched.sum()),
            "missing_item_master_key": len(missing),
            "ignored_scope_missing": int(ignored.sum()),
            "actionable_missing": len(actionable),
            "missing_usable_bom": int(missing.BOMStatus.eq("BOM structure usable").sum()),
            "missing_blocked_bom": int(missing.BOMStatus.ne("BOM structure usable").sum()),
            "actionable_with_stone_process_reference": int(actionable.StoneProcessReference.notna().sum()),
            "actionable_without_stone_process_reference": int(actionable.StoneProcessReference.isna().sum()),
            "matched_master_blank_process": 0,
        },
        "ignored_prefixes": list(EXCLUDED_SEMI_PREFIXES),
        "ignored_bom_suffixes": list(EXCLUDED_BOM_SUFFIXES),
        "sources": {str(path): file_hash(path) for path in (semi_report, item_master, stone_source)},
        "rows": actionable.fillna("").to_dict("records"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semi-report", type=Path, required=True)
    parser.add_argument("--item-master", type=Path, required=True)
    parser.add_argument("--stone", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    audit = prepare(args.semi_report, args.item_master, args.stone)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
