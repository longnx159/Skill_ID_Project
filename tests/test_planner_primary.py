import hashlib
import json
from pathlib import Path
import unittest
import uuid

import numpy as np
import pandas as pd

from scripts.export_planner_primary import export


class PlannerPrimaryTests(unittest.TestCase):
    def test_requested_blend_fallback_and_provisional_flags(self):
        root=Path('tests/_artifacts')/('planner_primary_'+uuid.uuid4().hex)
        artifacts=root/'artifacts'
        artifacts.mkdir(parents=True)
        groups=[]
        for group,score in [('A',2.),('B',np.nan),('C',4.)]:
            for branch in ['FIRST_PASS','REWORK']:
                v=score if branch=='FIRST_PASS' else np.nan
                groups.append(dict(Process='P',SizeAdjustedGroup=group,Branch=branch,SelectedOnValidation=True,
                    Model='M',Difficulty10=v,Lower95=v-.5,Upper95=v+.5,Lower975=v-.6,Upper975=v+.6,
                    WOs=10,QCPieces=100,Converged=False,
                    ValidationStatus='EXCLUDED_SEMI_SCOPE' if group=='C' else 'NOT_ACCEPTED_KEEP_RASCH'))
        tables={
            'Planner Semi branches':pd.DataFrame(groups),
            'Planner QC audit':pd.DataFrame([dict(WO=g,Process='P',SizeAdjustedGroup=g,Branch='FIRST_PASS',Eligibility='ELIGIBLE') for g in ['A','B']]),
            'Rasch first pass groups':pd.DataFrame([dict(Process='P',SizeAdjustedGroup=g,FPY_Rasch_Difficulty=6.,Rasch_Converged=True) for g in ['A','B','C']]),
            'Rasch rework groups':pd.DataFrame({'Status':['No records']}),
            'Planner workers':pd.DataFrame({'SelectedOnValidation':[True],'ModelStatus':['NO_ELIGIBLE_MODEL']}),
            'Planner actual worker anchors':pd.DataFrame({'SelectedOnValidation':[True]}),
            'Planner comparison':pd.DataFrame({'Model':['M']}),
            'Planner acceptance':pd.DataFrame({'Decision':['KEEP_RASCH']})}
        manifest=dict(run_id='fixture',execution_status='SUCCEEDED',sources=[],artifacts=[])
        for name,frame in tables.items():
            path=artifacts/(name+'.csv')
            frame.to_csv(path,index=False)
            manifest['artifacts'].append(dict(path=str(path.relative_to(root)),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        (root/'run_manifest.json').write_text(json.dumps(manifest))
        payload=export(root,root/'primary')
        result=pd.DataFrame(payload['tables']['Planner primary Quality']).set_index('SizeAdjustedGroup')
        self.assertAlmostEqual(result.loc['A','Quality'],2.8)
        self.assertEqual(result.loc['B','Quality'],6.)
        self.assertEqual(result.loc['B','PlannerModelWeight'],0.)
        self.assertTrue(pd.isna(result.loc['C','Quality']))
        self.assertEqual(result.loc['A','UseStatus'],'PROVISIONAL_NONCONVERGED_USER_SELECTED')
        self.assertEqual(result.loc['B','BlendStatus'],'100_PERCENT_RASCH_FALLBACK')
        self.assertEqual(payload['tables']['Statistical acceptance'][0]['Decision'],'KEEP_RASCH')
        tables['Planner comparison'].to_csv(artifacts/'Planner comparison.csv',index=False,header=False)
        with self.assertRaises(ValueError):
            export(root,root/'corrupt_export')


if __name__=='__main__':
    unittest.main()
