"""
So sánh hiệu năng SFace vs FaceLiVT trên 2 bộ dữ liệu:
  - data_faces     (Dataset gốc, chưa lọc)
  - dataset_clean  (Dataset đã lọc chất lượng, ảnh gốc full-size)

Logic:
  1. Tách 20% ảnh từ dataset_clean làm TEST SET (per-person random split).
  2. Enroll từ data_faces     → loại trừ ảnh trùng tên với test set.
  3. Enroll từ dataset_clean  → loại trừ ảnh đã nằm trong test set.
  4. Test nhận diện cả 2 gallery bằng cùng 1 test set.
  → Không có data leakage.

Chạy:
    python benchmarks/compare_datasets.py
"""
import sys, time, unicodedata, re, random
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
from app.face_detector import FaceDetector
from app.config import SFACE_MODEL, FACELIVT_MODEL

# ── Datasets ───────────────────────────────────────────────
DATA_FACES_DIR   = PROJECT_ROOT / "data_faces"
DATASET_CLEAN_DIR = PROJECT_ROOT / "dataset_clean"

# Tỷ lệ tách test (20%)
TEST_SPLIT_RATIO = 0.20
# Seed cố định để kết quả reproducible
RANDOM_SEED = 42

# ── Tọa độ chuẩn 5 điểm landmarks cho khung 112×112 ──────
ARCFACE_DST = np.array([
    [38.2946, 51.6963], [73.5318, 51.5014],
    [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]
], dtype=np.float32)

# ═══════════════════════════════════════════════════════════
#  Utilities
# ═══════════════════════════════════════════════════════════
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
    cv2.estimateAffinePartial2D (LMEDS) để khớp chính xác với
    cách align lúc training FaceLiVT.
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
    x, y, w, h = detection[:4].astype(int)
    crop = frame[max(0, y):min(frame.shape[0], y+h), max(0, x):min(frame.shape[1], x+w)]
    if crop.size > 0:
        return cv2.resize(crop, (image_size, image_size))
    return None

# ═══════════════════════════════════════════════════════════
#  Embedder wrappers
# ═══════════════════════════════════════════════════════════
class SFaceEmbedder:
    def __init__(self):
        import shutil, tempfile
        self._tmpdir = tempfile.mkdtemp(prefix="sface_")
        tmp_model = Path(self._tmpdir) / "sface.onnx"
        shutil.copy2(str(SFACE_MODEL), str(tmp_model))
        self.recognizer = cv2.FaceRecognizerSF_create(str(tmp_model), "")

    def get_embedding(self, frame, detection):
        aligned = self.recognizer.alignCrop(frame, detection)
        feature = self.recognizer.feature(aligned)
        emb = feature.flatten()
        norm = np.linalg.norm(emb)
        if norm > 1e-8: emb = emb / norm
        return emb

