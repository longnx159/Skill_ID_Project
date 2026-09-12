"""Portable Python Excel authoring for the requested reusable pipeline."""
from pathlib import Path
from math import ceil
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.utils import get_column_letter


def style_table(sheet, rows, columns, number=1):
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "C2"
    for cell in sheet[1]:
        cell.font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="254665")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    sheet.row_dimensions[1].height = 42
    for c in range(1, columns+1):
        values = [str(sheet.cell(r,c).value or "") for r in range(1,min(rows,100)+1)]
        sheet.column_dimensions[get_column_letter(c)].width = min(max(max(map(len, values),default=12)+2,16),42)
    if rows>1:
        table = Table(displayName=f"SkillTable{number}",ref=f"A1:{get_column_letter(columns)}{rows}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2",showRowStripes=True)
        sheet.add_table(table)


def write_result_workbook(path, tables):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for index,(name,frame) in enumerate(tables.items(),1):
        sheet = workbook.create_sheet(name[:31])
        if not len(frame.columns):
            frame = pd.DataFrame({"Status":["No records"]})
        sheet.append(list(frame.columns))
        for row in frame.itertuples(index=False,name=None):
            safe=[]
            for value in row:
                if pd.isna(value):
                    value=None
                elif isinstance(value,pd.Timestamp):
                    value=value.to_pydatetime()
                elif hasattr(value,"item"):
                    value=value.item()
                if isinstance(value,str) and value.startswith(("=","+","-","@")):
                    value="'"+value
                safe.append(value)
            sheet.append(safe)
        style_table(sheet,sheet.max_row,sheet.max_column,index)
        for row in sheet.iter_rows(min_row=2):
            line_count=1
            for cell in row:
                cell.font=Font(name="Arial",size=11)
                cell.alignment=Alignment(wrap_text=True,vertical="center")
                width=sheet.column_dimensions[cell.column_letter].width
                line_count=max(line_count,ceil(len(str(cell.value or ""))/max(width-2,1)))
                if isinstance(cell.value,float):
                    cell.number_format="0.000"
            sheet.row_dimensions[row[0].row].height=max(18,min(line_count*16,96))
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    workbook.save(path)
