"""
Script đánh giá toàn diện 8 mô hình nhận diện khuôn mặt:
1. SFace Original
2. SFace INT8
3. SFace INT8 BQ
4. FaceLiVT v2-L Original
5. FaceLiVT v2-L Finetuned (VN Celeb)
6. FaceLiVT v2-L Finetuned (Dataset Clean)
7. FaceLiVT v2-L INT8
8. FaceLiVT v2-S Original

Bao gồm 2 phần:
- Phần 1: Đánh giá Latency (Tốc độ / Pipeline hoàn chỉnh).
- Phần 2: Sweep Threshold (Độ chính xác, FAR, FRR).

Cách chạy:
  python benchmarks/evaluate_all_models.py
  python benchmarks/evaluate_all_models.py --dataset dataset_clean --max-latency 200
"""
import sys, time, random, argparse, csv, platform
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.face_detector import FaceDetector
from app.best_frame_selector import BestFrameSelector
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

def stats(vals):
    if not vals: return {"mean": 0, "med": 0, "p95": 0, "min": 0, "max": 0}
    a = np.array(vals)
    return {
        "mean": float(np.mean(a)), "med": float(np.median(a)),
        "p95": float(np.percentile(a, 95)),
        "min": float(np.min(a)), "max": float(np.max(a)),
    }

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


# ── PHẦN 1: LATENCY BENCHMARK ──────────────────────────────────
def knn_match(query, matrix, labels, k=5, threshold=0.3):
    if matrix.shape[0] == 0: return None
    scores = matrix @ query
    K = min(k, len(scores))
    top_k = np.argsort(scores)[-K:][::-1]
    votes = defaultdict(int)
    for idx in top_k:
        if float(scores[idx]) >= threshold: votes[labels[idx]] += 1
    if not votes: return None
    return max(votes, key=votes.get)

def run_latency_benchmark(images, detector, selector, embedders):
    print(f"\n{'='*70}")
    print(f"⏱️ PHẦN 1: BENCHMARK LATENCY (FULL PIPELINE)")
    print(f"{'='*70}")

    # Build dummy gallery cho KNN (lấy 100 ảnh đầu)
    print("  [+] Building dummy gallery for KNN...")
    galleries = {emb.name: ([], []) for emb in embedders}
    for p in images[:100]:
        img = imread_u(p)
        if img is None: continue
        box, raw = detector.detect_largest_with_raw(img)
        if raw is None: continue
        for emb in embedders:
            vec = emb.get_embedding(emb.align(img, raw))
            galleries[emb.name][0].append(vec)
            galleries[emb.name][1].append("dummy_label")
    
    for emb in embedders:
        galleries[emb.name] = (np.array(galleries[emb.name][0], dtype=np.float32), galleries[emb.name][1])

    det_times = {emb.name: [] for emb in embedders}
    bf_times = {emb.name: [] for emb in embedders}
    st_times = {emb.name: [] for emb in embedders}
    aln_times = {emb.name: [] for emb in embedders}
    emb_times = {emb.name: [] for emb in embedders}
    knn_times = {emb.name: [] for emb in embedders}
    tot_times = {emb.name: [] for emb in embedders}

    print(f"  [+] Benchmarking {len(images)} images independently for each model...")
    for emb in embedders:
        print(f"\n  ➤ Model: {emb.name}")
        for idx, p in enumerate(images):
            img = imread_u(p)
            if img is None: continue

            # 1. Detection
            t0 = time.perf_counter()
            box, raw = detector.detect_largest_with_raw(img)
            dt_det = (time.perf_counter() - t0) * 1000
            det_times[emb.name].append(dt_det)
            if raw is None: continue

            # 2. Best Frame
            t0 = time.perf_counter()
            selector.reset()
            selector.update(img.copy(), box, raw[4:14], raw)
            bf, br, _ = selector.get_best()
            if bf is None: bf, br = img, raw
            dt_bf = (time.perf_counter() - t0) * 1000
            bf_times[emb.name].append(dt_bf)

            # 3. Alignment
            t0 = time.perf_counter()
            aligned = emb.align(bf, br)
            dt_aln = (time.perf_counter() - t0) * 1000
            aln_times[emb.name].append(dt_aln)

            # 4. Embedding
            t0 = time.perf_counter()
            vec = emb.get_embedding(aligned)
            dt_emb = (time.perf_counter() - t0) * 1000
            emb_times[emb.name].append(dt_emb)

            # 5. KNN
            matrix, labels = galleries[emb.name]
            t0 = time.perf_counter()
            res = knn_match(vec, matrix, labels)
            dt_knn = (time.perf_counter() - t0) * 1000
            knn_times[emb.name].append(dt_knn)

            # 6. State Machine (simulate overhead)
            t0 = time.perf_counter()
            _ = res
            dt_st = (time.perf_counter() - t0) * 1000
            st_times[emb.name].append(dt_st)

            # Total
            tot_times[emb.name].append(dt_det + dt_bf + dt_aln + dt_emb + dt_knn + dt_st)

            if (idx+1) % 50 == 0 or (idx+1) == len(images):
                print(f"      ... {idx+1}/{len(images)}")

    return {
        "det": {e.name: stats(det_times[e.name]) for e in embedders},
        "bf": {e.name: stats(bf_times[e.name]) for e in embedders},
        "st": {e.name: stats(st_times[e.name]) for e in embedders},
        "aln": {e.name: stats(aln_times[e.name]) for e in embedders},
        "emb": {e.name: stats(emb_times[e.name]) for e in embedders},
        "knn": {e.name: stats(knn_times[e.name]) for e in embedders},
        "tot": {e.name: stats(tot_times[e.name]) for e in embedders},
    }

