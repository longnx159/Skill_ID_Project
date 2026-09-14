"""Strict canonical QC reconstruction and v0.5.3 observed recovery.

Input columns are documented in README. No inference of rounds or Process from
prefixes, no allocation of a WO's first-pass failures to rescuing workers.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .data_contracts import GROUP, require, attach_mapping

QC_COLUMNS = ["QualityOrderId", "WO", "Item Number", "RoundNo", "QCStatus", "QCQty",
              "ExpectedQty", "QC_Start", "QC_Stop"]


def reconstruct_qc(tickets, mapping, cutoff=None):
    tickets = tickets.copy()
    aliases = {
        "ItemId": "Item Number",
        "ExpectedInspectionQty": "ExpectedQty",
        "StartCW": "ExpectedQty",
        "CreatedDateTime": "QC_Start",
        "QCWorkerWrkCtrId": "InitialWorker",
    }
    for src, dst in aliases.items():
        if src in tickets.columns and dst not in tickets.columns:
            tickets = tickets.rename(columns={src: dst})
    if "QC_Stop" not in tickets.columns:
        if "ValidatedDateTime" in tickets.columns:
            val = pd.to_datetime(tickets["ValidatedDateTime"], errors="coerce")
            start = pd.to_datetime(tickets.get("QC_Start"), errors="coerce")
            valid_val = val.notna() & val.ge("2020-01-01") & (start.isna() | val.ge(start))
            tickets["QC_Stop"] = val.where(valid_val, start)
        elif "QC_Start" in tickets.columns:
            tickets["QC_Stop"] = tickets["QC_Start"]
    require(tickets, QC_COLUMNS, "QC")
    # The MES export contains cumulative round snapshots in addition to
    # ticket-level QCQty.  Collapse it to one authoritative row per WO-round
    # before reconstruction; otherwise the same inspected pieces are counted
    # once per ticket.
    round_source = all(c in tickets.columns for c in ("RoundPassQty", "RoundReworkFailQty", "RoundScrapQty", "RoundActualQty"))
    if round_source:
        source = tickets.copy()
        source["CreatedDateTime"] = pd.to_datetime(source.get("QC_Start", source.get("CreatedDateTime")), errors="coerce")
        source["QC_Start"] = source["CreatedDateTime"]
        source["QC_Stop"] = source["CreatedDateTime"]
        source = source.loc[~source["CreatedDateTime"].dt.to_period("M").eq(pd.Period("2026-07"))].copy()
        source["Item Number"] = source["Item Number"].astype("string").str.strip()
        description = source.get("JDescription", pd.Series("", index=source.index)).fillna("").astype(str).str.strip().str.casefold()
        source["Disposition"] = description.map({"đạt":"Pass", "sửa":"Rework", "hỏng":"Scrap"})
        group_cols = ["WO", "Item Number", "RoundNo"]
        numeric = ["RoundPassQty", "RoundReworkFailQty", "RoundScrapQty", "RoundActualQty", "ExpectedQty"]
        for c in numeric:
            source[c] = pd.to_numeric(source[c], errors="coerce")
        source["PassQty"] = source["RoundPassQty"]
        source["FailQty"] = source["RoundReworkFailQty"].fillna(0) + source["RoundScrapQty"].fillna(0)
        # Use the snapshot with the largest observed round quantity.  This is
        # equivalent to the fully populated cumulative snapshot for the
        # current export and avoids summing repeated ticket snapshots.
        source = source.sort_values(["RoundActualQty", "CreatedDateTime", "QualityOrderId"])
        agg = {c: "last" for c in numeric + ["PassQty", "FailQty"]}
        agg.update({"QC_Start": "min", "QC_Stop": "max", "QualityOrderId": "first", "InitialWorker": "first", "Disposition": "last"})
        data = source.groupby(group_cols, as_index=False, dropna=False).agg(agg)
        data["QCQty"] = data["RoundActualQty"]
        data["QCStatus"] = "pass"
        # A blank description on the selected cumulative snapshot inherits the
        # round outcome from its authoritative quantities.
        derived_disposition = pd.Series(
            np.select([data["RoundScrapQty"].gt(0), data["RoundReworkFailQty"].gt(0)],
                      ["Scrap", "Rework"], default="Pass"), index=data.index)
        data["Disposition"] = data["Disposition"].fillna(derived_disposition)
        data["_RoundSource"] = True
    else:
        data = tickets.copy()
        description = data.get("JDescription", pd.Series("", index=data.index)).fillna("").astype(str).str.strip().str.casefold()
        explicit = description.map({"đạt":"pass", "sửa":"fail", "hỏng":"fail"})
        data["Disposition"] = description.map({"đạt":"Pass", "sửa":"Rework", "hỏng":"Scrap"})
        data["QCStatus"] = explicit.where(description.ne(""), data["QCStatus"])
    data["SourceRow"] = np.arange(2, len(data)+2)
    for c in ("WO", "QualityOrderId", "Item Number", "QCStatus"):
        data[c] = data[c].astype("string").str.strip().replace("", pd.NA)
    for c in ("QC_Start", "QC_Stop"):
        data[c] = pd.to_datetime(data[c], errors="coerce")
    for c in ("RoundNo", "QCQty", "ExpectedQty"):
        data[c] = pd.to_numeric(data[c], errors="coerce")
    data["QCStatus"] = data.QCStatus.str.casefold()
    data = attach_mapping(data, mapping)
    # July is excluded at row level. Later rounds for the same WO remain
    # eligible, which is required when a WO starts in July and finishes later.
    july = data.QC_Start.dt.to_period("M").eq(pd.Period("2026-07")) | data.QC_Stop.dt.to_period("M").eq(pd.Period("2026-07"))
    future = pd.Series(False, index=data.index)
    if cutoff is not None:
        future = data.QC_Stop.gt(pd.Timestamp(cutoff))
    invalid = data[["WO", "QualityOrderId", "Item Number", "Process", "QC_Start", "QC_Stop"]].isna().any(axis=1)
    invalid |= data.QC_Stop.lt(data.QC_Start) | ~data.QCStatus.isin(["pass", "fail"])
    invalid |= ~data.RoundNo.ge(1) | data.RoundNo.mod(1).ne(0)
    invalid |= ~data.QCQty.ge(0) | data.QCQty.mod(1).ne(0) | ~data.ExpectedQty.gt(0) | data.ExpectedQty.mod(1).ne(0)
    invalid |= ~np.isfinite(data[["QCQty", "ExpectedQty", "RoundNo"]]).all(axis=1)
    invalid |= data.QualityOrderId.duplicated(keep=False)
    if "IsRoundValid" in data.columns:
        invalid |= pd.to_numeric(data["IsRoundValid"], errors="coerce").fillna(1).eq(0)
    bad_wos = set(data.loc[invalid & ~future, "WO"].dropna())
    reject = invalid | data.WO.isin(bad_wos) | future | july
    exceptions = data.loc[reject].copy()
    exceptions["Reason"] = "Invalid ticket or WO; inspect source"
    exceptions.loc[exceptions.QC_Start.dt.to_period("M").eq(pd.Period("2026-07")), "Reason"] = "July QC excluded"
    exceptions.loc[future.reindex(exceptions.index, fill_value=False), "Reason"] = "After source cutoff"
    clean = data.loc[~reject].copy()
    rounds, first, rejected = [], [], []
    for wo, trajectory in clean.groupby("WO", sort=False):
        trajectory = trajectory.sort_values(["RoundNo", "QC_Start"])
        reason = None
        if trajectory["Item Number"].nunique() != 1:
            reason = "WO has multiple Items"
        numbers = sorted(trajectory.RoundNo.astype(int).unique())
        if numbers != list(range(1, max(numbers)+1)):
            reason = "Round continuity failure"
        wo_rounds = []
        previous = None
        for number, g in trajectory.groupby("RoundNo"):
            if bool(g.get("_RoundSource", pd.Series(False, index=g.index)).any()):
                passed = float(g["PassQty"].max())
                failed = float(g["FailQty"].max())
                scrap = float(g.get("RoundScrapQty", pd.Series(0, index=g.index)).max())
                inspected = float(g["RoundActualQty"].max())
            else:
                passed = g.loc[g.QCStatus.eq("pass"), "QCQty"].sum()
                failed = g.loc[g.QCStatus.eq("fail"), "QCQty"].sum()
                scrap = 0.0
                inspected = passed + failed
            if g.ExpectedQty.nunique() != 1 or not np.isclose(passed+failed, g.ExpectedQty.iloc[0]):
                reason = "Round quantity reconciliation failure"
            rework_failed = max(0.0, failed - scrap)
            if previous and (g.QC_Start.min() <= previous["QC_Stop"] or inspected > previous.get("ReworkQty", previous["FailQty"])+1e-8):
                reason = "Invalid round timing or reinspected quantity exceeds prior failures"
            r = {"WO": wo, "RoundNo": int(number), "Item Number": g["Item Number"].iloc[0],
                 GROUP: g[GROUP].iloc[0], "Process": g.Process.iloc[0], "PassQty": passed,
                 "FailQty": failed, "ReworkQty": rework_failed, "ScrapQty": scrap, "InspectedQty": inspected, "Disposition": g.get("Disposition", pd.Series(pd.NA, index=g.index)).iloc[-1], "QC_Start": g.QC_Start.min(), "QC_Stop": g.QC_Stop.max()}
            wo_rounds.append(r)
            previous = r
        if wo_rounds and sum(r["PassQty"] for r in wo_rounds[1:]) > wo_rounds[0]["FailQty"]+1e-8:
            reason = "Recovered quantity exceeds first fail quantity"
        if reason:
            rejected.append(trajectory.assign(Reason=reason))
            continue
        rounds.extend(wo_rounds)
        if wo_rounds:
            r = wo_rounds[0].copy()
            r["FPY"] = r["PassQty"] / r["InspectedQty"]
            # Only an explicit, unique initial-worker field may attribute FPY.
            worker = trajectory.get("InitialWorker", pd.Series(dtype="string")).dropna().astype("string").str.strip().replace("", pd.NA).dropna().unique()
            r["Worker"] = worker[0] if len(worker)==1 else pd.NA
            r["AttributionStatus"] = "Explicit initial worker" if len(worker)==1 else "Missing or ambiguous initial worker"
            first.append(r)
    if rejected:
        exceptions = pd.concat([exceptions, *rejected], ignore_index=True)
    return pd.DataFrame(rounds), pd.DataFrame(first), exceptions


def recovery_trajectories(rounds, cutoff, closed_wos=None):
    """Unknown terminal dispositions stay open. No maturity-to-scrap conversion."""
    if rounds.empty:
        return pd.DataFrame()
    closed_wos = set(closed_wos or [])
    weights = {2: 1.0, 3: .65, 4: .30}
    rows = []
    for wo, g in rounds.groupby("WO"):
        g = g.sort_values("RoundNo")
        first, last = g.iloc[0], g.iloc[-1]
        # Scrap is terminal at the round where it occurs. Only remaining
        # rework failures can enter a later round.
        fail = float(first.get("ReworkQty", first.FailQty) if isinstance(first, pd.Series) else first.FailQty)
        recovered = float(g.loc[g.RoundNo.ge(2), "PassQty"].sum())
        if recovered > fail+1e-8:
            raise ValueError(f"WO {wo}: recovered quantity exceeds first failures")
        remaining = max(0.0, fail-recovered)
        is_open = remaining > 0 and wo not in closed_wos
        numerator = float((g.loc[g.RoundNo.ge(2), "PassQty"] * g.loc[g.RoundNo.ge(2), "RoundNo"].map(weights).fillna(0)).sum())
        pessimistic = numerator/fail if fail else np.nan
        optimistic = (numerator+remaining*weights.get(int(last.RoundNo)+1, 0))/fail if fail else np.nan
        if not is_open:
            optimistic = pessimistic
        rows.append({"WO": wo, "Item Number": first["Item Number"], GROUP: first[GROUP], "Process": first.Process,
            "FirstFailQty": fail, "RecoveredQty": recovered, "RemainingFailQty": remaining,
            "OpenWO": is_open, "RoundsReached": int(last.RoundNo), "RecoveryNumerator": numerator,
            "ObservedRecoveryDifficulty": 10*(1-pessimistic) if fail and not is_open else np.nan,
            "RecoveryIndex_pessimistic": pessimistic, "RecoveryIndex_optimistic": optimistic,
            "RecoverySensitivityRange": 10*(optimistic-pessimistic),
            "AgeDays": (pd.Timestamp(cutoff)-first.QC_Start).total_seconds()/86400,
            "DaysSinceLastQC": (pd.Timestamp(cutoff)-last.QC_Stop).total_seconds()/86400,
            "ScrapQty": np.nan, "ScrapDataStatus": "InDevelopment / NotAvailable",
            "RecoveryStatus": "No rework evidence" if fail==0 else ("Open / right-censored" if is_open else "Observed Recovery Only")})
    return pd.DataFrame(rows)


def recovery_groups(trajectories, open_threshold=None, sensitivity_threshold=None, approvals=False):
    rows = []
    if trajectories.empty:
        return pd.DataFrame()
    for (process, group), g in trajectories.groupby(["Process", GROUP]):
        closed = g[~g.OpenWO & g.FirstFailQty.gt(0)]
        denom = closed.FirstFailQty.sum()
        score = 10*(1-closed.RecoveryNumerator.sum()/denom) if denom else np.nan
        total = g.FirstFailQty.sum()
        pessimistic = g.RecoveryNumerator.sum()/total if total else np.nan
        optimistic = (g.RecoveryIndex_optimistic*g.FirstFailQty).sum()/total if total else np.nan
        span = 10*(optimistic-pessimistic)
        rate = g.OpenWO.mean()
        status = "RecoveryDiagnosticOnly"
        if sensitivity_threshold is not None and span>sensitivity_threshold:
            status = "RecoveryUnstable"
        elif approvals and open_threshold is not None and sensitivity_threshold is not None and rate<=open_threshold and span<=sensitivity_threshold and np.isfinite(score):
            status = "Pilot Provisional"
        rows.append({"Process": process, GROUP: group, "ObservedRecoveryDifficulty": score,
            "OpenWORate": rate, "ClosedRecoveryEvidenceN": len(closed), "FirstFailQty": total,
            "RecoveryIndex_pessimistic": pessimistic, "RecoveryIndex_optimistic": optimistic,
            "RecoverySensitivityRange": span, "RecoveryStabilityFlag": status,
            "ScrapDataStatus": "InDevelopment / NotAvailable"})
    return pd.DataFrame(rows)


def reconstruct_touch(events, rounds):
    require(events, ["WO", "Worker", "Process", "Worker_Start", "Worker_Stop"], "Touch events")
    data = events.copy()
    for c in ("Worker_Start", "Worker_Stop"):
        data[c] = pd.to_datetime(data[c], errors="coerce")
    rows = []
    for wo, touches in data.groupby("WO", dropna=False):
        q = rounds.loc[rounds.WO.eq(wo)].sort_values("RoundNo") if not rounds.empty else pd.DataFrame()
        initial = touches.loc[touches.Worker_Start.le(touches.Worker_Stop) & touches.Worker_Stop.le(q.iloc[0].QC_Start) & touches.Process.eq(q.iloc[0].Process), "Worker"].dropna().unique() if len(q) else []
        for _, e in touches.iterrows():
            r = e.to_dict()
            r.update(Phase="Unclassified", Attribution="Unavailable", TouchMinutes=np.nan, RoundNo=np.nan)
            if pd.isna(e.Worker_Start) or pd.isna(e.Worker_Stop) or e.Worker_Stop<e.Worker_Start or pd.isna(e.Worker):
                r["Phase"] = "InvalidTouch"
            elif len(q):
                # Reject overlapping intervals for the same worker (double-counted labor).
                overlaps = touches.Worker.eq(e.Worker) & touches.Worker_Start.lt(e.Worker_Stop) & touches.Worker_Stop.gt(e.Worker_Start)
                if overlaps.sum()>1:
                    r["Phase"] = "OverlappingTouch"
                elif e.Process != q.iloc[0].Process:
                    r["Phase"] = "OtherProcess"
                elif e.Worker_Stop <= q.iloc[0].QC_Start:
                    r.update(Phase="FirstPass", RoundNo=1, Attribution="InitialProduction")
                else:
                    for idx in range(len(q)-1):
                        before, after = q.iloc[idx], q.iloc[idx+1]
                        if e.Worker_Start>before.QC_Stop and e.Worker_Stop<after.QC_Start and before.FailQty>0:
                            r.update(Phase="Rework", RoundNo=int(after.RoundNo),
                                Attribution=("SelfRework" if e.Worker==initial[0] else "AssistedRescue") if len(initial)==1 else "AmbiguousInitialWorker")
                            break
                if r["Phase"] in ("FirstPass", "Rework"):
                    r["TouchMinutes"] = (e.Worker_Stop-e.Worker_Start).total_seconds()/60
            rows.append(r)
    return pd.DataFrame(rows)
