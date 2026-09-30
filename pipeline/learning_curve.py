"""Provisional Learning 5% from repeated first-round WO trajectories.

The source has WO completion dates, not first-production dates.  These scores
describe learning *observed within the source window* and stay separate from
the approved engineering Learning factor.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .run_reporting import file_hash


MIN_PAIR_WOS = 6
MIN_PAIR_DAYS = 30
MIN_GROUP_PAIRS = 3
MIN_GROUP_WOS = 18
MIN_GROUP_WORKERS = 2
RATIO_MIN, RATIO_MAX = 0.1, 10.0
IMPROVEMENT_LOG = np.log(1.10)
BOOTSTRAP_DRAWS = 200


def production_snapshot(core_run: Path) -> tuple[Path, str]:
    manifest = json.loads((core_run / "run_manifest.json").read_text(encoding="utf-8"))
    sources = [s for s in manifest["sources"] if s.get("dataset") == "Production"
               and Path(s["snapshot"]).name == "ProductionData.xlsx"]
    if len(sources) != 1:
        raise ValueError("Core run needs exactly one frozen ProductionData.xlsx source")
    source = sources[0]
    path = core_run / source["snapshot"]
    if not path.is_file() or file_hash(path) != source["sha256"]:
        raise ValueError("Frozen production source is missing or differs from its core-run hash")
    return path, source["sha256"]


def _pair_rows(worker_hours: pd.DataFrame, orders: pd.DataFrame,
               item_map: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    required_worker = {"ProductionOrderNumber", "Worker", "RoundNo", "Final"}
    required_order = {"ProductionOrderNumber", "Status", "MaxRAFDate", "ItemNumber",
                      "GoodCW", "StandardRuntime", "EarnedHours"}
    if not required_worker <= set(worker_hours) or not required_order <= set(orders):
        raise ValueError("Learning source is missing required MES worker or WO columns")
    if item_map["Item Number"].duplicated().any():
        raise ValueError("Learning item map has duplicate item identifiers")
    workers = worker_hours.copy()
    workers["RoundNo"] = pd.to_numeric(workers.RoundNo, errors="coerce")
    workers["Final"] = pd.to_numeric(workers.Final, errors="coerce")
    workers = workers.loc[workers.RoundNo.eq(1) & workers.ProductionOrderNumber.notna()
                          & workers.Worker.notna() & workers.ProductionOrderNumber.astype(str).str.upper().ne("OTHER")]
    worker_wo = workers.groupby(["ProductionOrderNumber", "Worker"], as_index=False).Final.sum()
    counts = worker_wo.groupby("ProductionOrderNumber").Worker.nunique()
    worker_wo = worker_wo.loc[worker_wo.ProductionOrderNumber.map(counts).eq(1)].copy()
    orders = orders.copy()
    if orders.ProductionOrderNumber.duplicated().any():
        raise ValueError("Learning source has duplicate WorkOrderData keys")
    orders = orders.loc[orders.Status.eq("Complete")].copy()
    frame = worker_wo.merge(orders, on="ProductionOrderNumber", how="inner", validate="many_to_one")
    frame["GoodCW"] = pd.to_numeric(frame.GoodCW, errors="coerce")
    frame["StandardRuntime"] = pd.to_numeric(frame.StandardRuntime, errors="coerce")
    frame["EarnedHours"] = pd.to_numeric(frame.EarnedHours, errors="coerce")
    frame["WODate"] = pd.to_datetime(frame.MaxRAFDate, errors="coerce")
    frame = frame.loc[frame.GoodCW.gt(0) & frame.StandardRuntime.gt(0)
                      & frame.Final.gt(0) & frame.WODate.notna()].copy()
    expected = frame.GoodCW * frame.StandardRuntime / 60
    mismatch = frame.EarnedHours.notna() & ~np.isclose(frame.EarnedHours, expected, atol=1e-5, rtol=1e-6)
    if mismatch.any():
        raise ValueError(f"Learning source has {int(mismatch.sum())} inconsistent EarnedHours rows")
    frame["EffortRatio"] = frame.Final / expected
    ratio_outliers = int((~frame.EffortRatio.between(RATIO_MIN, RATIO_MAX)).sum())
    frame = frame.loc[frame.EffortRatio.between(RATIO_MIN, RATIO_MAX)].copy()
    frame = frame.merge(item_map[["Item Number", "Process", "SizeAdjustedGroup"]],
                        left_on="ItemNumber", right_on="Item Number", how="inner", validate="many_to_one")
    frame = frame.loc[frame.Process.notna() & frame.SizeAdjustedGroup.notna()].copy()
    frame["LogEffortRatio"] = np.log(frame.EffortRatio)
    frame = frame.sort_values(["Process", "SizeAdjustedGroup", "ItemNumber", "Worker", "WODate", "ProductionOrderNumber"], kind="stable")
    pair_rows = []
    for (process, group, item, worker), history in frame.groupby(
            ["Process", "SizeAdjustedGroup", "ItemNumber", "Worker"], sort=False):
        n = len(history)
        span = (history.WODate.iloc[-1] - history.WODate.iloc[0]).days
        if n < MIN_PAIR_WOS or span < MIN_PAIR_DAYS or history.WODate.nunique() < 3:
            continue
        values = history.LogEffortRatio.to_numpy(dtype=float)
        early = float(np.median(values[:2]))
        middle = float(np.median(values[n // 2 - 1:n // 2 + 1]))
        late = float(np.median(values[-2:]))
        pair_rows.append({
            "Process": process, "SizeAdjustedGroup": group, "ItemNumber": item,
            "Worker": worker, "WOCount": n, "FirstWODate": history.WODate.iloc[0],
            "LastWODate": history.WODate.iloc[-1], "SpanDays": span,
            "FirstWO": history.ProductionOrderNumber.iloc[0],
            "LastWO": history.ProductionOrderNumber.iloc[-1],
            "EarlyEffortRatio": float(np.exp(early)),
            "MiddleEffortRatio": float(np.exp(middle)),
            "LateEffortRatio": float(np.exp(late)),
            "EarlyToLateLogDrop": early - late,
            "MiddleToLateLogDrop": middle - late,
            "ImprovedAtLeast10Pct": early - late > IMPROVEMENT_LOG,
        })
    audit = {
        "complete_single_worker_first_round_wos_after_filters": len(frame),
        "ratio_outlier_wos_excluded": ratio_outliers,
        "eligible_worker_item_trajectories": len(pair_rows),
    }
    return pd.DataFrame(pair_rows), audit


def _stage_ratios(pairs: pd.DataFrame) -> tuple[float, float, float]:
    """Remaining actual/standard effort at the early, middle and late stage."""
    return tuple(float(pairs[column].median()) for column in
                 ("EarlyEffortRatio", "MiddleEffortRatio", "LateEffortRatio"))


def _percentile_score(value: float, reference: np.ndarray) -> float:
    """0 is the lowest effort in the process; 10 is the highest."""
    if len(reference) == 1:
        return 5.0
    left = np.searchsorted(reference, value, side="left")
    right = np.searchsorted(reference, value, side="right")
    midpoint = (left + right - 1) / 2
    return float(np.clip(10 * midpoint / (len(reference) - 1), 0, 10))


def _stage_scores(ratios: tuple[float, float, float],
                  references: tuple[np.ndarray, np.ndarray, np.ndarray]) -> tuple[float, float, float]:
    return tuple(_percentile_score(value, reference)
                 for value, reference in zip(ratios, references))


def estimate_learning(worker_hours: pd.DataFrame, orders: pd.DataFrame,
                      item_map: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return group estimates, inspectable worker-item histories and fit audit."""
    pairs, audit = _pair_rows(worker_hours, orders, item_map)
    columns = ["Process", "SizeAdjustedGroup", "LearningEarlyRatio", "LearningMiddleRatio",
               "LearningLateRatio", "LearningL1", "LearningL2", "LearningL3",
               "LearningSourceScore", "LearningConfidencePct", "LearningInterval90Lower",
               "LearningInterval90Upper", "LearningConfidenceStatus", "LearningSourceStatus",
               "LearningTrajectoryN", "LearningWON", "LearningSpanDays"]
    if pairs.empty:
        audit["scored_groups"] = 0
        return pd.DataFrame(columns=columns), pairs, audit
    grouped = list(pairs.groupby(["Process", "SizeAdjustedGroup"], sort=True))
    eligible = []
    for key, history in grouped:
        n = len(history)
        wo_n = int(history.WOCount.sum())
        span = (history.LastWODate.max() - history.FirstWODate.min()).days
        if (n >= MIN_GROUP_PAIRS and wo_n >= MIN_GROUP_WOS
                and history.Worker.nunique() >= MIN_GROUP_WORKERS and span >= MIN_PAIR_DAYS):
            eligible.append((key, history, _stage_ratios(history)))
    reference_by_process = {}
    for process in sorted({key[0] for key, _, _ in eligible}):
        process_ratios = [ratios for key, _, ratios in eligible if key[0] == process]
        reference_by_process[process] = tuple(
            np.sort(np.array([ratios[i] for ratios in process_ratios], dtype=float))
            for i in range(3))
    eligible_map = {key: (history, ratios) for key, history, ratios in eligible}
    rng = np.random.default_rng(42)
    rows = []
    for key, history in grouped:
        n = len(history)
        wo_n = int(history.WOCount.sum())
        span = (history.LastWODate.max() - history.FirstWODate.min()).days
        base = {"Process": key[0], "SizeAdjustedGroup": key[1],
                "LearningTrajectoryN": n, "LearningWON": wo_n, "LearningSpanDays": span}
        if key not in eligible_map:
            rows.append({**base, "LearningSourceStatus": "INSUFFICIENT_REPEATED_HISTORY",
                         "LearningConfidenceStatus": "NOT_ESTIMATED"})
            continue
        ratios = eligible_map[key][1]
        references = reference_by_process[key[0]]
        l1, l2, l3 = _stage_scores(ratios, references)
        point = (l1 + l2 + l3) / 3
        bootstrap = np.empty(BOOTSTRAP_DRAWS)
        for i in range(BOOTSTRAP_DRAWS):
            sampled = history.iloc[rng.integers(0, n, size=n)]
            bootstrap[i] = np.mean(_stage_scores(_stage_ratios(sampled), references))
        rows.append({**base, "LearningEarlyRatio": ratios[0],
                     "LearningMiddleRatio": ratios[1], "LearningLateRatio": ratios[2],
                     "LearningL1": l1, "LearningL2": l2, "LearningL3": l3,
                     "LearningSourceScore": point,
                     "LearningConfidencePct": float(np.mean(np.abs(bootstrap - point) <= 1)),
                     "LearningInterval90Lower": float(np.quantile(bootstrap, .05)),
                     "LearningInterval90Upper": float(np.quantile(bootstrap, .95)),
                     "LearningConfidenceStatus": "CONDITIONAL_DIAGNOSTIC",
                     "LearningSourceStatus": "OBSERVED_WINDOW_MODEL_ESTIMATE"})
    audit.update({"scored_groups": len(eligible), "groups_with_repeat_history": len(grouped),
                  "score_scale": "WITHIN_PROCESS_EFFORT_PERCENTILE_0_10",
                  "reference_groups_by_process": {process: len(refs[0]) for process, refs in reference_by_process.items()},
                  "minimum_worker_item_wos": MIN_PAIR_WOS,
                  "minimum_worker_item_span_days": MIN_PAIR_DAYS,
                  "minimum_group_trajectories": MIN_GROUP_PAIRS,
                  "minimum_group_wos": MIN_GROUP_WOS,
                  "minimum_group_workers": MIN_GROUP_WORKERS,
                  "bootstrap_draws": BOOTSTRAP_DRAWS})
    return pd.DataFrame(rows, columns=columns), pairs, audit


def learning_from_core_run(core_run: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    source, sha256 = production_snapshot(core_run)
    workers = pd.read_excel(source, sheet_name="GSWorkerWorkingHours",
                            dtype={"ProductionOrderNumber": str, "Worker": str})
    orders = pd.read_excel(source, sheet_name="WorkOrderData",
                           dtype={"ProductionOrderNumber": str, "ItemNumber": str})
    item_map = pd.read_csv(core_run / "artifacts/Do kho SKU.csv",
                           dtype={"Item Number": str, "SizeAdjustedGroup": str}, low_memory=False)
    result, pairs, audit = estimate_learning(workers, orders, item_map)
    audit["source_sha256"] = sha256
    audit["source_path"] = str(source)
    return result, pairs, audit
