"""
Minh họa Input/Output từng bước Pipeline nhận diện khuôn mặt.

Lấy 1 ảnh mẫu → chạy qua từng bước → lưu ảnh minh họa.

Output: benchmarks/pipeline_visualization.png

Cách chạy:
  python benchmarks/visualize_pipeline.py
  python benchmarks/visualize_pipeline.py --image "dataset_clean/ca sĩ Sơn Tùng/001.jpg"
  python benchmarks/visualize_pipeline.py --dataset dataset_clean
"""
import sys, argparse, random
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.face_detector import FaceDetector
from app.config import SFACE_MODEL, FACELIVT_MODEL, MODELS_DIR

FACELIVT_INT8_MODEL = MODELS_DIR / "facelivtv2_s_512_int8.onnx"
IMG_EXTS = {".jpg", ".jpeg", ".png"}

ARCFACE_DST = np.array([
    [38.2946, 51.6963], [73.5318, 51.5014],
    [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]
], dtype=np.float32)

LANDMARK_NAMES = ["Mắt trái", "Mắt phải", "Mũi", "Miệng trái", "Miệng phải"]
LM_COLORS = [(0,255,0), (0,255,0), (255,255,0), (0,165,255), (0,165,255)]


def imread_u(path):
    buf = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def align_face(frame, det, size=112):
    lm = det[4:14].reshape((5, 2))
    dst = ARCFACE_DST * (float(size) / 112.0)
    M, _ = cv2.estimateAffinePartial2D(lm, dst)
    if M is None:
        M = cv2.getAffineTransform(lm[:3], dst[:3])
    return cv2.warpAffine(frame, M, (size, size), borderValue=0.0), lm, M


def find_sample_image(dataset_dir):
    """Tìm 1 ảnh mẫu ngẫu nhiên có mặt rõ."""
    rng = random.Random(42)
    people = sorted([d for d in dataset_dir.iterdir() if d.is_dir()])
    rng.shuffle(people)
    for pdir in people:
        imgs = sorted(f for f in pdir.iterdir() if f.suffix.lower() in IMG_EXTS)
        if imgs:
            return imgs[0], pdir.name
    return None, None


