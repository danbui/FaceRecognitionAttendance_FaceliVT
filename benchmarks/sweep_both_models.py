"""
Sweep Threshold cho SFace & FaceLiVT → Tìm ngưỡng tối ưu → So sánh.

  cd /d "D:\DAN\2. DAN\Bài tập\TTNT cho hệ thống nhúng\Đồ án hệ thống nhúng\FaceRecognitionAttendance"
  python benchmarks/sweep_both_models.py
  python benchmarks/sweep_both_models.py --max-people 50
"""
import sys, time, random, argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.face_detector import FaceDetector
from app.config import SFACE_MODEL, FACELIVT_MODEL

IMG_EXTS = {".jpg", ".jpeg", ".png"}
SEED = 42

ARCFACE_DST = np.array([
    [38.2946, 51.6963], [73.5318, 51.5014],
    [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]
], dtype=np.float32)


# ── Embedders ──
def align_face(frame, det, size=112):
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

def imread_u(path):
    buf = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


class SFaceEmb:
    name = "SFace"
    def __init__(self):
        try:
            buf = np.fromfile(str(SFACE_MODEL), dtype=np.uint8)
            self.rec = cv2.FaceRecognizerSF.create(framework="onnx",
                bufferModel=buf, bufferConfig=np.array([], dtype=np.uint8))
        except TypeError:
            self.rec = cv2.FaceRecognizerSF.create(str(SFACE_MODEL), "")
        self.embed_dim = 128

    def get_embedding(self, frame, det):
        aligned = self.rec.alignCrop(frame, det)
        feat = self.rec.feature(aligned).flatten()
        n = np.linalg.norm(feat)
        return feat / n if n > 1e-8 else feat


class FaceLiVTEmb:
    name = "FaceLiVT"
    def __init__(self):
        import onnxruntime as ort
        self.sess = ort.InferenceSession(str(FACELIVT_MODEL), providers=['CPUExecutionProvider'])
        self.inp = self.sess.get_inputs()[0].name
        dummy = np.random.randn(1, 3, 112, 112).astype(np.float32)
        self.embed_dim = self.sess.run(None, {self.inp: dummy})[0].flatten().shape[0]

    def get_embedding(self, frame, det):
        face = align_face(frame, det)
        if face is None: return np.zeros(self.embed_dim, dtype=np.float32)
        rgb = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
        blob = (rgb.astype(np.float32) - 127.5) / 127.5
        blob = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]
        emb = self.sess.run(None, {self.inp: blob})[0].flatten()
        n = np.linalg.norm(emb)
        return emb / n if n > 1e-8 else emb


# ── Data split ──
def split_dataset(data_dir, test_ratio=0.2, max_people=0):
    rng = random.Random(SEED)
    split = {}
    people = sorted([d for d in data_dir.iterdir() if d.is_dir()])
    if max_people > 0: people = people[:max_people]
    for pdir in people:
        label = pdir.name
        imgs = sorted(f for f in pdir.iterdir() if f.suffix.lower() in IMG_EXTS)
        if len(imgs) < 2: continue
        rng.shuffle(imgs)
        n_test = max(1, int(len(imgs) * test_ratio))
        split[label] = {"gallery": imgs[n_test:], "probe": imgs[:n_test]}
    return split


# ── Enroll ──
def enroll_gallery(split, detector, embedder):
    all_embs, all_labels = [], []
    for label, data in split.items():
        for path in data["gallery"]:
            img = imread_u(path)
            if img is None: continue
            dets = detector.detect_all(img)
            if dets is None: continue
            det = dets[int(np.argmax(dets[:, 2] * dets[:, 3]))]
            emb = embedder.get_embedding(img, det).flatten()
            n = np.linalg.norm(emb)
            if n < 1e-8: continue
            all_embs.append(emb / n)
            all_labels.append(label)
    matrix = np.array(all_embs, dtype=np.float32) if all_embs else np.zeros((0, embedder.embed_dim))
    return matrix, all_labels


# ── Extract probe embeddings (1 lần, dùng lại cho mọi threshold) ──
def extract_probes(split, detector, embedder):
    probes = []  # list of (true_label, emb_vector)
    no_face = 0
    for label, data in split.items():
        for path in data["probe"]:
            img = imread_u(path)
            if img is None: continue
            dets = detector.detect_all(img)
            if dets is None:
                no_face += 1
                continue
            det = dets[int(np.argmax(dets[:, 2] * dets[:, 3]))]
            emb = embedder.get_embedding(img, det).flatten()
            n = np.linalg.norm(emb)
            if n < 1e-8:
                no_face += 1
                continue
            probes.append((label, emb / n))
    return probes, no_face


