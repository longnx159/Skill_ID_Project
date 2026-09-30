"""Apply the user's Planner-primary policy without changing statistical verdicts.

Consumes a completed governed run. Does not refit, rewrite source data, or
silently turn missing/nonconverged estimates into validated results.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def export(run, destination):
    run, destination = Path(run), Path(destination)
    manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
    if manifest["execution_status"] not in {"SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"}:
        raise ValueError("A completed governed run is required")
    sources = {}
    def read(name):
        path = run / "artifacts" / (name + ".csv")
        expected = next(a["sha256"] for a in manifest["artifacts"] if Path(a["path"]).name == path.name)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("Source artifact changed: " + name)
        sources[name] = actual
        return pd.read_csv(path)
    groups = read("Planner Semi branches")
    groups = groups.loc[groups.SelectedOnValidation.eq(True)].copy()
    availability = read("Planner QC audit")
    counts = availability.loc[availability.Eligibility.eq("ELIGIBLE")].groupby(["Process", "SizeAdjustedGroup", "Branch"]).WO.nunique()
    rows = []
    for (process, group), part in groups.groupby(["Process", "SizeAdjustedGroup"]):
        r = {"Process":process,"SizeAdjustedGroup":group,"Quality":np.nan,
             "QualityLower95":np.nan,"QualityUpper95":np.nan,
             "PrimaryModel":"PLANNER_ANCHORED_RASCH","UseStatus":"PROVISIONAL_USER_SELECTED"}
        r["ReworkAvailableWOs"] = int(counts.get((process,group,"REWORK"),0))
        fw,rw = (1.,0.) if r["ReworkAvailableWOs"] == 0 else (.8,.2)
        r.update(FirstPassWeight=fw,ReworkWeight=rw)
        refs = {}
        for branch, prefix in [("FIRST_PASS","FirstPass"),("REWORK","Rework")]:
            b = part.loc[part.Branch.eq(branch)]
            if len(b)!=1:
                raise ValueError(f"Expected one selected estimate: {process}/{group}/{branch}")
            b=b.iloc[0]
            refs[branch]=b
            for src,dst in [("Difficulty10","Difficulty"),("Lower95","Lower95"),("Upper95","Upper95"),
                            ("WOs","TrainingWOs"),("QCPieces","TrainingQCPieces"),("Model","Model"),
                            ("Converged","Converged"),("ValidationStatus","ValidationStatus")]:
                r[prefix+dst]=b[src]
        fp, re = refs["FIRST_PASS"],refs["REWORK"]
        excluded = fp.ValidationStatus == "EXCLUDED_SEMI_SCOPE"
        available = pd.notna(fp.Difficulty10) and (rw == 0 or pd.notna(re.Difficulty10))
        if excluded:
            r["UseStatus"]="EXCLUDED_SEMI_SCOPE"
        elif available:
            r["Quality"] = fw*fp.Difficulty10 + rw*re.Difficulty10 if rw else fp.Difficulty10
            r["QualityLower95"] = fw*fp.Lower975 + rw*re.Lower975 if rw else fp.Lower95
            r["QualityUpper95"] = fw*fp.Upper975 + rw*re.Upper975 if rw else fp.Upper95
            if fp.ValidationStatus == "PASSED_STATISTICAL_GATES" and (rw == 0 or re.ValidationStatus == "PASSED_STATISTICAL_GATES"):
                r["UseStatus"]="STATISTICALLY_ELIGIBLE"
            elif not bool(fp.Converged) or (rw and not bool(re.Converged)):
                r["UseStatus"]="PROVISIONAL_NONCONVERGED_USER_SELECTED"
        else:
            r["UseStatus"]="UNAVAILABLE_REQUIRED_BRANCH_ESTIMATE"
        r["WeightReason"]="NO_USABLE_REWORK_100_PERCENT_FIRST_PASS" if rw==0 else "BOTH_BRANCHES_80_20"
        rows.append(r)
    primary = pd.DataFrame(rows)
    primary = primary.rename(columns={"Quality":"PlannerQuality", "QualityLower95":"PlannerQualityLower95", "QualityUpper95":"PlannerQualityUpper95"})
    old_fp = read("Rasch first pass groups")
    old_rw = read("Rasch rework groups")
    if "FPY_Rasch_Difficulty" in old_fp:
        primary = primary.merge(old_fp[["Process","SizeAdjustedGroup","FPY_Rasch_Difficulty","Rasch_Converged"]].rename(
            columns={"FPY_Rasch_Difficulty":"OldRaschFirstPass", "Rasch_Converged":"OldRaschFirstPassConverged"}),on=["Process","SizeAdjustedGroup"],how="left",validate="one_to_one")
    else:
        primary["OldRaschFirstPass"]=np.nan
    if "Rework_Rasch_Difficulty" in old_rw:
        primary = primary.merge(old_rw[["Process","SizeAdjustedGroup","Rework_Rasch_Difficulty","Rasch_Converged"]].rename(
            columns={"Rework_Rasch_Difficulty":"OldRaschRework", "Rasch_Converged":"OldRaschReworkConverged"}),on=["Process","SizeAdjustedGroup"],how="left",validate="one_to_one")
    else:
        primary["OldRaschRework"]=np.nan
    primary["OldRaschQuality"] = np.where(primary.ReworkWeight.eq(0), primary.OldRaschFirstPass,
        primary.FirstPassWeight*primary.OldRaschFirstPass + primary.ReworkWeight*primary.OldRaschRework)
    primary["PlannerModelWeight"] = np.where(primary.PlannerQuality.notna(),.8,0.)
    primary["OldRaschModelWeight"] = 1-primary.PlannerModelWeight
    primary["Quality"] = np.where(primary.PlannerQuality.notna(),.8*primary.PlannerQuality+.2*primary.OldRaschQuality,primary.OldRaschQuality)
    primary["BlendStatus"] = np.where(primary.PlannerQuality.notna(),"80_PERCENT_PLANNER_20_PERCENT_RASCH_PROVISIONAL","100_PERCENT_RASCH_FALLBACK")
    primary.loc[primary.Quality.isna(),"BlendStatus"]="UNAVAILABLE_REQUIRED_ESTIMATE"
    primary.loc[primary.UseStatus.eq("EXCLUDED_SEMI_SCOPE"),["Quality","OldRaschQuality"]]=np.nan
    primary.loc[primary.UseStatus.eq("EXCLUDED_SEMI_SCOPE"),"BlendStatus"]="EXCLUDED_SEMI_SCOPE"
    primary["QualityLower95Conditional"] = np.where(primary.PlannerQuality.notna() & primary.OldRaschQuality.notna(),.8*primary.PlannerQualityLower95+.2*primary.OldRaschQuality,np.nan)
    primary["QualityUpper95Conditional"] = np.where(primary.PlannerQuality.notna() & primary.OldRaschQuality.notna(),.8*primary.PlannerQualityUpper95+.2*primary.OldRaschQuality,np.nan)
    primary["BlendIntervalStatus"]="CONDITIONAL_ON_FIXED_OLD_RASCH_NOT_FULL_UNCERTAINTY"
    workers = read("Planner workers")
    workers = workers.loc[workers.SelectedOnValidation.eq(True) | workers.ModelStatus.eq("NO_ELIGIBLE_MODEL")]
    anchors = read("Planner actual worker anchors")
    anchors = anchors.loc[anchors.SelectedOnValidation.eq(True)]
    comparison = read("Planner comparison")
    acceptance = read("Planner acceptance")
    destination.mkdir(parents=True,exist_ok=False)
    tables = {"Planner primary Quality":primary,"Planner primary workers":workers,
              "Actual worker anchors":anchors,"Model comparison":comparison,"Statistical acceptance":acceptance}
    for name,frame in tables.items():
        frame.to_csv(destination/(name+".csv"),index=False,encoding="utf-8-sig")
    payload={"run_id":manifest["run_id"],"policy":"User selected 80% Planner-anchored Rasch plus 20% old Rasch. Missing Planner estimate uses 100% old Rasch. Statistical acceptance is unchanged; blend is provisional and not independently holdout-validated.",
             "score_definition":"Planner component: 10 * logistic(-SemiGroupEffect). Old Rasch component: original exported difficulty. Final blended 0-10 score is not a predicted failure probability.",
             "weighting":"Between models: Planner 80%, old Rasch 20%, or old Rasch 100% when Planner is missing. Within each model: first pass/rework 80/20; first pass 100% only without usable attributable rework data.",
             "planner_hashes":[s for s in manifest["sources"] if s["dataset"]=="Planner Skills"],
             "input_artifact_hashes":sources,"quality_status_counts":primary.BlendStatus.value_counts().to_dict(),
             "tables":{name:json.loads(frame.to_json(orient="records")) for name,frame in tables.items()}}
    (destination/"planner_primary_data.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(payload["quality_status_counts"]))
    return payload


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    export(args.run,args.output)