def draw_text_bg(img, text, pos, font_scale=0.5, color=(255,255,255),
                 bg_color=(0,0,0), thickness=1):
    """Vẽ text có nền."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    x, y = pos
    cv2.rectangle(img, (x, y - th - 4), (x + tw + 4, y + 4), bg_color, -1)
    cv2.putText(img, text, (x + 2, y), font, font_scale, color, thickness, cv2.LINE_AA)


def make_step_header(width, step_num, title, subtitle="", h=50):
    """Tạo header cho mỗi bước."""
    header = np.zeros((h, width, 3), dtype=np.uint8)
    header[:] = (40, 40, 40)
    cv2.putText(header, f"Step {step_num}: {title}", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 1, cv2.LINE_AA)
    if subtitle:
        cv2.putText(header, subtitle, (10, 43),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1, cv2.LINE_AA)
    return header


def visualize_embedding(emb, name, dim, h=200, w=300):
    """Vẽ vector embedding dưới dạng bar chart."""
    canvas = np.ones((h, w, 3), dtype=np.uint8) * 255

    # Chỉ vẽ 100 giá trị đầu (hoặc ít hơn)
    n = min(100, len(emb))
    vals = emb[:n]
    bar_w = max(1, (w - 40) // n)

    max_val = max(abs(vals.max()), abs(vals.min()), 0.01)
    mid_y = h // 2

    for i, v in enumerate(vals):
        x = 20 + i * bar_w
        bar_h = int((v / max_val) * (h // 2 - 20))
        color = (0, 150, 0) if v >= 0 else (0, 0, 200)
        y1 = mid_y - max(0, bar_h)
        y2 = mid_y - min(0, bar_h)
        cv2.rectangle(canvas, (x, y1), (x + bar_w - 1, y2), color, -1)

    # Baseline
    cv2.line(canvas, (20, mid_y), (w - 20, mid_y), (100, 100, 100), 1)

    # Label
    cv2.putText(canvas, f"{name} ({dim}d)", (10, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(canvas, f"First {n} dims shown", (10, h - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.3, (128, 128, 128), 1, cv2.LINE_AA)

    return canvas


def main():
    parser = argparse.ArgumentParser(description="Visualize Pipeline I/O")
    parser.add_argument("--image", type=str, default="")
    parser.add_argument("--dataset", type=str, default="dataset_clean")
    args = parser.parse_args()

    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(exist_ok=True)

    # Find image
    if args.image:
        img_path = Path(args.image)
        if not img_path.is_absolute():
            img_path = PROJECT_ROOT / img_path
        person_name = img_path.parent.name
    else:
        ds = Path(args.dataset)
        if not ds.is_absolute():
            ds = PROJECT_ROOT / ds
        img_path, person_name = find_sample_image(ds)

    if img_path is None or not img_path.exists():
        print(f"❌ Không tìm thấy ảnh: {img_path}")
        return

    print(f"📸 Ảnh: {img_path}")
    print(f"👤 Người: {person_name}")

    # Load
    frame = imread_u(img_path)
    if frame is None:
        print("❌ Không đọc được ảnh!")
        return

    detector = FaceDetector()

    # ════════════════════════════════════════════
    #  STEP 1: Input — Ảnh gốc
    # ════════════════════════════════════════════
    step1 = frame.copy()
    h_orig, w_orig = step1.shape[:2]
    draw_text_bg(step1, f"Input: {w_orig}x{h_orig} RGB", (5, h_orig - 10),
                 font_scale=0.4, color=(255,255,255), bg_color=(0,0,0))

    # ════════════════════════════════════════════
    #  STEP 2: Detection — YuNet
    # ════════════════════════════════════════════
    dets = detector.detect_all(frame)
    if dets is None or len(dets) == 0:
        print("❌ Không phát hiện khuôn mặt!")
        return

    det = dets[int(np.argmax(dets[:, 2] * dets[:, 3]))]
    x, y, w, h = det[:4].astype(int)
    landmarks = det[4:14].reshape((5, 2))
    conf = det[14] if len(det) > 14 else det[-1]

    step2 = frame.copy()
    cv2.rectangle(step2, (x, y), (x+w, y+h), (0, 255, 0), 2)
    for i, (lx, ly) in enumerate(landmarks):
        cv2.circle(step2, (int(lx), int(ly)), 3, LM_COLORS[i], -1)
        cv2.putText(step2, str(i+1), (int(lx)+5, int(ly)-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, LM_COLORS[i], 1)

    draw_text_bg(step2, f"BBox: ({x},{y},{w},{h}) conf={float(conf):.2f}", (5, h_orig - 25),
                 font_scale=0.35, bg_color=(0,100,0))
    draw_text_bg(step2, f"5 Landmarks detected", (5, h_orig - 10),
                 font_scale=0.35, bg_color=(0,100,0))

    # ════════════════════════════════════════════
    #  STEP 3: Alignment — ArcFace 112x112
    # ════════════════════════════════════════════
    aligned, lm, M = align_face(frame, det)
    step3 = aligned.copy()

    # Draw aligned landmarks (projected)
    for i, (lx, ly) in enumerate(ARCFACE_DST):
        cv2.circle(step3, (int(lx), int(ly)), 2, LM_COLORS[i], -1)

    # ════════════════════════════════════════════
    #  STEP 4: Embedding — 3 models
    # ════════════════════════════════════════════
    embeddings = {}

    # SFace
    try:
        try:
            buf = np.fromfile(str(SFACE_MODEL), dtype=np.uint8)
            rec = cv2.FaceRecognizerSF.create(framework="onnx",
                bufferModel=buf, bufferConfig=np.array([], dtype=np.uint8))
        except TypeError:
            rec = cv2.FaceRecognizerSF.create(str(SFACE_MODEL), "")
        sf_aligned = rec.alignCrop(frame, det)
        sf_feat = rec.feature(sf_aligned).flatten()
        n = np.linalg.norm(sf_feat)
        embeddings["SFace"] = (sf_feat / n if n > 1e-8 else sf_feat, 128)
    except Exception as e:
        print(f"  ⚠️ SFace: {e}")

    # FaceLiVT FP32
    try:
        import onnxruntime as ort
        sess = ort.InferenceSession(str(FACELIVT_MODEL), providers=['CPUExecutionProvider'])
        inp_name = sess.get_inputs()[0].name
        rgb = cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB)
        blob = (rgb.astype(np.float32) - 127.5) / 127.5
        blob = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]
        out = sess.run(None, {inp_name: blob})[0].flatten()
        n = np.linalg.norm(out)
        embeddings["FP32"] = (out / n if n > 1e-8 else out, len(out))
    except Exception as e:
        print(f"  ⚠️ FP32: {e}")

    # FaceLiVT INT8
    try:
        import onnxruntime as ort
        sess8 = ort.InferenceSession(str(FACELIVT_INT8_MODEL), providers=['CPUExecutionProvider'])
        inp8 = sess8.get_inputs()[0].name
        out8 = sess8.run(None, {inp8: blob})[0].flatten()
        n = np.linalg.norm(out8)
        embeddings["INT8"] = (out8 / n if n > 1e-8 else out8, len(out8))
    except Exception as e:
        print(f"  ⚠️ INT8: {e}")

    # ════════════════════════════════════════════
    #  Compose final image
    # ════════════════════════════════════════════
    TARGET_H = 250
    def resize_to_h(img, target_h):
        ratio = target_h / img.shape[0]
        new_w = int(img.shape[1] * ratio)
        return cv2.resize(img, (new_w, target_h))

    # Resize steps 1-3
    s1 = resize_to_h(step1, TARGET_H)
    s2 = resize_to_h(step2, TARGET_H)
    s3 = resize_to_h(aligned, TARGET_H)  # 112→250

    # Create embedding visualizations
    emb_imgs = []
    for name, (emb, dim) in embeddings.items():
        ev = visualize_embedding(emb, name, dim, h=TARGET_H, w=250)
        emb_imgs.append(ev)

    # Arrow between steps
    def make_arrow(h, w=40):
        arr = np.ones((h, w, 3), dtype=np.uint8) * 30
        mid = h // 2
        pts = np.array([[5, mid], [w-5, mid]], np.int32)
        cv2.arrowedLine(arr, (5, mid), (w-5, mid), (0, 200, 255), 2, tipLength=0.4)
        return arr

    arrow = make_arrow(TARGET_H)

    # Headers
    h1 = make_step_header(s1.shape[1], 1, "Input", f"{w_orig}x{h_orig} RGB")
    h2 = make_step_header(s2.shape[1], 2, "Detection", "YuNet → BBox + 5 Landmarks")
    h3 = make_step_header(s3.shape[1], 3, "Alignment", "ArcFace → 112x112")

    emb_headers = []
    for i, (name, (emb, dim)) in enumerate(embeddings.items()):
        eh = make_step_header(250, 4, f"Embedding", f"{name} → {dim}d vector")
        emb_headers.append(eh)

    # Row 1: headers
    header_row_parts = [h1, make_arrow(50, 40), h2, make_arrow(50, 40), h3]
    for eh in emb_headers:
        header_row_parts.append(make_arrow(50, 40))
        header_row_parts.append(eh)
    header_row = np.hstack(header_row_parts)

    # Row 2: images
    img_row_parts = [s1, arrow, s2, arrow, s3]
    for ev in emb_imgs:
        img_row_parts.append(arrow)
        img_row_parts.append(ev)
    img_row = np.hstack(img_row_parts)

    # Match widths
    max_w = max(header_row.shape[1], img_row.shape[1])
    if header_row.shape[1] < max_w:
        pad = np.zeros((header_row.shape[0], max_w - header_row.shape[1], 3), dtype=np.uint8)
        header_row = np.hstack([header_row, pad])
    if img_row.shape[1] < max_w:
        pad = np.zeros((img_row.shape[0], max_w - img_row.shape[1], 3), dtype=np.uint8)
        img_row = np.hstack([img_row, pad])

    # Title bar
    title_bar = np.zeros((40, max_w, 3), dtype=np.uint8)
    title_bar[:] = (50, 50, 50)
    cv2.putText(title_bar, f"Face Recognition Pipeline - {person_name}",
                (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)

    # Combine
    final = np.vstack([title_bar, header_row, img_row])

    # Info bar at bottom
    info_bar = np.zeros((35, max_w, 3), dtype=np.uint8)
    info_bar[:] = (40, 40, 40)
    info_text = "  |  ".join([f"{name}: [{dim}d float32]" for name, (_, dim) in embeddings.items()])
    cv2.putText(info_bar, f"Output vectors: {info_text}",
                (10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1, cv2.LINE_AA)
    final = np.vstack([final, info_bar])

    # Save
    out_path = out_dir / "pipeline_visualization.png"
    cv2.imwrite(str(out_path), final)
    print(f"\n✅ Pipeline visualization saved: {out_path}")
    print(f"   Size: {final.shape[1]}x{final.shape[0]}")

    # Print summary
    print(f"\n📋 Pipeline Summary:")
    print(f"   Step 1: Input         → {w_orig}x{h_orig} RGB image")
    print(f"   Step 2: Detection     → BBox ({x},{y},{w},{h}) + 5 landmarks, conf={float(conf):.2f}")
    print(f"   Step 3: Alignment     → 112x112 normalized face (ArcFace template)")
    for name, (emb, dim) in embeddings.items():
        print(f"   Step 4: Embedding     → {name}: [{dim}] float32 vector (L2-normalized)")
    print(f"   Step 5: Matching      → Cosine similarity (matrix @ query) → KNN Top-5 voting")


if __name__ == "__main__":
    main()
