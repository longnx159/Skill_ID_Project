from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd

from pipeline.semi_detail_workbook import _quotes, worker_validation, wo_summary
from pipeline.material_design_inputs import read_material_design
from pipeline.part_mechanism_inputs import read_part_mechanism
from pipeline.build_semi_detail_workbook_stream import _factor_provenance_rows, _sku_score_rows


class QuotedTimeTests(unittest.TestCase):
    def test_wo_summary_does_not_duplicate_quantities_or_average_team_skill(self) -> None:
        rounds = pd.DataFrame([
            ["A", 1, "S", "Polishing", 4, 0, 4, "2026-08-03"],
            ["B", 1, "S", "Polishing", 0, 1, 1, "2026-09-05"],
            ["B", 2, "S", "Polishing", 1, 0, 1, "2026-09-07"],
        ], columns=["WO", "RoundNo", "Item Number", "Process", "PassQty", "FailQty", "InspectedQty", "QC_Start"])
        workers = pd.DataFrame([
            ["A", 1, "Polishing", "E1"], ["A", 1, "Polishing", "E1"],
            ["B", 1, "Polishing", "E2"], ["B", 1, "Polishing", "E3"],
        ], columns=["WO", "RoundNo", "Process", "Worker"])
        planner = pd.DataFrame([["E1", "Polishing", 8], ["E2", "Polishing", 6], ["E3", "Polishing", 9]],
                               columns=["Worker ID", "Process", "Planner Verified Skill Level"])
        out = wo_summary(rounds, workers, planner).set_index("WO")
        self.assertEqual(len(out), 2)
        self.assertEqual(out.loc["A", "Verified Skill"], 8)
        self.assertEqual(out.loc["A", "Total Quantity"], 4)
        self.assertEqual(out.loc["B", "ProductionWorkers"], "E2; E3")
        self.assertEqual(out.loc["B", "Total Quantity"], 1)
        self.assertEqual(out.loc["B", "FPY"], 0)
        self.assertTrue(pd.isna(out.loc["B", "Verified Skill"]))

    def test_worker_validation_requires_both_reviewed_source_hashes(self) -> None:
        import json
        record = {"status": "USER_VALIDATED", "id": "test", "source_sha256": {
            "Rasch first pass workers.csv": "first", "Rasch rework workers.csv": "rework"}}
        with patch("pipeline.semi_detail_workbook.WORKER_VALIDATION") as path:
            path.is_file.return_value = True
            path.read_text.return_value = json.dumps(record)
            with patch("pipeline.semi_detail_workbook.file_hash", side_effect=["first", "rework"]):
                self.assertEqual(worker_validation(Path("core")), record)
            with patch("pipeline.semi_detail_workbook.file_hash", return_value="changed"):
                self.assertEqual(worker_validation(Path("core")), {})

    def test_quoted_hours_convert_to_minutes_without_duplicate_semi(self) -> None:
        with patch("pipeline.semi_detail_workbook.pd.read_csv", return_value=pd.DataFrame({"SemiBOM": ["2A", "2B"], "QuotedHours": [1.5, 0.25]})):
            result = _quotes(Path("quotes.csv"), {"2A", "2B"})
            self.assertEqual(result.QuotedMinutesPerSemi.tolist(), [90.0, 15.0])
            self.assertEqual(result.QuoteInputUnit.tolist(), ["HOURS_CONVERTED_X60"] * 2)
            self.assertEqual(result.QuoteBasis.tolist(), ["PER_SEMI_UNIT"] * 2)


    def test_quoted_time_rejects_duplicate_keys(self) -> None:
        with patch("pipeline.semi_detail_workbook.pd.read_csv", return_value=pd.DataFrame({"SemiBOM": ["2A", "2A"], "QuotedMinutes": [15, 20]})):
            with self.assertRaisesRegex(ValueError, "Duplicate quoted SemiBOM"):
                _quotes(Path("quotes.csv"), {"2A"})


