"""Read folder BOM exports; audit parts/stones per FG context and exact BOM version.

Never imports or executes the user's historical scripts. CSV outputs preserve IDs.
"""
from pathlib import Path
from collections import Counter
import argparse
import hashlib
import json
import math
import pandas as pd

STONE_GROUPS = {'RM_Diamond', 'RM_Art ST', 'RM_Nat ST', 'RM_Pearl', 'RM_Old ST'}
TYPE_NAMES = {'RM_Diamond':'Diamond', 'RM_Art ST':'Synthetic stone',
              'RM_Nat ST':'Natural stone', 'RM_Pearl':'Pearl', 'RM_Old ST':'Old stone (unspecified)'}


def run(input_dir, output_dir):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames, sources = [], []
    for f in sorted(Path(input_dir).glob('*.xlsx')):
        if f.name.startswith('~$'): continue
        d = pd.read_excel(f, dtype={'FG item number':str, 'FG BOM number':str,
                                  'BOM item number':str, 'BOM number':str,
                                  'Component item number':str, 'Supply BOM number':str})
        d['SourceFile'] = f.name
        d['SourceRow'] = range(2, len(d)+2)
        frames.append(d)
        sources.append({'file':str(f.resolve()), 'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
    if not frames: raise ValueError('No BOM Excel files found')
    raw = pd.concat(frames, ignore_index=True)
    original = [c for c in raw if c not in ('SourceFile','SourceRow')]
    required = ['FG BOM number','BOM number','BOM item number','Component item number',
                'Supply BOM number','BOM quantity','BOM unit','Quantity','Unit',
                'Exclude weight','BOM CW size','Item group','Sequence']
    if set(required)-set(raw): raise ValueError(f'Missing columns: {set(required)-set(raw)}')
    issues = []
    def issue(r, reason):
        issues.append({k:r.get(k) for k in ['SourceFile','SourceRow','FG BOM number','BOM number','Component item number']} | {'Issue':reason})
    keys = ['SourceFile','FG BOM number','BOM number']
    dup = raw.duplicated(['SourceFile']+original, keep=False)
    duplicate_nodes = set(map(tuple, raw.loc[dup,keys].values))
    for _,r in raw.loc[dup].iterrows(): issue(r, 'Identical export rows; no line ID to distinguish true repetition. Scenario retains one copy.')
    # Do not silently aggregate repeated snapshots or delete source records.
    d = raw.drop_duplicates(['SourceFile']+original).copy()
    for c in ['BOM quantity','Quantity','Exclude weight','BOM CW size','Sequence']:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    for c in ['BOM unit','Unit']:
        d[c] = d[c].fillna('').astype(str).str.strip().str.upper()
    d['Supply BOM number'] = d['Supply BOM number'].fillna('').str.strip()
    d['IsStone'] = d['Item group'].isin(STONE_GROUPS)
    s = d[d.IsStone].copy()
    s['StoneType'] = s['Item group'].map(TYPE_NAMES)
    s['UnitStoneWeightGram'] = s['Exclude weight'].div(s['BOM quantity']).where(
        s['Exclude weight'].gt(0)&s['BOM quantity'].gt(0)&s['BOM unit'].eq('PCS'))
    s['WeightStatus'] = s.UnitStoneWeightGram.notna().map({True:'Observed',False:'Missing or invalid; not zero weight'})
    for _,r in s[s.UnitStoneWeightGram.isna()].iterrows(): issue(r,'Stone weight missing/invalid')
    master = s.groupby('Component item number').agg(
        StoneType=('StoneType',lambda x:'; '.join(sorted(set(x)))),
        ProductName=('Product name2',lambda x:'; '.join(sorted(set(x.dropna().astype(str))))),
        PositiveWeightVariants=('UnitStoneWeightGram',lambda x:x.dropna().round(8).nunique()),
        KnownUnitWeightGram=('UnitStoneWeightGram','min'),
        SourceRows=('SourceRow','size'), MissingWeightRows=('UnitStoneWeightGram',lambda x:x.isna().sum())).reset_index()
    # Missing values remain missing even when another row supplies the same SKU's weight.
    s.to_csv(out/'stone_source_detail.csv',index=False,encoding='utf-8-sig')
    master.to_csv(out/'stone_master_check.csv',index=False,encoding='utf-8-sig')
    summaries, details, part_details, casting_details = [], [], [], []
    for (file,fg), ctx in d.groupby(['SourceFile','FG BOM number'],sort=False):
        nodes = {n:g.to_dict('records') for n,g in ctx.groupby('BOM number',sort=False)}
        incoming_masses = {}
        for rec in ctx.to_dict('records'):
            if rec['Supply BOM number'] and rec['Unit']=='GRAM' and rec['BOM quantity']>0:
                incoming_masses.setdefault(rec['Supply BOM number'],[]).append(round(rec['Quantity']/rec['BOM quantity'],8))
        cache = {}
        casting_cache = {}
        def casting_frontier(node, path=()):
            # A casting remains one physical casting even if its recipe contains
            # wax/raw materials/stones. Do not replace it with that recipe's leaves.
            if node in path or node not in nodes: return []
            if node in casting_cache: return casting_cache[node]
            result = []
            for r in nodes[node]:
                q = r['BOM quantity']
                if not math.isfinite(q) or q<=0 or r['BOM unit']!='PCS': continue
                if r['Item group']=='SM_Casting':
                    result.append((r,1.,node+' > '+r['Component item number']))
                elif r['Supply BOM number']:
                    result += [(leaf,m*q,node+' > '+trace) for leaf,m,trace in casting_frontier(r['Supply BOM number'],path+(node,))]
            casting_cache[node] = result
            return result
        def expand(node, path=()):
            if node in path: return [], {'Circular BOM'}
            if node in cache: return cache[node]
            if node not in nodes: return [], {'Missing child BOM: '+node}
            leaves, flags = [], set()
            if (file,fg,node) in duplicate_nodes: flags.add('Duplicate export rows: deduplicated scenario')
            if len({r['BOM item number'] for r in nodes[node]})!=1: flags.add('Conflicting BOM item identity')
            if any(r['BOM CW size']!=1 for r in nodes[node]): flags.add('BOM CW size is not 1: basis requires review')
            for r in nodes[node]:
                q = r['BOM quantity']
                if not math.isfinite(q) or q<=0:
                    flags.add('Nonpositive or invalid BOM quantity'); issue(r,'Nonpositive or invalid BOM quantity'); continue
                child = r['Supply BOM number']
                if child:
                    if r['BOM unit']!='PCS': flags.add('Child BOM quantity unit is not PCS'); continue
                    child_leaves, child_flags = expand(child,path+(node,))
                    flags |= child_flags
                    leaves += [(leaf,mult*q, node+' > '+trace) for leaf,mult,trace in child_leaves]
                else:
                    leaves.append((r,1.,node+' > '+r['Component item number']))
                    if r['Item group']=='SM_FGs': flags.add('Unexpanded assembly without Supply BOM')
            cache[node] = leaves,flags
            return leaves,flags
        for node, rows in nodes.items():
            if node==fg: continue  # Semi output, not a sum of FG snapshots.
            leaves, flags = expand(node)
            castings = casting_frontier(node)
            for r,m,trace in castings:
                casting_details.append({'SourceFile':file,'FG BOM':fg,'SemiBOM':node,
                    'SourceRow':r['SourceRow'],'Path':trace,'CastingItem':r['Component item number'],
                    'LineQty':r['BOM quantity'],'PathMultiplier':m,
                    'EffectiveCastingQty':r['BOM quantity']*m,
                    'CastingHasSupplyBOM':bool(r['Supply BOM number'])})
            stones = [(r,m,t) for r,m,t in leaves if r['IsStone']]
            count = total_known = 0.
            unit_weights, type_counts, sku_set = [], Counter(), set()
            weight_missing = False
            for r,m,trace in stones:
                q,w = r['BOM quantity'],r['Exclude weight']
                valid_count = r['BOM unit']=='PCS' and q>0 and abs(q-round(q))<1e-8
                if not valid_count: flags.add('Invalid stone count/unit')
                n=q*m
                count += n
                valid_weight = valid_count and math.isfinite(w) and w>0
                unit=w/q if valid_weight else math.nan
                weight_missing |= not valid_weight
                if valid_weight: total_known += w*m; unit_weights.append(unit)
                type_counts[TYPE_NAMES[r['Item group']]] += n
                sku_set.add(r['Component item number'])
                details.append({'SourceFile':file,'FG BOM':fg,'SemiBOM':node,
                    'SourceRow':r['SourceRow'],'Path':trace,'StoneSKU':r['Component item number'],
                    'StoneType':TYPE_NAMES[r['Item group']],'ProductName':r['Product name2'],
                    'LineQty':q,'PathMultiplier':m,'EffectiveStoneCount':n,
                    'LineWeightGram':w,'UnitStoneWeightGram':unit,
                    'EffectiveWeightGram':w*m if valid_weight else math.nan})
            structural_ok = not flags
            total = total_known if not weight_missing and structural_ok else math.nan
            mx = max(unit_weights) if unit_weights and not weight_missing and structural_ok else math.nan
            # An upstream line gives a declared gram mass for this Semi. Retain the
            # raw denominator separately: export alone does not prove inclusion of stones.
            masses = incoming_masses.get(node,[])
            declared = float(masses[0]) if masses and len(set(masses))==1 and masses[0]>0 else math.nan
            if len(set(masses))>1: flags.add('Conflicting incoming declared Semi gram mass')
            direct_parts = [r for r in rows if not r['IsStone'] and r['Item group']!='Services' and r['BOM unit']=='PCS']
            leaf_parts = [(r,m) for r,m,_ in leaves if not r['IsStone'] and r['Item group']!='Services' and r['BOM unit']=='PCS']
            for r,m,trace in leaves:
                if not r['IsStone']:
                    part_details.append({'SourceFile':file,'FG BOM':fg,'SemiBOM':node,'Path':trace,
                        'SourceRow':r['SourceRow'],'Component':r['Component item number'],
                        'ItemGroup':r['Item group'],'BOMUnit':r['BOM unit'],
                        'LineQty':r['BOM quantity'],'PathMultiplier':m,
                        'EffectiveQty':r['BOM quantity']*m,
                        'IncludedInPartCountPCS':r['BOM unit']=='PCS' and r['Item group']!='Services'})
            nonpcs = sorted({r['Item group']+':'+r['BOM unit'] for r,m,_ in leaves if not r['IsStone'] and r['BOM unit']!='PCS' and r['Item group']!='Services'})
            summaries.append({'SourceFile':file,'FG BOM':fg,'SemiBOM':node,'SemiItem':rows[0]['BOM item number'],
                'SemiName':rows[0]['Product name'],'Status':'; '.join(sorted(flags)) or 'BOM structure usable',
                'DirectPartCountPCS':sum(r['BOM quantity'] for r in direct_parts),
                'DirectPartSKUCount':len({r['Component item number'] for r in direct_parts}),
                'DirectCastingCountPCS':sum(r['BOM quantity'] for r in direct_parts if r['Item group']=='SM_Casting'),
                'DirectOtherPartCountPCS':sum(r['BOM quantity'] for r in direct_parts if r['Item group']!='SM_Casting'),
                'CastingCountScenario':sum(r['BOM quantity']*m for r,m,_ in castings),
                'CastingCountPCS':sum(r['BOM quantity']*m for r,m,_ in castings) if structural_ok else math.nan,
                'CastingSKUCount':len({r['Component item number'] for r,m,_ in castings}) if structural_ok else math.nan,
                'LeafPartCountPCS':sum(r['BOM quantity']*m for r,m in leaf_parts) if structural_ok else math.nan,
                'NonPCSExcludedFromPartCount':'; '.join(nonpcs),
                'StoneCountScenario':count,'StoneCount':count if structural_ok else math.nan,
                'DirectStoneCount':sum(r['BOM quantity'] for r in rows if r['IsStone']),
                'StoneSKUCount':len(sku_set) if structural_ok else math.nan,
                'StoneTypeCount':len(type_counts) if structural_ok else math.nan,
                'StoneTypes':'; '.join(type_counts),'StoneCountByType':json.dumps(type_counts),
                'KnownStoneWeightGram':total_known,'TotalStoneWeightGram':total,
                'AvgStoneWeightGram':total/count if count else math.nan,
                'MaxStoneWeightGram':mx,
                'LargestSingleStonePctOfAllStones':100*mx/total if total>0 else math.nan,
                'DeclaredSemiMassGram':declared,
                'LargestSingleStonePctOfDeclaredSemiMass':100*mx/declared if declared>0 else math.nan,
                'SemiMassIfDeclaredExcludesStonesGram':declared+total if declared>0 else math.nan,
                'LargestSingleStonePctIfDeclaredExcludesStones':100*mx/(declared+total) if declared>0 and total>0 else math.nan,
                'WeightStatus':'Missing stone weights' if weight_missing else ('No stones observed' if not count else 'Observed line grams; Semi denominator needs inclusion policy'),
                'ProductionModelReady':False})
    summary = pd.DataFrame(summaries)
    # Preserve context/version disagreement instead of choosing a random FG copy.
    metrics=['DirectPartCountPCS','CastingCountScenario','StoneCountScenario','KnownStoneWeightGram']
    conflicts=summary.groupby(['SourceFile','SemiBOM'])[metrics].nunique().max(axis=1)
    summary['ContextConflict']= [conflicts.loc[(r.SourceFile,r.SemiBOM)]>1 for r in summary.itertuples()]
    summary['SemiMassBasisStatus'] = 'Confirm whether declared mass includes stones'
    summary.loc[summary.MaxStoneWeightGram.gt(summary.DeclaredSemiMassGram), 'SemiMassBasisStatus'] = 'Largest stone exceeds declared Semi mass; cannot treat declared mass as gross weight without review'
    summary.to_csv(out/'semi_bom_features.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(details).to_csv(out/'semi_stone_paths.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(part_details).to_csv(out/'semi_part_paths.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(casting_details).to_csv(out/'semi_casting_paths.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(issues).to_csv(out/'bom_issues.csv',index=False,encoding='utf-8-sig')
    stats={'sources':sources,'raw_rows':len(raw),'duplicate_extra_rows':int(raw.duplicated(['SourceFile']+original).sum()),
        'stone_source_rows_raw':int(raw['Item group'].isin(STONE_GROUPS).sum()),
        'stone_rows_missing_weight_raw':int((raw['Item group'].isin(STONE_GROUPS)&raw['Exclude weight'].fillna(0).le(0)).sum()),
        'unique_stone_skus':len(master),'conflicting_positive_unit_weights':int(master.PositiveWeightVariants.gt(1).sum()),
        'semi_contexts':len(summary),'unique_semi_boms':summary.SemiBOM.nunique(),
        'contexts_with_stones':int(summary.StoneCountScenario.gt(0).sum()),
        'contexts_complete_stone_metrics':int(summary.MaxStoneWeightGram.notna().sum()),
        'contexts_with_conflicting_features':int(summary.ContextConflict.sum())}
    (out/'manifest.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(stats,indent=2,ensure_ascii=False))
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--input-dir',type=Path,default=Path('Bom Table'))
    parser.add_argument('--output',type=Path,default=Path('outputs/bom_review'))
    args=parser.parse_args()
    run(args.input_dir,args.output)
