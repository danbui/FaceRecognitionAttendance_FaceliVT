"""
Quantize FaceLiVT v2-S ONNX model từ FP32 → INT8.

Sử dụng ONNX Runtime static quantization với calibration data
từ dataset khuôn mặt có sẵn trong project.

Yêu cầu:
    pip install onnxruntime onnx

Cách chạy:
    python scripts/quantize_facelivt_int8.py

Output:
    models/facelivtv2_s_512_int8.onnx
"""
import os
import sys
import glob
import cv2
import numpy as np
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"

# Input: model FP32 gốc
INPUT_MODEL = MODELS_DIR / "facelivtv2_s_512.onnx"
# Output: model INT8
OUTPUT_MODEL = MODELS_DIR / "facelivtv2_s_512_int8.onnx"
# Thư mục ảnh calibration (dùng dataset có sẵn)
CALIB_DATA_DIR = BASE_DIR / "data_faces"

# Số lượng ảnh dùng để calibrate (càng nhiều càng chính xác, nhưng chậm hơn)
NUM_CALIB_IMAGES = 200
# Input size theo chuẩn FaceLiVT
INPUT_SIZE = 112


def collect_calibration_images(data_dir: Path, max_images: int) -> list:
    """
    Thu thập ảnh từ dataset để làm calibration data.
    Lấy đều từ các thư mục con (mỗi người 1-2 ảnh).
    """
    image_paths = []
    extensions = ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp")

    # Lấy tất cả thư mục con (mỗi thư mục = 1 người)
    subdirs = sorted([d for d in data_dir.iterdir() if d.is_dir()])

    if not subdirs:
        # Không có subdirectory → lấy ảnh trực tiếp
        for ext in extensions:
            image_paths.extend(glob.glob(str(data_dir / ext)))
    else:
        # Lấy đều từ mỗi thư mục
        images_per_person = max(1, max_images // len(subdirs))
        for subdir in subdirs:
            person_images = []
            for ext in extensions:
                person_images.extend(glob.glob(str(subdir / ext)))
                person_images.extend(glob.glob(str(subdir / "**" / ext), recursive=True))
            # Loại trùng
            person_images = list(set(person_images))
            if person_images:
                np.random.shuffle(person_images)
                image_paths.extend(person_images[:images_per_person])

            if len(image_paths) >= max_images:
                break

    np.random.shuffle(image_paths)
    return image_paths[:max_images]


def preprocess_face(image_path: str) -> np.ndarray:
    """
    Đọc ảnh và preprocess giống pipeline inference:
      1. Resize về 112x112
      2. BGR → RGB
      3. Normalize [-1, 1]
      4. HWC → CHW → thêm batch dim
    """
    # Đọc ảnh (hỗ trợ Unicode path trên Windows)
    buf = np.fromfile(image_path, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)

    if img is None:
        return None

    # Detect face bằng YuNet nếu có, nếu không thì crop center
    yunet_path = str(BASE_DIR / "models" / "face_detection_yunet_2023mar.onnx")
    face_crop = None

    if os.path.exists(yunet_path):
        try:
            detector = cv2.FaceDetectorYN.create(
                yunet_path, "", (img.shape[1], img.shape[0]),
                score_threshold=0.7
            )
            _, faces = detector.detect(img)
            if faces is not None and len(faces) > 0:
                # Lấy face lớn nhất
                areas = faces[:, 2] * faces[:, 3]
                best = faces[np.argmax(areas)]
                x, y, w, h = best[:4].astype(int)
                # Mở rộng bbox thêm 10%
                pad = int(max(w, h) * 0.1)
                x1 = max(0, x - pad)
                y1 = max(0, y - pad)
                x2 = min(img.shape[1], x + w + pad)
                y2 = min(img.shape[0], y + h + pad)
                face_crop = img[y1:y2, x1:x2]
        except Exception:
            pass

    if face_crop is None or face_crop.size == 0:
        # Fallback: center crop
        h, w = img.shape[:2]
        size = min(h, w)
        y_start = (h - size) // 2
        x_start = (w - size) // 2
        face_crop = img[y_start:y_start+size, x_start:x_start+size]

    # Resize về 112x112
    face_crop = cv2.resize(face_crop, (INPUT_SIZE, INPUT_SIZE))

    # Preprocessing giống face_embedder.py → _infer_facelivt()
    rgb = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
    blob = (rgb.astype(np.float32) - 127.5) / 127.5  # Normalize [-1, 1]
    blob = np.transpose(blob, (2, 0, 1))               # HWC → CHW
    blob = np.expand_dims(blob, axis=0)                 # Add batch dim

    return blob


class FaceLiVTDataReader:
    """
    CalibrationDataReader cho ONNX Runtime quantization.
    Cung cấp batch dữ liệu calibration từ dataset khuôn mặt.
    """

    def __init__(self, image_paths: list, input_name: str):
        self.image_paths = image_paths
        self.input_name = input_name
        self.index = 0
        self.data = []

        print(f"[*] Preprocessing {len(image_paths)} ảnh calibration...")
        for i, path in enumerate(image_paths):
            blob = preprocess_face(path)
            if blob is not None:
                self.data.append({self.input_name: blob})
            if (i + 1) % 50 == 0:
                print(f"    ... {i + 1}/{len(image_paths)}")

        print(f"[+] Đã load {len(self.data)} ảnh hợp lệ cho calibration")

    def get_next(self):
        if self.index >= len(self.data):
            return None
        result = self.data[self.index]
        self.index += 1
        return result

    def rewind(self):
        self.index = 0


def compare_outputs(fp32_model: str, int8_model: str, test_images: list):
    """So sánh chất lượng embedding giữa FP32 và INT8."""
    import onnxruntime as ort

    sess_fp32 = ort.InferenceSession(str(fp32_model), providers=["CPUExecutionProvider"])
    sess_int8 = ort.InferenceSession(str(int8_model), providers=["CPUExecutionProvider"])
    input_name = sess_fp32.get_inputs()[0].name

    cosine_sims = []
    l2_diffs = []

    for path in test_images[:20]:  # Test trên 20 ảnh
        blob = preprocess_face(path)
        if blob is None:
            continue

        out_fp32 = sess_fp32.run(None, {input_name: blob})[0].flatten()
        out_int8 = sess_int8.run(None, {input_name: blob})[0].flatten()

        # L2-normalize
        out_fp32 = out_fp32 / (np.linalg.norm(out_fp32) + 1e-8)
        out_int8 = out_int8 / (np.linalg.norm(out_int8) + 1e-8)

        cos_sim = np.dot(out_fp32, out_int8)
        l2_diff = np.linalg.norm(out_fp32 - out_int8)

        cosine_sims.append(cos_sim)
        l2_diffs.append(l2_diff)

    if cosine_sims:
        print(f"\n{'='*60}")
        print(f"📊 SO SÁNH CHẤT LƯỢNG FP32 vs INT8")
        print(f"{'='*60}")
        print(f"  Số ảnh test     : {len(cosine_sims)}")
        print(f"  Cosine Sim      : {np.mean(cosine_sims):.6f} ± {np.std(cosine_sims):.6f}")
        print(f"  Cosine Sim (min): {np.min(cosine_sims):.6f}")
        print(f"  L2 Distance     : {np.mean(l2_diffs):.6f} ± {np.std(l2_diffs):.6f}")
        print(f"{'='*60}")
        if np.mean(cosine_sims) > 0.99:
            print(f"  ✅ Chất lượng RẤT TỐT - embedding gần như giữ nguyên")
        elif np.mean(cosine_sims) > 0.95:
            print(f"  ✅ Chất lượng TỐT - sai số nhỏ, chấp nhận được")
        elif np.mean(cosine_sims) > 0.90:
            print(f"  ⚠️  Chất lượng TRUNG BÌNH - cần test kỹ hơn với threshold")
        else:
            print(f"  ❌ Chất lượng THẤP - cần xem lại calibration data")
    else:
        print("[!] Không có ảnh test hợp lệ để so sánh")


def main():
    print("=" * 60)
    print("🔧 QUANTIZE FaceLiVT v2-S: FP32 → INT8")
    print("=" * 60)

    # ── Kiểm tra dependencies ──
    try:
        import onnx
        import onnxruntime as ort
        from onnxruntime.quantization import (
            quantize_static,
            QuantType,
            QuantFormat,
            CalibrationDataReader,
        )
        print(f"[+] onnx {onnx.__version__}, onnxruntime {ort.__version__}")
    except ImportError as e:
        print(f"[-] Thiếu dependency: {e}")
        print("    Chạy: pip install onnx onnxruntime")
        return

    # ── Kiểm tra model input ──
    if not INPUT_MODEL.exists():
        print(f"[-] Model FP32 không tìm thấy: {INPUT_MODEL}")
        print("    Chạy trước: python scripts/convert_facelivt_onnx.py")
        return

    fp32_size = INPUT_MODEL.stat().st_size / (1024 * 1024)
    print(f"[*] Model FP32: {INPUT_MODEL.name} ({fp32_size:.1f} MB)")

    # ── Thu thập calibration data ──
    if not CALIB_DATA_DIR.exists():
        print(f"[-] Thư mục calibration data không tồn tại: {CALIB_DATA_DIR}")
        print("    Cần có ảnh khuôn mặt để calibrate model")
        return

    image_paths = collect_calibration_images(CALIB_DATA_DIR, NUM_CALIB_IMAGES)
    if len(image_paths) < 10:
        print(f"[-] Không đủ ảnh calibration ({len(image_paths)} ảnh, cần ít nhất 10)")
        return

    print(f"[+] Tìm thấy {len(image_paths)} ảnh calibration")

    # ── Lấy input name từ model ──
    sess = ort.InferenceSession(str(INPUT_MODEL), providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name
    output_name = sess.get_outputs()[0].name
    output_dim = sess.get_outputs()[0].shape
    print(f"[*] Input: '{input_name}', Output: '{output_name}' {output_dim}")
    del sess

    # ── Dùng thư mục tạm ASCII để tránh lỗi Unicode path ──
    # ONNX Runtime tạo file tạm (-inferred.onnx) cạnh model, nhưng lỗi với
    # đường dẫn chứa tiếng Việt trên Windows. Workaround: copy sang thư mục tạm.
    import tempfile
    import shutil
    from onnxruntime.quantization import quant_pre_process

    tmp_dir = Path(tempfile.mkdtemp(prefix="onnx_quant_"))
    # Giữ nguyên tên file gốc vì ONNX lưu tên file .data bên trong protobuf
    original_name = INPUT_MODEL.name  # facelivtv2_s_512.onnx
    tmp_input = tmp_dir / original_name
    tmp_preprocess = tmp_dir / "model_preprocess.onnx"
    tmp_output = tmp_dir / "model_int8.onnx"

    # Copy model gốc + data file (nếu có external data)
    print(f"\n[*] Copy model sang thư mục tạm: {tmp_dir}")
    shutil.copy2(str(INPUT_MODEL), str(tmp_input))
    # Copy .onnx.data nếu tồn tại (external weights) - giữ nguyên tên
    data_file = INPUT_MODEL.parent / (INPUT_MODEL.name + ".data")
    if data_file.exists():
        shutil.copy2(str(data_file), str(tmp_dir / data_file.name))

    # ── Pre-process model (cần thiết cho quantization) ──
    print(f"[*] Pre-processing model cho quantization...")
    try:
        quant_pre_process(
            input_model_path=str(tmp_input),
            output_model_path=str(tmp_preprocess),
        )
        quant_input = tmp_preprocess
        print(f"[+] Pre-processed OK")
    except Exception as e:
        print(f"[!] Pre-process thất bại (thử quantize trực tiếp): {e}")
        quant_input = tmp_input

    # ── Tạo CalibrationDataReader ──
    calib_reader = FaceLiVTDataReader(image_paths, input_name)

    if len(calib_reader.data) == 0:
        print("[-] Không có ảnh calibration hợp lệ nào!")
        shutil.rmtree(str(tmp_dir), ignore_errors=True)
        return

    # ── Quantize ──
    print(f"\n[*] Bắt đầu quantization INT8...")
    print(f"    Input : {quant_input.name}")
    print(f"    Output: {OUTPUT_MODEL.name}")
    print(f"    Format: QDQ (Quantize-DeQuantize)")
    print(f"    Type  : INT8 (weights + activations)")

    try:
        quantize_static(
            model_input=str(quant_input),
            model_output=str(tmp_output),
            calibration_data_reader=calib_reader,
            quant_format=QuantFormat.QDQ,
            weight_type=QuantType.QInt8,
            activation_type=QuantType.QInt8,
            per_channel=True,
            extra_options={
                "WeightSymmetric": True,
                "ActivationSymmetric": False,
                "CalibMovingAverage": True,
            }
        )
        print(f"[+] Quantization thành công!")
    except Exception as e:
        print(f"[-] Quantization thất bại: {e}")
        shutil.rmtree(str(tmp_dir), ignore_errors=True)
        return

    # ── Copy kết quả về thư mục models ──
    shutil.copy2(str(tmp_output), str(OUTPUT_MODEL))
    print(f"[+] Đã copy model INT8 về: {OUTPUT_MODEL}")

    # ── Cleanup thư mục tạm ──
    shutil.rmtree(str(tmp_dir), ignore_errors=True)
    print(f"[*] Đã xóa thư mục tạm")

    # ── Kiểm tra kết quả ──
    int8_size = OUTPUT_MODEL.stat().st_size / (1024 * 1024)
    reduction = (1 - int8_size / fp32_size) * 100

    print(f"\n{'='*60}")
    print(f"📦 KẾT QUẢ QUANTIZATION")
    print(f"{'='*60}")
    print(f"  FP32 : {INPUT_MODEL.name:40s} {fp32_size:7.1f} MB")
    print(f"  INT8 : {OUTPUT_MODEL.name:40s} {int8_size:7.1f} MB")
    print(f"  Giảm : {reduction:.1f}%")
    print(f"{'='*60}")

    # ── Verify với ONNX Runtime ──
    print(f"\n[*] Verify model INT8 với ONNX Runtime...")
    try:
        sess_int8 = ort.InferenceSession(str(OUTPUT_MODEL), providers=["CPUExecutionProvider"])
        dummy = np.random.randn(1, 3, INPUT_SIZE, INPUT_SIZE).astype(np.float32)
        out = sess_int8.run(None, {input_name: dummy})[0]
        print(f"[+] ONNX Runtime OK! Output shape: {out.shape}")
    except Exception as e:
        print(f"[-] Verify thất bại: {e}")
        return

    # ── Benchmark tốc độ ──
    print(f"\n[*] Benchmark tốc độ (100 iterations)...")
    import time

    sess_fp32 = ort.InferenceSession(str(INPUT_MODEL), providers=["CPUExecutionProvider"])
    sess_int8 = ort.InferenceSession(str(OUTPUT_MODEL), providers=["CPUExecutionProvider"])
    dummy = np.random.randn(1, 3, INPUT_SIZE, INPUT_SIZE).astype(np.float32)

    # Warmup
    for _ in range(10):
        sess_fp32.run(None, {input_name: dummy})
        sess_int8.run(None, {input_name: dummy})

    # FP32
    t0 = time.perf_counter()
    for _ in range(100):
        sess_fp32.run(None, {input_name: dummy})
    fp32_ms = (time.perf_counter() - t0) / 100 * 1000

    # INT8
    t0 = time.perf_counter()
    for _ in range(100):
        sess_int8.run(None, {input_name: dummy})
    int8_ms = (time.perf_counter() - t0) / 100 * 1000

    speedup = fp32_ms / int8_ms if int8_ms > 0 else 0

    print(f"\n{'='*60}")
    print(f"⚡ BENCHMARK TỐC ĐỘ (ONNX Runtime CPU)")
    print(f"{'='*60}")
    print(f"  FP32 : {fp32_ms:7.2f} ms/inference")
    print(f"  INT8 : {int8_ms:7.2f} ms/inference")
    print(f"  Speedup: {speedup:.2f}x")
    print(f"{'='*60}")

    # ── So sánh chất lượng embedding ──
    compare_outputs(INPUT_MODEL, OUTPUT_MODEL, image_paths)

    # ── Hướng dẫn sử dụng ──
    print(f"\n{'='*60}")
    print(f"📝 HƯỚNG DẪN SỬ DỤNG")
    print(f"{'='*60}")
    print(f"  Để dùng model INT8, cập nhật app/config.py:")
    print(f"")
    print(f'    FACELIVT_MODEL = MODELS_DIR / "{OUTPUT_MODEL.name}"')
    print(f"")
    print(f"  Hoặc giữ nguyên config và rename file:")
    print(f"    1. Backup: facelivtv2_s_512.onnx → facelivtv2_s_512_fp32.onnx")
    print(f"    2. Rename: {OUTPUT_MODEL.name} → facelivtv2_s_512.onnx")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
