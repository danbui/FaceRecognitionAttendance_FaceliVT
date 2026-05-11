"""
Confusion Matrix & Accuracy Report — So sánh SFace vs FaceLiVT FP32 vs FaceLiVT INT8.

Tách dataset_clean thành 80% gallery + 20% probe (test).
Enroll gallery → test probe → xuất confusion matrix + metrics.

Output:
  benchmarks/confusion_sface.png
  benchmarks/confusion_facelivt.png
  benchmarks/accuracy_report.txt

Cách chạy:
  python benchmarks/evaluate_accuracy.py
  python benchmarks/evaluate_accuracy.py --max-people 30
  python benchmarks/evaluate_accuracy.py --test-ratio 0.3
"""
import sys
import random
import time
import argparse
import unicodedata
import re
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

DATASET_DIR = PROJECT_ROOT / "dataset_clean"
IMG_EXTS = {".jpg", ".jpeg", ".png"}
SEED = 42

ARCFACE_DST = np.array([
    [38.2946, 51.6963], [73.5318, 51.5014],
    [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]
], dtype=np.float32)


# ═══════════════════════════════════════════════════════════
#  Utilities
# ═══════════════════════════════════════════════════════════

def slugify(text):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    return re.sub(r'[-\s]+', '_', text) or text.replace(" ", "_")

def imread_unicode(path):
    buf = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)

def align_face(frame, detection, size=112):
    try:
        lm = detection[4:14].reshape((5, 2))
        dst = ARCFACE_DST * (float(size) / 112.0)
        M, _ = cv2.estimateAffinePartial2D(lm, dst)
        if M is None:
            M = cv2.getAffineTransform(lm[:3], dst[:3])
        return cv2.warpAffine(frame, M, (size, size), borderValue=0.0)
    except Exception:
        x, y, w, h = detection[:4].astype(int)
        crop = frame[max(0,y):min(frame.shape[0],y+h), max(0,x):min(frame.shape[1],x+w)]
        return cv2.resize(crop, (size, size)) if crop.size > 0 else None


# ═══════════════════════════════════════════════════════════
#  Embedders
# ═══════════════════════════════════════════════════════════

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
            raise FileNotFoundError(f"INT8 model không tồn tại: {FACELIVT_INT8_MODEL}")
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
#  Data split
# ═══════════════════════════════════════════════════════════

def split_dataset(data_dir, test_ratio=0.2, max_people=0, seed=SEED):
    """Tách gallery/probe per person. Trả về dict {label: {gallery: [...], probe: [...]}}."""
    rng = random.Random(seed)
    split = {}
    people = sorted([d for d in data_dir.iterdir() if d.is_dir()])
    if max_people > 0:
        people = people[:max_people]

    for person_dir in people:
        label = slugify(person_dir.name)
        imgs = sorted(f for f in person_dir.iterdir() if f.suffix.lower() in IMG_EXTS)
        if len(imgs) < 2:
            continue
        rng.shuffle(imgs)
        n_test = max(1, int(len(imgs) * test_ratio))
        split[label] = {
            "name": person_dir.name,
            "gallery": imgs[n_test:],
            "probe": imgs[:n_test],
        }
    return split


# ═══════════════════════════════════════════════════════════
#  Enroll + Test
# ═══════════════════════════════════════════════════════════

def enroll_gallery(split, detector, embedder):
    """Enroll gallery → dict {label: numpy matrix (N, D)}."""
    gallery = {}
    total = 0
    for label, data in split.items():
        embs = []
        for path in data["gallery"]:
            img = imread_unicode(path)
            if img is None: continue
            dets = detector.detect_all(img)
            if dets is None: continue
            det = dets[int(np.argmax(dets[:, 2] * dets[:, 3]))]
            emb = embedder.get_embedding(img, det)
            embs.append(emb.flatten())
            total += 1
        if embs:
            gallery[label] = np.array(embs, dtype=np.float32)
    return gallery, total


