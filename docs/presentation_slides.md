# BỐ CỤC SLIDE THUYẾT TRÌNH ĐỒ ÁN: HỆ THỐNG ĐIỂM DANH BẰNG KHUÔN MẶT TRÊN NHÚNG

---

## PHẦN 1: NÊU VẤN ĐỀ BÀI TOÁN (3 SLIDES)

### Slide 1: Bối cảnh và Nhu cầu thực tế
*   **Vấn đề hiện tại:** Các phương pháp điểm danh truyền thống (thẻ từ, vân tay, điểm danh giấy) tồn tại nhiều hạn chế:
    *   Thẻ từ: Dễ quên, dễ đưa người khác quẹt hộ, tốn chi phí in ấn.
    *   Vân tay: Chậm, tiếp xúc vật lý (nguy cơ lây nhiễm dịch bệnh), khó nhận diện khi tay ướt/xước.
*   **Xu hướng:** Nhận diện khuôn mặt (Face Recognition) đang là tiêu chuẩn mới (Contactless, nhanh chóng, chính xác).
*   **Bài toán đặt ra:** Mang công nghệ nhận diện khuôn mặt vốn đòi hỏi máy chủ cấu hình cao (GPU) xuống các thiết bị nhúng nhỏ gọn (Edge Devices) để giảm chi phí triển khai và đảm bảo tính riêng tư.

### Slide 2: Thách thức khi triển khai trên Thiết bị Nhúng (Raspberry Pi)
*   **Tài nguyên phần cứng hạn chế:**
    *   CPU ARM công suất thấp, RAM giới hạn, không có GPU rời.
    *   Khó khăn trong việc chạy các mô hình AI nặng (như ResNet100, ArcFace gốc) ở tốc độ thời gian thực (Real-time).
*   **Thách thức về môi trường:**
    *   Ánh sáng phức tạp (ngược sáng, thiếu sáng).
    *   Góc mặt đa dạng, người dùng di chuyển liên tục gây nhòe ảnh (Motion blur).
*   **Nhiệt độ & Năng lượng:** Chạy AI liên tục làm thiết bị nóng lên, gây hiện tượng giảm xung nhịp (Thermal throttling).

### Slide 3: Mục tiêu và Giới hạn của Đồ án
*   **Mục tiêu chính:**
    *   Xây dựng hoàn chỉnh một trạm (Kiosk) điểm danh tự động bằng khuôn mặt chạy độc lập trên Raspberry Pi.
    *   Tối ưu hóa Pipeline phần mềm để đạt độ trễ thấp (< 100ms/frame) nhưng vẫn giữ độ chính xác cao (> 98%).
*   **Phương pháp giải quyết:**
    *   Sử dụng các mô hình AI siêu nhẹ được thiết kế riêng cho Edge/Mobile (YuNet, SFace, FaceLiVT).
    *   Áp dụng thuật toán chọn lọc khung hình (Best Frame Selector) để lọc ảnh nhiễu trước khi nhận diện.
    *   Quản lý cơ sở dữ liệu và chống điểm danh spam (State Machine).

---

## PHẦN 2: CƠ SỞ LÝ THUYẾT (4 SLIDES)

### Slide 4: Tổng quan Bài toán Face Recognition
*   Nhận diện khuôn mặt là bài toán xác minh (Verification: 1:1) hoặc nhận dạng (Identification: 1:N).
*   **Quy trình chuẩn (4 bước):**
    1.  **Face Detection:** Tìm vị trí khuôn mặt trong ảnh (Bounding Box) và các điểm đặc trưng (Landmarks).
    2.  **Face Alignment:** Căn chỉnh (xoay, thu phóng) khuôn mặt về một chuẩn chung dựa trên landmarks.
    3.  **Feature Extraction:** Chuyển đổi ảnh khuôn mặt thành một vector đặc trưng (Embedding vector) biểu diễn danh tính.
    4.  **Matching:** So sánh khoảng cách giữa các vectors để quyết định xem có cùng một người hay không.

### Slide 5: Mạng Neural Tích chập (CNN) và Margin-based Loss
*   **Kiến trúc mạng (Backbones):**
    *   Sử dụng CNN (Convolutional Neural Networks) để trích xuất đặc trưng.
    *   Hệ thống nhúng ưu tiên các mạng như MobileNet, ShuffleNet thay vì ResNet nặng nề.
