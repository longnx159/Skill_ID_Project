"""Conditional diagnostic Semi quality estimates from the selected QC experiment.

These are model-based estimates from WO-round QC outcomes, not raw FPY.
The percentage is a conditional precision probability within +/-1 point on
the 0-10 Quality scale, not validated production confidence or fit approval.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit

from .rasch_experiments import VARIANTS, build_design
from .run_reporting import file_hash


def _source_check(summary: dict, root: Path) -> None:
    required = {"Production", "QC Tickets", "Item Master"}
    checked = set()
    for entry in summary["sources"]:
        if entry.get("dataset") not in required or Path(entry["path"]).name.endswith("template.xlsx"):
            continue
        current = root / Path(entry["path"]).relative_to(root)
        if not current.is_file() or file_hash(current) != entry["sha256"]:
            raise ValueError(f"QC experiment source changed: {current}")
        checked.add(entry["dataset"])
    if checked != required:
        raise ValueError(f"QC experiment is missing verified sources: {required - checked}")


def _branch_estimates(model: dict, rounds: pd.DataFrame, process: str, branch: str) -> pd.DataFrame:
    if not model.get("converged") or "schema" not in model:
        raise ValueError(f"Selected {process}/{branch} model is not a converged penalized fit")
    variant = model["variant"]
    mode, weighting, legacy = VARIANTS[variant]
    if legacy:
        raise ValueError("Legacy model cannot provide conditional precision estimates")
    part = rounds.loc[rounds.Process.eq(process) & rounds.Branch.eq(branch) & rounds.WO.isin(model["training_wos"])].copy()
    if mode == "single":
        part = part.loc[part.Attribution.eq("single")].copy()
    if len(part) != model["training_rounds"]:
        raise ValueError(f"Training round count changed for {process}/{branch}")
    part["Workers"] = part.Workers.map(lambda value: tuple(json.loads(value)) if isinstance(value, str) else ())
    x, _ = build_design(part, mode, model["schema"])
    beta = np.asarray(model["coefficients"], dtype=float)
    p = expit(x @ beta)
    n = part.InspectedQty.to_numpy(float)
    if weighting == "capped":
        n = np.minimum(n, float(model["cap"]))
    elif weighting == "equal":
        n = np.ones(len(n))
    information = n * p * (1 - p)
    intercept_information = 1e-6 + information.sum()
    names = model["schema"]["names"]
    groups = part.SizeAdjustedGroup.astype(str).to_numpy()
    rows = []
    for idx, name in enumerate(names):
        if not name.startswith("g:"):
            continue
        group = name[2:]
        mask = groups == group
        # Uncertainty uses only observed QC information. Including the ridge
        # penalty as if it were data would make a one-round group look precise.
        group_info = float(information[mask].sum())
        if group_info <= 0:
            continue
        eta = float(beta[0] + beta[idx])
        rows.append({
            "Process": process, "SizeAdjustedGroup": group, "Branch": branch,
            "EtaReference": eta, "EtaSE_Conditional": float(np.sqrt(1 / group_info + 1 / intercept_information)),
            "ModelDifficulty": float(10 * (1 - expit(eta))),
            "ModelRounds": int(mask.sum()), "ModelPieces": float(part.loc[mask, "InspectedQty"].sum()),
            "SelectedVariant": variant,
        })
    return pd.DataFrame(rows)


def estimate_quality(experiment_run: Path, root: Path, draws: int = 4096) -> pd.DataFrame:
    """Return one conditional Quality score and precision estimate per modeled group."""
    summary = json.loads((experiment_run / "run_summary.json").read_text(encoding="utf-8"))
    if summary["execution_status"] not in {"SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"}:
        raise ValueError("QC experiment did not finish")
    _source_check(summary, root)
    manifest = json.loads((experiment_run / "run_manifest.json").read_text(encoding="utf-8"))
    recorded = {entry["path"].replace("\\", "/"): entry["sha256"] for entry in manifest["artifacts"]}
    def checked(relative: str) -> Path:
        source = experiment_run / relative
        if recorded.get(relative) != file_hash(source):
            raise ValueError(f"QC experiment artifact changed: {source}")
        return source
    rounds = pd.read_csv(checked("experiment/modeling_rounds.csv"), dtype={"WO": str, "SizeAdjustedGroup": str}, low_memory=False)
    branches = []
    for selected in summary["selections"]:
        variant = selected.get("selected_variant")
        if not variant:
            continue
        process, branch = selected["Process"], selected["Branch"]
        filename = (process + "_" + branch + "_" + variant).replace(" ", "_") + ".json"
        model = json.loads(checked("experiment/models/" + filename).read_text(encoding="utf-8"))
        branches.append(_branch_estimates(model, rounds, process, branch))
    all_branch = pd.concat(branches, ignore_index=True)
    first = all_branch.loc[all_branch.Branch.eq("First pass")].drop(columns="Branch").add_prefix("First_")
    rework = all_branch.loc[all_branch.Branch.eq("Rework")].drop(columns="Branch").add_prefix("Rework_")
    both = first.merge(rework, left_on=["First_Process", "First_SizeAdjustedGroup"], right_on=["Rework_Process", "Rework_SizeAdjustedGroup"], how="inner", validate="one_to_one")
    out = []
    for row in both.itertuples(index=False):
        process = row.First_Process
        group = row.First_SizeAdjustedGroup
        seed = int.from_bytes(hashlib.sha256(f"{process}|{group}".encode()).digest()[:4], "little")
        rng = np.random.default_rng(seed)
        first_draw = 10 * (1 - expit(rng.normal(row.First_EtaReference, row.First_EtaSE_Conditional, draws)))
        rework_draw = 10 * (1 - expit(rng.normal(row.Rework_EtaReference, row.Rework_EtaSE_Conditional, draws)))
        quality_draw = .8 * first_draw + .2 * rework_draw
        point = .8 * row.First_ModelDifficulty + .2 * row.Rework_ModelDifficulty
        out.append({
            "Process": process, "SizeAdjustedGroup": group,
            "QualityFactor_Diagnostic": float(point),
            "RaschConfidencePct": float(np.mean(np.abs(quality_draw - point) <= 1.0)),
            "RaschInterval90Lower": float(np.quantile(quality_draw, .05)),
            "RaschInterval90Upper": float(np.quantile(quality_draw, .95)),
            "RaschConfidenceStatus": "CONDITIONAL_DIAGNOSTIC",
            "QualityModelSource": f"{row.First_SelectedVariant} + {row.Rework_SelectedVariant}",
            "QualityFirstPassRounds": row.First_ModelRounds,
            "QualityReworkRounds": row.Rework_ModelRounds,
        })
    return pd.DataFrame(out)
