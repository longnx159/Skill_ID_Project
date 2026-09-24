import unittest

import pandas as pd

from pipeline.semi_scope import excluded_semi_mask, semi_scope_rule


class SemiScopeTests(unittest.TestCase):
    def test_prefixes_and_likely_outsource_suffixes(self) -> None:
        items = pd.Series(["2GH123", "2VS123", "2TD123", "2XD123", "2DG123", "2ME123", "3123", "9123", "2AA123", "2AA124", "2AA125"])
        boms = pd.Series(["A", "B", "C", "D", "E", "F", "G", "H", "2AA123-01", "2AA124-02", "2AA125-03"])
        self.assertEqual(excluded_semi_mask(items, boms).tolist(),
                         [True, True, True, True, True, True, True, True, True, True, False])
        self.assertEqual(semi_scope_rule(items, boms).tolist(),
                         ["PREFIX_2GH", "PREFIX_2VS", "PREFIX_2TD", "PREFIX_2XD", "PREFIX_2DG", "PREFIX_2ME", "PREFIX_3", "PREFIX_9",
                          "BOM_SUFFIX_-01", "BOM_SUFFIX_-02", ""])


if __name__ == "__main__":
    unittest.main()
