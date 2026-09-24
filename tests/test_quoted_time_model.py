import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from pipeline.quoted_inputs import read_bom_quotes
from pipeline.legacy_time import prepare_legacy_2025
from pipeline.quoted_time_model import fit_time, predict_parts, temporal_split


class QuoteDataTests(unittest.TestCase):
    def test_conflicts_and_zero_quotes_are_audited_not_modeled(self):
        raw = pd.DataFrame({"BOM number": ["2A", "2B", "2B", "2C", "1X"],
                            "BOM item number": ["2A", "2B", "2B", "2C", "1X"],
                            "Minutes": [5, 5, 0, 0, 4]})
        semis = pd.DataFrame({"SemiBOM": ["2A", "2B", "2C"]})
        with patch("pipeline.quoted_inputs.pd.read_excel", return_value=raw):
            quotes, audit = read_bom_quotes(Path("quotes.xlsx"), semis)
        by_key = quotes.set_index("SemiBOM")
        self.assertEqual(by_key.loc["2A", "QuotedMinutesPerSemi"], 5)
        self.assertEqual(by_key.loc["2B", "QuoteStatus"], "CONFLICTING_QUOTE")
        self.assertTrue(np.isnan(by_key.loc["2B", "QuotedMinutesPerSemi"]))
        self.assertEqual(by_key.loc["2C", "QuoteStatus"], "NONPOSITIVE_QUOTE")
        self.assertEqual(audit.loc[audit.SemiBOM.eq("1X"), "QuoteStatus"].iloc[0], "OUTSIDE_SEMI_SCOPE")

    def test_temporal_windows_keep_a_wo_together(self):
        dates = pd.date_range("2026-08-01", periods=30)
        data = pd.DataFrame({"WO": [f"W{i}" for i in range(30)] + ["W0"],
                             "Date": list(dates) + [dates[-1]]})
        qc = pd.DataFrame({"QC_Start": ["2026-08-01"]})
        split, cuts = temporal_split(data, qc)
        self.assertEqual(split.loc[split.WO.eq("W0"), "Split"].unique().tolist(), ["embargo"])
        self.assertEqual(len(cuts), 3)

    def test_joint_parts_reconcile_without_adding_quote_twice(self):
        data = pd.DataFrame({"PB": ["Sanding / First pass"] * 4,
                             "GroupKey": ["Sanding / First pass / G1"] * 2 + ["Sanding / First pass / G2"] * 2,
                             "WorkerKey": ["Sanding / First pass / W1", "Sanding / First pass / W2"] * 2,
                             "Pattern": ["stone_only"] * 4, "DifficultyScore": [2., 2., 8., 8.],
                             "QuotedMinutesPerSemi": [10., 10., 30., 30.],
                             "LogMinutes": np.log([11., 12., 27., 28.])})
        model = fit_time(data, True, 10.)
        parts = predict_parts(model, data)
        np.testing.assert_allclose(parts.PredictedMinutes,
                                   parts.WorkContentMinutes + parts.TechnicalDifficultyMinutes + parts.WorkerEffectMinutes)
        self.assertTrue(parts.PredictedMinutes.gt(0).all())

    def test_legacy_reference_uses_only_2025_and_keeps_measurement_separate(self):
        raw = pd.DataFrame({"Reference": ["A", "B", "C"], "Worker": ["W1"] * 3,
                            "Item Number": ["I1", "I1", "I2"],
                            "Item Number (Size Adjusted)": ["G1", "G1", "G2"],
                            "Qty Doing": [2, 2, 2], "Total Actual Hours": [1., 1., 1.],
                            "RAF Month": ["2025-05-01", "2026-05-01", "2025-06-01"],
                            "Process": ["Sanding", "Sanding", "Polishing"]})
        semis = pd.DataFrame({"SemiBOM": ["B1", "B2"], "SemiItem": ["I1", "I2"],
                              "Process": ["Sanding", "Sanding"], "SizeAdjustedGroup": ["G1", "G2"],
                              "QuotedMinutesPerSemi": [20., 30.], "StoneScore": [2., 3.],
                              "MaterialDesignSourceScore": [4., 5.],
                              "ReportStatus": ["DIAGNOSTIC_ONLY", "DIAGNOSTIC_ONLY"]})
        with patch("pipeline.legacy_time.pd.read_excel", return_value=raw):
            eligible, audit, counts = prepare_legacy_2025(Path("legacy.xlsx"), semis)
        self.assertEqual(counts["rows_2025"], 2)
        self.assertEqual(counts["eligible_quote_reference_rows"], 1)
        self.assertEqual(audit.loc[audit.Reference.eq("C"), "Exclusion"].iloc[0], "PROCESS_CHANGED_OR_CONFLICTING")
        self.assertEqual(eligible.ActualMinutes.iloc[0], 30.)
        self.assertEqual(eligible.Branch.iloc[0], "Legacy 2025 aggregate")

    def test_legacy_prior_only_changes_quote_slope_when_selected(self):
        data = pd.DataFrame({"PB": ["Sanding / First pass"] * 6,
                             "GroupKey": ["Sanding / First pass / G1"] * 3 + ["Sanding / First pass / G2"] * 3,
                             "WorkerKey": ["Sanding / First pass / W1"] * 6,
                             "Pattern": ["stone_only"] * 6, "DifficultyScore": [3.] * 6,
                             "QuotedMinutesPerSemi": [10., 15., 20., 30., 40., 50.],
                             "LogMinutes": np.log([11., 15., 18., 26., 34., 40.])})
        reference = {"global_elasticity": 2., "process_elasticity": {"Sanding": 2.},
                     "rows_by_process": {"Sanding": 100}, "scope": "test"}
        base = fit_time(data, True, 10.)
        zero = fit_time(data, True, 10., reference, 0.)
        informed = fit_time(data, True, 10., reference, 1000.)
        np.testing.assert_allclose(base["beta"], zero["beta"])
        idx = base["schema"]["names"].index("quote:global")
        target = reference["global_elasticity"] * base["schema"]["qscale"]
        self.assertLess(abs(informed["beta"][idx] - target), abs(base["beta"][idx] - target))


if __name__ == "__main__":
    unittest.main()