*   **Hàm mất mát (Loss Functions):**
    *   Softmax thông thường không đủ tốt cho nhận diện khuôn mặt (không tối ưu được khoảng cách không gian).
    *   **Margin-based Loss (ArcFace, CosFace):** Ép các ảnh của cùng một người tụ lại gần nhau hơn, và đẩy các ảnh của người khác ra xa nhau trên không gian hình cầu (Hypersphere).

### Slide 6: Vector Đặc trưng (Embedding) & Metric Learning
*   **Embedding là gì?** Là một mảng các số thực (Ví dụ: 128 chiều hoặc 512/1284 chiều). Đại diện cho "DNA khuôn mặt" của một người.
*   **Metric Learning:**
    *   Khoảng cách Euclid (Euclidean Distance): Tính độ dài đường thẳng giữa 2 điểm.
    *   **Độ tương tự Cosine (Cosine Similarity):** Đo góc giữa 2 vectors. Phổ biến nhất trong Face Recognition. Giá trị từ -1 đến 1 (càng gần 1 càng giống nhau).

### Slide 7: Tối ưu mô hình trên Edge Device (ONNX & Reparameterization)
*   **ONNX (Open Neural Network Exchange):**
    *   Định dạng chuẩn để biểu diễn mô hình học máy. Cho phép chạy mượt mà trên ONNX Runtime với CPU/NPU.
*   **Kỹ thuật Structural Reparameterization:**
    *   Dùng trong lúc huấn luyện (Training): Cấu trúc mạng phức tạp (nhiều nhánh) để học tốt hơn.
    *   Lúc triển khai (Inference): Gộp các nhánh lại thành một lớp chập (Conv) đơn giản duy nhất, giúp tăng tốc độ xử lý mà không giảm độ chính xác.

---

## PHẦN 3: TECH STACK & KIẾN TRÚC HỆ THỐNG (3 SLIDES)

### Slide 8: Tech Stack (Công nghệ sử dụng)
*   **Phần cứng:** Raspberry Pi 4/5 (ARM64), Camera USB/CSI.
*   **Ngôn ngữ lập trình:** Python 3.
*   **Computer Vision & AI Inference:**
    *   OpenCV (Xử lý ảnh, Căn chỉnh, SFace).
    *   ONNX Runtime (Chạy inference tốc độ cao cho mô hình FaceLiVT).
*   **Quản lý dữ liệu:** SQLite3 (Lưu trữ Embeddings và Lịch sử điểm danh dưới dạng file gọn nhẹ).
*   **Giao diện (UI):** PyQt5 hoặc Tkinter (hiển thị luồng video và thông báo).

### Slide 9: Kiến trúc Hệ thống (System Architecture) - Tổng thể
*   *(Chèn sơ đồ Architecture High-level)*
*   **Input Layer:** Nguồn video stream từ Camera.
*   **Processing Layer (Core Pipeline):** Các module Detection, Alignment, Extraction.
*   **Storage Layer:** Local SQLite Database (Chứa bảng `employees`, `face_embeddings`, `attendance_logs`).
*   **Application Layer:** Logic điểm danh, giao diện người dùng.

### Slide 10: Kiến trúc Phần mềm (Software Modules)
*   Thiết kế theo hướng Đối tượng (OOP) và Tách biệt trách nhiệm (Separation of Concerns).
*   Các class độc lập: `FaceDetector`, `FaceEmbedder`, `Matcher`, `Database`.
*   Cơ chế **In-memory Cache**:
    *   Load toàn bộ embeddings từ DB lên RAM (Numpy Matrix) khi khởi động để tối ưu tốc độ so sánh (Matching), thay vì truy vấn DB cho mỗi frame.

---

## PHẦN 4: PIPELINE TỔNG QUAN (3 SLIDES)

### Slide 11: Workflow Ghi danh (Enrollment)
*   *(Chèn sơ đồ flowchart Ghi danh)*
*   1. Nhập thông tin nhân viên (Mã NV, Tên).
*   2. Đọc ảnh từ thư mục hoặc chụp từ camera.
*   3. Tìm khuôn mặt (Detection) & Rút trích Vector (Embedding).
*   4. Lưu mảng float32 vào cột BLOB của CSDL SQLite.
*   5. Cập nhật In-memory Cache.