class SemiSkuSheetTests(unittest.TestCase):
    HEADERS = [
        "SemiBOM", "Process", "QualityFactor_Approved", "PartMechanismFactor_Approved",
        "MaterialDesignFactor_Approved", "StoneFactor_Approved", "LearningFactor_Approved",
        "FinalTechnicalComplexity", "ObservedFPY", "PassQty1", "InspectedQty1",
        "QCEvidenceN", "FirstPass_Calibration_Status", "RaschConfidencePct", "RaschConfidenceStatus",
        "QualityFactor_Diagnostic", "StoneSourceScore",
    ]

    def test_complete_factor_score_and_diagnostic_confidence(self) -> None:
        row = ["2A", "Polishing", 6, 4, 2, 8, 10, 5.1, 0.75, 6, 8, 1, "VALIDATED", 0.9, "NOT_ESTIMATED", None, None]
        result = _sku_score_rows(self.HEADERS, [row])[0]
        self.assertAlmostEqual(result[7], 5.1)
        self.assertAlmostEqual(result[8], 5.1)
        self.assertAlmostEqual(result[9], 1.0)
        self.assertIn("75.0% observed", result[10])
        self.assertIsNone(result[11])
        self.assertIsNone(result[12])
        self.assertIsNone(result[13])

    def test_partial_factor_is_normalized_to_score10(self) -> None:
        row = ["2A", "Polishing", 6, None, None, None, None, None, None, None, None, None, "NOT_VALIDATED", None, "NOT_ESTIMATED", None, None]
        result = _sku_score_rows(self.HEADERS, [row])[0]
        self.assertAlmostEqual(result[7], 6.0)
        self.assertAlmostEqual(result[8], 2.4)
        self.assertAlmostEqual(result[9], 0.4)
        self.assertIsNone(result[11])  # Quality score has no matching model confidence.

    def test_observed_fpy_never_becomes_factor_score(self) -> None:
        row = ["2A", "Polishing", None, None, None, None, None, None, 0.75, 6, 8, 1, "NOT_VALIDATED", None, "NOT_ESTIMATED", None, None]
        result = _sku_score_rows(self.HEADERS, [row])[0]
        self.assertIsNone(result[2])
        self.assertIsNone(result[7])
        self.assertIsNone(result[8])
        self.assertEqual(result[9], 0)
        self.assertIsNone(result[11])
        self.assertIsNone(result[12])
        self.assertEqual(result[13], 0)
        self.assertIn("75.0% observed", result[10])

    def test_fpy_summary_shows_provisional_score_use_and_validation(self) -> None:
        headers = self.HEADERS + ["FirstPass_Rasch_Converged"]
        row = ["2A", "Polishing", None, None, None, None, None, None,
               0.75, 6, 8, 1, "NOT_VALIDATED", None, "NOT_ESTIMATED",
               4.0, None, True]
        result = _sku_score_rows(headers, [row])[0]
        self.assertEqual(result[2], 4.0)
        self.assertIn("FIT_CONVERGED; MODEL_SCORE_INCLUDED_IN_TOTAL; VALIDATION_PENDING", result[10])

    def test_model_estimate_and_stone_source_are_provisional_contributions(self) -> None:
        row = ["2A", "Polishing", None, None, None, None, None, None, 0.75, 6, 8, 1, "NOT_VALIDATED", 0.62, "CONDITIONAL_DIAGNOSTIC", 4.0, 2.0]
        result = _sku_score_rows(self.HEADERS, [row])[0]
        self.assertEqual(result[2], 4.0)
        self.assertEqual(result[5], 2.0)
        self.assertAlmostEqual(result[7], 3.6)
        self.assertAlmostEqual(result[8], 1.8)
        self.assertAlmostEqual(result[9], 0.5)
        self.assertEqual(result[11], 0.62)
        self.assertIsNone(result[12])
        self.assertEqual(result[13], 0.31)

    def test_learning_source_score_uses_its_own_precision(self) -> None:
        headers = self.HEADERS + ["LearningSourceScore", "LearningConfidencePct", "LearningConfidenceStatus"]
        row = ["2A", "Polishing", None, None, None, None, None, None,
               0.75, 6, 8, 1, "NOT_VALIDATED", 0.62, "CONDITIONAL_DIAGNOSTIC",
               4.0, 2.0, 8.0, 0.5, "CONDITIONAL_DIAGNOSTIC"]
        result = _sku_score_rows(headers, [row])[0]
        self.assertEqual(result[6], 8.0)
        self.assertAlmostEqual(result[8], 2.2)
        self.assertAlmostEqual(result[9], 0.55)
        self.assertAlmostEqual(result[12], 0.5)
        self.assertAlmostEqual(result[13], 0.275)
        row[-2:] = [None, "NOT_ESTIMATED"]
        self.assertIsNone(_sku_score_rows(headers, [row])[0][12])
        self.assertIsNone(_sku_score_rows(headers, [row])[0][13])

    def test_fixed_only_factor_uses_weight_coverage_for_confidence(self) -> None:
        row = ["2A", "Polishing", None, None, None, None, None, None, None, None, None, None, "NOT_VALIDATED", None, "NOT_ESTIMATED", None, 2.0]
        result = _sku_score_rows(self.HEADERS, [row])[0]
        self.assertEqual((result[7], result[8], result[9], result[13]), (2.0, 0.2, 0.1, 0.1))
        self.assertIsNone(result[11])

    def test_material_design_source_contributes_provisionally(self) -> None:
        headers = self.HEADERS + ["MaterialDesignSourceScore"]
        row = ["2A", "Polishing", None, None, None, None, None, None, None, None, None, None,
               "NOT_VALIDATED", None, "NOT_ESTIMATED", None, 2.0, 6.0]
        result = _sku_score_rows(headers, [row])[0]
        self.assertEqual(result[4], 6.0)
        self.assertAlmostEqual(result[7], 4.6666666667)
        self.assertAlmostEqual(result[8], 1.4)
        self.assertAlmostEqual(result[9], 0.3)
        self.assertAlmostEqual(result[13], 0.3)
        material = next(f for f in _factor_provenance_rows(headers, [row]) if f[2] == "Material Design Process")
        self.assertEqual((material[4], material[5], material[6]), (6.0, "SOURCE_RULE_CALCULATION_PROVISIONAL", None))

    def test_part_mechanism_source_contributes_provisionally(self) -> None:
        headers = self.HEADERS + ["PartMechanismSourceScore", "PartMechanismEvidenceStatus"]
        row = ["2A", "Polishing", None, None, None, None, None, None, None, None, None, None,
               "NOT_VALIDATED", None, "NOT_ESTIMATED", None, None, 6.8, "SOURCE_COMPONENTS_PRESENT"]
        result = _sku_score_rows(headers, [row])[0]
        self.assertEqual(result[3], 6.8)
        self.assertAlmostEqual(result[8], 1.7)
        self.assertAlmostEqual(result[9], 0.25)
        part = next(f for f in _factor_provenance_rows(headers, [row]) if f[2] == "Part & Mechanism")
        self.assertEqual((part[4], part[5]), (6.8, "SOURCE_RULE_CALCULATION_PROVISIONAL"))

    def test_new_modeled_factor_needs_its_own_confidence(self) -> None:
        headers = self.HEADERS + ["LearningFactorMethod", "LearningConfidencePct", "LearningConfidenceStatus"]
        row = ["2A", "Polishing", None, None, None, None, 8.0, None, None, None, None, None, "NOT_VALIDATED", None, "NOT_ESTIMATED", None, None, "MODEL_ESTIMATE", None, "NOT_ESTIMATED"]
        result = _sku_score_rows(headers, [row])[0]
        self.assertEqual(result[7], 8.0)
        self.assertIsNone(result[11])
        row[-2:] = [0.7, "ESTIMATED_VALIDATED"]
        result = _sku_score_rows(headers, [row])[0]
        self.assertAlmostEqual(result[12], 0.7)
        self.assertAlmostEqual(result[13], 0.035)

    def test_excluded_scope_keeps_audit_row_without_scores(self) -> None:
        headers = self.HEADERS + ["DifficultyStatus", "SemiScopeStatus"]
        row = ["2A-01", "Polishing", 6, 4, 2, 8, 10, 5.1, 0.75, 6, 8, 1,
               "VALIDATED", 0.9, "CONDITIONAL_DIAGNOSTIC", 4.0, 2.0,
               "EXCLUDED_SEMI_SCOPE", "EXCLUDED_SEMI_SCOPE"]
        result = _sku_score_rows(headers, [row])[0]
        self.assertEqual(result[0], "2A-01")
        self.assertEqual(result[14], "EXCLUDED_SEMI_SCOPE")
        self.assertTrue(all(value is None for value in result[2:9]))
        self.assertEqual(result[9], 0.0)
        self.assertIsNone(result[11])
        self.assertIsNone(result[12])
        self.assertIsNone(result[13])
        self.assertEqual(len(_factor_provenance_rows(headers, [row])), 5)

    def test_bom_warning_does_not_block_direct_factor_score(self) -> None:
        headers = self.HEADERS + ["DifficultyStatus", "PartMechanismSourceScore"]
        row = ["2A", "Sanding", None, None, None, None, None, None, None, None, None, None,
               "NOT_VALIDATED", None, "NOT_ESTIMATED", None, None, "BLOCKED_RASCH_AND_FACTORS", 6.8]
        result = _sku_score_rows(headers, [row])[0]
        self.assertEqual(result[14], "IN_SCOPE")
        self.assertEqual(result[3], 6.8)
        self.assertEqual(result[7], 6.8)
        part = next(p for p in _factor_provenance_rows(headers, [row]) if p[2] == "Part & Mechanism")
        self.assertEqual(part[4], 6.8)

    def test_published_score_requires_all_factors(self) -> None:
        row = ["2A", "Polishing", 6, None, None, None, None, 2.4, None, None, None, None, "NOT_VALIDATED", None, "NOT_ESTIMATED", None, None]
        with self.assertRaisesRegex(ValueError, "lacks all five"):
            _sku_score_rows(self.HEADERS, [row])

    def test_factor_provenance_limits_confidence_to_fitted_quality(self) -> None:
        row = ["2A", "Polishing", None, None, None, None, None, None, 0.75, 6, 8, 1, "NOT_VALIDATED", 0.62, "CONDITIONAL_DIAGNOSTIC", 4.0, 2.0]
        factors = _factor_provenance_rows(self.HEADERS, [row])
        self.assertEqual(len(factors), 5)
        quality = next(f for f in factors if f[2] == "Quality")
        stone = next(f for f in factors if f[2] == "Stone")
        learning = next(f for f in factors if f[2] == "Learning")
        self.assertEqual((quality[4], quality[5], quality[6]), (4.0, "QC_RASCH_MODEL", 0.62))
        self.assertEqual((stone[4], stone[5], stone[6]), (2.0, "SOURCE_RULE_CALCULATION_PROVISIONAL", None))
        self.assertEqual((learning[4], learning[5], learning[6]), (None, "INSUFFICIENT_REPEATED_HISTORY", None))


