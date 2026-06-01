"""
Script đánh giá Độ chính xác (Accuracy, FAR, FRR) cho 8 mô hình nhận diện khuôn mặt.
Sử dụng Threshold Sweep để tìm ra ngưỡng tối ưu nhất cho từng model.

Cách chạy:
  python benchmarks/evaluate_all_sweep.py --dataset dataset_clean --test-ratio 0.2
"""
import sys, time, random, argparse, csv
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.face_detector import FaceDetector
from app.config import MODELS_DIR

# ── DANH SÁCH MÔ HÌNH ───────────────────────────────────────────
MODELS_TO_EVALUATE = [
    (MODELS_DIR / "face_recognition_sface_2021dec.onnx", "SFace Original", "sface"),
    (MODELS_DIR / "face_recognition_sface_2021dec_int8.onnx", "SFace INT8", "sface"),
    (MODELS_DIR / "face_recognition_sface_2021dec_int8bq.onnx", "SFace INT8 BQ", "sface"),
    (MODELS_DIR / "facelivtv2_l.onnx", "FaceLiVT v2-L", "facelivt"),
    (MODELS_DIR / "facelivtv2_l_finetuned_VN-celeb-clean.onnx", "FaceLiVT v2-L (VNCeleb)", "facelivt"),
    (MODELS_DIR / "facelivtv2_l_finetuned_dataset_clean.onnx", "FaceLiVT v2-L (DatasetClean)", "facelivt"),
    (MODELS_DIR / "facelivtv2_l_int8.onnx", "FaceLiVT v2-L INT8", "facelivt"),
    (MODELS_DIR / "facelivtv2_s_512.onnx", "FaceLiVT v2-S", "facelivt"),
]

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SEED = 42

ARCFACE_DST = np.array([
    [38.2946, 51.6963], [73.5318, 51.5014],
    [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]
], dtype=np.float32)

# ── UTILITIES ──────────────────────────────────────────────────
def imread_u(path):
    buf = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)

# ── WRAPPERS ───────────────────────────────────────────────────
class SFaceEmb:
    def __init__(self, model_path, name):
        self.name = name
        self.type = "sface"
        self.embed_dim = 128
        try:
            buf = np.fromfile(str(model_path), dtype=np.uint8)
            self.rec = cv2.FaceRecognizerSF.create(framework="onnx", bufferModel=buf, bufferConfig=np.array([], dtype=np.uint8))
        except TypeError:
            self.rec = cv2.FaceRecognizerSF.create(str(model_path), "")

    def align(self, frame, det):
        return self.rec.alignCrop(frame, det)

    def get_embedding(self, aligned):
        feat = self.rec.feature(aligned).flatten()
        n = np.linalg.norm(feat)
        return feat / n if n > 1e-8 else feat

class FaceLiVTEmb:
    def __init__(self, model_path, name):
        self.name = name
        self.type = "facelivt"
        import onnxruntime as ort
        self.sess = ort.InferenceSession(str(model_path), providers=['CPUExecutionProvider'])
        self.inp = self.sess.get_inputs()[0].name
        dummy = np.random.randn(1, 3, 112, 112).astype(np.float32)
        self.embed_dim = self.sess.run(None, {self.inp: dummy})[0].flatten().shape[0]

    def align(self, frame, det, size=112):
        try:
            lm = det[4:14].reshape((5, 2))
            dst = ARCFACE_DST * (float(size) / 112.0)
            M, _ = cv2.estimateAffinePartial2D(lm, dst)
            if M is None: M = cv2.getAffineTransform(lm[:3], dst[:3])
            return cv2.warpAffine(frame, M, (size, size), borderValue=0.0)
        except Exception:
            x, y, w, h = det[:4].astype(int)
            crop = frame[max(0,y):min(frame.shape[0],y+h), max(0,x):min(frame.shape[1],x+w)]
            return cv2.resize(crop, (size, size)) if crop.size > 0 else None

    def get_embedding(self, face):
        if face is None: return np.zeros(self.embed_dim, dtype=np.float32)
        rgb = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
        blob = (rgb.astype(np.float32) - 127.5) / 127.5
        blob = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]
        emb = self.sess.run(None, {self.inp: blob})[0].flatten()
        n = np.linalg.norm(emb)
        return emb / n if n > 1e-8 else emb