### Slide 12: Workflow Điểm danh (Recognition Pipeline)
*   *(Chèn sơ đồ flowchart luồng Điểm danh)*
*   **Vòng lặp liên tục (Real-time):**
    1. Lấy Frame từ Camera.
    2. Phát hiện mặt (Detection).
    3. Chọn khung hình tốt nhất (Best Frame).
    4. Căn chỉnh & Trích xuất đặc trưng (Embedding).
    5. So sánh với CSDL (Matching).
    6. Xử lý Logic (Chống spam, ghi log, phát âm thanh).

### Slide 13: Luồng Dữ liệu (Data Flow) trong Pipeline
*   **Camera Input:** Ảnh RGB kích thước 640x480 hoặc 1280x720.
*   **YuNet:** Trả về Bounding Box (x,y,w,h) và 5 Điểm Landmarks.
*   **Aligner:** Cắt và xoay ảnh về tensor chuẩn hóa (112x112).
*   **Model FaceLiVT/SFace:** Trả về Vector float32 kích thước 128-dim hoặc 1284-dim.
*   **Matcher:** Tính toán Cosine similarity trả về `Employee_ID` và `Confidence Score`.

---

## PHẦN 5: CHI TIẾT CÁC BƯỚC TRONG PIPELINE (10 SLIDES)

### Slide 14: Bước 1 - Face Detection (Giới thiệu YuNet)
*   **YuNet:** Mô hình phát hiện khuôn mặt cực nhẹ được tích hợp sẵn trong OpenCV DNN.
*   **Đặc điểm:** Hoạt động dựa trên kiến trúc CNN tối ưu, dung lượng model chỉ ~330KB.
*   **Khả năng:** Phát hiện mặt ở nhiều góc độ và cung cấp sẵn 5 điểm Landmarks (mắt trái, mắt phải, mũi, hai khóe miệng) trong một lần inference duy nhất.

### Slide 15: Bước 1 - Face Detection (Hiệu năng)
*   *(Chèn hình ảnh trực quan minh họa bounding box và 5 điểm màu)*
*   **Latency:** Chỉ mất ~6-10ms/frame trên PC và ổn định trên Raspberry Pi.
*   **Tối ưu trong Đồ án:**
    *   Thiết lập kích thước input cố định.
    *   Nếu trong ảnh có nhiều người, hàm `detect_largest()` tự động lọc ra khuôn mặt có diện tích lớn nhất để tập trung xử lý.

### Slide 16: Bước 2 - Best Frame Selector (Vấn đề)
*   **Tại sao cần?** Camera liên tục trả về 30 khung hình/giây. Nhưng khi người dùng di chuyển, ảnh có thể bị nhòe (motion blur), nhắm mắt, hoặc quay mặt đi chỗ khác.
*   Nếu đưa ảnh xấu vào nhận diện:
    *   Tốn tài nguyên tính toán vô ích.
    *   Tăng tỷ lệ nhận diện sai (False Accept) hoặc từ chối sai (False Reject).

### Slide 17: Bước 2 - Best Frame Selector (Giải pháp)
*   **Tiêu chí đánh giá chất lượng (Quality Score):**
    1.  **Độ sắc nét (Sharpness):** Dùng phương sai Laplacian để đo độ nét (tránh nhòe).
    2.  **Độ sáng (Brightness):** Đo giá trị pixel trung bình (tránh quá tối/quá chói).
    3.  **Diện tích mặt:** Mặt càng lớn, tỷ lệ càng cao.
*   **Logic:** Tích lũy khung hình trong một cửa sổ thời gian (ví dụ 10 frames), chọn ra frame có điểm cao nhất để đẩy qua bước tiếp theo.

### Slide 18: Bước 3 - Face Alignment (Căn chỉnh)
*   **Mục đích:** Mô hình AI được huấn luyện trên các ảnh đã căn giữa. Nếu đưa ảnh bị nghiêng, sai lệch vị trí mắt/mũi thì độ chính xác sẽ giảm mạnh.
*   **Phương pháp (ArcFace Standard):**
    *   Định nghĩa 5 tọa độ điểm chuẩn (Mắt, mũi, miệng) trên khung ảnh vuông 112x112.
    *   Sử dụng toán học (Affine Transform) để tính toán ma trận dịch chuyển/xoay từ 5 điểm thực tế khớp vào 5 điểm chuẩn.

