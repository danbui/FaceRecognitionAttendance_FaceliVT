# 🧑‍💻 Hệ Thống Điểm Danh Bằng Khuôn Mặt (Edge Face Recognition Attendance)

Dự án phát triển hệ thống Kiosk điểm danh tự động bằng khuôn mặt, được thiết kế và tối ưu hóa đặc biệt để chạy trên các thiết bị nhúng (Edge Devices) như **Raspberry Pi 4 / 5** mà không cần GPU.

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![OpenCV](https://img.shields.io/badge/OpenCV-4.8%2B-green)
![ONNXRuntime](https://img.shields.io/badge/ONNXRuntime-CPU-orange)
![FastAPI](https://img.shields.io/badge/FastAPI-Web%2BAPI-009688)
![PyQt5](https://img.shields.io/badge/PyQt5-Kiosk%20UI-41CD52)

---

## 🌟 Các Tính Năng Nổi Bật

1. **AI Pipeline Siêu Nhẹ & Chính Xác:**
   - **Face Detection (YuNet):** Phát hiện khuôn mặt và 5 điểm landmarks thời gian thực với chi phí tính toán cực thấp.
   - **Face Recognition (FaceLiVT v2-xs):** Trích xuất đặc trưng khuôn mặt (512-dim). Mô hình này được tối ưu hóa đặc biệt cho đặc trưng khuôn mặt người Việt Nam/Châu Á, cho độ chính xác vượt trội hơn các mô hình phương Tây truyền thống.
   - **Best Frame Selector:** Tự động lọc và chỉ chọn khung hình có góc quay thẳng nhất (yaw/roll thấp) và ổn định nhất để đưa vào AI, giảm thiểu sai sót do ảnh nhòe.
   - **Thuật toán Matching KNN Top-5:** Sử dụng bầu chọn (voting) thay vì so sánh đơn thuần, giúp giảm thiểu tối đa hiện tượng nhận diện nhầm (False Positive).

2. **Chống Spam (State Machine Logic):**
   - Áp dụng State Machine quản lý luồng điểm danh (IN → OUT → IN).
   - Thiết lập thời gian chờ (Cooldown) giữa các lần quẹt thẻ trùng lặp, đảm bảo không có log rác trong cơ sở dữ liệu.

3. **Admin Web Dashboard (FastAPI):**
   - Quản lý danh sách nhân viên, xem nhật ký điểm danh theo thời gian thực.
   - Xóa nhân viên và dữ liệu nhận diện dễ dàng (tự động dọn dẹp file rác).
   - Xuất báo cáo điểm danh ra file CSV.

4. **Kiosk UI (PyQt5):**
   - Giao diện toàn màn hình chuyên dụng cho máy Kiosk.
   - Luồng camera và luồng AI được xử lý đa luồng (Multi-threading) độc lập, đảm bảo UI không bao giờ bị đơ lag.

---

## ⚙️ Cấu Trúc Thư Mục

```text
FaceRecognitionAttendance/
├── app/
│   ├── attendance_service.py # Logic điểm danh (State machine, IN/OUT)
│   ├── best_frame_selector.py# Tối ưu hóa khung hình đầu vào
│   ├── camera_service.py     # Xử lý luồng Camera
│   ├── config.py             # Cấu hình chung (Ngưỡng AI, Path, Secret)
│   ├── database.py           # Kết nối SQLite (Employees, Logs, Users)
│   ├── face_detector.py      # YuNet ONNX wrapper
│   ├── face_embedder.py      # FaceLiVT ONNX wrapper & ArcFace Alignment
│   ├── main_qt.py            # Giao diện Kiosk bằng PyQt5
│   ├── matcher.py            # KNN Matcher & RAM Caching
│   ├── web_api.py            # FastAPI Admin Backend
│   └── web_ui/               # Giao diện HTML/CSS cho Admin
├── benchmarks/               # Công cụ test & vẽ biểu đồ Bell Curves
├── models/                   # (Cần tải thêm) Thư mục chứa file .onnx
├── scripts/                  # Script hỗ trợ (Clear data...)
├── tests/                    # Bộ Test tự động (PyTest/Custom)
├── requirements.txt          # Thư viện Python cần thiết
└── run.py                    # File khởi động Kiosk
```

---

## 🚀 Hướng Dẫn Cài Đặt

### 1. Cài đặt thư viện Python
Yêu cầu Python 3.9 trở lên. Mở Terminal và chạy:

```bash
pip install -r requirements.txt
```

*(Lưu ý cho Raspberry Pi: Khuyến khích tạo môi trường ảo `python -m venv venv` trước khi cài đặt).*

### 2. Tải mô hình AI (ONNX)
Do kích thước file mô hình lớn, chúng đã được loại bỏ khỏi GitHub. Bạn cần tự tải 2 file sau và đặt vào thư mục `models/`:
1. `face_detection_yunet_2023mar.onnx`
2. `facelivtv2_s.onnx` (Hoặc phiên bản v2-xs tương ứng).

### 3. Khởi tạo Cơ sở dữ liệu và Web Admin
Chạy server FastAPI để quản lý dữ liệu:

```bash
uvicorn app.web_api:api --host 0.0.0.0 --port 8000
```
- Truy cập Dashboard: `http://localhost:8000`
- Tài khoản Admin mặc định: `admin` / `admin123`

### 4. Khởi động Kiosk UI
Để chạy giao diện điểm danh trên màn hình Camera:

```bash
python run.py
```

---


## 🍓 Deploy Raspberry Pi 4 (64-bit mới nhất)

Khuyến nghị dùng **Raspberry Pi OS 64-bit (Bookworm) bản mới nhất** và chạy script cài đặt:

```bash
git clone <repo-url>
cd FaceRecognitionAttendance_FaceliVT
bash scripts/setup_pi.sh
source venv_pi/bin/activate
```

### Sửa lỗi ONNX Runtime trên Pi 4

Nếu bạn gặp lỗi khi `import onnxruntime` (ví dụ: `Illegal instruction`, `No matching distribution found`, hoặc lỗi thiếu `libatomic`), làm đúng theo thứ tự sau:

```bash
# 1) Đảm bảo máy là OS 64-bit
uname -m
# Kết quả phải là: aarch64

# 2) Cài dependency hệ thống bắt buộc
sudo apt-get update
sudo apt-get install -y libatomic1 python3-venv python3-dev build-essential

# 3) Tạo venv và cài onnxruntime từ piwheels
python3 -m venv --system-site-packages venv_pi
source venv_pi/bin/activate
pip install --upgrade pip setuptools wheel
pip install --prefer-binary --extra-index-url https://www.piwheels.org/simple onnxruntime==1.18.1

# 4) Verify
python -c "import onnxruntime as ort; print(ort.__version__, ort.get_available_providers())"
```

Nếu bước (4) chạy OK, bạn có thể chạy app bình thường.

## 🛠 Tối Ưu Hóa Dành Cho Raspberry Pi

- Hệ thống hiện tại lưu trữ vector Face Embedding dưới dạng **BLOB trên SQLite** và load toàn bộ lên **RAM Matrix** ở lần khởi động đầu tiên. Việc chấm công hoàn toàn không đọc/ghi đĩa từ thẻ nhớ SD cho đến khi lưu log, giúp tăng tốc độ phản hồi < 0.5s.
- ONNXRuntime mặc định sử dụng CPU ARM. Để đạt hiệu năng tối đa, khuyến khích cài đặt bản ONNXRuntime hỗ trợ **XNNPACK**.

---
*Dự án Đồ án Hệ thống nhúng - Phát triển bởi @danbui.*