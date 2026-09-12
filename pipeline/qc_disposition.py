"""Classify QC tickets by explicit disposition, falling back only for blanks."""
from pathlib import Path
import json
import hashlib
import pandas as pd


def classify(tickets):
    out=tickets.copy()
    description=out.get('JDescription',pd.Series('',index=out.index)).fillna('').astype(str).str.strip().str.casefold()
    status=out['QCStatus'].fillna('').astype(str).str.strip().str.casefold()
    explicit=description.map({'đạt':'Pass','sửa':'Rework','hỏng':'Scrap'})
    fallback=status.map({'pass':'Pass','fail':'Rework'})
    out['Disposition']=explicit.where(description.ne(''),fallback)
    out['DispositionSource']=description.eq('').map({True:'QCStatus fallback',False:'JDescription'})
    qty=pd.to_numeric(out.QCQty,errors='coerce')
    valid=qty.notna() & qty.ge(0) & qty.mod(1).eq(0) & out.Disposition.notna()
    out['DispositionValid']=valid
    for label in ['Pass','Rework','Scrap']:
        out['Classified'+label+'Qty']=qty.where(out.Disposition.eq(label),0).where(valid)
    out['DescriptionStatusConflict']=((explicit.eq('Pass')&status.eq('fail')) | (explicit.isin(['Rework','Scrap'])&status.eq('pass')))
    return out


def review(source=Path('QC data.xlsx'),output=Path('outputs/qc_review')):
    raw=pd.read_excel(source,dtype={'WO':str,'QualityOrderId':str,'ItemId':str})
    raw['SourceRow']=range(2,len(raw)+2)
    created=pd.to_datetime(raw.get('CreatedDateTime'),errors='coerce')
    july=created.dt.to_period('M').eq(pd.Period('2026-07'))
    raw['ExcludedJuly']=july
    raw=raw.loc[~july].copy()
    d=classify(raw)
    output.mkdir(parents=True,exist_ok=True)
    d.to_csv(output/'qc_ticket_dispositions.csv',index=False,encoding='utf-8-sig')
    keys=['WO','ItemId','RoundNo']
    # Round totals are authoritative when supplied by QC; ticket QCQty is only
    # a fallback because one round can contain multiple ticket/event rows.
    for col in ['RoundPassQty','RoundReworkFailQty','RoundScrapQty','RoundActualQty']:
        if col not in d: d[col]=pd.NA
    rounds=d.groupby(keys,dropna=False).agg(
        TicketCount=('QualityOrderId','size'),AllTicketsValid=('DispositionValid','all'),
        PassQty=('ClassifiedPassQty','sum'),ReworkQty=('ClassifiedReworkQty','sum'),
        ScrapQty=('ClassifiedScrapQty','sum'),RoundPassQty=('RoundPassQty','max'),
        RoundReworkFailQty=('RoundReworkFailQty','max'),RoundScrapQty=('RoundScrapQty','max'),
        RoundActualQty=('RoundActualQty','max'),QCFirstCreated=('CreatedDateTime','min'),
        QCLastCreated=('CreatedDateTime','max'),ExpectedVariants=('ExpectedInspectionQty','nunique'),
        ExpectedQty=('ExpectedInspectionQty','first')).reset_index()
    use_round=rounds.RoundActualQty.notna()
    rounds.loc[use_round,'PassQty']=rounds.loc[use_round,'RoundPassQty']
    rounds.loc[use_round,'ReworkQty']=rounds.loc[use_round,'RoundReworkFailQty']
    rounds.loc[use_round,'ScrapQty']=rounds.loc[use_round,'RoundScrapQty']
    rounds['ActualQty']=rounds[['PassQty','ReworkQty','ScrapQty']].sum(axis=1)
    rounds['QuantityReconciled']=rounds.ExpectedVariants.eq(1)&rounds.ActualQty.eq(rounds.ExpectedQty)&rounds.AllTicketsValid
    rounds.loc[~rounds.AllTicketsValid,['PassQty','ReworkQty','ScrapQty','ActualQty']]=float('nan')
    rounds.to_csv(output/'qc_round_dispositions.csv',index=False,encoding='utf-8-sig')
    stats={'source':str(source.resolve()),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
           'tickets':len(d),'july_rows_excluded':int(july.sum()),'descriptions':d.JDescription.fillna('(blank)').value_counts().to_dict(),
           'dispositions':d.Disposition.value_counts(dropna=False).to_dict(),
           'quantity':{x:float(d['Classified'+x+'Qty'].sum()) for x in ['Pass','Rework','Scrap']},
           'invalid_tickets':int((~d.DispositionValid).sum()),
           'duplicate_ticket_rows':int(d.QualityOrderId.duplicated(keep=False).sum()),
           'description_status_conflicts':int(d.DescriptionStatusConflict.sum()),
           'rounds':len(rounds),'rounds_not_reconciled':int((~rounds.QuantityReconciled).sum()),
           'validated_date_1900_or_missing':int((pd.to_datetime(d.ValidatedDateTime,errors='coerce').isna()|pd.to_datetime(d.ValidatedDateTime,errors='coerce').lt('2000-01-01')).sum()),
           'note':'Ticket quantities across rounds are inspection events, not unique final production quantities. No synthetic QC_Stop or time allocation.'}
    (output/'summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(stats,ensure_ascii=False,indent=2))


if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    review()