### Slide 19: Bước 3 - Face Alignment (Kết quả)
*   *(Chèn ảnh minh họa: Ảnh gốc bị nghiêng -> Ảnh 112x112 đã thẳng mặt)*
*   Toàn bộ khung nền thừa bị loại bỏ, chỉ giữ lại phần khuôn mặt trung tâm, được chuẩn hóa giá trị pixel (Normalize) trước khi đẩy vào mạng CNN.

### Slide 20: Bước 4 - Face Embedding (Mô hình)
*   **Trái tim của hệ thống:** Chuyển đổi ảnh 112x112 thành mảng số học.
*   Hệ thống thiết kế hỗ trợ linh hoạt 2 Backend:
    *   **SFace:** Model của OpenCV, tạo ra mảng 128 chiều. Rất nhẹ.
    *   **FaceLiVT (v2-XS):** Model chuyên dụng, tạo ra mảng 1284 chiều. Nặng hơn nhưng phân biệt tốt hơn.

### Slide 21: Bước 4 - Face Embedding (Chuẩn hóa vector)
*   **L2 Normalization:** Sau khi mạng CNN trả về Vector, cần chuẩn hóa (chia cho độ dài L2) để chiếu Vector lên bề mặt của một hình cầu đơn vị (Unit Hypersphere).
*   Điều này giúp phép tính so sánh Cosine về sau chỉ còn đơn giản là tính tích vô hướng (Dot product) giữa các vector, tối ưu tốc độ thực thi.

### Slide 22: Bước 5 - Matching (So sánh KNN Top-K)
*   Vector thu được (Query) được nhân ma trận (Matrix Multiplication) với toàn bộ Cache Vector trong DB để ra mảng điểm Cosine (Scores).
*   **K-Nearest Neighbors (KNN):**
    *   Thay vì chỉ lấy 1 người giống nhất (Top-1), hệ thống lấy Top-5 người giống nhất.
    *   Tiến hành "Bỏ phiếu" (Voting). Nếu nhiều vector của người A đều nằm trong top đầu, kết quả nhận diện sẽ ổn định và đáng tin cậy hơn.

### Slide 23: Bước 6 - State Machine (Quản lý trạng thái)
*   **Vấn đề chống Spam:** Nếu một người đứng trước camera 3 giây, hệ thống có thể nhận diện ra 30 lần, gây spam cơ sở dữ liệu.
*   **Giải pháp:**
    *   Sử dụng bộ nhớ đệm trạng thái (State Cache).
    *   Ghi nhớ lần quẹt thẻ cuối cùng (Last seen timestamp). Chỉ ghi Log mới nếu thời gian cách lần nhận diện trước đó vượt qua khoảng thời gian cấu hình (Ví dụ: 60 giây).

---

## PHẦN 6: ĐÁNH GIÁ & SO SÁNH MÔ HÌNH (3 SLIDES)

### Slide 24: So sánh Đặc trưng: SFace vs FaceLiVT vs INT8
*   **Bảng thông số 3 mô hình:**

| | SFace | FaceLiVT v2-S (FP32) | FaceLiVT v2-S (INT8) |
|---|---|---|---|
| Số chiều embedding | 128 | 512 | 512 |
| Dung lượng model | ~37 MB | ~17 MB | ~5 MB |
| Tốc độ (PC/x86) | ~42ms (~23 FPS) | **~15ms (~67 FPS)** | ~22ms (~46 FPS) |
| Tốc độ (Pi 4/ARM) | ~40ms | ~80ms | ~60ms |
| Dependency | OpenCV (sẵn có) | ONNX Runtime | ONNX Runtime |

*   **SFace:** Nhỏ gọn, chạy trực tiếp trên OpenCV. Tốc độ cực nhanh, phù hợp CSDL nhỏ.
*   **FaceLiVT v2-S (FP32):** Model chuyên dụng 512 chiều, phân biệt tốt khuôn mặt Châu Á.
*   **FaceLiVT v2-S (INT8):** Phiên bản lượng tử hóa (Quantized) giúp giảm dung lượng ~70%, tăng tốc inference, đánh đổi một phần accuracy.

### Slide 25: ⚡ Benchmark Accuracy tại Ngưỡng Tối Ưu
*   **Tập benchmark:** dataset_clean — 224 người, 957 probe images. Threshold tìm tự động bằng `sweep_both_models.py`.

