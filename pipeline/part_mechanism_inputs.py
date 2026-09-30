"""Reconcile the supplied Part & Mechanism source at SemiBOM grain."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED = ["Semi BOM", "Physical Part Count", "Assembly Type", "Mechanism Function Class",
            "Part Score", "Assembly Structure Score", "Mechanism Bonus", "Part & Mechanism Score"]


def read_part_mechanism(path: Path, semis: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    source = pd.read_excel(path, dtype={"Semi BOM": str})
    missing = set(REQUIRED) - set(source)
    if missing:
        raise ValueError(f"Part & Mechanism source missing columns: {sorted(missing)}")
    source["SourceRow"] = np.arange(2, len(source) + 2)
    source["Semi BOM"] = source["Semi BOM"].astype("string").str.strip()
    if source["Semi BOM"].isna().any() or source["Semi BOM"].eq("").any():
        raise ValueError("Part & Mechanism source has blank Semi BOM keys")
    if source["Semi BOM"].duplicated().any():
        raise ValueError("Part & Mechanism source has duplicate Semi BOM keys")
    for col in ("Physical Part Count", "Part Score", "Assembly Structure Score", "Mechanism Bonus", "Part & Mechanism Score"):
        source[col] = pd.to_numeric(source[col], errors="coerce")
    if source["Part Score"].isna().any() or source["Part & Mechanism Score"].isna().any():
        raise ValueError("Part & Mechanism source has missing numeric scores")
    scores = source[["Part Score", "Assembly Structure Score", "Mechanism Bonus", "Part & Mechanism Score"]]
    if scores.lt(0).any().any() or scores.gt(10).any().any():
        raise ValueError("Part & Mechanism source has scores outside 0–10")
    matching_weights = []
    for part_weight in (.6, .7):
        expected = (part_weight * source["Part Score"]
                    + (1 - part_weight) * source["Assembly Structure Score"].fillna(0)
                    + source["Mechanism Bonus"].fillna(0)).clip(upper=10)
        if not (expected - source["Part & Mechanism Score"]).abs().gt(1e-7).any():
            matching_weights.append(part_weight)
    if not matching_weights:
        raise ValueError("Part & Mechanism composite disagrees with both 60/40 and 70/30 source components")
    if len(matching_weights) > 1:
        raise ValueError("Part & Mechanism source weight is ambiguous")
    part_weight = matching_weights[0]
    source["SelectionStatus"] = np.where(source["Semi BOM"].isin(semis.SemiBOM),
                                         "MATCHED_SEMI_BOM", "OUTSIDE_BOM_SCOPE")
    source["EvidenceStatus"] = np.where(source["Assembly Type"].isna() |
        source["Assembly Structure Score"].isna(), "INCOMPLETE_COMPONENT_DETAIL", "SOURCE_COMPONENTS_PRESENT")
    matched = source.loc[source.SelectionStatus.eq("MATCHED_SEMI_BOM")]
    selected = matched[["Semi BOM", "Part & Mechanism Score", "Physical Part Count", "Assembly Type",
                        "Mechanism Function Class", "Part Score", "Assembly Structure Score", "Mechanism Bonus",
                        "SourceRow", "EvidenceStatus"]].rename(columns={
        "Semi BOM": "SemiBOM", "Part & Mechanism Score": "PartMechanismSourceScore",
        "Physical Part Count": "PartMechanismPhysicalPartCount", "Assembly Type": "PartMechanismAssemblyType",
        "Mechanism Function Class": "PartMechanismFunctionClass", "Part Score": "PartMechanismPartScore",
        "Assembly Structure Score": "PartMechanismAssemblyScore", "Mechanism Bonus": "PartMechanismBonus",
        "SourceRow": "PartMechanismSourceRow", "EvidenceStatus": "PartMechanismEvidenceStatus"})
    counts = {"source_rows": len(source), "part_weight": part_weight,
              "assembly_weight": 1 - part_weight, "matched_semi_boms": len(selected),
              "outside_bom_scope": int(source.SelectionStatus.eq("OUTSIDE_BOM_SCOPE").sum()),
              "missing_semi_boms": int((~semis.SemiBOM.isin(selected.SemiBOM)).sum()),
              "incomplete_component_detail": int(matched.EvidenceStatus.eq("INCOMPLETE_COMPONENT_DETAIL").sum())}
    return selected, source, counts
