"""
So sánh trực tiếp: Finetuned vs Original FaceLiVT v2-S
────────────────────────────────────────────────────────
Cùng dataset, cùng ảnh, cùng random seed → công bằng tuyệt đối.
"""
import sys, time, random, shutil, tempfile
from pathlib import Path
import functools
print = functools.partial(print, flush=True)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import cv2
import onnxruntime as ort

# ── Config ─────────────────────────────────────────────
MODELS = {
    "finetuned": PROJECT_ROOT / "models" / "facelivtv2_s_finetuned.onnx",
    "original":  PROJECT_ROOT / "models" / "facelivtv2_s.onnx",
}
DATASET_DIR = PROJECT_ROOT / "dataset_clean"
N_PERSONS = 999   # All people
THRESHOLDS = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]

ARCFACE_DST = np.array([
    [38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
    [41.5493, 92.3655], [70.7299, 92.2041]
], dtype=np.float32)


def align_face(img, landmarks, size=112):
    dst = ARCFACE_DST * (float(size) / 112.0)
    M, _ = cv2.estimateAffinePartial2D(landmarks, dst)
    if M is None:
        M = cv2.getAffineTransform(landmarks[:3], dst[:3])
    return cv2.warpAffine(img, M, (size, size), borderValue=0.0)


def imread_unicode(filepath):
    data = np.fromfile(str(filepath), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def load_model(model_path):
    tmp_dir = Path(tempfile.mkdtemp(prefix="facelivt_"))
    shutil.copy2(str(model_path), str(tmp_dir / model_path.name))
    # Also copy .data if exists
    for ext in [".data", ".onnx.data"]:
        data_path = model_path.parent / (model_path.stem + ext)
        if data_path.exists():
            shutil.copy2(str(data_path), str(tmp_dir / data_path.name))
    return ort.InferenceSession(str(tmp_dir / model_path.name),
                                providers=['CPUExecutionProvider'])


# ── Load YuNet ─────────────────────────────────────────
yunet_path = PROJECT_ROOT / "models" / "face_detection_yunet_2023mar.onnx"
try:
    buf = np.fromfile(str(yunet_path), dtype=np.uint8)
    detector = cv2.FaceDetectorYN.create(
        framework="onnx", bufferModel=buf,
        bufferConfig=np.array([], dtype=np.uint8),
        input_size=(320, 320), score_threshold=0.9,
        nms_threshold=0.8, top_k=5000)
except TypeError:
    detector = cv2.FaceDetectorYN.create(
        model=str(yunet_path), config="",
        input_size=(320, 320), score_threshold=0.9,
        nms_threshold=0.8, top_k=5000)


def detect_face(frame):
    h, w = frame.shape[:2]
    detector.setInputSize((w, h))
    _, dets = detector.detect(frame)
    if dets is None or len(dets) == 0:
        return None
    areas = dets[:, 2] * dets[:, 3]
    return dets[np.argmax(areas)]


def get_embedding(session, input_name, frame, det):
    landmarks = det[4:14].reshape((5, 2))
    face_crop = align_face(frame, landmarks)
    rgb = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
    blob = (rgb.astype(np.float32) - 127.5) / 127.5
    blob = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]
    out = session.run(None, {input_name: blob})[0]
    emb = out.flatten()
    norm = np.linalg.norm(emb)
    if norm > 1e-8:
        emb = emb / norm
    return emb


# ── Collect test images ────────────────────────────────
print("=" * 70)
print("COMPARE: Finetuned vs Original FaceLiVT v2-S")
print("=" * 70)

person_dirs = sorted([d for d in DATASET_DIR.iterdir() if d.is_dir()])
eligible = []
for pdir in person_dirs:
    imgs = [f for f in pdir.iterdir()
            if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.jfif', '.bmp', '.webp')]
    if len(imgs) >= 2:
        eligible.append((pdir, imgs))

random.seed(42)
selected = random.sample(eligible, min(N_PERSONS, len(eligible)))
print(f"Dataset: {len(eligible)} people, testing {len(selected)}")

# Pre-detect faces (same detections for both models)
print("Detecting faces ...")
test_data = []  # [(name, img1, det1, img2, det2)]
skipped = 0
for idx, (pdir, imgs) in enumerate(selected):
    chosen = random.sample(imgs, 2)
    frames = [imread_unicode(f) for f in chosen]
    dets = [detect_face(f) for f in frames]
    if all(d is not None for d in dets):
        test_data.append((pdir.name, frames[0], dets[0], frames[1], dets[1]))
    else:
        skipped += 1
    if (idx + 1) % 50 == 0:
        print(f"  {idx+1}/{len(selected)} detected ...")

print(f"Usable pairs: {len(test_data)} (skipped: {skipped})")

# ── Run both models ────────────────────────────────────
for model_label, model_path in MODELS.items():
    if not model_path.exists():
        print(f"\n{'='*70}")
        print(f"SKIP {model_label}: {model_path.name} not found")
        continue

    print(f"\n{'='*70}")
    print(f"MODEL: {model_label} ({model_path.name}, {model_path.stat().st_size/1e6:.1f} MB)")
    print("=" * 70)

    session = load_model(model_path)
    input_name = session.get_inputs()[0].name

    # Auto-detect dim
    dummy_out = session.run(None, {input_name: np.random.randn(1, 3, 112, 112).astype(np.float32)})[0]
    dim = dummy_out.flatten().shape[0]
    print(f"Dim: {dim}")

    same_scores = []
    all_embs = []  # (name, embedding)

    # Same-person embeddings
    print(f"  Extracting embeddings ...")
    t0 = time.perf_counter()
    for idx, (name, f1, d1, f2, d2) in enumerate(test_data):
        e1 = get_embedding(session, input_name, f1, d1)
        e2 = get_embedding(session, input_name, f2, d2)
        sim = float(np.dot(e1, e2))
        same_scores.append(sim)
        all_embs.append((name, e1))
        if (idx + 1) % 50 == 0:
            print(f"    {idx+1}/{len(test_data)} ...")
    elapsed = time.perf_counter() - t0
    print(f"  Done in {elapsed:.1f}s ({elapsed/len(test_data)*1000:.1f}ms/pair)")

    # Cross-person: compute ALL pairs (n*(n-1)/2)
    print(f"  Computing cross-person similarities ...")
    cross_scores = []
    n = len(all_embs)
    for i in range(n):
        for j in range(i + 1, n):
            sim = float(np.dot(all_embs[i][1], all_embs[j][1]))
            cross_scores.append(sim)
    print(f"  Cross pairs: {len(cross_scores)}")

    # Summary
    print(f"\n  SUMMARY ({model_label}):")
    print(f"    Same-person  : N={len(same_scores):<5d} mean={np.mean(same_scores):.4f}  std={np.std(same_scores):.4f}  min={np.min(same_scores):.4f}  max={np.max(same_scores):.4f}")
    print(f"    Cross-person : N={len(cross_scores):<5d} mean={np.mean(cross_scores):.4f}  std={np.std(cross_scores):.4f}  min={np.min(cross_scores):.4f}  max={np.max(cross_scores):.4f}")
    print(f"    Separation   : {np.mean(same_scores) - np.mean(cross_scores):.4f}")

    # Find optimal threshold (EER approximation)
    best_acc, best_th = 0, 0
    for th_candidate in np.arange(0.05, 0.70, 0.01):
        tp = sum(1 for s in same_scores if s >= th_candidate)
        tn = sum(1 for s in cross_scores if s < th_candidate)
        total = len(same_scores) + len(cross_scores)
        acc = (tp + tn) / total * 100
        if acc > best_acc:
            best_acc, best_th = acc, th_candidate

    print(f"    Best threshold: {best_th:.2f} -> Accuracy={best_acc:.2f}%")

    print(f"\n  ACCURACY TABLE:")
    print(f"    {'Threshold':<12s} {'TP':>8s} {'TN':>12s} {'Acc':>8s}")
    for th in THRESHOLDS:
        tp = sum(1 for s in same_scores if s >= th)
        tn = sum(1 for s in cross_scores if s < th)
        total = len(same_scores) + len(cross_scores)
        acc = (tp + tn) / total * 100
        marker = " <-- best" if abs(th - best_th) < 0.025 else ""
        print(f"    {th:<12.2f} {tp:>5d}/{len(same_scores):<5d} {tn:>5d}/{len(cross_scores):<5d} {acc:>7.1f}%{marker}")

print(f"\n{'='*70}")
print("Done!")
