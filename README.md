# 🧑‍💻 Hệ Thống Điểm Danh Bằng Nhận Diện Khuôn Mặt Trên Thiết Bị Nhúng

Dự án xây dựng hệ thống Kiosk điểm danh tự động bằng khuôn mặt, tối ưu hóa để chạy trên **Raspberry Pi 4/5** (ARM, CPU only, không cần GPU).

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![OpenCV](https://img.shields.io/badge/OpenCV-4.6%2B-green)
![ONNXRuntime](https://img.shields.io/badge/ONNXRuntime-CPU-orange)
![FastAPI](https://img.shields.io/badge/FastAPI-Web%20Dashboard-009688)
![SQLite](https://img.shields.io/badge/SQLite-Database-003B57)

---

## 🌟 Tính Năng Chính

### 1. AI Pipeline Siêu Nhẹ & Dual-Backend

| Thành phần | Model | Kích thước | Output | Vai trò |
|-----------|-------|------------|--------|---------|
| **Face Detection** | YuNet (OpenCV DNN) | 240 KB | BBox + 5 Landmarks | Phát hiện khuôn mặt real-time |
| **Face Recognition** | FaceLiVT v2-xs (ONNX Runtime) | 17 MB | 512-dim embedding | Nhận diện chính (ưu tiên) |
| **Face Recognition** | SFace (OpenCV native) | 37 MB | 128-dim embedding | Fallback khi không có ONNX Runtime |

Hệ thống **tự động chọn backend** phù hợp với phần cứng:
- Có ONNX Runtime → dùng **FaceLiVT** (512-dim, chính xác hơn, tối ưu khuôn mặt Châu Á)
- Không có ONNX Runtime → dùng **SFace** (128-dim, chỉ cần OpenCV)
- Override thủ công qua biến môi trường: `FACE_BACKEND=facelivt` hoặc `FACE_BACKEND=sface`

### 2. Thuật Toán Matching KNN Top-5 Voting

Thay vì so sánh 1-1 đơn thuần, hệ thống lấy **Top 5 embedding gần nhất** rồi **bầu chọn (voting)** theo nhân viên. Nếu 1 người có nhiều ảnh enroll, nhiều embedding sẽ cùng vote → giảm thiểu nhận nhầm (False Positive).

**Hiệu năng**: Toàn bộ embedding được cache trong RAM dưới dạng NumPy matrix → phép nhân `matrix @ query` cho kết quả trong **< 0.5ms** trên Pi 4 (với < 1000 nhân viên).

### 3. Best Frame Selector

Tự động chọn khung hình tốt nhất dựa trên:
- **Sharpness**: Laplacian variance (loại ảnh nhòe)
- **Brightness**: Loại ảnh quá tối/sáng
- **Face size**: Ưu tiên mặt lớn, rõ ràng
- **Frontalness**: Ưu tiên mặt chính diện (ít nghiêng)

### 4. State Machine Chống Spam

Quản lý luồng điểm danh: **IN → OUT → IN → OUT**
- Không cho phép `IN → IN` hoặc `OUT → OUT` liên tục
- Cooldown 1 phút giữa các lần quẹt trùng lặp
- Cache trạng thái trong RAM → không cần query DB mỗi frame

### 5. Admin Web Dashboard (FastAPI)

- Quản lý danh sách nhân viên, xem lịch sử điểm danh
- Lọc theo ngày, phòng ban
- Xuất báo cáo CSV
- Xóa nhân viên (tự động cascade xóa embedding + ảnh + logs)

---

## 🏗️ Kiến Trúc Hệ Thống

```
┌─────────────────────────────────────────────────────────────┐
│                      KIOSK UI LAYER                         │
│   main_cv2.py (Pi/OpenCV)  │  main_qt.py (PC/PyQt5)        │
│         ↓ Camera Thread          ↓ CameraWorker Thread      │
│         ↓ AI Worker Thread       ↓ AIWorker Thread           │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│                     AI PIPELINE                              │
│                                                              │
│  Camera → FaceDetector → BestFrameSelector → FaceEmbedder   │
│           (YuNet)        (Quality Filter)    (FaceLiVT/SFace)│
│                                                    ↓         │
│                                              Matcher (KNN-5) │
│                                                    ↓         │
│                                         AttendanceService    │
│                                         (State Machine)      │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│                    DATA LAYER                                │
│                                                              │
│  SQLite DB ← EmbeddingCache (RAM Matrix)                     │
│             ← AttendanceStateCache (RAM Dict)                │
│                                                              │
│  FastAPI Web Dashboard (web_api.py + web_ui/)                │
└─────────────────────────────────────────────────────────────┘
```

### Luồng Xử Lý Chi Tiết (1 chu kỳ điểm danh)

```
1. CameraThread đọc frame liên tục (~30 FPS)
2. YuNet phát hiện khuôn mặt + 5 landmarks         (~5ms trên Pi)
3. Kiểm tra mặt nằm trong khung guide
4. BestFrameSelector giữ frame tốt nhất             (~0ms)
5. Sau 1.5s ổn định → gửi sang AIWorker
6. FaceEmbedder trích xuất embedding                 (~40-80ms trên Pi)
7. Matcher so sánh vectorized: matrix @ query        (~0.3ms)
8. KNN Top-5 voting → chọn nhân viên
9. AttendanceStateCache kiểm tra logic IN/OUT        (~0ms)
10. Ghi DB + lưu ảnh                                 (~5ms)
11. Hiển thị kết quả trên UI                         (~0ms)

Tổng latency: ~50-90ms/chu kỳ (real-time trên Pi 4)
```

---

## ⚙️ Cấu Trúc Thư Mục

```
FaceRecognitionAttendance/
├── app/                          # Source code chính
│   ├── config.py                 # Cấu hình tập trung (thresholds, paths, backend)
│   ├── camera_service.py         # Auto-detect camera (PiCamera / USB / Demo)
│   ├── face_detector.py          # YuNet face detection + landmarks
│   ├── face_embedder.py          # Dual-backend: FaceLiVT (512d) / SFace (128d)
│   ├── best_frame_selector.py    # Online frame quality scoring
│   ├── matcher.py                # KNN Top-5 vectorized matching + RAM cache
│   ├── attendance_service.py     # Business logic + State Machine
│   ├── database.py               # SQLite CRUD + bcrypt auth
│   ├── main_cv2.py               # Kiosk UI - Pure OpenCV (cho Pi)
│   ├── main.py                   # Kiosk UI - OpenCV + CameraThread
│   ├── main_qt.py                # Kiosk UI - PyQt5 (cho PC)
│   ├── web_api.py                # FastAPI REST + Dashboard
│   └── web_ui/                   # HTML templates (login, dashboard)
├── models/                       # ONNX model files
│   ├── face_detection_yunet_2023mar.onnx
│   ├── face_recognition_sface_2021dec.onnx
│   └── facelivtv2_s.onnx
├── scripts/                      # Tiện ích
│   ├── setup_pi.sh               # Cài đặt tự động trên Pi
│   ├── build_onnxruntime_pi.sh   # Build ONNX Runtime từ source cho Pi
│   ├── download_models.py        # Tải models từ OpenCV Zoo
│   ├── enroll_from_folder.py     # Batch enroll từ thư mục ảnh
│   ├── seed_data.py              # Tạo dữ liệu test
│   ├── diagnose_pi.py            # Chẩn đoán lỗi trên Pi
│   ├── convert_facelivt_onnx.py  # Convert FaceLiVT PyTorch → ONNX
│   ├── clear_db.py               # Xóa toàn bộ database
│   └── clear_old_faces.py        # Dọn ảnh cũ
├── benchmarks/                   # Công cụ đánh giá & tuning
│   ├── sweep_threshold.py        # Tìm threshold tối ưu
│   ├── plot_bell_curves.py       # Vẽ phân bố cosine similarity
│   ├── compare_models.py         # So sánh SFace vs FaceLiVT
│   ├── benchmark_pipeline.py     # Đo tốc độ toàn pipeline
│   └── calculate_similarity_stats.py
├── tests/                        # Bộ test
├── requirements.txt              # Dependencies cho PC
├── requirements_pi.txt           # Dependencies cho Raspberry Pi
├── run.py                        # Entry point: PyQt5 version
├── run_cv2.py                    # Entry point: Pure OpenCV version (cho Pi)
└── setup.py                      # First-time setup script
```

---

## 🚀 Hướng Dẫn Cài Đặt

### Trên PC (Windows/macOS/Linux)

```bash
# 1. Clone repo
git clone <URL_REPO>
cd FaceRecognitionAttendance

# 2. Tạo virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

# 3. Cài dependencies
pip install -r requirements.txt

# 4. Tải models + khởi tạo DB
python setup.py

# 5. Chạy Kiosk
python run.py               # PyQt5 UI
python run_cv2.py            # Pure OpenCV UI

# 6. Chạy Web Dashboard (song song)
uvicorn app.web_api:api --host 0.0.0.0 --port 8000
```

### Trên Raspberry Pi 4/5 (64-bit)

```bash
# 1. Copy code sang Pi hoặc git clone
cd ~/FaceRecognitionAttendance

# 2. Chạy script cài đặt tự động
chmod +x scripts/setup_pi.sh
bash scripts/setup_pi.sh

# 3. Activate venv
source venv_pi/bin/activate

# 4. Kiểm tra
python3 scripts/diagnose_pi.py

# 5. Chạy Kiosk
python3 run_cv2.py --source usb --camera 0     # USB Camera
python3 run_cv2.py --source picam               # Pi Camera Module

# 6. Web Dashboard
uvicorn app.web_api:api --host 0.0.0.0 --port 8000
# Truy cập từ PC: http://<IP_PI>:8000
```

> ⚠️ **Bắt buộc dùng Pi OS 64-bit (aarch64)**. Bản 32-bit không tương thích ONNX Runtime.

> ⚠️ **KHÔNG `pip install opencv-python` hay `pip install numpy` trên Pi**. Luôn dùng bản APT:
> `sudo apt install python3-opencv python3-numpy`

---

## 🔧 Cấu Hình

Tất cả cấu hình tập trung trong `app/config.py`:

| Tham số | Giá trị mặc định | Mô tả |
|---------|-------------------|-------|
| `PREFERRED_BACKEND` | `"auto"` | Backend AI: `auto`, `facelivt`, `sface` |
| `SFACE_COSINE_THRESHOLD` | `0.363` | Ngưỡng nhận diện SFace |
| `FACELIVT_COSINE_THRESHOLD` | `0.50` | Ngưỡng nhận diện FaceLiVT |
| `STABLE_FACE_SECONDS` | `1.5` | Thời gian giữ yên mặt trước khi xử lý |
| `DUPLICATE_COOLDOWN_MINUTES` | `1` | Cooldown giữa các lần quẹt trùng |
| `DETECTION_SCORE_THRESHOLD` | `0.9` | Ngưỡng tin cậy phát hiện mặt |
| `CAMERA_WIDTH × HEIGHT` | `640 × 480` | Độ phân giải camera |

Override backend qua biến môi trường:
```bash
FACE_BACKEND=facelivt python3 run_cv2.py --source usb
FACE_BACKEND=sface python3 run_cv2.py --source usb
```

---

## 📊 Benchmarks & Tuning

### So sánh Backend

| | SFace | FaceLiVT v2-S (FP32) | FaceLiVT v2-S (INT8) |
|---|---|---|---|
| Embedding dim | 128 | 512 | 512 |
| Kích thước model | 37 MB | 17 MB | ~5 MB |
| Tốc độ (Pi 4) | ~40ms | ~80ms | ~60ms |
| Dependency | OpenCV (sẵn có) | ONNX Runtime | ONNX Runtime |
| Accuracy | Tốt | Rất tốt (khuôn mặt Châu Á) | Khá tốt |

### ⚡ So sánh tại Ngưỡng Tối Ưu

> Benchmark trên tập **3068 cặp so sánh** (VN-celeb dataset), threshold được tìm tự động bằng `sweep_threshold.py`.

| Metric | SFace (128d) | FaceLiVT2\_S FP32 (512d) | FaceLiVT2\_S INT8 (512d) |
|---|:---:|:---:|:---:|
| **Threshold tối ưu** | 0.400 | 0.250 | 0.100 |
| **Accuracy (%)** | **92.54%** | 89.96% | 88.01% |
| **FAR — nhầm người (%)** | **7.24%** | 9.71% | 11.99% |
| **FRR — từ chối sai (%)** | 0.23% | 0.33% | **0.00%** |
| Correct / Total | 2839 / 3068 | 2760 / 3068 | 2700 / 3068 |
| Wrong (nhầm) | 222 | 298 | 368 |
| Unknown (dưới threshold) | 7 | 10 | 0 |

> **Nhận xét:** SFace đạt accuracy cao nhất (92.54%) trên tập benchmark này. FaceLiVT2_S FP32 cho kết quả tốt ở ngưỡng thấp hơn (0.250). Phiên bản INT8 sau quantize bị giảm accuracy (~2%) nhưng FRR = 0% (không từ chối sai ai).

### Tuning Threshold

```bash
# Vẽ phân bố cosine similarity (Bell Curves)
python benchmarks/plot_bell_curves.py

# Tìm threshold tối ưu tự động (EER / F1)
python benchmarks/sweep_threshold.py

# So sánh SFace vs FaceLiVT
python benchmarks/compare_models.py
```

---

## 🔒 Bảo Mật

- Mật khẩu hash bằng `bcrypt` (cost factor 12)
- Session auth bằng `itsdangerous` signed cookie
- RBAC: Admin xem tất cả, Employee chỉ xem record của mình

> ⚠️ **Thay đổi trước khi deploy production:**
> - Mật khẩu admin mặc định: `admin123`
> - `SECRET_KEY` trong `config.py` → đổi sang giá trị ngẫu nhiên

---

## 📝 Ghi Chú Kỹ Thuật

- **Đổi backend = phải enroll lại**: SFace (128-dim) và FaceLiVT (512-dim) không tương thích. Hệ thống có kiểm tra dimension mismatch và cảnh báo.
- **Unicode path**: Hệ thống xử lý đường dẫn tiếng Việt trên Windows bằng `np.fromfile()` + buffer API (OpenCV ≥ 4.9) hoặc fallback string path (OpenCV < 4.9).
- **Scaling**: Với > 5000 nhân viên, nên thay `matcher.py` bằng ANN library (FAISS/Annoy).
- **WAL mode**: SQLite mặc định dùng journal_mode=DELETE. Nếu cần concurrent read/write cao, bật WAL.

---

*Đồ án Hệ thống nhúng — Hệ thống Điểm danh Khuôn mặt trên Raspberry Pi*
*Phát triển bởi @danbui*