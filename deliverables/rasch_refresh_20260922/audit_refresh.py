"""Rebuild source-refresh evidence from frozen experiment inputs; no fitting."""
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
OLD = ROOT / 'outputs/rasch_experiments/run_20260922T110034_324937Z_9c4bc2b2'
NEW = ROOT / 'outputs/rasch_experiments/run_20260922T141612_236215Z_1f94bd79'

old = pd.read_csv(OLD / 'experiment/modeling_rounds.csv')
new = pd.read_csv(NEW / 'experiment/modeling_rounds.csv')
joined = old.merge(new, on=['WO', 'RoundNo'], suffixes=('_old', '_new'), validate='one_to_one')
assert len(joined) == len(old) == len(new)
for col in ['PassQty', 'InspectedQty', 'QC_Start', 'QC_Stop', 'Item Number', 'Process']:
    assert joined[col + '_old'].equals(joined[col + '_new']), col
coverage = pd.concat([old.assign(Snapshot='Previous'), new.assign(Snapshot='Refreshed')])
coverage.groupby(['Snapshot', 'Branch', 'Attribution']).size().rename('Rounds').to_csv(OUT / 'coverage.csv')
new.assign(Date=new.QC_Stop.str[:10]).groupby(['Date', 'Branch', 'Attribution']).size().rename('Rounds').to_csv(OUT / 'daily_attribution.csv')
transitions = joined.groupby(['Attribution_old', 'Attribution_new']).size().rename('Rounds')
transitions.to_csv(OUT / 'attribution_transitions.csv')
lost = joined.loc[joined.Attribution_old.eq('single') & joined.Attribution_new.eq('unknown')].copy()
lost['Worker'] = lost.Workers_old.map(lambda value: json.loads(value)[0])
with pd.ExcelFile(NEW / 'inputs/01_Production/ProductionData.xlsx') as book:
    worker = pd.read_excel(book, sheet_name='GSWorkerWorkingHours', dtype={'Worker': str, 'ProductionOrderNumber': str})
    wo = pd.read_excel(book, sheet_name='WorkOrderData', dtype={'ProductionOrderNumber': str})
for frame in (worker, wo):
    frame['ProductionOrderNumber'] = frame.ProductionOrderNumber.str.strip()
worker['Worker'] = worker.Worker.str.strip()
keys = ['ProductionOrderNumber', 'RoundNo', 'Worker']
worker['Final'] = pd.to_numeric(worker.Final, errors='coerce')
hours = worker.groupby(keys, dropna=False).Final.sum().rename('CurrentHours').reset_index()
lost = lost.merge(hours, left_on=['WO', 'RoundNo', 'Worker'], right_on=keys, how='left', validate='many_to_one')
fields = ['ProductionOrderNumber', 'ItemNumber', 'GoodCW', 'MaxRAFDate']
lost = lost.merge(wo[fields], left_on='WO', right_on='ProductionOrderNumber', how='left', validate='many_to_one')
lost[['WO', 'RoundNo', 'Worker', 'CurrentHours', 'ItemNumber', 'GoodCW', 'MaxRAFDate']].to_csv(OUT / 'lost_link_audit.csv', index=False)
dates = pd.to_datetime(wo.MaxRAFDate, errors='coerce')
recent = new.loc[new.QC_Stop.ge('2026-09-15')]
summary = {
    'old_run': OLD.name, 'new_run': NEW.name,
    'same_qc_observations_and_outcomes': True,
    'production_worker_rows': len(worker), 'production_wo_rows': len(wo),
    'production_max_raf_date': str(dates.max()),
    'newly_linked_rounds': int((joined.Attribution_old.eq('unknown') & joined.Attribution_new.ne('unknown')).sum()),
    'lost_single_worker_links': len(lost),
    'lost_links_missing_worker_record': int(lost.CurrentHours.isna().sum()),
    'lost_links_nonpositive_hours': int(lost.CurrentHours.le(0).sum()),
    'lost_links_nonpositive_goodcw': int(lost.GoodCW.le(0).sum()),
    'lost_links_missing_rafdate': int(lost.MaxRAFDate.isna().sum()),
    'recent_qc_rounds': len(recent),
    'recent_single_worker_rounds': int(recent.Attribution.eq('single').sum()),
    'recent_team_rounds': int(recent.Attribution.eq('team').sum()),
    'recent_unknown_rounds': int(recent.Attribution.eq('unknown').sum()),
}
(OUT / 'refresh_audit.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary, indent=2))
