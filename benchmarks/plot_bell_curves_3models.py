"""
Vẽ biểu đồ Bell Curves (phân bố Cosine Similarity) cho 3 model:
  SFace (128d), FaceLiVT2_S_FP32 (512d), FaceLiVT2_S_INT8 (512d)

Tính toán tất cả cặp same-person / diff-person từ dataset_clean,
vẽ histogram + đánh dấu threshold tối ưu.

Cách chạy:
  python benchmarks/plot_bell_curves_3models.py
  python benchmarks/plot_bell_curves_3models.py --dataset dataset_clean --max-people 50
"""
import sys, time, random, argparse
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.face_detector import FaceDetector
from app.config import SFACE_MODEL, FACELIVT_MODEL, MODELS_DIR

FACELIVT_INT8_MODEL = MODELS_DIR / "facelivtv2_s_512_int8.onnx"
IMG_EXTS = {".jpg", ".jpeg", ".png"}
SEED = 42

ARCFACE_DST = np.array([
    [38.2946, 51.6963], [73.5318, 51.5014],
    [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]
], dtype=np.float32)


# ── Utilities ──
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


# ── Embedders ──
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


# ── Extract embeddings per person ──
def extract_all_embeddings(data_dir, detector, embedder, max_people=0, max_imgs_per_person=10):
    """Trích xuất embeddings cho mỗi người. Trả về dict {label: [emb1, emb2, ...]}."""
    people = sorted([d for d in data_dir.iterdir() if d.is_dir()])
    if max_people > 0:
        people = people[:max_people]

    rng = random.Random(SEED)
    person_embs = {}
    total = 0

    for pdir in people:
        label = pdir.name
        imgs = sorted(f for f in pdir.iterdir() if f.suffix.lower() in IMG_EXTS)
        if len(imgs) < 2:
            continue
        rng.shuffle(imgs)
        imgs = imgs[:max_imgs_per_person]

        embs = []
        for path in imgs:
            img = imread_u(path)
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
            total += 1

        if len(embs) >= 2:
            person_embs[label] = embs

    return person_embs, total


# ── Compute cosine pairs ──
def compute_score_pairs(person_embs):
    """Tính cosine similarity cho tất cả cặp same-person và diff-person."""
    same_scores = []
    diff_scores = []

    labels = list(person_embs.keys())
    # Same-person pairs
    for label in labels:
        embs = person_embs[label]
        for i in range(len(embs)):
            for j in range(i + 1, len(embs)):
                s = float(np.dot(embs[i], embs[j]))
                same_scores.append(s)

    # Diff-person pairs (sample to avoid O(N^4))
    rng = random.Random(SEED)
    all_emb_list = []
    for label in labels:
        for emb in person_embs[label]:
            all_emb_list.append((label, emb))

    max_diff_pairs = min(50000, len(all_emb_list) * (len(all_emb_list) - 1) // 2)
    diff_count = 0
    # Systematic sampling
    for i in range(len(all_emb_list)):
        for j in range(i + 1, len(all_emb_list)):
            if all_emb_list[i][0] != all_emb_list[j][0]:
                s = float(np.dot(all_emb_list[i][1], all_emb_list[j][1]))
                diff_scores.append(s)
                diff_count += 1
                if diff_count >= max_diff_pairs:
                    break
        if diff_count >= max_diff_pairs:
            break

    return same_scores, diff_scores


# ── Plot ──
def plot_bell_curves(all_data, out_dir, dataset_name):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n_models = len(all_data)
    fig, axes = plt.subplots(1, n_models, figsize=(7 * n_models, 5.5))
    if n_models == 1:
        axes = [axes]

    colors_same = {"SFace": "#4CAF50", "FaceLiVT2_S_FP32": "#2196F3", "FaceLiVT2_S_INT8": "#FF9800"}
    colors_diff = {"SFace": "#F44336", "FaceLiVT2_S_FP32": "#E91E63", "FaceLiVT2_S_INT8": "#FF5722"}
    opt_thresholds = {"SFace": 0.400, "FaceLiVT2_S_FP32": 0.200, "FaceLiVT2_S_INT8": 0.200}

    for ax, (name, data) in zip(axes, all_data.items()):
        same = data["same"]
        diff = data["diff"]
        dim = data["dim"]

        c_same = colors_same.get(name, "#4CAF50")
        c_diff = colors_diff.get(name, "#F44336")

        # Histogram
        w_same = np.ones(len(same)) / len(same)
        w_diff = np.ones(len(diff)) / len(diff)

        ax.hist(diff, bins=60, alpha=0.5, color=c_diff, weights=w_diff,
                label=f'Khác người ({len(diff):,} cặp)')
        ax.hist(same, bins=40, alpha=0.5, color=c_same, weights=w_same,
                label=f'Cùng người ({len(same):,} cặp)')

        # Mean lines
        mean_same = np.mean(same)
        mean_diff = np.mean(diff)
        ax.axvline(mean_same, color='darkgreen', linestyle='--', linewidth=1.5,
                   label=f'Mean cùng = {mean_same:.3f}')
        ax.axvline(mean_diff, color='darkred', linestyle='--', linewidth=1.5,
                   label=f'Mean khác = {mean_diff:.3f}')

        # Optimal threshold
        thr = opt_thresholds.get(name, 0.3)
        ax.axvline(thr, color='blue', linestyle=':', linewidth=2.5,
                   label=f'Threshold = {thr:.3f}')

        # Gap annotation
        gap = mean_same - mean_diff
        ax.annotate(f'Gap = {gap:.3f}',
                    xy=((mean_same + mean_diff) / 2, ax.get_ylim()[1] * 0.9 if ax.get_ylim()[1] > 0 else 0.1),
                    fontsize=10, fontweight='bold', ha='center',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.8))

        ax.set_title(f'{name} ({dim}d)', fontsize=13, fontweight='bold')
        ax.set_xlabel('Cosine Similarity')
        ax.set_ylabel('Tần suất (tỷ lệ)')
        ax.set_xlim(-0.3, 1.0)
        ax.legend(fontsize=7, loc='upper left')
        ax.grid(True, alpha=0.3)

    plt.suptitle(f'Phân bố Cosine Similarity — Genuine vs Impostor ({dataset_name})',
                 fontsize=14, fontweight='bold')
    plt.tight_layout()

    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    plot_path = out_dir / f"bell_curves_3models_{ts}.png"
    plt.savefig(str(plot_path), dpi=200, bbox_inches='tight')
    print(f"\n  📊 Bell Curves: {plot_path}")

    # Stats summary
    print(f"\n  {'Model':<25} │ {'Mean Same':>10} │ {'Mean Diff':>10} │ {'Gap':>8} │ {'Same pairs':>12} │ {'Diff pairs':>12}")
    print(f"  {'─'*25}─┼─{'─'*10}─┼─{'─'*10}─┼─{'─'*8}─┼─{'─'*12}─┼─{'─'*12}")
    for name, data in all_data.items():
        ms = np.mean(data["same"])
        md = np.mean(data["diff"])
        lbl = f"{name} ({data['dim']}d)"
        print(f"  {lbl:<25} │ {ms:>10.4f} │ {md:>10.4f} │ {ms-md:>8.4f} │ {len(data['same']):>12,} │ {len(data['diff']):>12,}")


