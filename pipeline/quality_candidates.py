"""Optional QC model comparison after filling the template and installing full dependencies."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .config import Config
from .pipeline_v053 import load_inputs
from .preprocessing import clean_planner_data
from .data_contracts import item_mapping, chronological_split, GROUP
from .qc_pipeline import reconstruct_qc
from .quality_model import attach_asof_skill, fit_quality_candidate, predict_quality, quality_metrics


def run_candidates(input_dir, output, draws=1000,tune=1000,chains=4,seed=42):
    inputs=load_inputs(Config(input_dir=Path(input_dir)))
    raw=inputs.get("Item Mapping",pd.DataFrame())
    if raw.empty: raw=inputs["Production"]
    mapping=item_mapping(raw)
    planner=clean_planner_data(inputs["Planner Skills"])
    qc=inputs["QC Tickets"]
    _,first,exceptions=reconstruct_qc(qc,mapping)
    if first.empty:
        raise ValueError("No eligible QC first rounds. Fill QC Tickets in the template first.")
    data=attach_asof_skill(first,planner)
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    exceptions.to_csv(output/"qc_exceptions.csv",index=False,encoding="utf-8-sig")
    rows=[]
    for process,part in data.groupby("Process"):
        # Ambiguous initial-worker attribution stays outside worker-effect fitting.
        part=part.dropna(subset=["Worker"])
        train,test,embargo=chronological_split(part,"QC_Start","WO")
        common_test=test.dropna(subset=["CertifiedSkill"])
        if len(train)<2 or common_test.empty or train.CertifiedSkill.dropna().nunique()<2:
            rows.append({"Process":process,"Status":"Insufficient dated skill / chronological QC evidence"})
            continue
        coverage=train.CertifiedSkill.notna().mean()
        # A reproducible subset is held out from training for strict unseen-group evaluation.
        groups=sorted(train[GROUP].unique())
        held_groups=set(groups[::5]) if len(groups)>1 else set()
        designs={"WO chronological":(train,common_test)}
        strict_train=train[~train[GROUP].isin(held_groups)]
        strict_test=common_test[common_test[GROUP].isin(held_groups)]
        if len(strict_train)>1 and len(strict_test)>0:
            designs["Chronological and group held out"]=(strict_train,strict_test)
        for design,(fitting,evaluation) in designs.items():
            for missing in ["observed","hierarchical"]:
                for likelihood in ["beta_binomial","wo_random_effect"]:
                    name=f"{process}_{design}_{missing}_{likelihood}".replace(" ","_")
                    fitted=fit_quality_candidate(fitting,likelihood,missing,draws,tune,chains,seed)
                    predictions=predict_quality(fitted,evaluation,seed)
                    predictions.to_csv(output/f"{name}_predictions.csv",index=False,encoding="utf-8-sig")
                    fitted["network"].to_csv(output/f"{name}_connectivity.csv",index=False)
                    np.savez_compressed(output/f"{name}_posterior.npz",**fitted["posterior"])
                    import arviz as az
                    summary=az.summary(fitted["trace"],var_names=["alpha","beta","worker_sd","group_sd"])
                    summary.to_csv(output/f"{name}_diagnostics.csv")
                    metadata={k:fitted[k] for k in ["workers","groups","likelihood","missing_skill","training_last_date","status"]}
                    metadata.update({"skill_sd_train":fitted["scaler"].sd,"training_wos":sorted(fitted["training_wos"]),"seed":seed,"input_dir":str(Path(input_dir).resolve())})
                    (output/f"{name}_metadata.json").write_text(json.dumps(metadata,indent=2,default=str),encoding="utf-8")
                    rows.append({"Process":process,"Design":design,"Likelihood":likelihood,"MissingSkill":missing,
                        "Training Skill Coverage":coverage,"Rhat Max":summary.r_hat.max(),
                        "Divergences":int(fitted["trace"].sample_stats.diverging.sum()),
                        "Status":"Exploratory / Diagnostic Only" if coverage<.6 else "Pilot candidate; calibration and review pending",
                        **quality_metrics(predictions)})
    result=pd.DataFrame(rows)
    result.to_csv(output/"quality_model_comparison.csv",index=False,encoding="utf-8-sig")
    print(result.to_string(index=False))
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-dir",required=True,type=Path)
    p.add_argument("--output",default=Path("output_quality_candidates"),type=Path)
    p.add_argument("--draws",type=int,default=1000)
    p.add_argument("--tune",type=int,default=1000)
    p.add_argument("--chains",type=int,default=4)
    args=p.parse_args()
    run_candidates(args.input_dir,args.output,args.draws,args.tune,args.chains)