def test_probes(split, gallery, detector, embedder, threshold):
    """Test probe images. Trả về (y_true, y_pred, details)."""
    # Flatten gallery → matrix
    all_embs, all_labels = [], []
    for label, mat in gallery.items():
        for e in mat:
            all_embs.append(e)
            all_labels.append(label)
    if not all_embs:
        return [], [], []
    matrix = np.array(all_embs, dtype=np.float32)

    y_true, y_pred = [], []
    details = []

    for label, data in split.items():
        for path in data["probe"]:
            img = imread_unicode(path)
            if img is None: continue
            dets = detector.detect_all(img)
            if dets is None:
                y_true.append(label)
                y_pred.append("__no_face__")
                continue
            det = dets[int(np.argmax(dets[:, 2] * dets[:, 3]))]
            emb = embedder.get_embedding(img, det).flatten()
            n = np.linalg.norm(emb)
            if n < 1e-8:
                y_true.append(label)
                y_pred.append("__no_face__")
                continue
            emb = emb / n

            scores = matrix @ emb
            # KNN Top-5
            K = min(5, len(scores))
            top_k = np.argsort(scores)[-K:][::-1]
            votes = defaultdict(int)
            best_scores = {}
            for idx in top_k:
                s = float(scores[idx])
                if s < threshold: continue
                c = all_labels[idx]
                votes[c] += 1
                if c not in best_scores or s > best_scores[c]:
                    best_scores[c] = s

            if not votes:
                pred = "__unknown__"
                conf = 0.0
            else:
                pred = max(votes, key=lambda c: (votes[c], best_scores[c]))
                conf = best_scores[pred]

            y_true.append(label)
            y_pred.append(pred)
            details.append({"true": label, "pred": pred, "conf": conf,
                            "image": Path(path).name})

    return y_true, y_pred, details


# ═══════════════════════════════════════════════════════════
#  Metrics
# ═══════════════════════════════════════════════════════════

def compute_metrics(y_true, y_pred, labels):
    """Tính accuracy, precision, recall, F1, confusion matrix."""
    n = len(y_true)
    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    wrong = sum(1 for t, p in zip(y_true, y_pred) if t != p and p not in ("__unknown__", "__no_face__"))
    unknown = sum(1 for p in y_pred if p == "__unknown__")
    no_face = sum(1 for p in y_pred if p == "__no_face__")

    acc = correct / n * 100 if n else 0
    far = wrong / n * 100 if n else 0  # False Accept Rate
    frr = (unknown + no_face) / n * 100 if n else 0  # False Reject Rate

    # Confusion matrix
    label_idx = {l: i for i, l in enumerate(labels)}
    cm = np.zeros((len(labels), len(labels)), dtype=int)
    for t, p in zip(y_true, y_pred):
        if t in label_idx and p in label_idx:
            cm[label_idx[t]][label_idx[p]] += 1

    return {
        "accuracy": acc, "far": far, "frr": frr,
        "correct": correct, "wrong": wrong, "unknown": unknown,
        "no_face": no_face, "total": n, "cm": cm,
    }