# ── ACCURACY CORE ──────────────────────────────────────────────
def split_dataset(data_dir, test_ratio=0.2):
    rng = random.Random(SEED)
    split = {}
    for pdir in sorted([d for d in data_dir.iterdir() if d.is_dir()]):
        imgs = sorted(f for f in pdir.iterdir() if f.suffix.lower() in IMG_EXTS)
        if len(imgs) < 2: continue
        rng.shuffle(imgs)
        n_test = max(1, int(len(imgs) * test_ratio))
        split[pdir.name] = {"gallery": imgs[n_test:], "probe": imgs[:n_test]}
    return split

def extract_all_faces(split, detector, embedder):
    gallery_embs, gallery_labels = [], []
    probe_embs, probe_labels = [], []

    for label, data in split.items():
        # Enroll Gallery
        for p in data["gallery"]:
            img = imread_u(p)
            if img is None: continue
            dets = detector.detect_all(img)
            if dets is None: continue
            det = dets[int(np.argmax(dets[:, 2] * dets[:, 3]))]
            vec = embedder.get_embedding(embedder.align(img, det))
            if np.linalg.norm(vec) < 1e-8: continue
            gallery_embs.append(vec)
            gallery_labels.append(label)
        
        # Extract Probe
        for p in data["probe"]:
            img = imread_u(p)
            if img is None: continue
            dets = detector.detect_all(img)
            if dets is None: continue
            det = dets[int(np.argmax(dets[:, 2] * dets[:, 3]))]
            vec = embedder.get_embedding(embedder.align(img, det))
            if np.linalg.norm(vec) < 1e-8: continue
            probe_embs.append(vec)
            probe_labels.append(label)

    matrix = np.array(gallery_embs, dtype=np.float32) if gallery_embs else np.zeros((0, embedder.embed_dim))
    return matrix, gallery_labels, probe_embs, probe_labels

def evaluate_at_threshold(probe_embs, probe_labels, matrix, gallery_labels, threshold):
    correct, wrong, unknown = 0, 0, 0
    for true_label, emb in zip(probe_labels, probe_embs):
        scores = matrix @ emb
        K = min(5, len(scores))
        top_k = np.argsort(scores)[-K:][::-1]
        votes = defaultdict(int)
        best_s = {}
        for idx in top_k:
            s = float(scores[idx])
            if s < threshold: continue
            c = gallery_labels[idx]
            votes[c] += 1
            if c not in best_s or s > best_s[c]: best_s[c] = s
        if not votes:
            unknown += 1
        else:
            pred = max(votes, key=lambda c: (votes[c], best_s[c]))
            if pred == true_label: correct += 1
            else: wrong += 1
            
    total = correct + wrong + unknown
    acc = correct / total * 100 if total else 0
    far = wrong / total * 100 if total else 0
    frr = unknown / total * 100 if total else 0
    return {"thr": threshold, "acc": acc, "far": far, "frr": frr, "correct": correct, "wrong": wrong, "unknown": unknown}

def print_threshold_table(model_name, results, best_thr):
    """In bảng chi tiết các thông số ở mỗi ngưỡng cho 1 model."""
    print(f"\n  {'─'*90}")
    print(f"  📋 Chi tiết từng ngưỡng: {model_name}")
    print(f"  {'─'*90}")
    print(f"  {'':>3} {'Threshold':>10} │ {'Acc%':>8} │ {'FAR%':>8} │ {'FRR%':>8} │ {'Correct':>8} │ {'Wrong':>8} │ {'Unknown':>8}")
    print(f"  {'':>3} {'─'*10}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*8}")
    for r in results:
        marker = " ★" if abs(r['thr'] - best_thr) < 1e-6 else "  "
        print(f"  {marker} {r['thr']:>10.3f} │ {r['acc']:>8.2f} │ {r['far']:>8.2f} │ {r['frr']:>8.2f} │ {r['correct']:>8d} │ {r['wrong']:>8d} │ {r['unknown']:>8d}")
    print(f"  {'─'*90}")

