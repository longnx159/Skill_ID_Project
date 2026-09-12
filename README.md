# Skill ID data template and Python pipeline

For a separate read-only BOM feature audit, put exports in `Bom Table/` and run
`python -B -m pipeline.bom_features --input-dir "Bom Table" --output "outputs/bom_review"`.
This writes part counts, stone counts/types, weighted average and maximum stone
weights, percentage denominator scenarios, and source-path evidence to CSV.
See `outputs/bom_review/README.md` for definitions and data-quality limitations.
It does not publish or overwrite Complexity model scores.

This project implements the usable data and diagnostic stages of the local **v0.5.3 specification**. It uses one folder-based input area only, a repeatable Python pipeline, canonical result sheets, source hashes, saved time-model parameters, and automated business-rule tests.

**Current status: diagnostic / pilot preparation.** Final Technical Complexity and automated matching are deliberately unpublished. The missing operational inputs and business validation gates are listed in each result workbook. Filling a template does not itself approve a production model.

## 1. Install once

Python 3.11 or newer is recommended. In PowerShell, from this project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The core run needs only pandas, NumPy and openpyxl. Existing optional legacy chart/model dependencies remain separate.

## 2. Fill the input folders

Use [input_data](input_data/) as the only data entry area. Each subfolder contains a blank single-sheet `_template.xlsx` with the correct columns. Open that file and enter rows from row 2. For monthly or incremental data, add another `.xlsx`, `.xls` or `.csv` file to the same subfolder. The pipeline combines all files in that subfolder.

The older workbook is preserved under `archive/source_files/` as a reference only. The public pipeline does not read archived files.

| Folder | Purpose | Needed for |
| --- | --- | --- |
| Production | Worker allocation on WO, final OK quantity, recorded hours, fiscal month | Minimum time-model run |
| Planner Skills | One current Worker–Process skill snapshot, plus effective date and lineage | Minimum run; dated values required for QC models |
| Item Mapping | Exact original Item to Size Adjusted group and Process | Use this, or the mapping columns in Production |
| QC Tickets | One transaction per QualityOrderId, authoritative round, Pass/Fail pieces and inspection timestamps | FPY, recovery and QC candidate models |
| Touch Events | Actual Worker Start/Stop labor intervals | First-pass/rework reconstruction and rescue classification |
| Engineering Factors | Five factor scores with evidence and approvals | Factor completeness review |
| Pilot Log | Prospective control/intervention assignment and override records | Collection only; future pilot analysis |

Keep identifiers as text, including leading zeroes. Use real Excel dates/times in **Asia/Saigon**. Do not put `0` or `N/A` into missing numeric fields. Save and close each workbook before running.

`Qty Doing` is retained for compatibility with the historical source: it means **final OK quantity allocated to the worker**, including fractional quantities. `Total Actual Hours` means recorded worker hours, including historical rework. The derived measure is `60 × Total Actual Hours / Qty Doing`, in **minutes per final OK**. It is not clean first-pass cycle time.

QC quantities must be whole pieces. `QCQty` is the transaction quantity, while `ExpectedQty` is the expected inspected quantity for that round. Enter the same expected total on all tickets in the round; the pipeline checks this field without summing it. Include July tickets when the WO continues into August: a WO with any July 2026 QC is excluded in full.

`InitialWorker` is the explicitly identified original producer. Never put a repair/rescue worker there. Ambiguous initial ownership does not receive an invented allocation of first-pass failures.

Excel data validation is an entry aid. Python performs the authoritative validation. Blank optional folders remain unavailable.

## 2A. Nhập dần theo từng thư mục

Để đưa dữ liệu vào dần, dùng thư mục [input_data](input_data/). Đây là một thư mục gốc duy nhất, có bảy thư mục con tương ứng với từng loại dữ liệu. Đặt một hoặc nhiều file `.xlsx`, `.xls` hoặc `.csv` vào đúng thư mục. Pipeline sẽ đọc tất cả file trong thư mục và nối chúng theo dòng, vì vậy bạn có thể thêm `production_2026_09.xlsx` sau khi đã có `production_2026_08.xlsx`.

```text
input_data/
  01_Production/
  02_Planner_Skills/
  03_Item_Mapping/
  04_QC_Tickets/
  05_Touch_Events/
  06_Engineering_Factors/
  07_Pilot_Log/
```

