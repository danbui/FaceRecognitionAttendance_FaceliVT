"""
Test inference với model facelivtv2_s_finetuned.onnx
─────────────────────────────────────────────────────
Chọn ngẫu nhiên N người từ dataset_clean, mỗi người lấy 2 ảnh:
  - So sánh same-person  → kỳ vọng cosine cao (> 0.5)
  - So sánh cross-person → kỳ vọng cosine thấp (< 0.5)
"""
import sys, time, random, shutil, tempfile, traceback
from pathlib import Path

# Force flush stdout for Windows Unicode terminal
import functools
print = functools.partial(print, flush=True)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import cv2
import onnxruntime as ort

# ── Config ─────────────────────────────────────────────
# Try finetuned model, fallback to original if corrupted
MODEL_FINETUNED = PROJECT_ROOT / "models" / "facelivtv2_s_finetuned.onnx"
DATA_FINETUNED  = PROJECT_ROOT / "models" / "facelivtv2_s_finetuned.data"
MODEL_ORIGINAL  = PROJECT_ROOT / "models" / "facelivtv2_s.onnx"
DATASET_DIR = PROJECT_ROOT / "dataset_clean"
N_PERSONS   = 8          # Số người test
THRESHOLD   = 0.50       # Ngưỡng cosine similarity