def run_accuracy_sweep(split, detector, embedders):
    print(f"\n{'='*70}")
    print(f"🎯 BENCHMARK ĐỘ CHÍNH XÁC (THRESHOLD SWEEP)")
    print(f"{'='*70}")

    thresholds = np.arange(0.10, 0.85, 0.025).tolist()
    all_results = {}

    for i, emb in enumerate(embedders):
        print(f"\n  [{i+1}/{len(embedders)}] Đang quét {emb.name}...")
        t0 = time.perf_counter()
        matrix, g_labels, p_embs, p_labels = extract_all_faces(split, detector, emb)
        
        results = []
        for thr in thresholds:
            r = evaluate_at_threshold(p_embs, p_labels, matrix, g_labels, thr)
            results.append(r)
        
        best = max(results, key=lambda r: (r["acc"], -r["far"]))
        all_results[emb.name] = {"best": best, "sweep": results}
        
        elapsed = time.perf_counter() - t0
        print(f"    -> Xong trong {elapsed:.1f}s. Gallery: {len(g_labels)}, Probes: {len(p_labels)}")
        print(f"    -> Tối ưu tại Thr={best['thr']:.3f}: Acc={best['acc']:.2f}%, FAR={best['far']:.2f}%, FRR={best['frr']:.2f}%")

        # In bảng chi tiết từng ngưỡng
        print_threshold_table(emb.name, results, best['thr'])

    return all_results

def print_accuracy_report(acc_res, embedders):
    print(f"\n  🏆 BẢNG XẾP HẠNG ĐỘ CHÍNH XÁC (Sắp xếp theo Accuracy):")
    col_w = 28
    print(f"  {'Model':<{col_w}} │ {'Thr':>6} │ {'Acc%':>7} │ {'FAR%':>7} │ {'FRR%':>7}")
    print(f"  {'─'*col_w}─┼─{'─'*6}─┼─{'─'*7}─┼─{'─'*7}─┼─{'─'*7}")
    
    # Sort by accuracy descending
    sorted_embs = sorted(embedders, key=lambda e: acc_res[e.name]["best"]["acc"], reverse=True)
    
    for emb in sorted_embs:
        b = acc_res[emb.name]["best"]
        print(f"  {emb.name:<{col_w}} │ {b['thr']:>6.3f} │ {b['acc']:>7.2f} │ {b['far']:>7.2f} │ {b['frr']:>7.2f}")


# ── MAIN ───────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default="dataset_clean")
    parser.add_argument("--test-ratio", type=float, default=0.2)
    args = parser.parse_args()

    ds = Path(args.dataset)
    if not ds.is_absolute(): ds = PROJECT_ROOT / ds
    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(exist_ok=True)

    print("=" * 80)
    print("  🚀 ĐÁNH GIÁ ĐỘ CHÍNH XÁC & NGƯỠNG TỐI ƯU CHO TẤT CẢ MÔ HÌNH")
    print("=" * 80)

    detector = FaceDetector()

    embedders = []
    for path, name, mtype in MODELS_TO_EVALUATE:
        if not path.exists(): continue
        try:
            if mtype == "sface": embedders.append(SFaceEmb(path, name))
            else: embedders.append(FaceLiVTEmb(path, name))
        except: pass

    if not embedders:
        print("Không có mô hình nào để chạy!")
        return

    split = split_dataset(ds, test_ratio=args.test_ratio)
    acc_res = run_accuracy_sweep(split, detector, embedders)
    print_accuracy_report(acc_res, embedders)

    # Save CSV — full sweep data (tất cả ngưỡng cho mỗi model)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = out_dir / f"sweep_all_models_{ts}.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Model", "Threshold", "Accuracy", "FAR", "FRR", "Correct", "Wrong", "Unknown", "Is_Optimal"])
        for emb in embedders:
            best_thr = acc_res[emb.name]["best"]["thr"]
            for r in acc_res[emb.name]["sweep"]:
                is_opt = "YES" if abs(r['thr'] - best_thr) < 1e-6 else ""
                w.writerow([
                    emb.name, f"{r['thr']:.3f}", f"{r['acc']:.2f}", f"{r['far']:.2f}", f"{r['frr']:.2f}",
                    r['correct'], r['wrong'], r['unknown'], is_opt
                ])
    print(f"\n✅ Đã lưu kết quả Sweep đầy đủ ra: {csv_path}")

    # Save summary CSV — chỉ best threshold mỗi model
    csv_summary = out_dir / f"sweep_summary_{ts}.csv"
    with open(csv_summary, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Model", "Opt_Thr", "Accuracy", "FAR", "FRR", "Correct", "Wrong", "Unknown"])
        for emb in embedders:
            b = acc_res[emb.name]["best"]
            w.writerow([
                emb.name, f"{b['thr']:.3f}", f"{b['acc']:.2f}", f"{b['far']:.2f}", f"{b['frr']:.2f}",
                b['correct'], b['wrong'], b['unknown']
            ])
    print(f"  📊 Bảng tóm tắt (best threshold): {csv_summary}")

if __name__ == "__main__":
    main()
