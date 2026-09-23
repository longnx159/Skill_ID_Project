import unittest
import numpy as np
import pandas as pd
from scipy.optimize import check_grad

from pipeline.rasch_experiments import build_design, objective, fit_candidate, predict, metrics, split_wo_time, paired_bootstrap


def fixture():
    rng = np.random.default_rng(5)
    rows = []
    for i in range(100):
        worker, group = str(i % 4), str((i // 3) % 5)
        p = 1 / (1 + np.exp(-(float(worker) * .3 - float(group) * .2)))
        rows.append({"WO": f"WO{i}", "RoundNo": 1, "Workers": (worker,), "Attribution": "single",
                     "SizeAdjustedGroup": group, "Process": "P", "PassQty": rng.binomial(10, p),
                     "InspectedQty": 10, "QC_Start": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i),
                     "QC_Stop": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)})
    return pd.DataFrame(rows)


class RaschExperimentsTests(unittest.TestCase):
    def test_gradient_matches_numerical_derivative(self):
        data = fixture()
        x, _ = build_design(data, "single")
        beta = np.linspace(-.1, .1, x.shape[1])
        args = (x, data.PassQty.to_numpy(), data.InspectedQty.to_numpy(), np.ones(x.shape[1]))
        error = check_grad(lambda b: objective(b, *args)[0], lambda b: objective(b, *args)[1], beta)
        self.assertLess(error, 1e-4)

    def test_team_outcome_is_one_observation(self):
        data = fixture().iloc[:3].copy()
        data["Workers"] = [("A", "B"), (), ("C",)]
        x, schema = build_design(data, "expanded")
        names = schema["names"]
        self.assertEqual(x.shape[0], 3)
        self.assertEqual(x[0, names.index("w:A")], .5)
        self.assertEqual(x[0, names.index("w:B")], .5)
        self.assertEqual(x[1, names.index("a:unknown")], 1.)
        worker_columns = [i for i,n in enumerate(names) if n.startswith("w:")]
        self.assertEqual(x[1, worker_columns].sum(), 0)

    def test_fit_predict_and_frozen_unseen_entities(self):
        data = fixture()
        model = fit_candidate(data, "ridge_single_pieces")
        self.assertTrue(model["converged"])
        new = data.iloc[:2].copy()
        new["Workers"] = [("UNSEEN",)] * 2
        new["SizeAdjustedGroup"] = "UNSEEN"
        before = model["coefficients"].copy()
        p = predict(model, new)
        self.assertTrue(np.isfinite(p).all())
        np.testing.assert_array_equal(before, model["coefficients"])
        new["PassQty"] = 0
        np.testing.assert_array_equal(p, predict(model, new))

    def test_split_embargo_keeps_wo_outcomes_out_of_training(self):
        data = fixture()
        data.loc[0, "QC_Stop"] = pd.Timestamp("2026-04-01")
        split, bounds = split_wo_time(data)
        self.assertEqual(split.iloc[0].Split, "embargo")
        train = split.loc[split.Split.eq("train")]
        self.assertTrue(train.QC_Stop.lt(pd.Timestamp(bounds["validation_start"])).all())
        self.assertEqual(split.groupby("WO").Split.nunique().max(), 1)

    def test_metric_denominators_and_bootstrap(self):
        data = fixture()
        data["PassQty"] = 5
        result = metrics(data, np.full(len(data), .5))
        self.assertAlmostEqual(result["piece_log_loss"], np.log(2))
        self.assertAlmostEqual(result["piece_brier"], .25)
        self.assertAlmostEqual(result["round_rate_rmse"], 0)
        paired = paired_bootstrap(data, np.full(len(data), .5), np.full(len(data), .5))
        self.assertEqual(paired["lower_95"], 0)
        self.assertEqual(paired["upper_95"], 0)

    def test_all_fail_all_pass_stay_finite(self):
        for outcome in (0, 10):
            data = fixture()
            data["PassQty"] = outcome
            model = fit_candidate(data, "ridge_single_pieces")
            self.assertTrue(np.isfinite(predict(model, data)).all())


if __name__ == "__main__":
    unittest.main()
