"""
Benchmark Latency — So sánh 3 mô hình: SFace vs FaceLiVT2_S_FP32 vs FaceLiVT2_S_INT8.

Đo từng bước pipeline: Detection → Alignment → Embedding → KNN Matching.
Detection & Alignment chạy chung, Embedding & KNN chạy riêng cho mỗi model.

Cách chạy:
  python benchmarks/benchmark_latency_3models.py
  python benchmarks/benchmark_latency_3models.py --max 200
  python benchmarks/benchmark_latency_3models.py --dataset dataset_clean --max 500
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
from app.config import SFACE_MODEL, FACELIVT_MODEL, MODELS_DIR

FACELIVT_INT8_MODEL = MODELS_DIR / "facelivtv2_s_512_int8.onnx"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
ARCFACE_DST = np.array([
    [38.2946, 51.6963], [73.5318, 51.5014],
    [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]
], dtype=np.float32)


# ═══════════════════════════════════════════════════════════
#  Utilities
# ═══════════════════════════════════════════════════════════

def imread_u(path):
    buf = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)

def align_face(frame, det, size=112):
    try:
        lm = det[4:14].reshape((5, 2))
        dst = ARCFACE_DST * (float(size) / 112.0)
        M, _ = cv2.estimateAffinePartial2D(lm, dst)
        if M is None:
            M = cv2.getAffineTransform(lm[:3], dst[:3])
        return cv2.warpAffine(frame, M, (size, size), borderValue=0.0)
    except Exception:
        x, y, w, h = det[:4].astype(int)
        crop = frame[max(0,y):min(frame.shape[0],y+h), max(0,x):min(frame.shape[1],x+w)]
        return cv2.resize(crop, (size, size)) if crop.size > 0 else None

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
    try:
        import onnxruntime as ort
        info["onnxruntime"] = ort.__version__
    except ImportError:
        info["onnxruntime"] = "N/A"
    return info


# ═══════════════════════════════════════════════════════════
#  Embedders
# ═══════════════════════════════════════════════════════════

class SFaceEmb:
    name = "SFace"
    def __init__(self):
        try:
            buf = np.fromfile(str(SFACE_MODEL), dtype=np.uint8)
            self.rec = cv2.FaceRecognizerSF.create(
                framework="onnx", bufferModel=buf,
                bufferConfig=np.array([], dtype=np.uint8))
        except TypeError:
            self.rec = cv2.FaceRecognizerSF.create(str(SFACE_MODEL), "")
        self.embed_dim = 128

    def get_embedding(self, frame, det):
        aligned = self.rec.alignCrop(frame, det)
        feat = self.rec.feature(aligned).flatten()
        n = np.linalg.norm(feat)
        return feat / n if n > 1e-8 else feat


class FaceLiVTEmb:
    name = "FaceLiVT2_S_FP32"
    def __init__(self):
        import onnxruntime as ort
        self.sess = ort.InferenceSession(str(FACELIVT_MODEL), providers=['CPUExecutionProvider'])
        self.inp = self.sess.get_inputs()[0].name
        dummy = np.random.randn(1, 3, 112, 112).astype(np.float32)
        self.embed_dim = self.sess.run(None, {self.inp: dummy})[0].flatten().shape[0]

    def get_embedding(self, frame, det):
        face = align_face(frame, det)
        if face is None:
            return np.zeros(self.embed_dim, dtype=np.float32)
        rgb = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
        blob = (rgb.astype(np.float32) - 127.5) / 127.5
        blob = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]
        emb = self.sess.run(None, {self.inp: blob})[0].flatten()
        n = np.linalg.norm(emb)
        return emb / n if n > 1e-8 else emb


class FaceLiVTInt8Emb:
    name = "FaceLiVT2_S_INT8"
    def __init__(self):
        import onnxruntime as ort
        if not FACELIVT_INT8_MODEL.exists():
            raise FileNotFoundError(f"INT8 model not found: {FACELIVT_INT8_MODEL}")
        self.sess = ort.InferenceSession(str(FACELIVT_INT8_MODEL), providers=['CPUExecutionProvider'])
        self.inp = self.sess.get_inputs()[0].name
        dummy = np.random.randn(1, 3, 112, 112).astype(np.float32)
        self.embed_dim = self.sess.run(None, {self.inp: dummy})[0].flatten().shape[0]

    def get_embedding(self, frame, det):
        face = align_face(frame, det)
        if face is None:
            return np.zeros(self.embed_dim, dtype=np.float32)
        rgb = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
        blob = (rgb.astype(np.float32) - 127.5) / 127.5
        blob = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]
        emb = self.sess.run(None, {self.inp: blob})[0].flatten()
        n = np.linalg.norm(emb)
        return emb / n if n > 1e-8 else emb


# ═══════════════════════════════════════════════════════════
#  Gallery & KNN
# ═══════════════════════════════════════════════════════════

def enroll_gallery(images, detector, embedder, max_enroll=500):
    """Enroll một phần ảnh làm gallery cho KNN matching."""
    embs, labels = [], []
    for p in images[:max_enroll]:
        img = imread_u(p)
        if img is None:
            continue
        dets = detector.detect_all(img)
        if dets is None:
            continue
        det = dets[int(np.argmax(dets[:, 2] * dets[:, 3]))]
        emb = embedder.get_embedding(img, det).flatten()
        n = np.linalg.norm(emb)
        if n < 1e-8:
            continue
        embs.append(emb / n)
        labels.append(p.parent.name)
    if not embs:
        return np.zeros((0, embedder.embed_dim), dtype=np.float32), []
    return np.array(embs, dtype=np.float32), labels


def knn_match(query, matrix, labels, k=5, threshold=0.3):
    if matrix.shape[0] == 0:
        return None
    q = query.flatten()
    n = np.linalg.norm(q)
    if n < 1e-8:
        return None
    q = q / n
    scores = matrix @ q
    K = min(k, len(scores))
    top_k = np.argsort(scores)[-K:][::-1]
    votes = defaultdict(int)
    for idx in top_k:
        if float(scores[idx]) >= threshold:
            votes[labels[idx]] += 1
    if not votes:
        return None
    return max(votes, key=votes.get)


# ═══════════════════════════════════════════════════════════
#  Benchmark Core
# ═══════════════════════════════════════════════════════════

def benchmark_models(images, detector, embedders, galleries, warmup=5):
    """Benchmark tất cả model. Detection chạy chung, embedding & KNN riêng."""
    model_names = [e.name for e in embedders]

    # Warmup
    print(f"  Warmup ({warmup} ảnh)...")
    for p in images[:warmup]:
        img = imread_u(p)
        if img is None:
            continue
        dets = detector.detect_all(img)
        if dets is None:
            continue
        det = dets[int(np.argmax(dets[:, 2] * dets[:, 3]))]
        for emb in embedders:
            emb.get_embedding(img, det)

    # Accumulators
    det_times = []
    align_times = []
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

        # 1. Detection (SHARED)
        t0 = time.perf_counter()
        dets = detector.detect_all(img)
        dt_det = (time.perf_counter() - t0) * 1000
        det_times.append(dt_det)

        if dets is None:
            continue
        det = dets[int(np.argmax(dets[:, 2] * dets[:, 3]))]
        n_faces += 1

        # 2. Alignment (SHARED — tính riêng cho FaceLiVT models)
        t0 = time.perf_counter()
        _ = align_face(img, det)
        dt_align = (time.perf_counter() - t0) * 1000
        align_times.append(dt_align)

        # 3. Embedding + KNN per model
        for i, emb_model in enumerate(embedders):
            name = emb_model.name
            matrix, labels = galleries[i]

            # Embedding
            t0 = time.perf_counter()
            emb_vec = emb_model.get_embedding(img, det)
            dt_emb = (time.perf_counter() - t0) * 1000
            emb_times[name].append(dt_emb)

            # KNN Matching
            t0 = time.perf_counter()
            _ = knn_match(emb_vec, matrix, labels)
            dt_knn = (time.perf_counter() - t0) * 1000
            knn_times[name].append(dt_knn)

            # Total = detection + embedding + knn
            total_times[name].append(dt_det + dt_emb + dt_knn)

        if (idx + 1) % 200 == 0 or (idx + 1) == total:
            print(f"    [{idx+1}/{total}] faces={n_faces} errors={n_errors}")

    return {
        "detection": stats(det_times),
        "alignment": stats(align_times),
        "emb": {name: stats(emb_times[name]) for name in model_names},
        "knn": {name: stats(knn_times[name]) for name in model_names},
        "total": {name: stats(total_times[name]) for name in model_names},
        "n_total": total, "n_faces": n_faces, "n_errors": n_errors,
        "model_names": model_names,
        "dims": {e.name: e.embed_dim for e in embedders},
    }


# ═══════════════════════════════════════════════════════════
#  Reports
# ═══════════════════════════════════════════════════════════

def print_report(r, sys_info, source):
    names = r["model_names"]
    dims = r["dims"]

    print(f"\n{'='*100}")
    print(f"  ⏱️  BENCHMARK LATENCY — 3 Models")
    print(f"{'='*100}")
    print(f"  Thời gian  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Platform   : {sys_info['platform']} ({sys_info['machine']})")
    print(f"  OpenCV     : {sys_info['opencv']}   ONNX RT: {sys_info['onnxruntime']}")
    print(f"  Dataset    : {source}")
    print(f"  Tổng ảnh   : {r['n_total']}  |  Có mặt: {r['n_faces']}  |  Lỗi: {r['n_errors']}")
    print(f"{'-'*100}")

    # Header
    col_w = 18
    hdr = f"  {'Bước':<30}"
    for n in names:
        hdr += f" │ {n+f' ({dims[n]}d)':>{col_w}}"
    print(hdr)
    sep = f"  {'─'*30}"
    for _ in names:
        sep += f"─┼─{'─'*col_w}"
    print(sep)

    # Shared steps
    det = r["detection"]
    aln = r["alignment"]
    det_line = f"  {'1. Detection (YuNet)':<30}"
    aln_line = f"  {'2. Alignment (ArcFace)':<30}"
    for _ in names:
        det_line += f" │ {det['mean']:>{col_w-2}.2f}ms"
        aln_line += f" │ {aln['mean']:>{col_w-2}.2f}ms"
    print(det_line + "  (shared)")
    print(aln_line + "  (shared)")

    # Per-model steps
    emb_line = f"  {'3. Embedding':<30}"
    knn_line = f"  {'4. KNN Top-5 Matching':<30}"
    for n in names:
        emb_line += f" │ {r['emb'][n]['mean']:>{col_w-2}.2f}ms"
        knn_line += f" │ {r['knn'][n]['mean']:>{col_w-2}.2f}ms"
    print(emb_line)
    print(knn_line)

    print(sep)

    # Totals
    tot_line = f"  {'★ TỔNG PIPELINE':<30}"
    for n in names:
        tot_line += f" │ {r['total'][n]['mean']:>{col_w-2}.2f}ms"
    print(tot_line)

    # FPS
    fps_line = f"  {'  → FPS':<30}"
    for n in names:
        m = r["total"][n]["mean"]
        fps_line += f" │ {'~'+str(int(1000/max(m,1)))+' FPS':>{col_w}}"
    print(fps_line)

    print(f"{'='*100}")

    # P95 table
    print(f"\n  📊 Chi tiết thống kê (ms):")
    print(f"  {'Model':<25} │ {'Mean':>8} │ {'Median':>8} │ {'P95':>8} │ {'Min':>8} │ {'Max':>8} │ {'StdDev':>8}")
    print(f"  {'─'*25}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*8}")
    for n in names:
        s = r["total"][n]
        print(f"  {n+f' ({dims[n]}d)':<25} │ {s['mean']:>8.2f} │ {s['med']:>8.2f} │ "
              f"{s['p95']:>8.2f} │ {s['min']:>8.2f} │ {s['max']:>8.2f} │ {s['std']:>8.2f}")

    # Winner
    print()
    sorted_names = sorted(names, key=lambda n: r["total"][n]["mean"])
    fastest = sorted_names[0]
    slowest = sorted_names[-1]
    ratio = r["total"][slowest]["mean"] / max(r["total"][fastest]["mean"], 0.01)
    print(f"  🏆 Nhanh nhất: {fastest} ({r['total'][fastest]['mean']:.1f}ms) — "
          f"nhanh hơn {slowest} ~{ratio:.1f}x")

    for n in sorted_names:
        m = r["total"][n]["mean"]
        if m < 100:
            v = "✅ Real-time"
        elif m < 200:
            v = "✅ Tốt"
        elif m < 500:
            v = "⚠️ Trung bình"
        else:
            v = "❌ Chậm"
        print(f"  {n:>25}: {v} ({m:.1f}ms, ~{1000/max(m,1):.0f} FPS)")
    print()


def save_csv(r, sys_info, source, out_dir):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    names = r["model_names"]
    dims = r["dims"]

    csv_path = out_dir / f"latency_3models_{ts}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["step", "model", "dim", "mean_ms", "median_ms", "p95_ms", "min_ms", "max_ms", "count"])

        # Shared steps
        det = r["detection"]
        aln = r["alignment"]
        w.writerow(["detection", "shared", "", f"{det['mean']:.2f}", f"{det['med']:.2f}",
                     f"{det['p95']:.2f}", f"{det['min']:.2f}", f"{det['max']:.2f}", det['n']])
        w.writerow(["alignment", "shared", "", f"{aln['mean']:.2f}", f"{aln['med']:.2f}",
                     f"{aln['p95']:.2f}", f"{aln['min']:.2f}", f"{aln['max']:.2f}", aln['n']])

        # Per-model
        for step_key in ["emb", "knn", "total"]:
            for n in names:
                s = r[step_key][n]
                w.writerow([step_key, n, dims[n], f"{s['mean']:.2f}", f"{s['med']:.2f}",
                             f"{s['p95']:.2f}", f"{s['min']:.2f}", f"{s['max']:.2f}", s['n']])

        w.writerow([])
        w.writerow(["# METADATA"])
        for k, v in sys_info.items():
            w.writerow([k, v])
        w.writerow(["source", source])
        w.writerow(["timestamp", datetime.now().isoformat()])

    print(f"  📄 CSV: {csv_path}")
    return csv_path


def save_plot(r, out_dir):
    """Vẽ biểu đồ bar chart so sánh latency 3 model."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  ⚠️ matplotlib chưa cài, bỏ qua vẽ biểu đồ.")
        return

    names = r["model_names"]
    dims = r["dims"]
    colors = {"SFace": "#2196F3", "FaceLiVT2_S_FP32": "#FF5722", "FaceLiVT2_S_INT8": "#4CAF50"}

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Bar chart: Latency breakdown
    ax = axes[0]
    x = np.arange(len(names))
    width = 0.2
    det_vals = [r["detection"]["mean"]] * len(names)
    emb_vals = [r["emb"][n]["mean"] for n in names]
    knn_vals = [r["knn"][n]["mean"] for n in names]

    bars1 = ax.bar(x - width, det_vals, width, label="Detection", color="#78909C", alpha=0.8)
    bars2 = ax.bar(x, emb_vals, width, label="Embedding", color=[colors.get(n, "#999") for n in names], alpha=0.8)
    bars3 = ax.bar(x + width, knn_vals, width, label="KNN Match", color="#FFC107", alpha=0.8)

    ax.set_xlabel("Model")
    ax.set_ylabel("Latency (ms)")
    ax.set_title("Latency Breakdown per Step", fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{n}\n({dims[n]}d)" for n in names], fontsize=8)
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')

    # Add value labels
    for bars in [bars1, bars2, bars3]:
        for bar in bars:
            h = bar.get_height()
            if h > 0.1:
                ax.text(bar.get_x() + bar.get_width()/2., h + 0.3,
                        f'{h:.1f}', ha='center', va='bottom', fontsize=7)

    # Bar chart: Total pipeline
    ax2 = axes[1]
    totals = [r["total"][n]["mean"] for n in names]
    p95s = [r["total"][n]["p95"] for n in names]
    bar_colors = [colors.get(n, "#999") for n in names]

    bars = ax2.bar(x, totals, 0.5, color=bar_colors, alpha=0.8, label="Mean")
    ax2.bar(x, p95s, 0.5, color=bar_colors, alpha=0.3, label="P95")

    ax2.set_xlabel("Model")
    ax2.set_ylabel("Latency (ms)")
    ax2.set_title("Total Pipeline Latency", fontweight="bold")
    ax2.set_xticks(x)
    ax2.set_xticklabels([f"{n}\n({dims[n]}d)" for n in names], fontsize=8)
    ax2.legend()
    ax2.grid(True, alpha=0.3, axis='y')

    for bar, val in zip(bars, totals):
        ax2.text(bar.get_x() + bar.get_width()/2., val + 0.5,
                 f'{val:.1f}ms\n~{1000/max(val,1):.0f} FPS',
                 ha='center', va='bottom', fontsize=8, fontweight='bold')

    plt.suptitle(f"Benchmark Latency — 3 Models ({r['n_faces']} faces)",
                 fontsize=13, fontweight='bold')
    plt.tight_layout()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    plot_path = out_dir / f"latency_3models_{ts}.png"
    plt.savefig(str(plot_path), dpi=150, bbox_inches='tight')
    print(f"  📊 Plot: {plot_path}")


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Benchmark Latency: SFace vs FaceLiVT FP32 vs INT8")
    parser.add_argument("--dataset", type=str, default="dataset_clean")
    parser.add_argument("--max", type=int, default=0, help="Giới hạn số ảnh (0 = tất cả)")
    args = parser.parse_args()

    ds = Path(args.dataset)
    if not ds.is_absolute():
        ds = PROJECT_ROOT / ds
    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(exist_ok=True)

    print("=" * 80)
    print("  ⏱️  BENCHMARK LATENCY: SFace vs FaceLiVT2_S_FP32 vs FaceLiVT2_S_INT8")
    print("=" * 80)

    sys_info = get_sys_info()
    print(f"  Platform: {sys_info['platform']} ({sys_info['machine']})")
    print(f"  OpenCV: {sys_info['opencv']}  ONNX RT: {sys_info['onnxruntime']}")

    # 1. Init models
    print(f"\n[1/4] Khởi tạo models...")
    detector = FaceDetector()
    embedders = []
    for EmbClass in [SFaceEmb, FaceLiVTEmb, FaceLiVTInt8Emb]:
        try:
            emb = EmbClass()
            embedders.append(emb)
            print(f"  ✅ {emb.name}: {emb.embed_dim}-dim")
        except Exception as e:
            print(f"  ⚠️ Bỏ qua {EmbClass.name}: {e}")

    if not embedders:
        print("  ❌ Không có model nào khả dụng!")
        return

    # 2. Collect images
    print(f"\n[2/4] Thu thập ảnh từ {ds}...")
    images = sorted(f for f in ds.rglob("*") if f.is_file() and f.suffix.lower() in IMG_EXTS)
    if args.max > 0:
        images = images[:args.max]
    print(f"  📷 {len(images)} ảnh")
    if not images:
        print("  ❌ Không có ảnh!")
        return

    # 3. Enroll galleries
    print(f"\n[3/4] Enroll gallery cho KNN...")
    galleries = []
    for emb in embedders:
        t0 = time.perf_counter()
        matrix, labels = enroll_gallery(images, detector, emb, max_enroll=300)
        dt = time.perf_counter() - t0
        galleries.append((matrix, labels))
        print(f"  {emb.name}: {matrix.shape[0]} embeddings ({dt:.1f}s)")

    # 4. Benchmark
    print(f"\n[4/4] Benchmark ({len(images)} ảnh)...")
    results = benchmark_models(images, detector, embedders, galleries)

    # Reports
    print_report(results, sys_info, str(ds))
    save_csv(results, sys_info, str(ds), out_dir)
    save_plot(results, out_dir)
    print("  ✅ Hoàn tất!")


if __name__ == "__main__":
    main()
