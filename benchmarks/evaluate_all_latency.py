"""
Script đánh giá Latency (Tốc độ) toàn diện cho 8 mô hình nhận diện khuôn mặt.
Các bước đo lường được cô lập hoàn toàn cho từng model để đảm bảo tính công bằng (Cache Isolated).

Cách chạy:
  python benchmarks/evaluate_all_latency.py --dataset dataset_clean --max-latency 200
"""
import sys, time, argparse, csv
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

# ── BENCHMARK CORE ──────────────────────────────────────────────
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
    print(f"⏱️ BENCHMARK LATENCY (FULL PIPELINE CACHE-ISOLATED)")
    print(f"{'='*70}")

    print("  [+] Building dummy gallery for KNN (Warmup)...")
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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default="dataset_clean")
    parser.add_argument("--max-latency", type=int, default=200)
    args = parser.parse_args()

    ds = Path(args.dataset)
    if not ds.is_absolute(): ds = PROJECT_ROOT / ds
    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(exist_ok=True)

    print("=" * 80)
    print("  🚀 ĐÁNH GIÁ TỐC ĐỘ (LATENCY) CHO TẤT CẢ MÔ HÌNH")
    print("=" * 80)

    detector = FaceDetector()
    selector = BestFrameSelector()

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

    all_images = sorted(f for f in ds.rglob("*") if f.is_file() and f.suffix.lower() in IMG_EXTS)
    lat_images = all_images[:args.max_latency] if args.max_latency > 0 else all_images
    
    lat_res = run_latency_benchmark(lat_images, detector, selector, embedders)
    print_latency_report(lat_res, embedders)

    # Save CSV
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = out_dir / f"latency_all_models_{ts}.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Model", "Detect_Mean", "Select_Mean", "Align_Mean", "Embed_Mean", "KNN_Mean", "Total_Mean", "FPS", "Total_P95", "Total_Max"])
        for emb in embedders:
            w.writerow([
                emb.name,
                f"{lat_res['det'][emb.name]['mean']:.2f}",
                f"{lat_res['bf'][emb.name]['mean']:.2f}",
                f"{lat_res['aln'][emb.name]['mean']:.2f}",
                f"{lat_res['emb'][emb.name]['mean']:.2f}",
                f"{lat_res['knn'][emb.name]['mean']:.2f}",
                f"{lat_res['tot'][emb.name]['mean']:.2f}",
                f"{1000 / max(lat_res['tot'][emb.name]['mean'], 1):.1f}",
                f"{lat_res['tot'][emb.name]['p95']:.2f}",
                f"{lat_res['tot'][emb.name]['max']:.2f}",
            ])
    print(f"\n✅ Đã lưu kết quả Latency ra: {csv_path}")

if __name__ == "__main__":
    main()
