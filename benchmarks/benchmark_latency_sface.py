"""
Benchmark Latency — So sánh 3 mô hình SFace: 
1. SFace Gốc (face_recognition_sface_2021dec.onnx)
2. SFace INT8 (face_recognition_sface_2021dec_int8.onnx)
3. SFace INT8 BQ (face_recognition_sface_2021dec_int8bq.onnx)

Cách chạy:
  python benchmarks/benchmark_latency_sface.py
  python benchmarks/benchmark_latency_sface.py --max 200
"""
import sys, time, csv, argparse, platform
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.face_detector import FaceDetector
from app.config import MODELS_DIR

SFACE_ORIGINAL = MODELS_DIR / "face_recognition_sface_2021dec.onnx"
SFACE_INT8 = MODELS_DIR / "face_recognition_sface_2021dec_int8.onnx"
SFACE_INT8BQ = MODELS_DIR / "face_recognition_sface_2021dec_int8bq.onnx"

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

def imread_u(path):
    buf = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)

def stats(vals):
    if not vals:
        return {"mean": 0, "med": 0, "p95": 0, "min": 0, "max": 0, "std": 0, "n": 0}
    a = np.array(vals)
    return {
        "mean": float(np.mean(a)), "med": float(np.median(a)),
        "p95": float(np.percentile(a, 95)),
        "min": float(np.min(a)), "max": float(np.max(a)),
        "std": float(np.std(a)), "n": len(a),
    }

def get_sys_info():
    info = {
        "platform": platform.platform(), "machine": platform.machine(),
        "python": platform.python_version(),
        "opencv": cv2.__version__, "numpy": np.__version__,
    }
    return info

class SFaceVariantEmb:
    def __init__(self, model_path, name):
        self.name = name
        self.embed_dim = 128
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")
        
        try:
            buf = np.fromfile(str(model_path), dtype=np.uint8)
            self.rec = cv2.FaceRecognizerSF.create(
                framework="onnx", bufferModel=buf,
                bufferConfig=np.array([], dtype=np.uint8)
            )
        except TypeError:
            self.rec = cv2.FaceRecognizerSF.create(str(model_path), "")

    def get_embedding(self, frame, det):
        # SFace handles alignment internally using its FaceRecognizerSF API
        aligned = self.rec.alignCrop(frame, det)
        feat = self.rec.feature(aligned).flatten()
        n = np.linalg.norm(feat)
        return feat / n if n > 1e-8 else feat

def enroll_gallery(images, detector, embedder, max_enroll=500):
    embs, labels = [], []
    for p in images[:max_enroll]:
        img = imread_u(p)
        if img is None: continue
        dets = detector.detect_all(img)
        if dets is None: continue
        det = dets[int(np.argmax(dets[:, 2] * dets[:, 3]))]
        emb = embedder.get_embedding(img, det).flatten()
        n = np.linalg.norm(emb)
        if n < 1e-8: continue
        embs.append(emb / n)
        labels.append(p.parent.name)
    if not embs:
        return np.zeros((0, embedder.embed_dim), dtype=np.float32), []
    return np.array(embs, dtype=np.float32), labels

def knn_match(query, matrix, labels, k=5, threshold=0.3):
    if matrix.shape[0] == 0: return None
    q = query.flatten()
    n = np.linalg.norm(q)
    if n < 1e-8: return None
    q = q / n
    scores = matrix @ q
    K = min(k, len(scores))
    top_k = np.argsort(scores)[-K:][::-1]
    votes = defaultdict(int)
    for idx in top_k:
        if float(scores[idx]) >= threshold:
            votes[labels[idx]] += 1
    if not votes: return None
    return max(votes, key=votes.get)

def benchmark_models(images, detector, embedders, galleries, warmup=5):
    model_names = [e.name for e in embedders]
    print(f"  Warmup ({warmup} ảnh)...")
    for p in images[:warmup]:
        img = imread_u(p)
        if img is None: continue
        dets = detector.detect_all(img)
        if dets is None: continue
        det = dets[int(np.argmax(dets[:, 2] * dets[:, 3]))]
        for emb in embedders: emb.get_embedding(img, det)

    det_times = []
    # SFace aligns internally, so we time (Align+Embed) together or just Embed.
    # We will log it as "Alignment + Embedding" time.
    emb_times = {name: [] for name in model_names}
    knn_times = {name: [] for name in model_names}
    total_times = {name: [] for name in model_names}

    n_faces, n_errors = 0, 0
    total = len(images)

    print(f"  Benchmarking {total} ảnh...")
    for idx, p in enumerate(images):
        img = imread_u(p)
        if img is None:
            n_errors += 1
            continue

        t0 = time.perf_counter()
        dets = detector.detect_all(img)
        dt_det = (time.perf_counter() - t0) * 1000
        det_times.append(dt_det)

        if dets is None: continue
        det = dets[int(np.argmax(dets[:, 2] * dets[:, 3]))]
        n_faces += 1

        for i, emb_model in enumerate(embedders):
            name = emb_model.name
            matrix, labels = galleries[i]

            # SFace get_embedding includes alignCrop + feature extraction
            t0 = time.perf_counter()
            emb_vec = emb_model.get_embedding(img, det)
            dt_emb = (time.perf_counter() - t0) * 1000
            emb_times[name].append(dt_emb)

            t0 = time.perf_counter()
            _ = knn_match(emb_vec, matrix, labels)
            dt_knn = (time.perf_counter() - t0) * 1000
            knn_times[name].append(dt_knn)

            total_times[name].append(dt_det + dt_emb + dt_knn)

        if (idx + 1) % 50 == 0 or (idx + 1) == total:
            print(f"    [{idx+1}/{total}] faces={n_faces} errors={n_errors}")

    return {
        "detection": stats(det_times),
        "emb": {name: stats(emb_times[name]) for name in model_names},
        "knn": {name: stats(knn_times[name]) for name in model_names},
        "total": {name: stats(total_times[name]) for name in model_names},
        "n_total": total, "n_faces": n_faces, "n_errors": n_errors,
        "model_names": model_names,
        "dims": {e.name: e.embed_dim for e in embedders},
    }

