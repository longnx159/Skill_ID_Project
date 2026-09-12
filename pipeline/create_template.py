"""Generate the blank, reusable v0.5.3 Skill ID data collection workbook."""
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.comments import Comment
from openpyxl.utils import get_column_letter
from .workbook_io import style_table

SCHEMAS = {
    "Production": [
        ("Reference","Required for real WO validation. DUMMY rows are diagnostic only."),
        ("Worker","Required Worker ID as text, matching Planner Skills."),
        ("Item Number","Required exact original Item ID as text."),
        ("Qty Doing","Required positive final OK output allocated to worker. Fractional quantities are valid. Enter one row per worker and production round/check round."),
        ("Total Actual Hours","Required positive actual worker hours for this production round/check round. Do not include queue or overnight waiting time." )],
    "Planner Skills": [
        ("Worker ID","Required. One row per Worker + Process for this snapshot."),
        ("Process","Required exact Process."),
        ("Planner Verified Skill Level","Required number 0-10. Official Planner value is never min-max rescaled."),
        ("EffectiveFrom","Collect effective date for future as-of use. Current pipeline uses a snapshot only."),
        ("Approver","Planner approval lineage. Blanks block go-live."),
        ("Version","Approved skill snapshot version."),
        ("Name","Optional display name.")],
    "Item Mapping": [
        ("Item Number","Required original Item ID. One row per Item."),
        ("Item Number (Size Adjusted)","Reviewed group. Blank means original Item fallback; never derive from a prefix."),
        ("Process","Required exact Process. Every group must map to one Process."),
        ("MappingVersion","Engineering reviewed mapping version."),
        ("Approver","Engineering mapping approver.")],
    "QC Tickets": [
        ("QualityOrderId","Required globally unique QC transaction ID."),
        ("WO","Required exact production Reference."),
        ("Item Number","Required original Item. Must be unique within WO."),
        ("RoundNo","Required positive integer from authoritative QC round sequence. No inferred rounds."),
        ("QCStatus","Required Pass or Fail."),
        ("QCQty","Required nonnegative integer ticket piece count; not cumulative."),
        ("ExpectedQty","Required positive integer expected inspected pieces for this round. Repeated value is checked, never summed."),
        ("QC_Start","Required Excel date-time, local factory time (Asia/Saigon)."),
        ("QC_Stop","Required Excel date-time; must be >= QC_Start."),
        ("InitialWorker","Explicit original first-pass worker only. Never enter a rescuing worker here."),
        ("Process","Optional cross-check. Exact Item Mapping is authoritative.")],
    "Touch Events": [
        ("WO","Required exact WO. QC boundaries must exist."),
        ("Worker","Required active worker ID."),
        ("Process","Required actual process for this labor event."),
        ("Worker_Start","Required active labor start date-time; exclude queue/overnight time."),
        ("Worker_Stop","Required active labor stop date-time; must be >= start."),
        ("EventID","Collect unique MES touch transaction ID."),
        ("HandedFailQty","Actual assigned defective quantity. Not inferred from total WO failures. Collection only."),
        ("RecoveredQty","Explicit recovered quantity attributable to this repair assignment. Collection only.")],
    "Engineering Factors": [
        ("Item Number","Required original Item ID."),
        ("Process","Required exact Process."),
        ("Factor","Exactly Quality, PartMechanism, MaterialDesignProcess, Stone, Learning. One each per Item/Process."),
        ("Score","Number 0-10. Missing remains blank. Stone=0 requires evidence of no stone."),
        ("Evidence","Required source/specification or reviewed evidence reference."),
        ("Scorer","Required reviewer who assigned the factor score."),
        ("Approver","Required approving authority."),
        ("Version","Required rubric/BOM/model version."),
        ("Approved","TRUE only when actually approved. Blank/FALSE is unapproved."),
        ("DataQualityStatus","Valid only when the evidence passes data-quality checks.")],
    "Pilot Log": [
        ("WO","Prospective pilot WO; collected for future matching validation."),
        ("Process","Exact Process."),
        ("Arm","Control or Intervention; ITT primary analysis."),
        ("AssignedWorker","Actual Planner-selected worker."),
        ("RecommendationVersion","Version of the recommendation shown."),
        ("FollowedTop3","TRUE/FALSE; PP secondary analysis only."),
        ("OverrideReason","Required when Planner overrides Top 3."),
        ("AssignmentTime","Actual decision time. No automatic assignment.")],
    "Reference Master": [
        ("Reference","Required unique production/WO reference."),
        ("RAF Month","Required Excel date, normally the first day of the fiscal month."),
        ("Customer Name","Customer master value; use Training only when it is genuinely training data."),
        ("Product Type","Product master value for the reference.")],
    "Item Master": [
        ("Item Number","Required exact original Item ID as text."),
        ("Item Number (Size Adjusted)","Reviewed size-adjusted group; blank means original Item fallback only after review."),
        ("Process","Required exact production Process; no prefix inference."),
        ("Material","Material master value for the Item.")],
    "Worker Master": [
        ("Worker","Required unique Worker ID as text."),
        ("Name","Worker master display name.")],
}