def print_latency_report(res, embedders):
    short_names = [e.name.replace("FaceLiVT", "FL").replace("Original", "Orig").replace("DatasetClean", "D.Clean").replace("VNCeleb", "VN.Cel") for e in embedders]
    metrics = ['mean', 'med', 'p95', 'min', 'max']
    
    print(f"\n{'='*120}")
    print(f"  📊 BÁO CÁO CHI TIẾT LATENCY (ms) - {len(embedders)} MÔ HÌNH")
    print(f"{'='*120}")
    
    hdr = f"  {'Bước (Metric)':<18}"
    sep = f"  {'─'*18}"
    for name in short_names:
        hdr += f" │ {name[:10]:>10}"
        sep += f"─┼─{'─'*10}"
    print(hdr)
    print(sep)

    def print_model_step(step_name, data_key):
        for m in metrics:
            row = f"  {f'{step_name} ({m})':<18}"
            for emb in embedders:
                val = res[data_key][emb.name][m]
                row += f" │ {val:>8.2f}  "
            print(row)
        print(sep)
    
    print_model_step("1. Detect", "det")
    print_model_step("2. Select", "bf")
    print_model_step("3. Align", "aln")
    print_model_step("4. Embed", "emb")
    print_model_step("5. KNN", "knn")
    print_model_step("★ TOTAL", "tot")
    
    row_fps = f"  {'🚀 FPS (từ Mean)':<18}"
    for emb in embedders:
        mean_tot = res['tot'][emb.name]['mean']
        fps = 1000 / max(mean_tot, 1)
        row_fps += f" │ {fps:>8.1f}  "
    print(row_fps)
    print(f"{'='*120}")


# ── PHẦN 2: THRESHOLD SWEEP (ACCURACY) ─────────────────────────
def split_dataset(data_dir, test_ratio=0.2, max_people=0):
    rng = random.Random(SEED)
    split = {}
    pdirs = sorted([d for d in data_dir.iterdir() if d.is_dir()])
    if max_people > 0:
        pdirs = pdirs[:max_people]
    for pdir in pdirs:
        imgs = sorted(f for f in pdir.iterdir() if f.suffix.lower() in IMG_EXTS)
        if len(imgs) < 2: continue
        rng.shuffle(imgs)
        n_test = max(1, int(len(imgs) * test_ratio))
        split[pdir.name] = {"gallery": imgs[n_test:], "probe": imgs[:n_test]}
    return split

def pre_detect_faces(split, detector):
    print("  [+] Pre-detecting faces to speed up embedding extraction...")
    t0 = time.perf_counter()
    face_cache = {}
    total_imgs = 0
    detected_imgs = 0
    
    paths = []
    for label, data in split.items():
        paths.extend(data["gallery"])
        paths.extend(data["probe"])
        
    for idx, p in enumerate(paths):
        img = imread_u(p)
        total_imgs += 1
        if img is None: continue
        dets = detector.detect_all(img)
        if dets is not None:
            det = dets[int(np.argmax(dets[:, 2] * dets[:, 3]))]
            face_cache[str(p)] = det
            detected_imgs += 1
            
        if (idx + 1) % 500 == 0 or (idx + 1) == len(paths):
            print(f"      Pre-detected {idx+1}/{len(paths)} images...")
            
    print(f"  → Pre-detected {detected_imgs}/{total_imgs} faces in {time.perf_counter()-t0:.1f}s.")
    return face_cache

def extract_all_faces(split, face_cache, embedder):
    gallery_embs, gallery_labels = [], []
    probe_embs, probe_labels = [], []

    for label, data in split.items():
        # Enroll Gallery
        for p in data["gallery"]:
            p_str = str(p)
            if p_str not in face_cache: continue
            img = imread_u(p)
            if img is None: continue
            det = face_cache[p_str]
            vec = embedder.get_embedding(embedder.align(img, det))
            if np.linalg.norm(vec) < 1e-8: continue
            gallery_embs.append(vec)
            gallery_labels.append(label)
        
        # Extract Probe
        for p in data["probe"]:
            p_str = str(p)
            if p_str not in face_cache: continue
            img = imread_u(p)
            if img is None: continue
            det = face_cache[p_str]
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

