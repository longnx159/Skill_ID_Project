"""Independent bottom-up checks of BOM features against source edges."""
from pathlib import Path
from graphlib import TopologicalSorter, CycleError
import json
import pandas as pd
from .bom_features import STONE_GROUPS


def audit(input_dir=Path('Bom Table'), output=Path('outputs/bom_review')):
    summary=pd.read_csv(output/'semi_bom_features.csv',dtype={'FG BOM':str,'SemiBOM':str})
    expected=summary.set_index(['SourceFile','FG BOM','SemiBOM'])
    failures=[]
    checked=0
    classification=[]
    for f in sorted(input_dir.glob('*.xlsx')):
        if f.name.startswith('~$'): continue
        raw=pd.read_excel(f,dtype={'FG BOM number':str,'BOM number':str,'Component item number':str,'Supply BOM number':str})
        d=raw.drop_duplicates().copy()
        d['Supply BOM number']=d['Supply BOM number'].fillna('')
        d['BOM unit']=d['BOM unit'].str.upper()
        casting=d['Item group'].eq('SM_Casting')
        classification.append({'File':f.name,'RawCastingRows':int(raw['Item group'].eq('SM_Casting').sum()),
            'CastingWithRecipeRows':int((casting&d['Supply BOM number'].ne('')).sum()),
            'CastingGroupPrefixMismatch':int((casting!=d['Component item number'].str.startswith('2DU')).sum())})
        for fg,g in d.groupby('FG BOM number',sort=False):
            nodes={n:part.to_dict('records') for n,part in g.groupby('BOM number',sort=False)}
            graph={n:{r['Supply BOM number'] for r in rows if r['Supply BOM number']} for n,rows in nodes.items()}
            try: order=list(TopologicalSorter(graph).static_order())
            except CycleError:
                failures.append({'FG BOM':fg,'Issue':'Cycle in source'});continue
            totals={}
            for n in order:
                casts=stones=weight=parts=directcasts=0.
                for r in nodes.get(n,[]):
                    q=float(r['BOM quantity'])
                    if not pd.notna(q) or q<=0:continue
                    pcs=r['BOM unit']=='PCS';stone=r['Item group'] in STONE_GROUPS
                    child=r['Supply BOM number']
                    if pcs and not stone and r['Item group']!='Services':parts+=q
                    if pcs and r['Item group']=='SM_Casting':casts+=q;directcasts+=q
                    elif child and pcs:casts+=q*totals[child][0]
                    if child and pcs:
                        stones+=q*totals[child][1];weight+=q*totals[child][2]
                    elif not child and stone:
                        stones+=q
                        w=r['Exclude weight']
                        if pcs and abs(q-round(q))<1e-8 and pd.notna(w) and w>0:weight+=w
                totals[n]=(casts,stones,weight)
                key=(f.name,fg,n)
                if key not in expected.index:continue
                row=expected.loc[key]
                for col,value in {'DirectPartCountPCS':parts,'DirectCastingCountPCS':directcasts,
                                  'CastingCountScenario':casts,'StoneCountScenario':stones,
                                  'KnownStoneWeightGram':weight}.items():
                    checked+=1
                    if pd.isna(row[col]) or abs(row[col]-value)>1e-7:
                        failures.append({'FG BOM':fg,'SemiBOM':n,'Metric':col,'Actual':row[col],'Expected':value})
    complete=summary[summary.MaxStoneWeightGram.notna()]
    invariant_errors=int(((complete.AvgStoneWeightGram*complete.StoneCount-complete.TotalStoneWeightGram).abs()>1e-8).sum())
    invariant_errors+=int((~complete.LargestSingleStonePctOfAllStones.between(0,100.0000001)).sum())
    target=summary[summary.SemiBOM.eq('2SN16620M025010100Z')]
    report={'source_classification':classification,'independent_checks':checked,
            'mismatches':len(failures),'stone_invariant_errors':invariant_errors,
            'semi_contexts':len(summary),'target':target[['SemiBOM','DirectPartCountPCS','DirectCastingCountPCS','DirectOtherPartCountPCS','CastingCountPCS','StoneCount']].to_dict('records'),
            'contexts_with_castings':int(summary.CastingCountScenario.gt(0).sum()),
            'unique_semi_with_castings':summary.loc[summary.CastingCountScenario.gt(0),'SemiBOM'].nunique(),
            'structure_status':summary.Status.value_counts().to_dict()}
    pd.DataFrame(failures,columns=['FG BOM','SemiBOM','Metric','Actual','Expected','Issue']).to_csv(output/'overall_audit_mismatches.csv',index=False,encoding='utf-8-sig')
    (output/'overall_audit.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(report,indent=2,ensure_ascii=False))
    if failures or invariant_errors:raise AssertionError('BOM review has audit mismatches')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--input-dir',type=Path,default=Path('Bom Table'))
    parser.add_argument('--output',type=Path,default=Path('outputs/bom_review_v2'))
    args=parser.parse_args()
    audit(args.input_dir,args.output)
