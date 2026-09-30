import unittest
from unittest.mock import patch
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.data_contracts import GROUP
from pipeline.planner_quality import prepare_rounds, combine_quality, calibration, rank_stability, run_comparison
from pipeline.quality_model import SkillScaler, predict_quality


class PlannerQualityTests(unittest.TestCase):
    def fixture(self):
        q = pd.DataFrame({"WO": [f"W{i}" for i in range(10)], "RoundNo": 1, "Process": "P", GROUP: "G",
                          "Item Number": "2SN1", "PassQty": 8, "InspectedQty": 10,
                          "QC_Start": pd.date_range("2026-08-01", periods=10), "QC_Stop": pd.date_range("2026-08-01", periods=10),
                          "Worker": "INSPECTOR"})
        p = pd.DataFrame({"Reference": q.WO, "RoundNo": 1, "Worker": ["A", "B"] * 5, "Process": "P", "Item Number": "2SN1"})
        planner = pd.DataFrame({"Worker ID": ["A", "B", "C"], "Process": "P", "Planner Verified Skill Level": [3., 8., 6.]})
        return q, p, planner

    def test_round_attribution_skill_and_retrospective(self):
        q,p,planner = self.fixture()
        p = pd.concat([p, p.iloc[[0]].assign(Worker="C")], ignore_index=True)
        data, official, _ = prepare_rounds(q,p,planner)
        self.assertEqual(len(data), len(q))
        self.assertEqual(data.iloc[0].Eligibility, "AUDIT_ONLY_MULTIPLE_WORKERS")
        self.assertTrue(pd.isna(data.iloc[0].Worker))
        self.assertFalse(data.Worker.eq("INSPECTOR").any())
        self.assertEqual(data.iloc[1]["Planner Verified Skill Level"], 8.)
        self.assertTrue(data.iloc[1].RetrospectivePlanner)
        self.assertFalse(data.iloc[3].RetrospectivePlanner)
        pd.testing.assert_frame_equal(official, planner.astype({"Worker ID": "string", "Process": "string"}))

    def test_all_rounds_same_wo_never_cross_split(self):
        q,p,planner = self.fixture()
        extra = q.iloc[[0]].assign(RoundNo=2, QC_Start=pd.Timestamp("2026-08-10"), QC_Stop=pd.Timestamp("2026-08-10"))
        q = pd.concat([q,extra], ignore_index=True)
        data,_,_ = prepare_rounds(q,p,planner)
        self.assertTrue(data.groupby("WO").Split.nunique().eq(1).all())
        self.assertTrue(data.loc[data.WO.eq("W0"),"Split"].eq("embargo").all())

    def test_missing_not_mean_imputed_and_scope_preserved(self):
        q,p,planner = self.fixture()
        q.loc[0, "Item Number"] = "2GC1"
        p.loc[0, "Item Number"] = "2GC1"
        data,_,_ = prepare_rounds(q,p,planner.iloc[[0]])
        self.assertEqual(data.iloc[0].Eligibility,"EXCLUDED_SEMI_SCOPE")
        self.assertTrue(data.loc[data.Worker.eq("B"),"CertifiedSkill"].isna().all())
        self.assertTrue(data.loc[data.Worker.eq("B"),"PlannerSkillStatus"].eq("MISSING_PLANNER_SKILL").all())

    def model(self):
        return {"posterior": {"alpha": np.zeros(100), "beta": np.ones(100), "u": np.zeros((100,1)),
                "v": np.zeros((100,1)), "worker_sd": np.zeros(100), "group_sd": np.zeros(100)},
                "workers": ["A"], "groups": ["G"], "scaler": SkillScaler(2.), "training_wos": {"train"}, "likelihood": "beta_binomial"}

    def test_skill_slope_conditional_on_same_semi(self):
        q,_,_ = self.fixture()
        q = q.iloc[:3].assign(Worker="A", CertifiedSkill=[3,5,7])
        pred = predict_quality(self.model(),q)
        self.assertTrue(np.all(np.diff(pred.PredictedFPY)>0))
        self.assertEqual(pred.PredictedFPY.iloc[1], .5)
        model = self.model()
        model["posterior"]["beta"] *= -1
        self.assertTrue(np.all(np.diff(predict_quality(model,q).PredictedFPY)<0))

    def test_hierarchical_missing_prediction_not_official_skill(self):
        q,_,_ = self.fixture()
        q = q.iloc[:2].assign(Worker="A", CertifiedSkill=np.nan)
        model = self.model()
        model.update(missing_skill="hierarchical", missing_workers=["A"])
        model["posterior"]["missing_skill"] = np.full((100,1),7.)
        pred = predict_quality(model,q)
        self.assertTrue(pred.CertifiedSkill.isna().all())
        self.assertTrue((pred.PredictedFPY>.5).all())

    def test_shared_wo_random_effect_for_repeated_rounds(self):
        q,_,_ = self.fixture()
        q = q.iloc[:2].assign(WO="test", RoundNo=[2,3], Worker="A", CertifiedSkill=5.)
        model = self.model()
        model["likelihood"] = "wo_random_effect"
        model["posterior"]["wo_sd"] = np.ones(100)
        pred = predict_quality(model,q)
        self.assertEqual(pred.PredictedFPY.iloc[0], pred.PredictedFPY.iloc[1])

    def group_rows(self):
        return pd.DataFrame([{ "Process":"P", GROUP:"G", "Branch":b, "Model":"M", "SelectedOnValidation":True,
            "Difficulty10":v, "Lower95":v-.5, "Upper95":v+.5,"Lower975":v-.6,"Upper975":v+.6,
            "WOs":20,"QCPieces":200,"Converged":True,"EstimateEligible":True,
            "ValidationStatus":"PASSED_STATISTICAL_GATES"} for b,v in [("FIRST_PASS",2.),("REWORK",8.)]])

    def test_weights_follow_latest_user_rule(self):
        groups = self.group_rows()
        result = combine_quality(groups).iloc[0]
        self.assertAlmostEqual(result.Quality,3.2)
        fp = groups.iloc[[0]]
        result = combine_quality(fp, {("P","G","REWORK"):0}).iloc[0]
        self.assertEqual(result.Quality,2.)
        self.assertEqual(result.FirstPassWeight,1.)
        self.assertEqual(result.ReworkWeight,0.)
        result = combine_quality(fp, {("P","G","REWORK"):3}).iloc[0]
        self.assertTrue(pd.isna(result.Quality))
        groups.loc[1,"EstimateEligible"] = False
        self.assertTrue(pd.isna(combine_quality(groups).iloc[0].Quality))

    def test_piece_weighted_metrics(self):
        data = pd.DataFrame({"WO":["A","B"],"PassQty":[90,0],"InspectedQty":[100,1]})
        c,b = calibration(data,np.array([.9,.1]))
        self.assertAlmostEqual(c["CalibrationGap"],.1/101)
        self.assertEqual(b.Pieces.sum(),101)

    def test_rasch_relative_score_is_not_reference_worker_failure(self):
        model = self.model()
        _, scores = rank_stability(model)
        self.assertTrue(np.all(scores == 5.))
        model["posterior"]["alpha"] += 4
        model["posterior"]["beta"] *= 3
        self.assertTrue(np.all(rank_stability(model)[1] == 5.))
        model["posterior"]["v"] -= 1
        self.assertTrue(np.all(rank_stability(model)[1] > 5.))

    def test_comparison_end_to_end_with_deterministic_posterior(self):
        count = 90
        q = pd.DataFrame({"WO":[f"W{i}" for i in range(count)], "RoundNo":1,"Process":"P",
            GROUP:["G","H","I"]*(count//3),"Item Number":"2SN1","PassQty":8,"InspectedQty":10,
            "QC_Start":pd.date_range("2026-08-04",periods=count),"QC_Stop":pd.date_range("2026-08-04",periods=count)})
        p = pd.DataFrame({"Reference":q.WO,"RoundNo":1,"Worker":["A","B"]*(count//2),"Process":"P","Item Number":"2SN1"})
        planner = pd.DataFrame({"Worker ID":["A","B"],"Process":"P","Planner Verified Skill Level":[3.,8.]})
        captured=[]
        def fit(frame, likelihood, missing, *args, **kwargs):
            from pipeline.data_contracts import connectivity
            model=self.model()
            captured.append((frame.copy(),kwargs["scaler"].sd))
            model.update(workers=["A","B"],groups=["G","H","I"],scaler=kwargs["scaler"],
                missing_skill=missing,likelihood=likelihood,training_wos=set(frame.WO),network=connectivity(frame),trace=None)
            model["posterior"].update(u=np.zeros((100,2)),v=np.tile([-.2,0,.2],(100,1)),wo_sd=np.zeros(100))
            return model
        diag={"Converged":True,"RhatMax":1.,"ESSMin":500.,"Divergences":0,"MaxTreeDepthHits":0}
        folder=Path("tests/_artifacts") / ("planner_"+uuid.uuid4().hex)
        folder.mkdir(parents=True)
        with patch("pipeline.planner_quality.fit_quality_candidate",side_effect=fit), patch("pipeline.planner_quality.posterior_diagnostics",return_value=(diag,pd.DataFrame({"r_hat":[1.]}))):
            tables, metadata=run_comparison(q,p,planner,Path(folder),[])
            self.assertEqual(len(captured),4)
            self.assertEqual(len({sd for _,sd in captured}),1)
            self.assertEqual(metadata["decision"],"KEEP_RASCH")
            audit=tables["Planner QC audit"]
            ids=tables["Planner fit WO lists"]
            self.assertFalse(set(ids.loc[ids.Use.eq("train"),"WO"]) & set(ids.loc[ids.Use.eq("test"),"WO"]))
            self.assertEqual(len(tables["Planner comparison"]),5)
            self.assertTrue(tables["Planner Quality"].ReworkWeight.eq(0).all())
            self.assertTrue(tables["Planner actual worker anchors"].Worker.isin(["A","B"]).all())


if __name__ == "__main__":
    unittest.main()