def run_accuracy_sweep(split, face_cache, embedders):
    print(f"\n{'='*70}")
    print(f"🎯 PHẦN 2: THRESHOLD SWEEP (ACCURACY, FAR, FRR)")
    print(f"{'='*70}")

    thresholds = np.arange(0.10, 0.85, 0.025).tolist()
    all_results = {}

    for i, emb in enumerate(embedders):
        print(f"\n  [{i+1}/{len(embedders)}] Đang quét {emb.name}...")
        t0 = time.perf_counter()
        matrix, g_labels, p_embs, p_labels = extract_all_faces(split, face_cache, emb)
        
        results = []
        for thr in thresholds:
            r = evaluate_at_threshold(p_embs, p_labels, matrix, g_labels, thr)
            results.append(r)
        
        best = max(results, key=lambda r: (r["acc"], -r["far"]))
        all_results[emb.name] = {"best": best, "sweep": results}
        
        print(f"    -> Xong trong {time.perf_counter()-t0:.1f}s. Gallery: {len(g_labels)}, Probes: {len(p_labels)}")
        print(f"    -> Tối ưu tại Thr={best['thr']:.3f}: Acc={best['acc']:.2f}%, FAR={best['far']:.2f}%, FRR={best['frr']:.2f}%")

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
    parser.add_argument("--max-latency", type=int, default=200, help="Số ảnh để test latency")
    parser.add_argument("--max-people", type=int, default=0, help="Số người tối đa để test nhanh")
    parser.add_argument("--test-ratio", type=float, default=0.2, help="Tỉ lệ test set cho accuracy")
    args = parser.parse_args()

    ds = Path(args.dataset)
    if not ds.is_absolute(): ds = PROJECT_ROOT / ds
    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(exist_ok=True)

    print("=" * 80)
    print("  🚀 TOÀN TẬP ĐÁNH GIÁ 8 MÔ HÌNH NHẬN DIỆN KHUÔN MẶT")
    print("=" * 80)

    detector = FaceDetector()
    selector = BestFrameSelector()

    # Khởi tạo models
    print("\n[+] Đang tải các mô hình...")
    embedders = []
    for path, name, mtype in MODELS_TO_EVALUATE:
        if not path.exists():
            print(f"  ⚠️ Bỏ qua: {name} (Không tìm thấy {path.name})")
            continue
        try:
            if mtype == "sface":
                embedders.append(SFaceEmb(path, name))
            else:
                embedders.append(FaceLiVTEmb(path, name))
            print(f"  ✅ {name} đã sẵn sàng.")
        except Exception as e:
            print(f"  ❌ Lỗi khi load {name}: {e}")

    if not embedders:
        print("Không có mô hình nào để chạy!")
        return

    # Chuẩn bị ảnh
    all_images = sorted(f for f in ds.rglob("*") if f.is_file() and f.suffix.lower() in IMG_EXTS)
    print(f"\n[+] Đã tìm thấy {len(all_images)} ảnh trong {ds}.")

    # --- Phần 1: Latency ---
    lat_images = all_images[:args.max_latency] if args.max_latency > 0 else all_images
    lat_res = run_latency_benchmark(lat_images, detector, selector, embedders)
    print_latency_report(lat_res, embedders)

    # --- Phần 2: Accuracy ---
    split = split_dataset(ds, test_ratio=args.test_ratio, max_people=args.max_people)
    face_cache = pre_detect_faces(split, detector)
    acc_res = run_accuracy_sweep(split, face_cache, embedders)
    print_accuracy_report(acc_res, embedders)

    # --- Lưu CSV tổng hợp ---
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = out_dir / f"evaluation_all_models_{ts}.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Model", "Opt_Thr", "Accuracy", "FAR", "FRR", "Latency_Align", "Latency_Embed", "Latency_KNN", "Latency_Total", "FPS"])
        for emb in embedders:
            b = acc_res[emb.name]["best"]
            aln = lat_res["aln"][emb.name]["mean"]
            e = lat_res["emb"][emb.name]["mean"]
            k = lat_res["knn"][emb.name]["mean"]
            tot = lat_res["tot"][emb.name]["mean"]
            fps = 1000 / max(tot, 1)
            w.writerow([
                emb.name, f"{b['thr']:.3f}", f"{b['acc']:.2f}", f"{b['far']:.2f}", f"{b['frr']:.2f}",
                f"{aln:.2f}", f"{e:.2f}", f"{k:.2f}", f"{tot:.2f}", f"{fps:.1f}"
            ])
    print(f"\n✅ Đã lưu kết quả chi tiết ra: {csv_path}")

if __name__ == "__main__":
    main()