def print_report(r, sys_info, source):
    names = r["model_names"]
    dims = r["dims"]

    print(f"\n{'='*100}")
    print(f"  ⏱️  BENCHMARK LATENCY — SFace Variants")
    print(f"{'='*100}")
    print(f"  Thời gian  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Platform   : {sys_info['platform']} ({sys_info['machine']})")
    print(f"  Dataset    : {source}")
    print(f"{'-'*100}")

    col_w = 20
    hdr = f"  {'Bước':<30}"
    for n in names: hdr += f" │ {n:>{col_w}}"
    print(hdr)
    sep = f"  {'─'*30}"
    for _ in names: sep += f"─┼─{'─'*col_w}"
    print(sep)

    det = r["detection"]
    det_line = f"  {'1. Detection (YuNet)':<30}"
    for _ in names:
        det_line += f" │ {det['mean']:>{col_w-2}.2f}ms"
    print(det_line + "  (shared)")

    emb_line = f"  {'2. Align + Embed (OpenCV)':<30}"
    knn_line = f"  {'3. KNN Top-5 Matching':<30}"
    for n in names:
        emb_line += f" │ {r['emb'][n]['mean']:>{col_w-2}.2f}ms"
        knn_line += f" │ {r['knn'][n]['mean']:>{col_w-2}.2f}ms"
    print(emb_line); print(knn_line)
    print(sep)

    tot_line = f"  {'★ TỔNG PIPELINE':<30}"
    for n in names: tot_line += f" │ {r['total'][n]['mean']:>{col_w-2}.2f}ms"
    print(tot_line)

    fps_line = f"  {'  → FPS':<30}"
    for n in names: fps_line += f" │ {'~'+str(int(1000/max(r['total'][n]['mean'],1)))+' FPS':>{col_w}}"
    print(fps_line)
    print(f"{'='*100}\n")

def save_csv(r, sys_info, source, out_dir):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = out_dir / f"latency_sface_variants_{ts}.csv"
    names, dims = r["model_names"], r["dims"]

    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["step", "model", "mean_ms", "median_ms", "p95_ms", "min_ms", "max_ms"])
        
        det = r["detection"]
        w.writerow(["detection", "shared", f"{det['mean']:.2f}", f"{det['med']:.2f}", f"{det['p95']:.2f}", f"{det['min']:.2f}", f"{det['max']:.2f}"])
        
        for step_key in ["emb", "knn", "total"]:
            for n in names:
                s = r[step_key][n]
                w.writerow([step_key, n, f"{s['mean']:.2f}", f"{s['med']:.2f}", f"{s['p95']:.2f}", f"{s['min']:.2f}", f"{s['max']:.2f}"])
    print(f"  📄 CSV: {csv_path}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default="dataset_clean")
    parser.add_argument("--max", type=int, default=0)
    args = parser.parse_args()

    ds = Path(args.dataset)
    if not ds.is_absolute(): ds = PROJECT_ROOT / ds
    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(exist_ok=True)

    print("=" * 80)
    print("  ⏱️  BENCHMARK LATENCY: SFACE VARIANTS")
    print("=" * 80)

    sys_info = get_sys_info()

    print(f"\n[1/4] Khởi tạo models...")
    detector = FaceDetector()
    
    embedders = []
    models_to_test = [
        (SFACE_ORIGINAL, "SFace Original"),
        (SFACE_INT8, "SFace INT8"),
        (SFACE_INT8BQ, "SFace INT8 BQ")
    ]
    
    for path, name in models_to_test:
        try:
            emb = SFaceVariantEmb(path, name)
            embedders.append(emb)
            print(f"  ✅ {name}")
        except Exception as e:
            print(f"  ⚠️ Bỏ qua {name}: {e}")

    if not embedders:
        print("  ❌ Không có model nào khả dụng!")
        return

    print(f"\n[2/4] Thu thập ảnh từ {ds}...")
    images = sorted(f for f in ds.rglob("*") if f.is_file() and f.suffix.lower() in IMG_EXTS)
    if args.max > 0: images = images[:args.max]
    print(f"  📷 {len(images)} ảnh")
    if not images: return

    print(f"\n[3/4] Enroll gallery cho KNN...")
    galleries = []
    for emb in embedders:
        t0 = time.perf_counter()
        matrix, labels = enroll_gallery(images, detector, emb, max_enroll=300)
        galleries.append((matrix, labels))
        print(f"  {emb.name}: {matrix.shape[0]} embeddings ({time.perf_counter()-t0:.1f}s)")

    print(f"\n[4/4] Benchmark...")
    results = benchmark_models(images, detector, embedders, galleries)

    print_report(results, sys_info, str(ds))
    save_csv(results, sys_info, str(ds), out_dir)
    print("  ✅ Hoàn tất!")

if __name__ == "__main__":
    main()