| Metric | SFace (128d) | FaceLiVT2\_S FP32 (512d) | FaceLiVT2\_S INT8 (512d) |
|---|:---:|:---:|:---:|
| **Threshold tối ưu** | 0.400 | 0.200 | 0.200 |
| **Accuracy** | **90.28%** | 89.86% | 87.77% |
| **FAR (nhầm người)** | **9.09%** | 9.93% | 12.12% |
| **FRR (từ chối sai)** | 0.63% | 0.21% | **0.10%** |
| Correct / Total | 864 / 957 | 860 / 957 | 840 / 957 |
| Wrong (nhầm) | 87 | 95 | 116 |
| Unknown (dưới thr) | 6 | 2 | 1 |

*   **Nhận xét:**
    *   🏆 SFace đạt accuracy cao nhất (90.28%) với FAR thấp nhất (9.09%).
    *   FaceLiVT2_S FP32 gần sát (89.86%) với FRR rất thấp (0.21%) — ít từ chối sai.
    *   INT8 quantize mất ~2% accuracy nhưng model nhỏ hơn ~70%.

### Slide 26: Benchmark Hiệu năng (Latency & FPS)
*   Đo trên PC (Windows 10, AMD64, ONNX Runtime 1.20) với 500 ảnh từ dataset_clean:

| Bước | SFace (128d) | FaceLiVT FP32 (512d) | FaceLiVT INT8 (512d) |
|---|:---:|:---:|:---:|
| Detection (YuNet) | 4.6ms | 4.6ms | 4.6ms |
| Embedding | 37.9ms | **10.3ms** | 17.2ms |
| KNN Matching | 0.1ms | 0.2ms | 0.2ms |
| **Tổng Pipeline** | **42.6ms (~23 FPS)** | **15.0ms (~67 FPS)** | **21.9ms (~46 FPS)** |

*   🏆 **FaceLiVT FP32 nhanh nhất** trên PC: nhanh hơn SFace **2.8x** nhờ ONNX Runtime tận dụng AVX2/AVX-512.
*   Trên Pi 4 (ARM): SFace nhanh hơn (~40ms vs ~80ms) do OpenCV DNN tối ưu tốt cho ARM NEON.
*   Cả 3 model đều đạt **Real-time** (> 20 FPS) trên cả PC lẫn Pi.

---

## PHẦN 7: CHẠY THAM SỐ VÀ TỐI ƯU (1 SLIDE)

### Slide 27: Tìm kiếm Ngưỡng chuẩn (Threshold Tuning)
*   *(Chèn biểu đồ Bell Curves cắt nhau - Histogram Xanh/Đỏ)*
*   **Trade-off (Sự đánh đổi):**
    *   Threshold cao: Khó nhận diện (FRR tăng), nhưng an toàn, không nhận nhầm người lạ (FAR giảm).
    *   Threshold thấp: Dễ nhận diện, góc nghiêng cũng nhận, nhưng dễ nhận nhầm người.
*   **Phương pháp:** Vẽ biểu đồ phân bố Cosine Similarity của "Cùng người" (Xanh) và "Khác người" (Đỏ). Điểm giao nhau giữa 2 phân bố chính là ngưỡng (Threshold) tối ưu lý thuyết. (Ví dụ: SFace = 0.363, FaceLiVT = 0.50 - 0.60).

---

## PHẦN 8: BƯỚC PHÁT TRIỂN & TƯƠNG LAI (1 SLIDE)

### Slide 28: Hướng phát triển mở rộng
1.  **Liveness Detection (Chống giả mạo):**
    *   Hiện tại hệ thống có thể bị qua mặt bởi ảnh in trên giấy hoặc màn hình điện thoại. Cần tích hợp module chống giả mạo (Anti-spoofing).
2.  **Tăng tốc phần cứng (Hardware Acceleration):**
    *   Biên dịch ONNX Runtime với XNNPACK hoặc sử dụng NPU (Neural Processing Unit) như Google Coral / Hailo-8L trên Raspberry Pi 5 để tăng tốc lên 30+ FPS.
3.  **Hệ thống phân tán (Cloud Sync):**
    *   Trạm Raspberry Pi chỉ làm Edge Node, đồng bộ log điểm danh và Database nhân viên theo thời gian thực lên một Server Web/Cloud trung tâm.
