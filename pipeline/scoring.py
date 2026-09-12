"""Business publication rules: missing evidence never becomes a score."""
import numpy as np
import pandas as pd

FACTOR_WEIGHTS = {"Quality": .40, "PartMechanism": .25, "MaterialDesignProcess": .20, "Stone": .10, "Learning": .05}


def technical_complexity(factors):
    """Long-form approved factors; duplicate factors invalidate the entire Item."""
    required = ["Item Number", "Process", "Factor", "Score", "Evidence", "Scorer", "Approver", "Version", "Approved", "DataQualityStatus"]
    from .data_contracts import require
    require(factors, required, "Engineering factors")
    rows = []
    for (item, process), g in factors.groupby(["Item Number", "Process"]):
        reason = []
        if set(g.Factor)!=set(FACTOR_WEIGHTS) or len(g)!=5:
            reason.append("Missing or duplicate factors")
        scores = pd.to_numeric(g.Score, errors="coerce")
        if not scores.between(0,10).all():
            reason.append("Missing or invalid factor score")
        for c in ("Evidence", "Scorer", "Approver", "Version"):
            if g[c].isna().any() or g[c].astype(str).str.strip().eq("").any():
                reason.append(f"Missing {c}")
        if not g.Approved.astype(str).str.strip().str.casefold().eq("true").all():
            reason.append("Pending factor approval")
        if not g.DataQualityStatus.eq("Valid").all():
            reason.append("Data quality exception")
        rows.append({"Item Number": item, "Process": process,
            "Final Technical Complexity": np.nan if reason else float((scores*g.Factor.map(FACTOR_WEIGHTS)).sum()),
            "FactorGate": "; ".join(reason) or "All five factors approved"})
    return pd.DataFrame(rows)


def confidence_tier(lower, upper):
    """Central 90% interval = 5th to 95th percentile (spec notation corrected)."""
    if not np.isfinite(lower) or not np.isfinite(upper) or upper<lower:
        return "Low", "Insufficient Evidence"
    width = upper-lower
    return ("High", "Eligible for review") if width<=.8 else (("Medium", "Uncertainty warning") if width<=1.8 else ("Low", "Insufficient Evidence"))


def quality_difficulty(fpy, recovery, recovery_usable=False, weighting_calibrated=False):
    if not recovery_usable or not weighting_calibrated or not np.isfinite(fpy) or not np.isfinite(recovery):
        return np.nan
    return .8*fpy+.2*recovery
