"""
So sánh hiệu năng giữa SFace (128-dim) và FaceLiVT (512-dim).

Chạy cả 2 mô hình trên cùng một bộ dữ liệu test (data_benchmark/test),
sau đó in ra bảng so sánh và vẽ biểu đồ Bell Curves cạnh nhau.

Usage:
    python benchmarks/compare_models.py
"""
import sys
import time
import numpy as np
import unicodedata
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
from app.face_detector import FaceDetector
from app.config import SFACE_MODEL, FACELIVT_MODEL

DATA_DIR = PROJECT_ROOT / "data_faces"
TEST_DIR = PROJECT_ROOT / "benchmarks" / "data_benchmark" / "test"

# ═══════════════════════════════════════════════════════════
#  Tọa độ chuẩn 5 điểm landmarks cho khung 112x112 (ArcFace standard)
# ═══════════════════════════════════════════════════════════
ARCFACE_DST = np.array([
    [38.2946, 51.6963],
    [73.5318, 51.5014],
    [56.0252, 71.7366],
    [41.5493, 92.3655],
    [70.7299, 92.2041]
], dtype=np.float32)


def slugify(text: str) -> str:
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    code = re.sub(r'[-\s]+', '_', text)
    return code if code else text.replace(" ", "_")


def imread_unicode(filepath):
    data = np.fromfile(str(filepath), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def align_face_arcface(frame, detection, image_size=112):
    """
    Căn chỉnh khuôn mặt theo chuẩn InsightFace/ArcFace.
    Dùng skimage.SimilarityTransform (least-squares) thay vì
    cv2.estimateAffinePartial2D (LMEDS).
    """
    from skimage import transform as trans
    try:
        landmarks = detection[4:14].reshape((5, 2))
        dst = ARCFACE_DST * (float(image_size) / 112.0)
        tform = trans.SimilarityTransform()
        tform.estimate(landmarks, dst)
        M = tform.params[0:2, :]
        return cv2.warpAffine(frame, M, (image_size, image_size), borderValue=0.0)
    except Exception:
        pass
    # Fallback: crop bounding box
    x, y, w, h = detection[:4].astype(int)
    crop = frame[max(0, y):min(frame.shape[0], y+h), max(0, x):min(frame.shape[1], x+w)]
    if crop.size > 0:
        return cv2.resize(crop, (image_size, image_size))
    return None


# ═══════════════════════════════════════════════════════════
#  Wrapper cho SFace (128-dim, OpenCV DNN)
# ═══════════════════════════════════════════════════════════
class SFaceEmbedder:
    def __init__(self):
        import shutil, tempfile
        # OpenCV FaceRecognizerSF không hỗ trợ đường dẫn Unicode (tiếng Việt) trên Windows.
        # Workaround: copy model sang thư mục tạm có đường dẫn ASCII thuần.
        self._tmpdir = tempfile.mkdtemp(prefix="sface_")
        tmp_model = Path(self._tmpdir) / "sface.onnx"
        shutil.copy2(str(SFACE_MODEL), str(tmp_model))
        self.recognizer = cv2.FaceRecognizerSF_create(str(tmp_model), "")

    def get_embedding(self, frame, detection):
        """Trích xuất embedding 128-dim bằng SFace."""
        aligned = self.recognizer.alignCrop(frame, detection)
        feature = self.recognizer.feature(aligned)
        emb = feature.flatten()
        norm = np.linalg.norm(emb)
        if norm > 1e-8:
            emb = emb / norm
        return emb


# ═══════════════════════════════════════════════════════════
#  Wrapper cho FaceLiVT (512-dim, ONNX Runtime)
# ═══════════════════════════════════════════════════════════
class FaceLiVTEmbedder:
    def __init__(self):
        import onnxruntime as ort
        self.session = ort.InferenceSession(str(FACELIVT_MODEL), providers=['CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name

    def get_embedding(self, frame, detection):
        """Trích xuất embedding 512-dim bằng FaceLiVT."""
        face_crop = align_face_arcface(frame, detection)
        if face_crop is None:
            return np.zeros(512, dtype=np.float32)

        rgb = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
        blob = (rgb.astype(np.float32) - 127.5) / 127.5
        blob = np.transpose(blob, (2, 0, 1))
        blob = np.expand_dims(blob, axis=0)

        out = self.session.run(None, {self.input_name: blob})[0]
        emb = out.flatten()
        norm = np.linalg.norm(emb)
        if norm > 1e-8:
            emb = emb / norm
        return emb


# ═══════════════════════════════════════════════════════════
#  Bước 1: Enroll tất cả data_faces vào bộ nhớ (RAM, không dùng DB)
# ═══════════════════════════════════════════════════════════
def enroll_all(detector, embedder, data_dir):
    """Trả về dict: {employee_code: [list of embeddings]}"""
    db = {}
    total = 0
    for person_dir in sorted(data_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        code = slugify(person_dir.name)
        embeddings = []
        for img_file in person_dir.iterdir():
            if img_file.suffix.lower() not in ['.jpg', '.jpeg', '.png']:
                continue
            img = imread_unicode(img_file)
            if img is None:
                continue
            detections = detector.detect_all(img)
            if detections is None:
                continue
            areas = detections[:, 2] * detections[:, 3]
            det = detections[int(np.argmax(areas))]
            emb = embedder.get_embedding(img, det)
            embeddings.append(emb)
            total += 1
        if embeddings:
            db[code] = embeddings
    return db, total


# ═══════════════════════════════════════════════════════════
#  Bước 2: Tính phân bố Cosine Similarity (Same vs Different)
# ═══════════════════════════════════════════════════════════
def compute_distributions(db):
    """Tính điểm cosine giữa tất cả cặp (cùng người & khác người)."""
    # Xây dựng danh sách (code, embedding)
    items = []
    for code, embs in db.items():
        for e in embs:
            items.append((code, e))

    same_scores = []
    diff_scores = []

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            score = float(np.dot(items[i][1], items[j][1]))
            if items[i][0] == items[j][0]:
                same_scores.append(score)
            else:
                diff_scores.append(score)

    return np.array(same_scores), np.array(diff_scores)


# ═══════════════════════════════════════════════════════════
#  Bước 3: Test nhận diện trên thư mục test
# ═══════════════════════════════════════════════════════════
def test_recognition(detector, embedder, db, threshold):
    """Test nhận diện trên thư mục test, trả về (correct, wrong, not_found, total_time)."""
    # Tạo ma trận embeddings từ db
    codes_list = []
    emb_matrix = []
    for code, embs in db.items():
        for e in embs:
            codes_list.append(code)
            emb_matrix.append(e)
    emb_matrix = np.array(emb_matrix, dtype=np.float32)

    correct = wrong = not_found = no_face = 0
    total_inference_time = 0.0

    for person_dir in sorted(TEST_DIR.iterdir()):
        if not person_dir.is_dir():
            continue
        true_code = slugify(person_dir.name)

        for img_file in sorted(person_dir.glob("*.jpg")):
            frame = imread_unicode(img_file)
            if frame is None:
                continue
            detections = detector.detect_all(frame)
            if detections is None:
                no_face += 1
                continue
            areas = detections[:, 2] * detections[:, 3]
            det = detections[int(np.argmax(areas))]

            t0 = time.perf_counter()
            emb = embedder.get_embedding(frame, det)
            total_inference_time += (time.perf_counter() - t0)

            query = emb.flatten().astype(np.float32)
            q_norm = np.linalg.norm(query)
            if q_norm < 1e-8:
                not_found += 1
                continue
            query = query / q_norm

            scores = emb_matrix @ query
            best_idx = int(np.argmax(scores))
            best_score = float(scores[best_idx])

            if best_score < threshold:
                not_found += 1
            elif codes_list[best_idx] == true_code:
                correct += 1
            else:
                wrong += 1

    tested = correct + wrong + not_found
    return {
        "correct": correct,
        "wrong": wrong,
        "not_found": not_found,
        "no_face": no_face,
        "tested": tested,
        "accuracy": correct / tested * 100 if tested else 0,
        "wrong_pct": wrong / tested * 100 if tested else 0,
        "total_inference_ms": total_inference_time * 1000,
        "avg_inference_ms": (total_inference_time / tested * 1000) if tested else 0,
    }


# ═══════════════════════════════════════════════════════════
#  Bước 4: Vẽ biểu đồ so sánh
# ═══════════════════════════════════════════════════════════
def plot_comparison(sface_same, sface_diff, facelivt_same, facelivt_diff, output_path):
    """Vẽ biểu đồ Bell Curves cạnh nhau."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("Cần cài matplotlib: pip install matplotlib")
        return

    fig, axes = plt.subplots(1, 2, figsize=(16, 6), sharey=True)

    # ── SFace ──
    ax = axes[0]
    if len(sface_diff) > 0:
        w_diff = np.ones_like(sface_diff) / len(sface_diff)
        ax.hist(sface_diff, bins=50, alpha=0.6, color='red', weights=w_diff,
                label=f'Khác người ({len(sface_diff)} cặp)')
    if len(sface_same) > 0:
        w_same = np.ones_like(sface_same) / len(sface_same)
        ax.hist(sface_same, bins=30, alpha=0.6, color='green', weights=w_same,
                label=f'Cùng người ({len(sface_same)} cặp)')
    ax.axvline(0.363, color='blue', linestyle='dotted', linewidth=2, label='Default Threshold (0.363)')
    ax.set_title('SFace (128-dim)', fontsize=14, fontweight='bold')
    ax.set_xlabel('Cosine Similarity')
    ax.set_ylabel('Tần suất')
    ax.set_xlim(-0.2, 1.0)
    ax.legend(fontsize=9)
    ax.grid(True, linestyle='--', alpha=0.5)

    # ── FaceLiVT ──
    ax = axes[1]
    if len(facelivt_diff) > 0:
        w_diff = np.ones_like(facelivt_diff) / len(facelivt_diff)
        ax.hist(facelivt_diff, bins=50, alpha=0.6, color='red', weights=w_diff,
                label=f'Khác người ({len(facelivt_diff)} cặp)')
    if len(facelivt_same) > 0:
        w_same = np.ones_like(facelivt_same) / len(facelivt_same)
        ax.hist(facelivt_same, bins=30, alpha=0.6, color='green', weights=w_same,
                label=f'Cùng người ({len(facelivt_same)} cặp)')
    ax.axvline(0.60, color='blue', linestyle='dotted', linewidth=2, label='Threshold (0.60)')
    ax.set_title('FaceLiVT v2-XS (512-dim)', fontsize=14, fontweight='bold')
    ax.set_xlabel('Cosine Similarity')
    ax.set_xlim(-0.2, 1.0)
    ax.legend(fontsize=9)
    ax.grid(True, linestyle='--', alpha=0.5)

    plt.suptitle('So sánh phân bố Cosine Similarity: SFace vs FaceLiVT',
                 fontsize=16, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(str(output_path), dpi=300, bbox_inches='tight')
    print(f"\n📊 Đã lưu biểu đồ so sánh: {output_path}")
    try:
        plt.show()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════
def main():
    print("=" * 70)
    print("   SO SÁNH MÔ HÌNH: SFace (128-dim) vs FaceLiVT v2-XS (512-dim)")
    print("=" * 70)

    detector = FaceDetector()

    # ── Khởi tạo 2 embedder ──
    print("\n[1/6] Khởi tạo SFace embedder...")
    sface = SFaceEmbedder()

    print("[2/6] Khởi tạo FaceLiVT embedder...")
    facelivt = FaceLiVTEmbedder()

    # ── Enroll ──
    print(f"\n[3/6] Đang enroll dữ liệu từ {DATA_DIR.name}/ bằng SFace...")
    t0 = time.perf_counter()
    sface_db, sface_total = enroll_all(detector, sface, DATA_DIR)
    sface_enroll_time = time.perf_counter() - t0
    print(f"    → SFace: {sface_total} ảnh, {len(sface_db)} người, {sface_enroll_time:.1f}s")

    print(f"[4/6] Đang enroll dữ liệu từ {DATA_DIR.name}/ bằng FaceLiVT...")
    t0 = time.perf_counter()
    facelivt_db, facelivt_total = enroll_all(detector, facelivt, DATA_DIR)
    facelivt_enroll_time = time.perf_counter() - t0
    print(f"    → FaceLiVT: {facelivt_total} ảnh, {len(facelivt_db)} người, {facelivt_enroll_time:.1f}s")

    # ── Phân bố Cosine ──
    print("\n[5/6] Đang tính phân bố Cosine Similarity...")
    sface_same, sface_diff = compute_distributions(sface_db)
    facelivt_same, facelivt_diff = compute_distributions(facelivt_db)

    # ── Test Recognition ──
    print("[6/6] Đang test nhận diện trên thư mục test/...")
    sface_result = test_recognition(detector, sface, sface_db, threshold=0.363)
    facelivt_result = test_recognition(detector, facelivt, facelivt_db, threshold=0.60)

    # ═══════════════════════════════════════════════════════
    #  In bảng so sánh
    # ═══════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("                     BẢNG SO SÁNH KẾT QUẢ")
    print("=" * 70)
    print(f"{'Tiêu chí':<35} | {'SFace (128-dim)':>18} | {'FaceLiVT (512-dim)':>18}")
    print("-" * 70)
    print(f"{'Kích thước model (MB)':<35} | {SFACE_MODEL.stat().st_size/1e6:>17.1f} | {FACELIVT_MODEL.stat().st_size/1e6:>17.1f}")
    print(f"{'Số chiều embedding':<35} | {'128':>18} | {'512':>18}")
    print(f"{'Tốc độ enroll tổng (s)':<35} | {sface_enroll_time:>17.1f} | {facelivt_enroll_time:>17.1f}")
    print(f"{'Tốc độ inference TB (ms/ảnh)':<35} | {sface_result['avg_inference_ms']:>17.2f} | {facelivt_result['avg_inference_ms']:>17.2f}")
    print("-" * 70)
    print(f"{'Accuracy (%)':<35} | {sface_result['accuracy']:>17.2f} | {facelivt_result['accuracy']:>17.2f}")
    print(f"{'Wrong (%)':<35} | {sface_result['wrong_pct']:>17.2f} | {facelivt_result['wrong_pct']:>17.2f}")
    print(f"{'Correct / Tested':<35} | {sface_result['correct']:>7} / {sface_result['tested']:<8} | {facelivt_result['correct']:>7} / {facelivt_result['tested']:<8}")
    print(f"{'Wrong #':<35} | {sface_result['wrong']:>18} | {facelivt_result['wrong']:>18}")
    print(f"{'Not Found #':<35} | {sface_result['not_found']:>18} | {facelivt_result['not_found']:>18}")
    print("-" * 70)

    if len(sface_same) > 0 and len(sface_diff) > 0:
        print(f"{'Cosine TB (Cùng người)':<35} | {np.mean(sface_same):>17.4f} | {np.mean(facelivt_same):>17.4f}")
        print(f"{'Cosine TB (Khác người)':<35} | {np.mean(sface_diff):>17.4f} | {np.mean(facelivt_diff):>17.4f}")
        sface_gap = np.mean(sface_same) - np.mean(sface_diff)
        facelivt_gap = np.mean(facelivt_same) - np.mean(facelivt_diff)
        print(f"{'Khoảng cách phân bố (Gap)':<35} | {sface_gap:>17.4f} | {facelivt_gap:>17.4f}")
        print(f"{'Percentile 1% (Cùng người)':<35} | {np.percentile(sface_same, 1):>17.4f} | {np.percentile(facelivt_same, 1):>17.4f}")
        print(f"{'Percentile 99% (Khác người)':<35} | {np.percentile(sface_diff, 99):>17.4f} | {np.percentile(facelivt_diff, 99):>17.4f}")

    print("=" * 70)

    # ── Vẽ biểu đồ ──
    output_path = PROJECT_ROOT / "benchmarks" / "model_comparison_plot.png"
    plot_comparison(sface_same, sface_diff, facelivt_same, facelivt_diff, output_path)

    print("\n✅ Hoàn thành so sánh!")


if __name__ == "__main__":
    main()
