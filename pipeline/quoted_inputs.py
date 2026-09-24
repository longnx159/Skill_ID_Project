"""Read the supplied BOM quote export without interpreting zero as free work."""
from pathlib import Path

import numpy as np
import pandas as pd


def read_bom_quotes(path: Path, semis: pd.DataFrame):
    raw = pd.read_excel(path, dtype={"BOM number": str, "BOM item number": str})
    required = {"BOM number", "BOM item number", "Minutes"}
    if not required.issubset(raw):
        raise ValueError(f"Quote export requires {sorted(required)}")
    raw = raw.rename(columns={"BOM number": "SemiBOM", "BOM item number": "QuoteItem", "Minutes": "SourceMinutes"})
    raw["SourceRow"] = np.arange(2, len(raw) + 2)
    for key in ("SemiBOM", "QuoteItem"):
        raw[key] = raw[key].astype("string").str.strip()
    raw["NumericMinutes"] = pd.to_numeric(raw.SourceMinutes, errors="coerce")
    keys = set(semis.SemiBOM)
    raw["QuoteStatus"] = "OUTSIDE_SEMI_SCOPE"
    rows = []
    for key, group in raw.loc[raw.SemiBOM.isin(keys)].groupby("SemiBOM"):
        values = group.NumericMinutes
        if values.isna().any() or not np.isfinite(values).all():
            status = "INVALID_VALUE"
        elif values.nunique() != 1 or group.QuoteItem.nunique() != 1:
            status = "CONFLICTING_QUOTE"
        elif values.iloc[0] <= 0:
            status = "NONPOSITIVE_QUOTE"
        else:
            status = "SUPPLIED"
        raw.loc[group.index, "QuoteStatus"] = status
        rows.append({"SemiBOM": key, "QuotedMinutesPerSemi": float(values.iloc[0]) if status == "SUPPLIED" else np.nan,
                     "QuoteStatus": status, "QuoteInputUnit": "MINUTES", "QuoteBasis": "PER_SEMI_UNIT",
                     "QuoteSourceRows": ",".join(group.SourceRow.astype(str)), "QuoteItem": group.QuoteItem.iloc[0]})
    quotes = pd.DataFrame(rows, columns=["SemiBOM", "QuotedMinutesPerSemi", "QuoteStatus", "QuoteInputUnit", "QuoteBasis", "QuoteSourceRows", "QuoteItem"])
    return quotes, raw
