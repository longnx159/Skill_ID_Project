import unittest

import pandas as pd

from pipeline.semi_item_report import BOM_COLUMNS, MODEL_COLUMNS, build_item_rows


class SemiItemReportTests(unittest.TestCase):
    def test_one_row_per_semi_and_approved_score_gate(self):
        features = pd.DataFrame([
            {"SemiBOM": "A", "SemiItem": "A", "SemiName": "A name", "SourceFile": "z.xlsx", "FG BOM": "Z", "Status": "BOM structure usable"},
            {"SemiBOM": "A", "SemiItem": "A", "SemiName": "A name", "SourceFile": "a.xlsx", "FG BOM": "A", "Status": "BOM problem"},
            {"SemiBOM": "B", "SemiItem": "B", "SemiName": "B name", "SourceFile": "a.xlsx", "FG BOM": "B", "Status": "BOM problem"},
            {"SemiBOM": "C", "SemiItem": "C", "SemiName": "C name", "SourceFile": "a.xlsx", "FG BOM": "C", "Status": "BOM structure usable"},
            {"SemiBOM": "D", "SemiItem": "D", "SemiName": "D name", "SourceFile": "a.xlsx", "FG BOM": "D", "Status": "BOM structure usable"},
            {"SemiBOM": "E", "SemiItem": "E", "SemiName": "E name", "SourceFile": "a.xlsx", "FG BOM": "E", "Status": "BOM structure usable"},
        ])
        defaults = dict.fromkeys(BOM_COLUMNS, 0)
        inputs = pd.DataFrame([
            {"SemiBOM": key, "SemiItem": key, "Process": process, "Material": "Silver", "Product Type": "Ring", **defaults}
            for key, process in [("A", "Sanding"), ("C", "Unmapped"), ("D", "Sanding"), ("E", "Sanding")]
        ])
        model_defaults = dict.fromkeys(MODEL_COLUMNS)
        model = pd.DataFrame([
            {"Item Number": "A", "Process": "Sanding", **model_defaults,
             "Final Technical Complexity": 2.2, "Approval Status": "Approved", "FirstPass_Decision_Eligibility": "ELIGIBLE"},
            {"Item Number": "B", "Process": "Sanding", **model_defaults,
             "Final Technical Complexity": 5, "Approval Status": "Approved", "FirstPass_Decision_Eligibility": "ELIGIBLE"},
            {"Item Number": "D", "Process": "Polishing", **model_defaults,
             "Final Technical Complexity": 7, "Approval Status": "Approved", "FirstPass_Decision_Eligibility": "ELIGIBLE"},
            {"Item Number": "E", "Process": "Sanding", **model_defaults,
             "Final Technical Complexity": 3, "Approval Status": "Diagnostic Only", "FirstPass_Decision_Eligibility": "BLOCKED"},
        ])
        master = pd.DataFrame([{"Item Number": "B", "Product Type": "Neck"}])
        result = build_item_rows(features, inputs, model, master).set_index("SemiBOM")
        self.assertEqual(len(result), 5)
        self.assertEqual(result.loc["A", "ReportStatus"], "APPROVED")
        self.assertEqual(result.loc["A", "FinalTechnicalComplexity"], 2.2)
        self.assertEqual(result.loc["A", "ContextCount"], 2)
        self.assertEqual(result.loc["B", "ReportStatus"], "BOM_BLOCKED")
        self.assertEqual(result.loc["B", "ModelLinkStatus"], "NOT_EVALUATED_BOM_BLOCKED")
        self.assertEqual(result.loc["B", "Process"], "Sanding")
        self.assertEqual(result.loc["B", "Product Type"], "Neck")
        self.assertTrue(pd.isna(result.loc["B", "FinalTechnicalComplexity"]))
        self.assertEqual(result.loc["C", "ReportStatus"], "ITEM_MASTER_UNMAPPED")
        self.assertEqual(result.loc["D", "ReportStatus"], "PROCESS_MISMATCH")
        self.assertTrue(pd.isna(result.loc["D", "FinalTechnicalComplexity"]))
        self.assertEqual(result.loc["E", "ReportStatus"], "DIAGNOSTIC_ONLY")
        self.assertTrue(pd.isna(result.loc["E", "FinalTechnicalComplexity"]))

    def test_duplicate_model_item_fails(self):
        features = pd.DataFrame([{"SemiBOM": "A", "SemiItem": "A", "SemiName": "A", "SourceFile": "x", "FG BOM": "x", "Status": "BOM structure usable"}])
        inputs = pd.DataFrame([{"SemiBOM": "A", "SemiItem": "A", "Process": "Sanding", "Material": "Silver", "Product Type": "Ring", **dict.fromkeys(BOM_COLUMNS, 0)}])
        model = pd.DataFrame([{"Item Number": "A", "Process": "Sanding", **dict.fromkeys(MODEL_COLUMNS)}] * 2)
        with self.assertRaisesRegex(ValueError, "not unique"):
            build_item_rows(features, inputs, model)


if __name__ == "__main__":
    unittest.main()