def plot_confusion_matrix(cm, labels, title, output_path, top_n=30):
    """Vẽ confusion matrix (giới hạn top_n người)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  ⚠️ matplotlib chưa cài. Bỏ qua vẽ biểu đồ.")
        return

    if len(labels) > top_n:
        # Lấy top_n người có nhiều probe nhất
        row_sums = cm.sum(axis=1)
        top_idx = np.argsort(row_sums)[-top_n:]
        cm = cm[np.ix_(top_idx, top_idx)]
        labels = [labels[i] for i in top_idx]

    fig, ax = plt.subplots(figsize=(max(10, len(labels)*0.4), max(8, len(labels)*0.35)))
    im = ax.imshow(cm, interpolation='nearest', cmap='Blues')
    ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    # Labels
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    short = [l[:12] for l in labels]
    ax.set_xticklabels(short, rotation=90, fontsize=6)
    ax.set_yticklabels(short, fontsize=6)
    ax.set_xlabel('Predicted', fontsize=11)
    ax.set_ylabel('True', fontsize=11)

    # Annotate cells
    thresh = cm.max() / 2.0
    for i in range(len(labels)):
        for j in range(len(labels)):
            v = cm[i, j]
            if v > 0:
                ax.text(j, i, str(v), ha='center', va='center', fontsize=5,
                        color='white' if v > thresh else 'black')

    plt.tight_layout()
    plt.savefig(str(output_path), dpi=200, bbox_inches='tight')
    print(f"  📊 {output_path}")


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Confusion Matrix & Accuracy Evaluation")
    parser.add_argument("--dataset", type=str, default="dataset_clean")
    parser.add_argument("--test-ratio", type=float, default=0.2)
    parser.add_argument("--max-people", type=int, default=0)
    parser.add_argument("--sface-threshold", type=float, default=0.363)
    parser.add_argument("--facelivt-threshold", type=float, default=0.50)
    args = parser.parse_args()

    ds = Path(args.dataset)
    if not ds.is_absolute():
        ds = PROJECT_ROOT / ds
    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(exist_ok=True)

    print("=" * 70)
    print("  📊 Confusion Matrix & Accuracy: SFace vs FaceLiVT FP32 vs INT8")
    print("=" * 70)

    detector = FaceDetector()

    # Split dataset
    print(f"\n[1/6] Tách dataset ({100-args.test_ratio*100:.0f}% gallery / {args.test_ratio*100:.0f}% probe)...")
    split = split_dataset(ds, test_ratio=args.test_ratio, max_people=args.max_people)
    labels = sorted(split.keys())
    n_gallery = sum(len(d["gallery"]) for d in split.values())
    n_probe = sum(len(d["probe"]) for d in split.values())
    print(f"  {len(labels)} người, {n_gallery} gallery, {n_probe} probe")

    results = {}

    model_configs = [
        (SFaceEmb,        args.sface_threshold),
        (FaceLiVTEmb,     args.facelivt_threshold),
        (FaceLiVTInt8Emb, args.facelivt_threshold),
    ]

    for step, (EmbClass, threshold) in enumerate(model_configs, start=1):
        try:
            emb = EmbClass()
        except Exception as e:
            print(f"\n  ⚠️ Bỏ qua {EmbClass.name}: {e}")
            continue
        name = emb.name
        dim = emb.embed_dim

        print(f"\n[{step}/{len(model_configs)}] {name} ({dim}-dim, threshold={threshold})...")

        # Enroll
        print(f"  Enrolling gallery...")
        t0 = time.perf_counter()
        gallery, n_enrolled = enroll_gallery(split, detector, emb)
        enroll_t = time.perf_counter() - t0
        print(f"  → {n_enrolled} embeddings, {len(gallery)} người, {enroll_t:.1f}s")

        # Test
        print(f"  Testing probes...")
        t0 = time.perf_counter()
        y_true, y_pred, details = test_probes(split, gallery, detector, emb, threshold)
        test_t = time.perf_counter() - t0

        metrics = compute_metrics(y_true, y_pred, labels)
        metrics["enroll_time"] = enroll_t
        metrics["test_time"] = test_t
        metrics["dim"] = dim
        metrics["threshold"] = threshold
        results[name] = metrics

        print(f"  → Accuracy: {metrics['accuracy']:.2f}%  FAR: {metrics['far']:.2f}%  FRR: {metrics['frr']:.2f}%")

        # Plot
        slug = name.lower().replace(" ", "_")
        plot_confusion_matrix(
            metrics["cm"], labels,
            f"Confusion Matrix — {name} ({dim}-dim, thr={threshold})",
            out_dir / f"confusion_{slug}.png"
        )

    # ═══════════════════════════════════════════════════════
    #  Bảng so sánh
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*90}")
    print(f"  BẢNG SO SÁNH ACCURACY")
    print(f"{'='*90}")
    s = results.get("SFace", {})
    f = results.get("FaceLiVT2_S_FP32", {})
    q = results.get("FaceLiVT2_S_INT8", {})
    col_s = f"SFace ({s.get('dim','')}d)"
    col_f = f"FaceLiVT2_S_FP32 ({f.get('dim','')}d)"
    col_q = f"FaceLiVT2_S_INT8 ({q.get('dim','')}d)"
    print(f"  {'Metric':<25} │ {col_s:>22} │ {col_f:>22} │ {col_q:>22}")
    print(f"  {'─'*25}─┼─{'─'*22}─┼─{'─'*22}─┼─{'─'*22}")
    rows = [
        ("Threshold",
         f"{s.get('threshold',0):.3f}", f"{f.get('threshold',0):.3f}", f"{q.get('threshold',0):.3f}"),
        ("Accuracy (%)",
         f"{s.get('accuracy',0):.2f}%", f"{f.get('accuracy',0):.2f}%", f"{q.get('accuracy',0):.2f}%"),
        ("FAR — False Accept (%)",
         f"{s.get('far',0):.2f}%", f"{f.get('far',0):.2f}%", f"{q.get('far',0):.2f}%"),
        ("FRR — False Reject (%)",
         f"{s.get('frr',0):.2f}%", f"{f.get('frr',0):.2f}%", f"{q.get('frr',0):.2f}%"),
        ("Correct / Total",
         f"{s.get('correct',0)}/{s.get('total',0)}",
         f"{f.get('correct',0)}/{f.get('total',0)}",
         f"{q.get('correct',0)}/{q.get('total',0)}"),
        ("Wrong (nhầm người)",
         str(s.get('wrong',0)), str(f.get('wrong',0)), str(q.get('wrong',0))),
        ("Unknown (dưới thr)",
         str(s.get('unknown',0)), str(f.get('unknown',0)), str(q.get('unknown',0))),
        ("No face detected",
         str(s.get('no_face',0)), str(f.get('no_face',0)), str(q.get('no_face',0))),
        ("Enroll time (s)",
         f"{s.get('enroll_time',0):.1f}", f"{f.get('enroll_time',0):.1f}", f"{q.get('enroll_time',0):.1f}"),
        ("Test time (s)",
         f"{s.get('test_time',0):.1f}", f"{f.get('test_time',0):.1f}", f"{q.get('test_time',0):.1f}"),
    ]
    for row in rows:
        label, sv, fv, qv = row
        print(f"  {label:<25} │ {sv:>22} │ {fv:>22} │ {qv:>22}")
    print(f"{'='*90}")

    # Save text report
    report_path = out_dir / f"accuracy_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(f"Accuracy Report — {datetime.now()}\n")
        fh.write(f"Dataset: {ds}\n")
        fh.write(f"People: {len(labels)}, Gallery: {n_gallery}, Probe: {n_probe}\n\n")
        for name in ["SFace", "FaceLiVT2_S_FP32", "FaceLiVT2_S_INT8"]:
            m = results.get(name, {})
            if not m:
                continue
            fh.write(f"{name} ({m.get('dim','')}d, thr={m.get('threshold','')}):\n")
            fh.write(f"  Accuracy: {m.get('accuracy',0):.2f}%\n")
            fh.write(f"  FAR: {m.get('far',0):.2f}%  FRR: {m.get('frr',0):.2f}%\n")
            fh.write(f"  Correct={m.get('correct',0)} Wrong={m.get('wrong',0)} "
                     f"Unknown={m.get('unknown',0)} NoFace={m.get('no_face',0)}\n")
            fh.write(f"  Enroll: {m.get('enroll_time',0):.1f}s  Test: {m.get('test_time',0):.1f}s\n\n")
    print(f"\n  📄 Report: {report_path}")
    print(f"  ✅ Hoàn tất!")


if __name__ == "__main__":
    main()