if __name__ == "__main__":
    unittest.main()


class MaterialDesignInputTests(unittest.TestCase):
    def test_duplicate_context_selects_matching_master_product_type(self) -> None:
        source = pd.DataFrame([
            {"Semi Item": "A", "Semi BOM Item": "A-01", "Name": "Semi", "FG Item": "F",
             "Material": "Silver", "Product Type": "Bracelet", "Process": "Sanding",
             "Material Score": 3, "Design Score": 7, "Process Score": 3, "Material Design Process": 4.6},
            {"Semi Item": "A", "Semi BOM Item": "A-01", "Name": "Semi", "FG Item": "F",
             "Material": "Silver", "Product Type": "Necklace", "Process": "Sanding",
             "Material Score": 3, "Design Score": 8, "Process Score": 3, "Material Design Process": 5.0},
        ])
        semis = pd.DataFrame({"SemiBOM": ["A-01"], "SemiItem": ["A"],
                              "Process": ["Sanding"], "Product Type": ["Neck"]})
        with patch("pipeline.material_design_inputs.pd.read_excel", return_value=source):
            chosen, audit, counts = read_material_design(Path("source.xlsx"), semis)
        self.assertEqual(chosen.MaterialDesignSourceScore.tolist(), [5.0])
        self.assertEqual(chosen.MaterialDesignSourceRow.tolist(), [3])
        self.assertEqual(audit.SelectionStatus.tolist(), ["NOT_SELECTED_CONTEXT", "SELECTED_PRODUCT_TYPE"])
        self.assertEqual(counts["selected_semi_boms"], 1)

    def test_invalid_composite_is_rejected(self) -> None:
        source = pd.DataFrame([{"Semi Item": "A", "Semi BOM Item": "A", "Name": "Semi", "FG Item": "F",
                                "Material": "Silver", "Product Type": "Ring", "Process": "Sanding",
                                "Material Score": 3, "Design Score": 7, "Process Score": 3,
                                "Material Design Process": 7.0}])
        semis = pd.DataFrame({"SemiBOM": ["A"], "SemiItem": ["A"], "Process": ["Sanding"], "Product Type": ["Ring"]})
        with patch("pipeline.material_design_inputs.pd.read_excel", return_value=source):
            with self.assertRaisesRegex(ValueError, "composite disagrees"):
                read_material_design(Path("source.xlsx"), semis)