# ── Main ──
def main():
    parser = argparse.ArgumentParser(description="Bell Curves: 3 Models Cosine Similarity Distribution")
    parser.add_argument("--dataset", type=str, default="dataset_clean")
    parser.add_argument("--max-people", type=int, default=0)
    parser.add_argument("--max-imgs", type=int, default=10,
                        help="Số ảnh tối đa mỗi người (mặc định 10)")
    args = parser.parse_args()

    ds = Path(args.dataset)
    if not ds.is_absolute():
        ds = PROJECT_ROOT / ds
    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(exist_ok=True)

    print("=" * 70)
    print("  🔔 BELL CURVES: SFace vs FaceLiVT2_S_FP32 vs FaceLiVT2_S_INT8")
    print("=" * 70)

    detector = FaceDetector()
    all_data = {}

    for EmbClass in [SFaceEmb, FaceLiVTEmb, FaceLiVTInt8Emb]:
        try:
            emb = EmbClass()
        except Exception as e:
            print(f"\n  ⚠️ Bỏ qua {EmbClass.name}: {e}")
            continue

        name = emb.name
        dim = emb.embed_dim
        print(f"\n[{name}] Extracting embeddings ({dim}-dim)...")

        t0 = time.perf_counter()
        person_embs, total = extract_all_embeddings(
            ds, detector, emb,
            max_people=args.max_people,
            max_imgs_per_person=args.max_imgs)
        dt = time.perf_counter() - t0
        print(f"  {len(person_embs)} người, {total} embeddings ({dt:.1f}s)")

        print(f"  Computing cosine pairs...")
        t0 = time.perf_counter()
        same, diff = compute_score_pairs(person_embs)
        dt = time.perf_counter() - t0
        print(f"  Same: {len(same):,} cặp, Diff: {len(diff):,} cặp ({dt:.1f}s)")

        all_data[name] = {"same": same, "diff": diff, "dim": dim}

    if not all_data:
        print("  ❌ Không có model nào!")
        return

    print(f"\n  Vẽ biểu đồ...")
    plot_bell_curves(all_data, out_dir, ds.name)
    print(f"  ✅ Hoàn tất!")


if __name__ == "__main__":
    main()
