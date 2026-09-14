# Skill ID data drop folder

Đây là một thư mục nhập dữ liệu duy nhất. Bạn có thể đưa dữ liệu vào từng thư mục con theo từng đợt hoặc từng tháng. Pipeline sẽ đọc và nối tất cả file `.xlsx`, `.xls` và `.csv` trong mỗi thư mục.

Mỗi thư mục có một file `_template.xlsx` để mở và điền trực tiếp. Giữ dòng tiêu đề ở dòng 1 đúng theo file mẫu. Có thể dùng mỗi file một tháng. Không đưa file lock bắt đầu bằng `~$` vào xử lý. `02_Planner_Skills` nên chỉ chứa một snapshot hiện hành cho mỗi Worker + Process; nhiều snapshot lịch sử cần tách theo từng lần chạy cho đến khi effective-date workflow được triển khai đầy đủ.

| Thư mục | Dữ liệu | Khi chưa có dữ liệu |
| --- | --- | --- |
| `01_Production` | Production / dữ liệu sản xuất | Bắt buộc cho lần chạy tối thiểu |
| `02_Planner_Skills` | Planner Skills | Bắt buộc cho lần chạy tối thiểu |
| `09_Item_Master` | Item Master & Mapping (Process, Group, Material, Type) | Tự động suy luận từ mã nếu chưa có |
| `04_QC_Tickets` | Ticket QC và các vòng kiểm | Không có thì FPY và Recovery để trống |
| `05_Touch_Events` | Worker Start/Stop | Không bắt buộc; để trống nếu chưa có scan touch time |
| `06_Engineering_Factors` | Năm yếu tố kỹ thuật | Không có thì Final Technical Complexity để trống |
| `07_Pilot_Log` | Nhật ký pilot | Không bắt buộc; để trống trước khi chạy pilot thực nghiệm |

Ví dụ tên file: `production_2026_08.xlsx`, `planner_snapshot_2026_08.xlsx`, `qc_2026_08.csv`. Có thể thêm file mới vào đúng thư mục mà không cần gộp các file cũ.

Chạy từ thư mục project:

```powershell
python -m pipeline.main --input-dir "input_data" --output "outputs/run_next"
```

Hoặc:

```powershell
.\run_pipeline.ps1 -InputDir "input_data"
```

Không cần ghép các sheet thành một workbook. Chỉ đặt dữ liệu vào đúng thư mục con rồi chạy pipeline.

## Thứ tự đẩy dữ liệu

1. Đẩy `Production` và `Planner Skills` để chạy chẩn đoán năng lực thợ.
2. Đẩy `Item Master` để quản lý quy trình (Process), nhóm quy cách (Size Adjusted Group) và thuộc tính sản phẩm.
3. Đẩy `QC Tickets` khi có dữ liệu QC. Pipeline sẽ loại cả WO nếu WO có ticket QC trong tháng 07/2026 theo quy định hiện tại.
4. Đẩy `Touch Events` khi MES có Worker Start/Stop và QC boundaries.
5. Đẩy `Engineering Factors` và `Pilot Log` sau khi có người duyệt.

Dữ liệu thiếu không được biến thành số 0. Đặc biệt không nhập `ScrapQty = 0` khi Scrap chưa được ghi nhận.
