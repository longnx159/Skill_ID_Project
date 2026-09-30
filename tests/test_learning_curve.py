import unittest

import pandas as pd

from pipeline.learning_curve import estimate_learning


class LearningCurveTests(unittest.TestCase):
    def test_repeated_worker_item_effort_produces_auditable_group_score(self) -> None:
        worker_rows, order_rows = [], []
        for item, pattern in (("IMPROVES", [2.0, 1.9, 1.5, 1.4, 1.0, 0.9]),
                              ("FLAT", [1.0] * 6),
                              ("STAYS_SLOW", [2.0] * 6),
                              ("SPARSE", [2.0, 1.9, 1.5, 1.4, 1.0, 0.9]),
                              ("ONE1", [2.0, 1.9, 1.5, 1.4, 1.0, 0.9]),
                              ("ONE2", [2.0, 1.9, 1.5, 1.4, 1.0, 0.9]),
                              ("ONE3", [2.0, 1.9, 1.5, 1.4, 1.0, 0.9])):
            worker_count = 1 if item in {"SPARSE", "ONE1", "ONE2", "ONE3"} else 3
            for worker in range(worker_count):
                for i, ratio in enumerate(pattern):
                    wo = f"{item}-{worker}-{i}"
                    worker_rows.append({"ProductionOrderNumber": wo, "Worker": f"W{worker}",
                                        "RoundNo": 1, "Final": ratio})
                    order_rows.append({"ProductionOrderNumber": wo, "Status": "Complete",
                                       "MaxRAFDate": pd.Timestamp("2026-01-01") + pd.Timedelta(days=15 * i),
                                       "ItemNumber": item, "GoodCW": 1,
                                       "StandardRuntime": 60, "EarnedHours": 1})
        mapping = pd.DataFrame({"Item Number": ["IMPROVES", "FLAT", "STAYS_SLOW", "SPARSE", "ONE1", "ONE2", "ONE3"],
                                "Process": ["Polishing"] * 7,
                                "SizeAdjustedGroup": ["G1", "G2", "G5", "G3", "G4", "G4", "G4"]})
        groups, pairs, audit = estimate_learning(pd.DataFrame(worker_rows), pd.DataFrame(order_rows), mapping)
        lookup = groups.set_index("SizeAdjustedGroup")
        self.assertEqual(audit["scored_groups"], 3)
        self.assertEqual(len(pairs), 13)
        self.assertEqual(audit["score_scale"], "WITHIN_PROCESS_EFFORT_PERCENTILE_0_10")
        self.assertGreater(lookup.loc["G5", "LearningSourceScore"], lookup.loc["G1", "LearningSourceScore"])
        self.assertGreater(lookup.loc["G1", "LearningSourceScore"], lookup.loc["G2", "LearningSourceScore"])
        self.assertTrue(pd.isna(lookup.loc["G3", "LearningSourceScore"]))
        self.assertEqual(lookup.loc["G3", "LearningSourceStatus"], "INSUFFICIENT_REPEATED_HISTORY")
        self.assertEqual(lookup.loc["G4", "LearningSourceStatus"], "INSUFFICIENT_REPEATED_HISTORY")
        self.assertEqual(lookup.loc["G1", "LearningConfidenceStatus"], "CONDITIONAL_DIAGNOSTIC")


if __name__ == "__main__":
    unittest.main()
