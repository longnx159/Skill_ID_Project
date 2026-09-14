# Production

Đặt các file dữ liệu sản xuất vào đây. Có thể chia theo tháng. Bắt buộc: `Reference`, `Worker`, `Item Number`, `Process`, `Qty Doing`, `Total Actual Hours`, `RAF Month`. Giữ `RoundNo` bắt buộc khi dữ liệu có nhiều vòng làm hoặc sửa; khóa dữ liệu là `Reference + Worker + Item Number + RAF Month + RoundNo`. Nếu có, giữ `Item Number (Size Adjusted)` trong file. Với MES `ProductionData.xlsx`, pipeline tự đọc hai sheet và giữ RoundNo của `GSWorkerWorkingHours`.
