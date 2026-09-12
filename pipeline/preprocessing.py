"""Deterministic cleaning and feature engineering."""
import logging
import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)


def clean_production_data(df: pd.DataFrame, incomplete_month: str = "") -> pd.DataFrame:
    """Apply the specification's filters and create log time per piece."""
    required = ["Worker", "Item Number", "Qty Doing", "Total Actual Hours", "RAF Month"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Raw workbook is missing columns: {missing}")
    out = df.copy()
    out["SourceRow"] = np.arange(2, len(out)+2)
    customer = out.get("Customer Name", pd.Series("", index=out.index)).astype("string")
    product = out.get("Product Type", pd.Series("", index=out.index)).astype("string")
    month = pd.to_datetime(out["RAF Month"], errors="coerce")
    for col in ("Qty Doing", "Total Actual Hours"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    mask = ~customer.str.strip().str.casefold().eq("training").fillna(False)
    mask &= ~product.str.strip().str.casefold().eq("training").fillna(False)
    mask &= pd.to_numeric(out["Qty Doing"], errors="coerce").gt(0)
    mask &= pd.to_numeric(out["Total Actual Hours"], errors="coerce").gt(0)
    if incomplete_month:
        mask &= ~month.dt.strftime("%Y-%m").eq(incomplete_month)
    mask &= out["Worker"].notna() & out["Item Number"].notna() & month.notna()
    out = out.loc[mask].copy()
    out["Worker"] = out["Worker"].astype("string").str.strip()
    out["Item Number"] = out["Item Number"].astype("string").str.strip()
    out = out.loc[out["Worker"].ne("") & out["Item Number"].ne("")].copy()
    out["time_per_piece"] = out["Total Actual Hours"] / out["Qty Doing"]
    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=["time_per_piece"])
    out = out.loc[out["time_per_piece"].gt(0)].copy()
    out["log_time"] = np.log(out["time_per_piece"])
    out["Minutes per final OK"] = 60 * out["time_per_piece"]
    out["RAF Month"] = month.loc[out.index]
    for col in ("Material", "Product Type", "Process"):
        if col not in out:
            out[col] = "Unknown"
        out[col] = out[col].astype("string").str.strip().fillna("Unknown")
    LOGGER.info("Retained %d rows after cleaning", len(out))
    return out.reset_index(drop=True)


def clean_planner_data(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize planner identifiers and verified scores."""
    required = ["Worker ID", "Process", "Planner Verified Skill Level"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Planner workbook is missing columns: {missing}")
    out = df.copy()
    out["Worker ID"] = out["Worker ID"].astype("string").str.strip()
    out["Process"] = out["Process"].astype("string").str.strip()
    out["Planner Verified Skill Level"] = pd.to_numeric(out["Planner Verified Skill Level"], errors="coerce")
    out = out.dropna(subset=["Worker ID", "Process", "Planner Verified Skill Level"])
    if not out["Planner Verified Skill Level"].between(0, 10).all():
        raise ValueError("Planner skill must be in [0, 10]; no rescaling is permitted")
    if out.duplicated(["Worker ID", "Process"]).any():
        raise ValueError("Duplicate Worker-Process Planner keys require resolution, not averaging")
    return out
