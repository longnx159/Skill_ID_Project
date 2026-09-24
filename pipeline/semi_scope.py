"""Business scope for Semi difficulty and allocated-time calibration."""
from __future__ import annotations

import pandas as pd


# Codes intentionally omitted from Semi difficulty, not missing master fixes.
EXCLUDED_SEMI_PREFIXES = (
    "2GC", "2XI", "2WA", "2DU", "2EP", "2GD",
    "2GH", "2VS", "2TD", "2XD", "2DG", "2ME", "3", "9",
)
EXCLUDED_BOM_SUFFIXES = ("-01", "-02")
EXCLUDED_STATUS = "EXCLUDED_SEMI_SCOPE"


def excluded_semi_mask(items: pd.Series, semi_boms: pd.Series | None = None) -> pd.Series:
    identifiers = items.astype("string").str.strip().str.upper()
    excluded = identifiers.str.startswith(EXCLUDED_SEMI_PREFIXES, na=False)
    excluded |= identifiers.str.endswith(EXCLUDED_BOM_SUFFIXES, na=False)
    if semi_boms is not None:
        bom = semi_boms.astype("string").str.strip().str.upper()
        excluded |= bom.str.endswith(EXCLUDED_BOM_SUFFIXES, na=False)
    return excluded.fillna(False)


def semi_scope_rule(items: pd.Series, semi_boms: pd.Series | None = None) -> pd.Series:
    identifiers = items.astype("string").str.strip().str.upper()
    rules = pd.Series("", index=items.index, dtype="string")
    for prefix in EXCLUDED_SEMI_PREFIXES:
        rules = rules.mask(rules.eq("") & identifiers.str.startswith(prefix, na=False),
                           "PREFIX_" + prefix)
    suffix_target = identifiers if semi_boms is None else semi_boms.astype("string").str.strip().str.upper()
    for suffix in EXCLUDED_BOM_SUFFIXES:
        rules = rules.mask(identifiers.str.endswith(suffix, na=False) | suffix_target.str.endswith(suffix, na=False),
                           "BOM_SUFFIX_" + suffix)
    return rules