class FaceLiVTEmbedder:
    def __init__(self):
        import onnxruntime as ort
        self.session = ort.InferenceSession(str(FACELIVT_MODEL), providers=['CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name

    def get_embedding(self, frame, detection):
        face_crop = align_face_arcface(frame, detection)
        if face_crop is None:
            return np.zeros(512, dtype=np.float32)
        return self._inference(face_crop)

    def _inference(self, face_112):
        rgb = cv2.cvtColor(face_112, cv2.COLOR_BGR2RGB)
        blob = (rgb.astype(np.float32) - 127.5) / 127.5
        blob = np.transpose(blob, (2, 0, 1))
        blob = np.expand_dims(blob, axis=0)
        out = self.session.run(None, {self.input_name: blob})[0]
        emb = out.flatten()
        norm = np.linalg.norm(emb)
        if norm > 1e-8: emb = emb / norm
        return emb


# ═══════════════════════════════════════════════════════════
#  Bước 1: Tách test set từ dataset_clean (20% per person)
# ═══════════════════════════════════════════════════════════
def split_test_from_clean(clean_dir, test_ratio=0.20, seed=42):
    """
    Tách ảnh từ dataset_clean thành 2 phần:
      - enroll_files: dùng để enroll
      - test_files:   dùng để test (probe)

    Returns:
        test_filenames_per_person: {person_name: set(filename1, filename2, ...)}
            → Dùng set tên file để loại trừ khi enroll từ data_faces
    """
    rng = random.Random(seed)
    test_filenames = {}   # person_name → set of filenames in test
    total_test = 0
    total_enroll = 0

    for person_dir in sorted(clean_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        # Lấy tất cả file ảnh
        all_imgs = sorted([
            f for f in person_dir.iterdir()
            if f.suffix.lower() in ['.jpg', '.jpeg', '.png']
        ])
        if len(all_imgs) < 2:
            # Quá ít ảnh → không tách, bỏ tất cả vào enroll
            test_filenames[person_dir.name] = set()
            total_enroll += len(all_imgs)
            continue

        # Tách ngẫu nhiên
        n_test = max(1, int(len(all_imgs) * test_ratio))
        test_imgs = set(rng.sample(all_imgs, n_test))
        test_filenames[person_dir.name] = {f.name for f in test_imgs}

        total_test += n_test
        total_enroll += len(all_imgs) - n_test

    print(f"  📊 Split dataset_clean: {total_enroll} enroll + {total_test} test "
          f"({len(test_filenames)} người)")
    return test_filenames


# ═══════════════════════════════════════════════════════════
#  Bước 2: Enroll với loại trừ test files
# ═══════════════════════════════════════════════════════════
def enroll_with_exclusion(detector, embedder, data_dir, excluded_filenames):
    """
    Enroll tất cả ảnh trong data_dir, nhưng BỎ QUA các file có tên
    nằm trong excluded_filenames[person_name].

    Args:
        excluded_filenames: {person_folder_name: set(filename1, ...)}
    """
    db, total = {}, 0
    skipped_excl = 0
    skipped_noface = 0
    for person_dir in sorted(data_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        code = slugify(person_dir.name)
        excluded = excluded_filenames.get(person_dir.name, set())
        embeddings = []
        for img_file in person_dir.iterdir():
            if img_file.suffix.lower() not in ['.jpg', '.jpeg', '.png']:
                continue
            # Loại trừ ảnh test
            if img_file.name in excluded:
                skipped_excl += 1
                continue
            img = imread_unicode(img_file)
            if img is None:
                continue
            detections = detector.detect_all(img)
            if detections is None:
                skipped_noface += 1
                continue
            areas = detections[:, 2] * detections[:, 3]
            det = detections[int(np.argmax(areas))]
            emb = embedder.get_embedding(img, det)
            embeddings.append(emb)
            total += 1
        if embeddings:
            db[code] = embeddings
    if skipped_excl > 0:
        print(f"    ⊘ Loại trừ {skipped_excl} ảnh test (tránh leakage)")
    if skipped_noface > 0:
        print(f"    ⚠ Bỏ qua {skipped_noface} ảnh (không detect được face)")
    return db, total


# ═══════════════════════════════════════════════════════════
#  Bước 3: Tính phân bố Cosine
# ═══════════════════════════════════════════════════════════
def compute_distributions(db):
    items = [(code, e) for code, embs in db.items() for e in embs]
    same, diff = [], []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            score = float(np.dot(items[i][1], items[j][1]))
            (same if items[i][0] == items[j][0] else diff).append(score)
    return np.array(same), np.array(diff)


# ═══════════════════════════════════════════════════════════
#  Bước 4: Test nhận diện bằng test set từ dataset_clean
# ═══════════════════════════════════════════════════════════
def test_recognition(detector, embedder, db, threshold, test_filenames, clean_dir):
    """
    Test nhận diện sử dụng ảnh test đã tách từ dataset_clean.

    Args:
        test_filenames: {person_folder_name: set(filename1, ...)}
        clean_dir: path to dataset_clean
    """
    # Tạo gallery matrix
    codes_list, emb_list = [], []
    for code, embs in db.items():
        for e in embs:
            codes_list.append(code)
            emb_list.append(e)

    if len(emb_list) == 0:
        return {"correct": 0, "wrong": 0, "not_found": 0, "no_face": 0,
                "tested": 0, "accuracy": 0, "wrong_pct": 0, "avg_ms": 0}

    emb_matrix = np.array(emb_list, dtype=np.float32)

    correct = wrong = not_found = no_face = 0
    total_t = 0.0

    for person_dir in sorted(clean_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        true_code = slugify(person_dir.name)
        person_test_files = test_filenames.get(person_dir.name, set())

        for img_file in sorted(person_dir.iterdir()):
            if img_file.suffix.lower() not in ['.jpg', '.jpeg', '.png']:
                continue
            # Chỉ dùng ảnh nằm trong test set
            if img_file.name not in person_test_files:
                continue

            frame = imread_unicode(img_file)
            if frame is None:
                continue
            dets = detector.detect_all(frame)
            if dets is None:
                no_face += 1
                continue
            areas = dets[:, 2] * dets[:, 3]
            det = dets[int(np.argmax(areas))]

            t0 = time.perf_counter()
            emb = embedder.get_embedding(frame, det)
            total_t += (time.perf_counter() - t0)

            query = emb.flatten().astype(np.float32)
            qn = np.linalg.norm(query)
            if qn < 1e-8:
                not_found += 1
                continue
            query /= qn

            scores = emb_matrix @ query
            
            # Thuật toán KNN Top-5
            K = min(5, len(scores))
            top_k_indices = np.argsort(scores)[-K:][::-1]
            
            votes = {}
            best_ind_score = {}
            for idx in top_k_indices:
                score = float(scores[idx])
                if score < threshold:
                    continue
                c = codes_list[idx]
                votes[c] = votes.get(c, 0) + 1
                if c not in best_ind_score or score > best_ind_score[c]:
                    best_ind_score[c] = score
                    
            if not votes:
                not_found += 1
            else:
                best_code = max(votes.keys(), key=lambda c: (votes[c], best_ind_score[c]))
                if best_code == true_code:
                    correct += 1
                else:
                    wrong += 1

    tested = correct + wrong + not_found
    return {
        "correct": correct, "wrong": wrong, "not_found": not_found,
        "no_face": no_face, "tested": tested,
        "accuracy": correct / tested * 100 if tested else 0,
        "wrong_pct": wrong / tested * 100 if tested else 0,
        "avg_ms": (total_t / tested * 1000) if tested else 0,
    }


# ═══════════════════════════════════════════════════════════
#  Plotting – 2×2 Bell Curves
# ═══════════════════════════════════════════════════════════
def plot_all(all_results, output_path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("⚠ matplotlib chưa cài. Bỏ qua vẽ biểu đồ.")
        return

    fig, axes = plt.subplots(2, 2, figsize=(18, 12), sharey=False)
    ds_names = list(all_results.keys())

    for row, ds_name in enumerate(ds_names):
        for col, model_name in enumerate(["SFace", "FaceLiVT"]):
            ax = axes[row][col]
            data = all_results[ds_name][model_name]
            same = data["same_scores"]
            diff = data["diff_scores"]
            threshold = data.get("threshold_used", 0.363 if model_name == "SFace" else 0.60)

            if len(diff) > 0:
                w = np.ones_like(diff) / len(diff)
                ax.hist(diff, bins=50, alpha=0.6, color='red', weights=w,
                        label=f'Khác người ({len(diff):,} cặp)')
            if len(same) > 0:
                w = np.ones_like(same) / len(same)
                ax.hist(same, bins=30, alpha=0.6, color='green', weights=w,
                        label=f'Cùng người ({len(same):,} cặp)')

            ax.axvline(threshold, color='blue', ls='dotted', lw=2,
                       label=f'Threshold ({threshold})')
            acc = data["result"]["accuracy"]
            wrong = data["result"]["wrong_pct"]
            ax.set_title(f'{model_name} | {ds_name}\n'
                         f'Acc={acc:.1f}%  Wrong={wrong:.1f}%',
                         fontsize=12, fontweight='bold')
            ax.set_xlabel('Cosine Similarity')
            if col == 0:
                ax.set_ylabel('Tần suất (normalized)')
            ax.set_xlim(-0.2, 1.0)
            ax.legend(fontsize=8)
            ax.grid(True, ls='--', alpha=0.4)

    plt.suptitle('So sánh Dataset gốc (data_faces) vs Dataset đã lọc (dataset_clean)\n'
                 'SFace (128-dim) vs FaceLiVT v2-XS (512-dim)\n'
                 'Test set tách từ dataset_clean (không trùng enrollment)',
                 fontsize=14, fontweight='bold', y=1.03)
    plt.tight_layout()
    plt.savefig(str(output_path), dpi=200, bbox_inches='tight')
    print(f"\n📊 Đã lưu biểu đồ: {output_path}")


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════
def main():
    print("=" * 85)
    print("  SO SÁNH MÔ HÌNH × DATASET: data_faces (gốc) vs dataset_clean (đã lọc)")
    print("  Test set: tách từ dataset_clean, không trùng enrollment")
    print("=" * 85)

    detector = FaceDetector()
    print("\n🔧 Khởi tạo SFace...")
    sface = SFaceEmbedder()
    print("🔧 Khởi tạo FaceLiVT...")
    facelivt = FaceLiVTEmbedder()

    embedders = {
        "SFace":    (sface,    0.363),
        "FaceLiVT": (facelivt, None),   # None = auto-calibrate từ phân bố
    }

    # ── Bước 1: Tách test set từ dataset_clean ──
    print("\n" + "─" * 85)
    print("📂 Tách test set từ dataset_clean...")
    test_filenames = split_test_from_clean(
        DATASET_CLEAN_DIR,
        test_ratio=TEST_SPLIT_RATIO,
        seed=RANDOM_SEED
    )
    print("─" * 85)

    # ── Bước 2: Enroll + Evaluate ──
    datasets = [
        ("data_faces",    DATA_FACES_DIR),
        ("dataset_clean", DATASET_CLEAN_DIR),
    ]

    all_results = {}

    for ds_name, ds_path in datasets:
        print(f"\n{'─'*85}")
        print(f"📂 Dataset: {ds_name}")
        print(f"   Path: {ds_path}")
        print(f"{'─'*85}")
        all_results[ds_name] = {}

        for model_name, (embedder, threshold) in embedders.items():
            print(f"\n  ▸ [{model_name}] Đang enroll (loại trừ test files)...")
            t0 = time.perf_counter()
            db, n_imgs = enroll_with_exclusion(
                detector, embedder, ds_path,
                excluded_filenames=test_filenames
            )
            enroll_t = time.perf_counter() - t0
            print(f"    → {n_imgs} ảnh enrolled, {len(db)} người, {enroll_t:.1f}s")

            print(f"  ▸ [{model_name}] Đang tính phân bố cosine...")
            same, diff = compute_distributions(db)

            # Auto-calibrate threshold nếu chưa set
            actual_threshold = threshold
            if actual_threshold is None:
                same_mean = float(np.mean(same)) if len(same) > 0 else 0.5
                diff_mean = float(np.mean(diff)) if len(diff) > 0 else 0.0
                actual_threshold = (same_mean + diff_mean) / 2
                print(f"    🎯 Auto-threshold (midpoint): {actual_threshold:.4f}")
                print(f"       (CosAvg Same={same_mean:.4f}, CosAvg Diff={diff_mean:.4f})")

            print(f"  ▸ [{model_name}] Đang test nhận diện (threshold={actual_threshold:.4f})...")
            result = test_recognition(
                detector, embedder, db, actual_threshold,
                test_filenames, DATASET_CLEAN_DIR
            )

            all_results[ds_name][model_name] = {
                "n_imgs": n_imgs, "n_people": len(db),
                "enroll_time": enroll_t,
                "same_scores": same, "diff_scores": diff,
                "threshold_used": actual_threshold,
                "result": result,
            }

    # ═══════════════════════════════════════════════════════
    #  Bảng tổng hợp
    # ═══════════════════════════════════════════════════════
    print("\n\n" + "=" * 110)
    print("                           BẢNG TỔNG HỢP KẾT QUẢ")
    print("  (Test set tách từ dataset_clean, không trùng enrollment)")
    print("=" * 110)
    header = (f"{'Dataset':<18} | {'Model':<10} | {'#Enroll':<7} | {'#People':>7} "
              f"| {'Acc %':>7} | {'Wrong %':>7} | {'Correct':>7}/{'':>5} "
              f"| {'CosAvg Same':>11} | {'CosAvg Diff':>11} | {'Gap':>7}")
    print(header)
    print("-" * 110)

    for ds_name, _ in datasets:
        for model_name in ["SFace", "FaceLiVT"]:
            d = all_results[ds_name][model_name]
            r = d["result"]
            same_avg = np.mean(d["same_scores"]) if len(d["same_scores"]) > 0 else 0
            diff_avg = np.mean(d["diff_scores"]) if len(d["diff_scores"]) > 0 else 0
            gap = same_avg - diff_avg
            print(f"{ds_name:<18} | {model_name:<10} | {d['n_imgs']:<7} | {d['n_people']:>7} "
                  f"| {r['accuracy']:>6.2f}% | {r['wrong_pct']:>6.2f}% | {r['correct']:>7}/{r['tested']:<5} "
                  f"| {same_avg:>11.4f} | {diff_avg:>11.4f} | {gap:>7.4f}")
        print("-" * 110)

    # ── Cải thiện ──
    print("\n📈 SỰ THAY ĐỔI KHI DÙNG dataset_clean:")
    for model_name in ["SFace", "FaceLiVT"]:
        old = all_results["data_faces"][model_name]["result"]
        new = all_results["dataset_clean"][model_name]["result"]
        delta_acc = new["accuracy"] - old["accuracy"]
        delta_wrong = new["wrong_pct"] - old["wrong_pct"]
        sign_acc = "+" if delta_acc >= 0 else ""
        sign_wr = "+" if delta_wrong >= 0 else ""
        print(f"  {model_name:<10}: Accuracy {sign_acc}{delta_acc:.2f}%  |  Wrong {sign_wr}{delta_wrong:.2f}%")

    print("=" * 110)

    # ── Vẽ biểu đồ ──
    output = PROJECT_ROOT / "benchmarks" / "dataset_comparison_plot.png"
    plot_all(all_results, output)

    print("\n✅ Hoàn thành!")

if __name__ == "__main__":
    main()
