"""Run from repo root: python -B -m deliverables.rasch_refresh_20260922.summarize_results."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from pipeline.rasch_assessment import verify
from pipeline.rasch_experiments import paired_bootstrap
from pipeline.run_reporting import file_hash

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
audit = json.loads((OUT / 'refresh_audit.json').read_text())
run = ROOT / 'outputs/rasch_experiments' / audit['new_run']
manifest = verify(run)
assert manifest['execution_status'] == 'SUCCEEDED_WITH_WARNINGS'
for source in manifest['sources']:
    assert file_hash(run / source['snapshot']) == source['sha256']
old = verify(ROOT / 'outputs/rasch_experiments' / audit['old_run'])
old_hashes = {s['dataset']: s['sha256'] for s in old['sources']}
audit['changed_source_datasets'] = sorted({s['dataset'] for s in manifest['sources'] if old_hashes.get(s['dataset']) != s['sha256']})
result = pd.read_csv(run / 'experiment/comparison.csv')
convergence = result.loc[result.Cohort.eq('single')].groupby('Variant').converged.agg(['sum', 'count'])
convergence.to_csv(OUT / 'convergence.csv')
p = pd.read_csv(run / 'experiment/predictions.csv', dtype={'WO': str})
p = p.loc[p.Attribution.eq('single')].copy()
p['NLL'] = -(p.PassQty * np.log(p.Prediction) + (p.InspectedQty-p.PassQty)*np.log1p(-p.Prediction))
pooled = p.groupby(['Branch', 'Variant']).agg(NLL=('NLL', 'sum'), Pieces=('InspectedQty', 'sum'), Rounds=('WO', 'size'))
pooled['LogLoss'] = pooled.NLL / pooled.Pieces
pooled.to_csv(OUT / 'pooled_comparison.csv')
intervals = []
for branch, group in p.groupby('Branch'):
    baseline = group.loc[group.Variant.eq('legacy_1000')]
    for variant, part in group.groupby('Variant'):
        common = baseline.merge(part[['WO', 'RoundNo', 'Prediction']], on=['WO', 'RoundNo'], validate='one_to_one', suffixes=('_baseline', '_candidate'))
        assert len(common) == len(baseline) == len(part)
        intervals.append({'Branch': branch, 'Variant': variant, **paired_bootstrap(common, common.Prediction_candidate.to_numpy(), common.Prediction_baseline.to_numpy())})
pd.DataFrame(intervals).to_csv(OUT / 'paired_intervals.csv', index=False)
audit['verified_artifacts'] = len(manifest['artifacts'])
(OUT / 'refresh_audit.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
print('Changed source datasets:', audit['changed_source_datasets'])
print(pooled.to_string())
print(pd.DataFrame(intervals).to_string(index=False))
