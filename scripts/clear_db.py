import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

db_files = [
    BASE_DIR / "attendance.db",
    BASE_DIR / "benchmark.db"
]

for db in db_files:
    if db.exists():
        try:
            os.remove(db)
            print(f"Đã xóa thành công: {db.name}")
        except Exception as e:
            print(f"Lỗi khi xóa {db.name} (Có thể file đang được mở bởi ứng dụng khác): {e}")
    else:
        print(f"File không tồn tại (đã sạch): {db.name}")

print("\nĐã dọn dẹp xong Database! Hệ thống sẽ tự động tạo lại DB mới tinh trong lần chạy tiếp theo.")