# ── ArcFace alignment ─────────────────────────────────
ARCFACE_DST = np.array([
    [38.2946, 51.6963],
    [73.5318, 51.5014],
    [56.0252, 71.7366],
    [41.5493, 92.3655],
    [70.7299, 92.2041]
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


def load_onnx_model(model_path, data_path=None):
    """Load ONNX model — always copy to ASCII-safe temp dir.
    
    ONNX Runtime segfaults (not a Python exception) when loading models
    with external .data files from Unicode paths on Windows.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="facelivt_"))
    print(f"  Copying to temp: {tmp_dir}")
    shutil.copy2(str(model_path), str(tmp_dir / model_path.name))
    if data_path and data_path.exists():
        # ONNX model internally expects "{model_name}.data" e.g. "xxx.onnx.data"
        expected_data_name = model_path.name + ".data"
        shutil.copy2(str(data_path), str(tmp_dir / expected_data_name))
        print(f"  Copied .data as {expected_data_name} ({data_path.stat().st_size / 1e6:.1f} MB)")
    tmp_model = tmp_dir / model_path.name
    sess = ort.InferenceSession(str(tmp_model), providers=['CPUExecutionProvider'])
    print(f"  Model loaded OK")
    return sess


# ── Load model ─────────────────────────────────────────
print("=" * 60)
print("TEST INFERENCE - FaceLiVT v2-S")
print("=" * 60)

model_name = None
session = None

# Try finetuned first
if MODEL_FINETUNED.exists():
    print(f"Trying finetuned: {MODEL_FINETUNED.name} ...")
    try:
        session = load_onnx_model(MODEL_FINETUNED, DATA_FINETUNED)
        model_name = "finetuned"
        print("  Finetuned model loaded!")
    except Exception as e:
        print(f"  Finetuned FAILED: {e}")
        print("  -> Falling back to original model")

# Fallback to original
if session is None:
    if not MODEL_ORIGINAL.exists():
        print(f"No model found! Check models/ folder.")
        sys.exit(1)
    print(f"Using original: {MODEL_ORIGINAL.name} ...")
    try:
        session = load_onnx_model(MODEL_ORIGINAL)
        model_name = "original"
    except Exception as e:
        print(f"FATAL: {e}")
        traceback.print_exc()
        sys.exit(1)

print(f"Model  : {model_name}")
print(f"Dataset: {DATASET_DIR}")
input_name = session.get_inputs()[0].name
input_shape = session.get_inputs()[0].shape
output_shape = session.get_outputs()[0].shape

# Auto-detect dim
dummy = np.random.randn(1, 3, 112, 112).astype(np.float32)
dummy_out = session.run(None, {input_name: dummy})[0]
embed_dim = dummy_out.flatten().shape[0]

print(f"Input : {input_shape}")
print(f"Output: {output_shape} → {embed_dim}-dim")
print(f"ORT   : {ort.__version__}")

# ── Load YuNet detector ────────────────────────────────
yunet_path = PROJECT_ROOT / "models" / "face_detection_yunet_2023mar.onnx"
try:
    model_buffer = np.fromfile(str(yunet_path), dtype=np.uint8)
    config_buffer = np.array([], dtype=np.uint8)
    detector = cv2.FaceDetectorYN.create(
        framework="onnx",
        bufferModel=model_buffer,
        bufferConfig=config_buffer,
        input_size=(320, 320),
        score_threshold=0.9,
        nms_threshold=0.8,
        top_k=5000,
    )
except TypeError:
    detector = cv2.FaceDetectorYN.create(
        model=str(yunet_path),
        config="",
        input_size=(320, 320),
        score_threshold=0.9,
        nms_threshold=0.8,
        top_k=5000,
    )
print(f"YuNet : loaded ✓")


def get_embedding(frame):
    """Detect face → align → extract embedding."""
    h, w = frame.shape[:2]
    detector.setInputSize((w, h))
    _, dets = detector.detect(frame)
    if dets is None or len(dets) == 0:
        return None

    # Largest face
    areas = dets[:, 2] * dets[:, 3]
    det = dets[np.argmax(areas)]
    landmarks = det[4:14].reshape((5, 2))

    face_crop = align_face(frame, landmarks)
    rgb = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
    blob = (rgb.astype(np.float32) - 127.5) / 127.5
    blob = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]

    t0 = time.perf_counter()
    out = session.run(None, {input_name: blob})[0]
    dt = (time.perf_counter() - t0) * 1000

    emb = out.flatten()
    norm = np.linalg.norm(emb)
    if norm > 1e-8:
        emb = emb / norm
    return emb, dt


def cosine_sim(a, b):
    return float(np.dot(a, b))


# ── Collect persons ────────────────────────────────────
print(f"\n{'─' * 60}")
print("📂 Đang quét dataset_clean ...")

person_dirs = sorted([d for d in DATASET_DIR.iterdir() if d.is_dir()])
# Filter: chỉ lấy thư mục có >= 2 ảnh
eligible = []
for pdir in person_dirs:
    imgs = [f for f in pdir.iterdir() if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.jfif', '.bmp', '.webp')]
    if len(imgs) >= 2:
        eligible.append((pdir, imgs))

print(f"Tổng: {len(person_dirs)} người, đủ ảnh (≥2): {len(eligible)}")

if len(eligible) < 2:
    print("❌ Cần ít nhất 2 người có >= 2 ảnh để test")
    sys.exit(1)

# Random sample
random.seed(42)
selected = random.sample(eligible, min(N_PERSONS, len(eligible)))
print(f"Chọn test: {len(selected)} người\n")

# ── Extract embeddings ─────────────────────────────────
print("🔄 Đang trích xuất embeddings ...")
person_embeddings = {}   # name -> [(emb, img_name), ...]
latencies = []

for pdir, imgs in selected:
    name = pdir.name
    chosen_imgs = random.sample(imgs, 2)
    embs = []
    for img_file in chosen_imgs:
        frame = imread_unicode(img_file)
        if frame is None:
            print(f"  ⚠ Không đọc được: {img_file.name}")
            continue
        result = get_embedding(frame)
        if result is None:
            print(f"  ⚠ Không detect face: {img_file.name}")
            continue
        emb, dt = result
        embs.append((emb, img_file.name))
        latencies.append(dt)
    if len(embs) >= 2:
        person_embeddings[name] = embs
        print(f"  ✓ {name}: {len(embs)} embeddings")
    else:
        print(f"  ✗ {name}: chỉ có {len(embs)} embedding (bỏ qua)")

# ── Same-person similarity ─────────────────────────────
print(f"\n{'=' * 60}")
print("📊 SAME-PERSON SIMILARITY (kỳ vọng > {:.2f})".format(THRESHOLD))
print("=" * 60)

same_scores = []
for name, embs in person_embeddings.items():
    e1, n1 = embs[0]
    e2, n2 = embs[1]
    sim = cosine_sim(e1, e2)
    same_scores.append(sim)
    status = "✅" if sim >= THRESHOLD else "❌"
    print(f"  {status} {name[:40]:<40s}  cos={sim:.4f}  [{n1[:20]} vs {n2[:20]}]")

# ── Cross-person similarity ────────────────────────────
print(f"\n{'=' * 60}")
print("📊 CROSS-PERSON SIMILARITY (kỳ vọng < {:.2f})".format(THRESHOLD))
print("=" * 60)

cross_scores = []
names = list(person_embeddings.keys())
for i in range(len(names)):
    for j in range(i + 1, len(names)):
        e1 = person_embeddings[names[i]][0][0]
        e2 = person_embeddings[names[j]][0][0]
        sim = cosine_sim(e1, e2)
        cross_scores.append(sim)
        status = "✅" if sim < THRESHOLD else "❌ FALSE MATCH"
        short_i = names[i][:20]
        short_j = names[j][:20]
        print(f"  {status} {short_i} vs {short_j}  cos={sim:.4f}")

# ── Summary ────────────────────────────────────────────
print(f"\n{'=' * 60}")
print("📈 SUMMARY")
print("=" * 60)

if same_scores:
    print(f"  Same-person  : mean={np.mean(same_scores):.4f}  min={np.min(same_scores):.4f}  max={np.max(same_scores):.4f}")
if cross_scores:
    print(f"  Cross-person : mean={np.mean(cross_scores):.4f}  min={np.min(cross_scores):.4f}  max={np.max(cross_scores):.4f}")

if same_scores and cross_scores:
    gap = np.mean(same_scores) - np.mean(cross_scores)
    print(f"  Separation   : {gap:.4f} (càng lớn càng tốt)")

    # Accuracy at threshold
    tp = sum(1 for s in same_scores if s >= THRESHOLD)
    tn = sum(1 for s in cross_scores if s < THRESHOLD)
    total = len(same_scores) + len(cross_scores)
    acc = (tp + tn) / total * 100
    print(f"  Accuracy @{THRESHOLD}: {acc:.1f}%  (TP={tp}/{len(same_scores)}, TN={tn}/{len(cross_scores)})")

if latencies:
    print(f"  Latency      : mean={np.mean(latencies):.1f}ms  min={np.min(latencies):.1f}ms  max={np.max(latencies):.1f}ms")

print(f"\n{'=' * 60}")
print("✅ Test inference hoàn tất!")