def create_template(path=Path("Mau_nhap_du_lieu_Skill_ID.xlsx")):
    if Path(path).exists():
        raise FileExistsError(f"Refusing to overwrite {path}. Choose another --output path.")
    wb=Workbook()
    intro=wb.active
    intro.title="Start Here"
    notes=[
        ["Skill ID input template", "v0.5.3-pilot.1"],
        ["Start", "Save a copy before entering data. Keep sheet names and row-1 column names unchanged."],
        ["Minimum run", "Fill Production and Planner Skills. Add exact Item Mapping, or use the mapping columns in Production."],
        ["Quality and recovery", "Fill QC Tickets. Enter all relevant WO tickets, including July tickets needed for whole-WO exclusion."],
        ["Touch time", "Fill Touch Events with actual labor intervals. Queue time is never worker touch time."],
        ["Blank values", "Do not put 0 or N/A into missing numeric cells. Scrap tracking is unavailable; do not assume ScrapQty=0."],
        ["Identifiers", "Keep Worker, WO and Item identifiers as text, including leading zeroes."],
        ["Dates", "Use real Excel dates/times in Asia/Saigon. Format yyyy-mm-dd hh:mm:ss."],
        ["Units", "Qty Doing=final OK pieces allocated to worker; Total Actual Hours=recorded worker hours including rework."],
        ["Version rule", "Use one current Planner snapshot per run. Historical effective-date scoring is not yet validated."],
        ["Run", 'python -m pipeline.main --input-dir "input_data" --output "outputs/run_next"'],
        ["Results", "Skill_ID_Ket_qua_chay_thu.xlsx, CSV tables, time_models.json and run_manifest.json."],
        ["Publication", "Outputs are diagnostic. Final complexity and automated matching remain blank until required validation gates pass."],
        ["Pilot Log", "Collection only; prospective power and ITT/PP analysis require an approved pilot design."],
        ["Rows", "Enter data from row 2. Add rows as needed; the Python reader reads all populated rows."],
        ["Checks", "Excel validation helps entry. Python rechecks keys, quantities, timing, mappings and joins."],
    ]
    for row in notes: intro.append(row)
    intro.column_dimensions["A"].width=25
    intro.column_dimensions["B"].width=110
    intro.sheet_view.showGridLines=False
    for row in intro:
        for cell in row:
            cell.font=Font(name="Arial",size=11,bold=cell.column==1)
            cell.alignment=Alignment(wrap_text=True,vertical="center")
        intro.row_dimensions[row[0].row].height=34
    dictionary=wb.create_sheet("Data Dictionary")
    dictionary.append(["Sheet","Column","Definition / Entry Rule"])
    for idx,(name, fields) in enumerate(SCHEMAS.items(),1):
        ws=wb.create_sheet(name)
        ws.append([c for c,_ in fields])
        style_table(ws,1,len(fields),idx)
        for column,(header,definition) in enumerate(fields,1):
            letter=get_column_letter(column)
            ws.cell(1,column).comment=Comment(definition,"Skill ID")
            dictionary.append([name,header,definition])
            ws.column_dimensions[letter].width=min(max(len(header)+3,21),35)
            is_date=header in ["RAF Month","QC_Start","QC_Stop","Worker_Start","Worker_Stop","EffectiveFrom","AssignmentTime"]
            is_number=header in ["Qty Doing","Total Actual Hours","QCQty","ExpectedQty","RoundNo","Score","Planner Verified Skill Level","HandedFailQty","RecoveredQty"]
            for row in range(2,102):
                cell=ws.cell(row,column)
                cell.font=Font(name="Arial",size=11)
                cell.number_format="yyyy-mm-dd hh:mm:ss" if is_date else ("0.000" if is_number else "@")
            options=None
            if header=="QCStatus": options='"Pass,Fail"'
            elif header=="Factor": options='"Quality,PartMechanism,MaterialDesignProcess,Stone,Learning"'
            elif header in ["Approved","FollowedTop3"]: options='"TRUE,FALSE"'
            elif header=="Arm": options='"Control,Intervention"'
            elif header=="DataQualityStatus": options='"Valid,Pending,Exception"'
            validation=None
            if options:
                validation=DataValidation(type="list",formula1=options,allow_blank=True)
            elif header in ["Score","Planner Verified Skill Level"]:
                validation=DataValidation(type="decimal",operator="between",formula1=0,formula2=10,allow_blank=True)
            elif header in ["RoundNo","QCQty","ExpectedQty"]:
                validation=DataValidation(type="whole",operator="greaterThanOrEqual",formula1=0 if header=="QCQty" else 1,allow_blank=True)
            elif is_number:
                validation=DataValidation(type="decimal",operator="greaterThanOrEqual",formula1=0,allow_blank=True)
            if validation:
                validation.showErrorMessage=True
                validation.errorTitle="Invalid entry"
                validation.error="Check the Data Dictionary for allowed values."
                ws.add_data_validation(validation)
                validation.add(f"{letter}2:{letter}1048576")
        ws.auto_filter.ref=f"A1:{get_column_letter(len(fields))}101"
    style_table(dictionary,dictionary.max_row,3,99)
    dictionary.column_dimensions["C"].width=105
    for row in dictionary.iter_rows(min_row=2):
        row[2].alignment=Alignment(wrap_text=True)
        dictionary.row_dimensions[row[0].row].height=32
    wb.save(path)
    print(f"Created {Path(path).resolve()}")


if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,default=Path("Mau_nhap_du_lieu_Skill_ID.xlsx"))
    create_template(p.parse_args().output)