# ── Evaluate at 1 threshold (pure numpy, no re-extraction) ──
def evaluate_at_threshold(probes, matrix, gallery_labels, threshold):
    correct, wrong, unknown = 0, 0, 0
    for true_label, emb in probes:
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
            if pred == true_label:
                correct += 1
            else:
                wrong += 1
    total = correct + wrong + unknown
    acc = correct / total * 100 if total else 0
    far = wrong / total * 100 if total else 0
    frr = unknown / total * 100 if total else 0
    return {"thr": threshold, "acc": acc, "far": far, "frr": frr,
            "correct": correct, "wrong": wrong, "unknown": unknown, "total": total}


# ── Sweep ──
def sweep(probes, matrix, gallery_labels, thresholds):
    results = []
    for thr in thresholds:
        r = evaluate_at_threshold(probes, matrix, gallery_labels, thr)
        results.append(r)
    return results


# ── Main ──
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default="dataset_clean")
    parser.add_argument("--max-people", type=int, default=0)
    parser.add_argument("--test-ratio", type=float, default=0.2)
    parser.add_argument("--step", type=float, default=0.025,
                        help="Bước nhảy threshold (mặc định 0.025)")
    args = parser.parse_args()

    ds = Path(args.dataset)
    if not ds.is_absolute(): ds = PROJECT_ROOT / ds
    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(exist_ok=True)

    thresholds = np.arange(0.10, 0.85, args.step).tolist()

    print("=" * 70)
    print("  🔍 SWEEP THRESHOLD: SFace vs FaceLiVT")
    print("=" * 70)

    detector = FaceDetector()

    print(f"\n[1/5] Tách dataset (gallery {100-args.test_ratio*100:.0f}% / probe {args.test_ratio*100:.0f}%)...")
    split = split_dataset(ds, test_ratio=args.test_ratio, max_people=args.max_people)
    n_people = len(split)
    n_gallery = sum(len(d["gallery"]) for d in split.values())
    n_probe = sum(len(d["probe"]) for d in split.values())
    print(f"  {n_people} người, {n_gallery} gallery, {n_probe} probe")

    all_results = {}

    for EmbClass in [SFaceEmb, FaceLiVTEmb]:
        emb = EmbClass()
        name = emb.name
        dim = emb.embed_dim

        step_n = "2" if name == "SFace" else "3"
        print(f"\n[{step_n}/5] {name} ({dim}-dim)...")

        # Enroll
        t0 = time.perf_counter()
        matrix, g_labels = enroll_gallery(split, detector, emb)
        print(f"  Gallery: {matrix.shape[0]} embeddings ({time.perf_counter()-t0:.1f}s)")

        # Extract probes
        t0 = time.perf_counter()
        probes, no_face = extract_probes(split, detector, emb)
        print(f"  Probes:  {len(probes)} (no_face={no_face}) ({time.perf_counter()-t0:.1f}s)")

        # Sweep
        t0 = time.perf_counter()
        results = sweep(probes, matrix, g_labels, thresholds)
        print(f"  Sweep:   {len(thresholds)} thresholds ({time.perf_counter()-t0:.1f}s)")

        all_results[name] = {
            "dim": dim, "results": results, "no_face": no_face,
            "n_probes": len(probes),
        }

        # Print sweep table
        print(f"\n  {'Thr':>6} │ {'Acc%':>7} │ {'FAR%':>7} │ {'FRR%':>7} │ {'Correct':>7} │ {'Wrong':>6} │ {'Unknown':>7}")
        print(f"  {'─'*6}─┼─{'─'*7}─┼─{'─'*7}─┼─{'─'*7}─┼─{'─'*7}─┼─{'─'*6}─┼─{'─'*7}")
        for r in results:
            marker = " ★" if r["acc"] == max(x["acc"] for x in results) else "  "
            print(f"{marker}{r['thr']:>5.3f} │ {r['acc']:>7.2f} │ {r['far']:>7.2f} │ {r['frr']:>7.2f} │ "
                  f"{r['correct']:>7} │ {r['wrong']:>6} │ {r['unknown']:>7}")

    # ═══════════════════════════════════════════════════════
    #  Tìm ngưỡng tối ưu & so sánh
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"  ⭐ KẾT QUẢ: NGƯỠNG TỐI ƯU CỦA TỪNG MÔ HÌNH")
    print(f"{'='*70}")

    best = {}
    for name in ["SFace", "FaceLiVT"]:
        data = all_results[name]
        # Tìm threshold có accuracy cao nhất
        # Nếu hòa accuracy, ưu tiên FAR thấp nhất
        b = max(data["results"], key=lambda r: (r["acc"], -r["far"]))
        best[name] = b
        dim = data["dim"]
        print(f"\n  {name} ({dim}-dim):")
        print(f"    Threshold tối ưu : {b['thr']:.3f}")
        print(f"    Accuracy         : {b['acc']:.2f}%")
        print(f"    FAR (nhầm người) : {b['far']:.2f}% ({b['wrong']} lần)")
        print(f"    FRR (từ chối sai): {b['frr']:.2f}% ({b['unknown']} lần)")
        print(f"    Correct/Total    : {b['correct']}/{b['total']}")

    # Bảng so sánh tại ngưỡng tối ưu
    s, f = best["SFace"], best["FaceLiVT"]
    sd, fd = all_results["SFace"]["dim"], all_results["FaceLiVT"]["dim"]

    print(f"\n{'='*70}")
    print(f"  ⚡ SO SÁNH TẠI NGƯỠNG TỐI ƯU")
    print(f"{'='*70}")
    print(f"  {'Metric':<25} │ {'SFace ('+str(sd)+'d)':>18} │ {'FaceLiVT ('+str(fd)+'d)':>18}")
    print(f"  {'─'*25}─┼─{'─'*18}─┼─{'─'*18}")
    rows = [
        ("Threshold tối ưu", f"{s['thr']:.3f}", f"{f['thr']:.3f}"),
        ("Accuracy (%)", f"{s['acc']:.2f}%", f"{f['acc']:.2f}%"),
        ("FAR — nhầm người (%)", f"{s['far']:.2f}%", f"{f['far']:.2f}%"),
        ("FRR — từ chối sai (%)", f"{s['frr']:.2f}%", f"{f['frr']:.2f}%"),
        ("Correct / Total", f"{s['correct']}/{s['total']}", f"{f['correct']}/{f['total']}"),
        ("Wrong (nhầm)", str(s["wrong"]), str(f["wrong"])),
        ("Unknown (dưới thr)", str(s["unknown"]), str(f["unknown"])),
    ]
    for label, sv, fv in rows:
        print(f"  {label:<25} │ {sv:>18} │ {fv:>18}")
    print(f"{'='*70}")

    winner = "SFace" if s["acc"] > f["acc"] else "FaceLiVT" if f["acc"] > s["acc"] else "Hòa"
    print(f"  🏆 Winner (Accuracy): {winner}")
    safer = "SFace" if s["far"] < f["far"] else "FaceLiVT" if f["far"] < s["far"] else "Hòa"
    print(f"  🔒 Safer (FAR thấp): {safer}")

    # ── Plot ──
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 3, figsize=(18, 5))

        for name, color in [("SFace", "#2196F3"), ("FaceLiVT", "#FF5722")]:
            data = all_results[name]["results"]
            thrs = [r["thr"] for r in data]
            accs = [r["acc"] for r in data]
            fars = [r["far"] for r in data]
            frrs = [r["frr"] for r in data]

            axes[0].plot(thrs, accs, '-o', color=color, markersize=3, label=f'{name} ({all_results[name]["dim"]}d)')
            axes[1].plot(thrs, fars, '-o', color=color, markersize=3, label=f'{name}')
            axes[2].plot(thrs, frrs, '-o', color=color, markersize=3, label=f'{name}')

        # Mark optimal
        for name, marker, color in [("SFace", "s", "#1565C0"), ("FaceLiVT", "D", "#BF360C")]:
            b = best[name]
            axes[0].axvline(b["thr"], color=color, linestyle='--', alpha=0.5)
            axes[0].plot(b["thr"], b["acc"], marker, color=color, markersize=10, zorder=5)

        axes[0].set_title("Accuracy vs Threshold", fontweight='bold')
        axes[0].set_xlabel("Threshold"); axes[0].set_ylabel("Accuracy (%)")
        axes[0].legend(); axes[0].grid(True, alpha=0.3)

        axes[1].set_title("FAR (nhầm người) vs Threshold", fontweight='bold')
        axes[1].set_xlabel("Threshold"); axes[1].set_ylabel("FAR (%)")
        axes[1].legend(); axes[1].grid(True, alpha=0.3)

        axes[2].set_title("FRR (từ chối sai) vs Threshold", fontweight='bold')
        axes[2].set_xlabel("Threshold"); axes[2].set_ylabel("FRR (%)")
        axes[2].legend(); axes[2].grid(True, alpha=0.3)

        plt.suptitle(f"Threshold Sweep — SFace vs FaceLiVT ({n_people} người, {n_probe} probe)",
                     fontsize=14, fontweight='bold')
        plt.tight_layout()
        plot_path = out_dir / f"sweep_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        plt.savefig(str(plot_path), dpi=150, bbox_inches='tight')
        print(f"\n  📊 Plot: {plot_path}")
    except ImportError:
        print("  ⚠️ matplotlib chưa cài, bỏ qua vẽ biểu đồ.")

    # ── Save CSV ──
    csv_path = out_dir / f"sweep_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(csv_path, "w", encoding="utf-8") as fh:
        fh.write("model,dim,threshold,accuracy,far,frr,correct,wrong,unknown,total\n")
        for name in ["SFace", "FaceLiVT"]:
            d = all_results[name]
            for r in d["results"]:
                fh.write(f"{name},{d['dim']},{r['thr']:.3f},{r['acc']:.2f},{r['far']:.2f},"
                         f"{r['frr']:.2f},{r['correct']},{r['wrong']},{r['unknown']},{r['total']}\n")
    print(f"  📄 CSV: {csv_path}")
    print(f"  ✅ Hoàn tất!")


if __name__ == "__main__":
    main()
