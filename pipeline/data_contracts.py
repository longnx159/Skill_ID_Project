"""v0.5.3 identity, provenance, network and temporal controls."""
from __future__ import annotations

import numpy as np
import pandas as pd

GROUP = "SizeAdjustedGroup"


def require(frame, columns, source):
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{source} missing columns: {missing}")


def item_mapping(raw):
    require(raw, ["Item Number", "Process"], "Item mapping")
    out = raw[["Item Number", "Process"]].copy()
    for col in out:
        out[col] = out[col].astype("string").str.strip().replace("", pd.NA)
    source = raw.get("Item Number (Size Adjusted)", pd.Series(pd.NA, index=raw.index))
    source = source.astype("string").str.strip().replace("", pd.NA)
    out[GROUP] = source
    # Use the exact known mapping for an Item if present elsewhere in the source.
    for key in ("Process", GROUP):
        if out.groupby("Item Number")[key].nunique().gt(1).any():
            raise ValueError(f"Item Number maps to multiple {key} values")
        out[key] = out.groupby("Item Number")[key].transform("first")
    out["MappingFallback"] = out[GROUP].isna()
    out[GROUP] = out[GROUP].fillna(out["Item Number"])
    out = out.drop_duplicates().dropna(subset=["Item Number"])
    if out.groupby(GROUP)["Process"].nunique().gt(1).any():
        raise ValueError("Size Adjusted group maps to multiple Processes")
    out["GroupItemCount"] = out.groupby([GROUP, "Process"])["Item Number"].transform("nunique")
    out["PoolingVersion"] = "source-mapping-v053-unapproved"
    out["SizeEffectFlag"] = np.where(out.GroupItemCount.gt(5), "Pending Engineering Review (>5 Items)", "Pending Size Residual Validation")
    return out.reset_index(drop=True)


def attach_mapping(frame, mapping):
    require(frame, ["Item Number"], "Input")
    out = frame.copy()
    out["Item Number"] = out["Item Number"].astype("string").str.strip()
    supplied_process = out.pop("Process") if "Process" in out else None
    out = out.drop(columns=[c for c in mapping if c != "Item Number" and c in out])
    out = out.merge(mapping, on="Item Number", how="left", validate="many_to_one")
    if supplied_process is not None:
        old = supplied_process.reset_index(drop=True).astype("string").str.strip()
        mismatch = old.notna() & out.Process.notna() & old.ne(out.Process)
        if mismatch.any():
            raise ValueError("Input Process conflicts with exact Item mapping")
    return out


def trajectory_keys(frame):
    """DUMMY/missing references are not real WO identities; retain as diagnostics."""
    ref = frame.get("Reference", pd.Series(pd.NA, index=frame.index)).astype("string").str.strip()
    valid = ref.notna() & ref.ne("") & ~ref.str.upper().str.startswith("DUMMY", na=False)
    keys = ref.copy()
    keys.loc[~valid] = [f"unlinked-row:{i}" for i in frame.index[~valid]]
    return keys, valid


def chronological_split(frame, date_col, key_col, fraction=0.8):
    """Embargo trajectories spanning the cutoff; never use future training events."""
    dates = pd.to_datetime(frame[date_col], errors="raise")
    if dates.isna().any() or frame[key_col].isna().any():
        raise ValueError("Split requires nonmissing dates and trajectory keys")
    spans = pd.DataFrame({"key": frame[key_col], "date": dates}).groupby("key").date.agg(["min", "max"])
    unique_dates = sorted(spans["min"].unique())
    if len(unique_dates) < 2:
        return frame.iloc[:0].copy(), frame.iloc[:0].copy(), frame.copy()
    cutoff = unique_dates[min(max(int(len(unique_dates) * fraction), 1), len(unique_dates)-1)]
    train_ids = spans.index[spans["max"].lt(cutoff)]
    test_ids = spans.index[spans["min"].ge(cutoff)]
    train = frame[frame[key_col].isin(train_ids)].copy()
    test = frame[frame[key_col].isin(test_ids)].copy()
    embargo = frame[~frame[key_col].isin(train_ids.union(test_ids))].copy()
    assert not set(train[key_col]) & set(test[key_col])
    if len(train) and len(test):
        assert pd.to_datetime(train[date_col]).max() < pd.to_datetime(test[date_col]).min()
    return train, test, embargo


def connectivity(frame, min_n=30, anchor_tolerance=1.0):
    """Bipartite diagnostics computed before fitting. Thresholds are provisional."""
    require(frame, ["Worker", GROUP, "Process"], "Connectivity")
    rows = []
    for process, data in frame.groupby("Process"):
        parent = {}
        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for worker, group in data[["Worker", GROUP]].itertuples(index=False, name=None):
            a, b = find(("w", worker)), find(("g", group))
            parent[b] = a
        roots = {root: i+1 for i, root in enumerate(sorted({find(x) for x in parent}))}
        data = data.copy()
        data["ConnectedComponentID"] = data[GROUP].map(lambda g: f"{process}:{roots[find(('g', g))]}")
        for component, part in data.groupby("ConnectedComponentID"):
            skill = part.get("CertifiedSkill", pd.Series(np.nan, index=part.index))
            anchor = bool(skill.between(5-anchor_tolerance, 5+anchor_tolerance).any())
            edges = part[["Worker", GROUP]].drop_duplicates()
            for group, g in part.groupby(GROUP):
                rows.append({"Process": process, GROUP: group, "ConnectedComponentID": component,
                    "ComponentSize": len(part), "ComponentWorkers": part.Worker.nunique(),
                    "ComponentGroups": part[GROUP].nunique(), "WorkerGroupEdges": len(edges),
                    "RepeatedLinks": int(part.groupby(["Worker", GROUP]).size().gt(1).sum()),
                    "WorkersPerGroup": g.Worker.nunique(), "GroupEvidenceN": len(g),
                    "GroupsPerWorkerMean": float(part.groupby("Worker")[GROUP].nunique().mean()),
                    "SkillCoverage": g.get("CertifiedSkill", pd.Series(np.nan, index=g.index)).notna().mean(),
                    "CertifiedSkillMin": skill.min(), "CertifiedSkillMax": skill.max(),
                    "AnchorAvailability": anchor, "ExtrapolationFlag": not anchor,
                    "ConnectivityStatus": "WeakNetwork" if len(part)<min_n or not anchor or g.Worker.nunique()<2 else "Pilot Network Evidence",
                    "AssignmentInterpretation": "Assignment-Conditional Difficulty"})
    return pd.DataFrame(rows)