class PartMechanismInputTests(unittest.TestCase):
    def test_source_formula_and_missing_component_audit(self) -> None:
        source = pd.DataFrame([
            {"Semi BOM": "2A", "Physical Part Count": 2, "Assembly Type": "FIT_REQUIRED",
             "Mechanism Function Class": "HINGE", "Part Score": 4,
             "Assembly Structure Score": 6, "Mechanism Bonus": 2,
             "Part & Mechanism Score": 6.8},
            {"Semi BOM": "2B", "Physical Part Count": 1, "Assembly Type": None,
             "Mechanism Function Class": None, "Part Score": 2,
             "Assembly Structure Score": None, "Mechanism Bonus": None,
             "Part & Mechanism Score": 1.2},
        ])
        with patch("pipeline.part_mechanism_inputs.pd.read_excel", return_value=source):
            selected, audit, counts = read_part_mechanism(Path("parts.xlsx"), pd.DataFrame({"SemiBOM": ["2A", "2B"]}))
        self.assertEqual(selected.PartMechanismSourceScore.tolist(), [6.8, 1.2])
        self.assertEqual(counts["incomplete_component_detail"], 1)
        self.assertEqual(audit.EvidenceStatus.tolist(), ["SOURCE_COMPONENTS_PRESENT", "INCOMPLETE_COMPONENT_DETAIL"])

    def test_rejects_wrong_composite(self) -> None:
        source = pd.DataFrame([{"Semi BOM": "2A", "Physical Part Count": 2,
                                "Assembly Type": "FIT_REQUIRED", "Mechanism Function Class": "HINGE",
                                "Part Score": 4, "Assembly Structure Score": 6,
                                "Mechanism Bonus": 2, "Part & Mechanism Score": 8.0}])
        with patch("pipeline.part_mechanism_inputs.pd.read_excel", return_value=source):
            with self.assertRaisesRegex(ValueError, "composite disagrees"):
                read_part_mechanism(Path("parts.xlsx"), pd.DataFrame({"SemiBOM": ["2A"]}))