Tên cột phải giống template. File bắt đầu bằng `~$` được bỏ qua. Mỗi file được ghi vào `SourceFile` trong output để truy vết. Nếu dùng cách thư mục, chạy:

```powershell
python -m pipeline.main --input-dir "input_data" --output "outputs/run_next"
```

Có thể để trống các thư mục chưa có dữ liệu. Chỉ `01_Production` và `02_Planner_Skills` là cần cho lần chạy tối thiểu. Pipeline chỉ đọc `input_data` và không tự trộn các file cũ ở thư mục project. Điều này giúp bạn biết chính xác lần chạy đang dùng những file nào.

### Touch Events là gì?

`Touch Events` là nhật ký các khoảng thời gian một worker thực sự chạm vào và làm trên một WO trong một Process. Mỗi dòng là một phiên làm việc có `Worker_Start` và `Worker_Stop`, không phải trạng thái của WO và cũng không phải thời gian từ lúc tạo WO đến lúc hoàn thành.

Ví dụ: QC kết thúc lúc 15:00 ngày 1, worker bắt đầu sửa lúc 09:00 ngày 2 và kết thúc lúc 09:20. Touch Event chỉ ghi 20 phút làm việc. Khoảng chờ qua đêm 18 giờ không được tính. Nếu worker B cứu hàng cho WO của worker A, tạo event của worker B với đúng worker B và process thực tế.

Các cột chính là `WO`, `Worker`, `Process`, `Worker_Start`, `Worker_Stop`. `EventID` nên là mã giao dịch MES duy nhất. `HandedFailQty` và `RecoveredQty` chỉ điền khi hệ thống ghi nhận trực tiếp, không tự suy ra từ tổng lỗi QC.

Pipeline dùng QC Start/Stop làm ranh giới: event kết thúc trước QC vòng 1 là `FirstPass`; event nằm giữa QC vòng r và vòng r+1, cùng Process với QC, là `Rework`. Process khác được giữ là `OtherProcess`, không tính là rework. Nếu worker sửa chính WO của mình, event được gắn `SelfRework`; nếu worker khác tiếp nhận, gắn `AssistedRescue`. Event có stop trước start, chồng thời gian, thiếu worker hoặc thiếu QC boundary đi vào trạng thái lỗi để kiểm tra.

Nếu chưa có Start/Stop thực tế, để trống `05_Touch_Events`. Đừng dùng `Total Actual Hours` để giả lập Touch Events, vì trường đó là tổng thời gian lịch sử và có thể đã bao gồm rework.

## 3. Run future updates

```powershell
.\.venv\Scripts\python.exe -m pipeline.main --input-dir "input_data" --output "outputs/run_next"
```

Or use the PowerShell wrapper, which creates a dated output directory by default:

```powershell
.\run_pipeline.ps1 -InputDir "input_data"
```

Use an explicit timestamp to freeze an as-of run, or explicitly exclude an incomplete month:

```powershell
.\.venv\Scripts\python.exe -m pipeline.main --input-dir "input_data" --cutoff "2026-09-30T23:59:59" --exclude-month "2026-09" --output "outputs/run_202609"
```

All production months are retained by default. A cutoff expressed as a date alone means midnight at the start of that date; use the end-of-day timestamp when appropriate. Historical `RAF Month` has monthly resolution only, so it cannot prove daily availability within that month.

## 4. Results

Each output directory contains:

- **Skill_ID_Ket_qua_chay_thu.xlsx**: canonical `Do kho SKU`, worker capability, validation, connectivity, QC/recovery views, exceptions and go-live gates.
- CSV copies of result tables for Power BI or review.
- **run_manifest.json**: input paths, SHA-256 hashes, configuration, cutoff, model version and limitations.
- **time_models.json**: process-specific aggregate time-model intercepts, worker/group effects and smearing correction.

Use a new output folder for each run to retain history. Running again in the same output folder replaces the generated results. Input workbooks are never edited.

