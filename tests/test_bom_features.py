"""BOM arithmetic checks using in-memory Excel reader fixtures."""
import uuid
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from pipeline.bom_features import run


def row(parent, component, qty=1, child='', group='SM_FGs', weight=0):
    return {'FG BOM number':'FG','FG item number':'FG','BOM number':parent,
            'BOM item number':parent,'Component item number':component,
            'Supply BOM number':child,'BOM quantity':qty,'BOM unit':'PCS',
            'Quantity':qty if group=='RM_Diamond' else 10*qty,
            'Unit':'PCS' if group=='RM_Diamond' else 'Gram','Exclude weight':weight,
            'BOM CW size':1,'Item group':group,'Sequence':1,
            'Product name':parent,'Product name2':component}


class BOMFeatures(unittest.TestCase):
    def calculate(self, rows):
        base=Path(__file__).parent/'_artifacts'/('bom_'+uuid.uuid4().hex)
        base.mkdir(parents=True)
        (base/'fixture.xlsx').write_bytes(b'fixture')
        with patch('pipeline.bom_features.pd.read_excel', return_value=pd.DataFrame(rows)):
            result=run(base,base/'out').set_index('SemiBOM')
        for p in (base/'out').iterdir(): p.unlink()
        (base/'out').rmdir()
        (base/'fixture.xlsx').unlink()
        base.rmdir()
        return result

    def test_shared_descendant_multiplies_each_path_and_max_is_one_stone(self):
        rows=[row('FG','S',child='S'),row('S','A',2,'A'),row('S','B',3,'B'),
              row('A','C',child='C'),row('B','C',child='C'),
              row('C','D',2,group='RM_Diamond',weight=4),
              row('C','casting',group='SM_Casting')]
        s=self.calculate(rows).loc['S']
        self.assertEqual(s.StoneCount,10)
        self.assertEqual(s.TotalStoneWeightGram,20)
        self.assertEqual(s.AvgStoneWeightGram,2)
        self.assertEqual(s.MaxStoneWeightGram,2)
        self.assertEqual(s.LargestSingleStonePctOfAllStones,10)
        self.assertEqual(s.LeafPartCountPCS,5)

    def test_missing_weight_does_not_become_zero(self):
        s=self.calculate([row('FG','S',child='S'),row('S','D',group='RM_Diamond')]).loc['S']
        self.assertEqual(s.StoneCount,1)
        self.assertTrue(pd.isna(s.TotalStoneWeightGram))
        self.assertTrue(pd.isna(s.MaxStoneWeightGram))

    def test_duplicate_rows_block_authoritative_rollup(self):
        stone=row('S','D',group='RM_Diamond',weight=1)
        s=self.calculate([row('FG','S',child='S'),stone,stone]).loc['S']
        self.assertEqual(s.StoneCountScenario,1)
        self.assertTrue(pd.isna(s.StoneCount))
        self.assertIn('Duplicate',s.Status)

    def test_missing_child_blocks_zero_stone_claim(self):
        s=self.calculate([row('FG','S',child='S'),row('S','M',child='M')]).loc['S']
        self.assertTrue(pd.isna(s.StoneCount))
        self.assertIn('Missing child',s.Status)

    def test_three_castings_plus_one_silver_component(self):
        s=self.calculate([row('FG','S',child='S'),row('S','A',group='SM_Casting'),
                          row('S','C',group='SM_Casting'),row('S','D',group='SM_Casting'),
                          row('S','silver',group='RM_Silver')]).loc['S']
        self.assertEqual(s.DirectPartCountPCS,4)
        self.assertEqual(s.DirectCastingCountPCS,3)
        self.assertEqual(s.CastingCountPCS,3)
        self.assertEqual(s.DirectOtherPartCountPCS,1)

    def test_casting_recipe_keeps_casting_identity_and_rolls_stones(self):
        s=self.calculate([row('FG','S',child='S'),row('S','casting',2,'C','SM_Casting'),
                          row('C','D',3,group='RM_Diamond',weight=6)]).loc['S']
        self.assertEqual(s.CastingCountPCS,2)
        self.assertEqual(s.StoneCount,6)
        self.assertEqual(s.TotalStoneWeightGram,12)
