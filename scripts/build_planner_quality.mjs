import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const out = path.resolve(process.argv[2]);
const data = JSON.parse(await fs.readFile(path.join(out,'planner_primary_data.json'),'utf8'));
const wb = Workbook.create();
const definitions = [
 ['Quality','Planner primary Quality',['Process','SizeAdjustedGroup','Quality','PlannerQuality','OldRaschQuality','PlannerModelWeight','OldRaschModelWeight','FirstPassWeight','ReworkWeight','BlendStatus','FirstPassDifficulty','ReworkDifficulty','OldRaschFirstPass','OldRaschRework','PlannerQualityLower95','PlannerQualityUpper95','QualityLower95Conditional','QualityUpper95Conditional','FirstPassTrainingWOs','ReworkTrainingWOs','FirstPassConverged','ReworkConverged','FirstPassValidationStatus','ReworkValidationStatus','WeightReason','BlendIntervalStatus']],
 ['Worker effects','Planner primary workers',['Worker','Process','Branch','Planner Verified Skill Level','PlannerSkillStatus','WorkerResidual','WorkerResidualLower95','WorkerResidualUpper95','WOsUsed','Converged','ModelStatus']],
 ['Actual worker anchors','Actual worker anchors',['Process','SizeAdjustedGroup','Branch','Worker','Planner Verified Skill Level','WOsUsed','QCPieces','PredictedPassProbabilityAtTypicalWO','AnchorStatus']],
 ['Model comparison','Model comparison',['Process','Branch','Model','Converged','piece_log_loss','ValidationLoss','Beta','BetaLower95','BetaUpper95','RhatMax','ESSMin','Divergences','Comparison_lower_95','Comparison_upper_95']],
 ['Statistical acceptance','Statistical acceptance',['Process','Branch','SelectedCandidate','Decision','Reason','TestWOs','Convergence','Improvement','Calibration','RankStability','Network','BeforeAfterEvidence']],
];
for (const [name] of definitions) wb.worksheets.add(name);
const note = wb.worksheets.add('Read me');
const notes = [
 ['Topic','Definition'],
 ['Primary score','80% Planner-anchored Rasch + 20% old Rasch. Missing Planner component uses 100% old Rasch.'],
 ['Branch weights','Each model uses 80% first pass + 20% rework. No usable attributable rework observations: 100% first pass.'],
 ['Actual-worker anchors','Planner scores of production workers in the correct WO-round anchor the model. QC inspectors are not production workers.'],
 ['Official Planner skill','Raw verified 0-10 score. It is never replaced by a fitted worker residual or predicted pass probability.'],
 ['Score interpretation',data.score_definition],
 ['Provisional results','User-selected blended scores retain nonconvergence and validation flags. This blend has not been independently holdout-validated.'],
 ['Intervals','Planner intervals are model-dependent credible intervals. Blended bounds hold old Rasch fixed and do not include its uncertainty.'],
 ['Training scope','Planner effect estimates use the training split. Test WOs remain excluded from fitting. Existing Rasch output uses its recorded full eligible cohort.'],
 ['Multiple-worker QC','Retained in the full run audit. No shared QC outcome is split into individual outcomes.'],
 ['Run',data.run_id],
 ...data.planner_hashes.map(s=>['Planner SHA-256',s.sha256]),
];
note.getRangeByIndexes(0,0,notes.length,2).values=notes;
note.getRangeByIndexes(0,0,notes.length,2).format.font={name:'Arial',size:11};
note.getRange('A:A').format.columnWidth=25;
note.getRange('B:B').format.columnWidth=105;
note.getRangeByIndexes(0,0,notes.length,2).format.wrapText=true;
note.getRangeByIndexes(1,0,notes.length-1,2).format.rowHeight=42;
note.getRange('A1:B1').format={fill:'#243C55',font:{name:'Arial',bold:true,color:'#FFFFFF'}};
note.showGridLines=false;
for(const [name,key,columns] of definitions){
 const sh=wb.worksheets.getItem(name);
 const records=data.tables[key];
 sh.showGridLines=false;
 sh.getRange('A1').values=[[name==='Quality'?'Semi quality: Planner 80% + Rasch 20%':name]];
 sh.getRange('A1').format.font={name:'Arial',size:15,bold:true};
 sh.getRange('A2').values=[[name==='Quality'?'Missing Planner estimate: 100% Rasch. Provisional scores retain their statistical status.':'Source: frozen governed run '+data.run_id]];
 sh.getRange('A2').format.font={name:'Arial',size:10,color:'#555555'};
 const matrix=[columns,...records.map(r=>columns.map(c=>r[c]??null))];
 sh.getRangeByIndexes(3,0,matrix.length,columns.length).values=matrix;
 const range=sh.getRangeByIndexes(3,0,matrix.length,columns.length);
 range.format.font={name:'Arial',size:11};
 range.format.rowHeight=22;
 range.format.columnWidth=18;
 range.setNumberFormat('0.000');
 sh.getRangeByIndexes(3,0,1,columns.length).format={fill:'#243C55',font:{name:'Arial',bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:60};
 sh.freezePanes.freezeRows(4);
 sh.freezePanes.freezeColumns(2);
 sh.tables.add(sh.getRangeByIndexes(3,0,matrix.length,columns.length),true,name.replace(/\W/g,'')+'Table');
 columns.forEach((c,i)=>{
   const r=sh.getRangeByIndexes(4,i,Math.max(records.length,1),1);
   if(c.includes('Weight')&&!c.includes('Reason')) r.setNumberFormat('0%');
   if(/WOs|QCPieces|Divergences|ESSMin/.test(c))r.setNumberFormat('#,##0');
   if(/Probability/.test(c))r.setNumberFormat('0.0%');
   if(/Status|Reason|Model|Decision|SizeAdjustedGroup/.test(c))sh.getRangeByIndexes(3,i,matrix.length,1).format.columnWidth=36;
 });
 if(name==='Quality'){
   sh.getRangeByIndexes(4,2,records.length,1).formulas=records.map((r,i)=>{
     const n=i+5;
     return [`=IF(E${n}="","",IF(D${n}="",E${n},F${n}*D${n}+G${n}*E${n}))`];
   });
 }
 const preview=await wb.render({sheetName:name,range:'A1:H12',scale:1.4,format:'png'});
 await fs.writeFile(path.join(out,name.replace(/\W/g,'_')+'_preview.png'),new Uint8Array(await preview.arrayBuffer()));
}
const preview=await wb.render({sheetName:'Read me',range:'A1:B12',scale:1.4,format:'png'});
await fs.writeFile(path.join(out,'Read_me_preview.png'),new Uint8Array(await preview.arrayBuffer()));
console.log((await wb.inspect({kind:'table',range:'Quality!A4:J10',include:'values,formulas',tableMaxRows:7,tableMaxCols:10,maxChars:2500})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!',options:{useRegex:true,maxResults:20},maxChars:1000})).ndjson);
const file=await SpreadsheetFile.exportXlsx(wb);
await file.save(path.join(out,'Planner_Rasch_Quality.xlsx'));
console.log('Workbook saved');