The core time model uses a random-worker / fixed-group diagnostic, with source Size Adjusted pooling. Original Item IDs remain in the canonical output. It computes network diagnostics before fitting, flags weak components, retains official Planner scores unchanged, and evaluates real WOs chronologically. DUMMY/unlinked references remain time-model diagnostics but cannot establish WO-level validation. WOs spanning the validation cutoff are embargoed. Test predictions use train-fitted effects and a train-only smearing correction; unseen workers/groups are counted.

The historical estimator's approximate worker intervals are conditional diagnostics, not validated skill-certification confidence. Nonconvergence is explicitly reported. No time effect is relabeled as quality difficulty or an official 0–10 worker skill.

## 5. Optional Bayesian QC candidate comparison

After collecting real QC and dated Planner skills:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-full.txt
.\.venv\Scripts\python.exe -m pipeline.quality_candidates --input-dir "input_data" --output "outputs/quality_candidates"
```

This optional research stage compares the specification's **Beta-Binomial** and **Binomial with WO random effect** candidates separately, each with observed-skill or hierarchical missing-skill handling. It fits process-specific worker/group effects after connectivity diagnostics, centers skill at 5 using training-only SD, freezes training effects for predictions, and reports a common observed-skill chronological test cohort. A separate group-held-out design runs when evidence permits. Unseen entities receive predictive random-effect draws. Processes below 60% observed training skill coverage remain exploratory.

It saves posterior arrays, training WO identities, the training scale, predictions, log-loss/Brier summaries, R-hat and divergence diagnostics. It does **not** automatically select a winner, certify interval coverage, or publish calibrated item difficulty. Prior sensitivity, paired comparison uncertainty/parsimony rules, calibration bands, size residual bootstrap, empirical coverage, recovery-weight calibration and business approvals remain review work. Candidate samplers were **not run in this delivery** because real QC inputs and PyMC are unavailable. The pure-Python scale, as-of feature and frozen-prediction controls are tested.

Reference for the likelihood parameterization: [PyMC BetaBinomial documentation](https://www.pymc.io/projects/docs/en/latest/api/distributions/generated/pymc.BetaBinomial.html).

## 6. Implemented gates and remaining scope

| Area | Implemented behavior | Remaining before production |
| --- | --- | --- |
| Mapping and joins | Exact mappings, uniqueness, no prefix inference, many-to-one join validation | Engineering sign-off and size residual screening |
| Planner skill | Raw 0–10 preserved; duplicate keys rejected; candidate model rejects future/undated skill as an observed feature | Effective-dated history with multiple snapshots and full approval workflow |
| Time | Aggregate effort diagnostics, chronological validation, explicit units | Clean-time estimator and approved WAPE threshold |
| QC | July whole-WO exclusion, unique tickets, first-round denominator and round reconciliation | Validate source-specific QC adapter against actual transactions |
| Recovery | Zero failures → missing; observed decay weights; open WO diagnostics and sensitivity; no Scrap=0 | Approved terminal status/maturity policy and calibrated recovery usability/weights |
| Touch | Actual labor intervals, QC boundaries, Process guard, SelfRework/AssistedRescue | Empirical coverage/reconciliation; capacity and rescue-success quantity attribution |
| Quality model | Optional candidate implementation, train-only scaling and effects | Run candidates on actual QC, calibration, coverage, confounding and sensitivity validation |
| Complexity | Strict five-factor weights and evidence checks; approved sum may be shown diagnostically | Quality validation and all production approval gates; final complexity stays blank |
| Matching | Canonical view explains missing prerequisites | Reviewed probability/ranking engine, certification/capacity inputs, Planner overrides and prospective validation |
| Scrap | Explicit unavailable status; missing quantities stay missing | Actual MES scrap/disposition collection and approved loss model |

Open trajectories stay visible and are excluded from the closed-trajectory recovery score. There is no inferred closure after 14 days and no assumed scrap. Unresolved pieces remain open unless an authoritative closure policy is later integrated. The core run emits raw FPY fallback only; it does not claim a calibrated Rasch score.

## 7. Recreate template / run tests

```powershell
.\.venv\Scripts\python.exe -m pipeline.create_folder_templates --input-dir "input_data"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The template generator refuses to overwrite an existing workbook. Tests contain synthetic fixtures only and clean up their temporary artifacts after each run.

The previous entry point is preserved under `archive/legacy_code/` for reference only. Old result folders and source workbooks are under `archive/` and do not override the v0.5.3 outputs.
