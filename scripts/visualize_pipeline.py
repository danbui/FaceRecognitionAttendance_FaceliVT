"""
Pipeline Visualizer – Xuất input/output chi tiết từng công đoạn.

Lấy 1 ảnh → chạy qua toàn bộ pipeline → lưu ảnh + metadata từng bước
vào thư mục output để phục vụ báo cáo đồ án.

Output:
  pipeline_output/
  ├── 0_original.jpg              ← Ảnh gốc
  ├── 1_detection.jpg             ← Ảnh với bounding box + landmarks
  ├── 2_best_frame_score.jpg      ← Ảnh với quality score overlay
  ├── 3a_aligned_arcface.jpg      ← Ảnh khuôn mặt đã căn chỉnh (112×112)
  ├── 3b_aligned_sface.jpg        ← Ảnh SFace alignCrop
  ├── 4a_embedding_facelivt.txt   ← Vector embedding FaceLiVT (đầy đủ)
  ├── 4b_embedding_sface.txt      ← Vector embedding SFace (đầy đủ)
  ├── 5_matching_result.txt       ← Kết quả matching
  └── pipeline_summary.txt        ← Tóm tắt I/O từng bước

Cách chạy:
  python scripts/visualize_pipeline.py --image captures/enroll_NV001.jpg
  python scripts/visualize_pipeline.py --image dataset_clean/ca\ sĩ\ Mỹ\ Tâm/001.jpg
  python scripts/visualize_pipeline.py --camera 0
"""
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import init_db
from app.face_detector import FaceDetector
from app.best_frame_selector import BestFrameSelector
from app.matcher import match_embedding, embedding_cache
from app.config import SFACE_MODEL, FACELIVT_MODEL

# ── ArcFace landmarks ──
ARCFACE_DST = np.array([
    [38.2946, 51.6963], [73.5318, 51.5014],
    [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]
], dtype=np.float32)

# ── Colors ──
GREEN  = (0, 255, 0)
RED    = (0, 0, 255)
BLUE   = (255, 0, 0)
YELLOW = (0, 255, 255)
CYAN   = (255, 255, 0)
WHITE  = (255, 255, 255)
ORANGE = (0, 165, 255)

LANDMARK_COLORS = [RED, BLUE, GREEN, YELLOW, CYAN]  # RE, LE, Nose, RM, LM
LANDMARK_LABELS = ["Right Eye", "Left Eye", "Nose", "R.Mouth", "L.Mouth"]


def load_image(path):
    buf = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Không đọc được ảnh: {path}")
    return img


def save_image(img, path):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if ok:
        with open(path, "wb") as f:
            f.write(buf.tobytes())


def align_face_arcface(frame, landmarks, size=112):
    dst = ARCFACE_DST * (float(size) / 112.0)
    M, _ = cv2.estimateAffinePartial2D(landmarks, dst)
    if M is None:
        M = cv2.getAffineTransform(landmarks[:3], dst[:3])
    return cv2.warpAffine(frame, M, (size, size), borderValue=0.0), M


# ═══════════════════════════════════════════════════════════
#  Main Pipeline
# ═══════════════════════════════════════════════════════════

def run_pipeline(image_path, output_dir, use_camera=False, camera_idx=0):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = []

    def log(msg):
        summary.append(msg)
        print(msg)

    log("=" * 70)
    log("  PIPELINE VISUALIZER — Input/Output từng công đoạn")
    log("=" * 70)
    log(f"  Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"  Output:    {output_dir}")
    log("")

    # ── Init ──
    init_db()
    detector = FaceDetector()
    selector = BestFrameSelector()

    # Load embedders
    sface_rec = None
    facelivt_sess = None
    facelivt_inp = None
    facelivt_dim = 0

    if SFACE_MODEL.exists():
        try:
            buf = np.fromfile(str(SFACE_MODEL), dtype=np.uint8)
            cfg = np.array([], dtype=np.uint8)
            sface_rec = cv2.FaceRecognizerSF.create(
                framework="onnx", bufferModel=buf, bufferConfig=cfg)
        except TypeError:
            sface_rec = cv2.FaceRecognizerSF.create(
                model=str(SFACE_MODEL), config="")

    if FACELIVT_MODEL.exists():
        try:
            import onnxruntime as ort
            facelivt_sess = ort.InferenceSession(
                str(FACELIVT_MODEL), providers=['CPUExecutionProvider'])
            facelivt_inp = facelivt_sess.get_inputs()[0].name
            dummy = np.random.randn(1, 3, 112, 112).astype(np.float32)
            facelivt_dim = facelivt_sess.run(None, {facelivt_inp: dummy})[0].flatten().shape[0]
        except Exception as e:
            log(f"  ⚠️ FaceLiVT không khả dụng: {e}")

    # ═══════════════════════════════════════════════════════
    #  BƯỚC 0: Input — Ảnh gốc
    # ═══════════════════════════════════════════════════════
    log("─" * 70)
    log("  BƯỚC 0: INPUT — Ảnh gốc")
    log("─" * 70)

    if use_camera:
        cap = cv2.VideoCapture(camera_idx)
        for _ in range(15): cap.read()
        ret, frame = cap.read()
        cap.release()
        if not ret:
            log("  ❌ Không đọc được camera!")
            return
        source = f"Camera {camera_idx}"
    else:
        frame = load_image(image_path)
        source = str(image_path)

    h, w, c = frame.shape
    log(f"  Source:     {source}")
    log(f"  Kích thước: {w} × {h} pixels")
    log(f"  Channels:   {c} (BGR)")
    log(f"  Dtype:      {frame.dtype}")
    log(f"  File size:  {Path(image_path).stat().st_size / 1024:.1f} KB" if not use_camera else "")
    log(f"  Shape:      {frame.shape}")

    save_image(frame, output_dir / "0_original.jpg")
    log(f"  → Saved: 0_original.jpg")

    # ═══════════════════════════════════════════════════════
    #  BƯỚC 1: Face Detection (YuNet)
    # ═══════════════════════════════════════════════════════
    log("")
    log("─" * 70)
    log("  BƯỚC 1: FACE DETECTION — YuNet")
    log("─" * 70)
    log(f"  Model:      face_detection_yunet_2023mar.onnx")
    log(f"  Input:      BGR frame {w}×{h}")

    t0 = time.perf_counter()
    detections = detector.detect_all(frame)
    dt = (time.perf_counter() - t0) * 1000

    if detections is None:
        log("  ❌ Không phát hiện khuôn mặt nào!")
        return

    log(f"  Latency:    {dt:.2f}ms")
    log(f"  Số mặt:     {len(detections)}")

    # Lấy mặt lớn nhất
    areas = detections[:, 2] * detections[:, 3]
    idx = int(np.argmax(areas))
    det = detections[idx]
    x, y, bw, bh = int(det[0]), int(det[1]), int(det[2]), int(det[3])
    score = float(det[14])
    landmarks = det[4:14].reshape((5, 2))

    log(f"  Output (mặt lớn nhất):")
    log(f"    Bounding Box: x={x}, y={y}, w={bw}, h={bh}")
    log(f"    Score:        {score:.4f}")
    log(f"    Landmarks (5 điểm):")
    for i, (lx, ly) in enumerate(landmarks):
        log(f"      [{i}] {LANDMARK_LABELS[i]:<12}: ({lx:.1f}, {ly:.1f})")

    # Vẽ detection lên ảnh
    vis = frame.copy()

    # BBox
    cv2.rectangle(vis, (x, y), (x+bw, y+bh), GREEN, 2)
    cv2.putText(vis, f"Score: {score:.3f}", (x, y-10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, GREEN, 2)

    # Landmarks
    for i, (lx, ly) in enumerate(landmarks):
        px, py = int(lx), int(ly)
        cv2.circle(vis, (px, py), 4, LANDMARK_COLORS[i], -1)
        cv2.putText(vis, f"{i}:{LANDMARK_LABELS[i]}", (px+6, py-4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, LANDMARK_COLORS[i], 1)

    # Vẽ đường nối landmarks
    pairs = [(0,1), (0,2), (1,2), (2,3), (2,4), (3,4)]
    for a, b in pairs:
        p1 = (int(landmarks[a][0]), int(landmarks[a][1]))
        p2 = (int(landmarks[b][0]), int(landmarks[b][1]))
        cv2.line(vis, p1, p2, WHITE, 1, cv2.LINE_AA)

    save_image(vis, output_dir / "1_detection.jpg")
    log(f"  → Saved: 1_detection.jpg")

    # ═══════════════════════════════════════════════════════
    #  BƯỚC 2: Best Frame Selector
    # ═══════════════════════════════════════════════════════
    log("")
    log("─" * 70)
    log("  BƯỚC 2: BEST FRAME SELECTOR — Quality Scoring")
    log("─" * 70)
    log(f"  Input:      Frame + BBox + Landmarks")

    t0 = time.perf_counter()
    selector.reset()
    selector.update(frame.copy(), (x, y, bw, bh), det[4:14], det)
    best_frame, best_raw, best_score = selector.get_best()
    dt = (time.perf_counter() - t0) * 1000

    # Tính individual scores
    face_crop_bfs = frame[y:y+bh, x:x+bw]
    if face_crop_bfs.size > 0:
        gray = cv2.cvtColor(face_crop_bfs, cv2.COLOR_BGR2GRAY)
        sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
        brightness = float(gray.mean())
        face_size_score = (bw * bh) / (w * h)
    else:
        sharpness = brightness = face_size_score = 0

    log(f"  Latency:    {dt:.2f}ms")
    log(f"  Output:")
    log(f"    Quality Score:  {best_score:.4f}")
    log(f"    Sharpness:      {sharpness:.1f} (Laplacian variance)")
    log(f"    Brightness:     {brightness:.1f} / 255")
    log(f"    Face area ratio:{face_size_score:.4f} ({face_size_score*100:.1f}% of frame)")

    vis2 = frame.copy()
    cv2.rectangle(vis2, (x, y), (x+bw, y+bh), GREEN, 2)
    info_lines = [
        f"Quality: {best_score:.3f}",
        f"Sharp: {sharpness:.0f}",
        f"Bright: {brightness:.0f}",
    ]
    for i, txt in enumerate(info_lines):
        cv2.putText(vis2, txt, (x, y + bh + 20 + i*20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, YELLOW, 1)

    save_image(vis2, output_dir / "2_best_frame_score.jpg")
    log(f"  → Saved: 2_best_frame_score.jpg")

    # ═══════════════════════════════════════════════════════
    #  BƯỚC 3: Face Alignment
    # ═══════════════════════════════════════════════════════
    log("")
    log("─" * 70)
    log("  BƯỚC 3: FACE ALIGNMENT — Căn chỉnh khuôn mặt")
    log("─" * 70)

    # 3a: ArcFace alignment (dùng cho FaceLiVT)
    log(f"  [3a] ArcFace Alignment (cho FaceLiVT)")
    log(f"    Input:    Frame {w}×{h} + 5 landmarks")
    log(f"    Method:   estimateAffinePartial2D → warpAffine")
    log(f"    Target:   112×112 chuẩn ArcFace/InsightFace")

    aligned_arcface, M = align_face_arcface(frame, landmarks)
    log(f"    Output:   {aligned_arcface.shape[1]}×{aligned_arcface.shape[0]} BGR")
    log(f"    Affine M: [[{M[0][0]:.4f}, {M[0][1]:.4f}, {M[0][2]:.4f}],")
    log(f"               [{M[1][0]:.4f}, {M[1][1]:.4f}, {M[1][2]:.4f}]]")

    # Vẽ landmarks trên aligned
    aligned_vis = aligned_arcface.copy()
    dst_pts = ARCFACE_DST
    for i, (px, py) in enumerate(dst_pts):
        cv2.circle(aligned_vis, (int(px), int(py)), 3, LANDMARK_COLORS[i], -1)

    save_image(aligned_arcface, output_dir / "3a_aligned_arcface.jpg")
    save_image(aligned_vis, output_dir / "3a_aligned_arcface_landmarks.jpg")
    log(f"    → Saved: 3a_aligned_arcface.jpg")
    log(f"    → Saved: 3a_aligned_arcface_landmarks.jpg")

    # 3b: SFace alignCrop
    if sface_rec is not None:
        log(f"  [3b] SFace alignCrop (OpenCV built-in)")
        log(f"    Input:    Frame {w}×{h} + detection row (15 values)")

        aligned_sface = sface_rec.alignCrop(frame, det)
        ah, aw = aligned_sface.shape[:2]
        log(f"    Output:   {aw}×{ah} BGR")

        save_image(aligned_sface, output_dir / "3b_aligned_sface.jpg")
        log(f"    → Saved: 3b_aligned_sface.jpg")

    # 3c: Raw crop (no alignment)
    raw_crop = frame[max(0,y):min(h,y+bh), max(0,x):min(w,x+bw)]
    if raw_crop.size > 0:
        save_image(raw_crop, output_dir / "3c_raw_crop.jpg")
        log(f"  [3c] Raw Crop (no alignment): {raw_crop.shape[1]}×{raw_crop.shape[0]}")
        log(f"    → Saved: 3c_raw_crop.jpg")

    # ═══════════════════════════════════════════════════════
    #  BƯỚC 4: Face Embedding
    # ═══════════════════════════════════════════════════════
    log("")
    log("─" * 70)
    log("  BƯỚC 4: FACE EMBEDDING — Trích xuất đặc trưng")
    log("─" * 70)

    # 4a: FaceLiVT embedding
    if facelivt_sess is not None:
        log(f"  [4a] FaceLiVT (ONNX Runtime)")
        log(f"    Model:    facelivtv2_s.onnx")
        log(f"    Input:    Aligned face 112×112 → RGB → normalize [-1,1] → CHW → (1,3,112,112)")

        rgb = cv2.cvtColor(aligned_arcface, cv2.COLOR_BGR2RGB)
        blob = (rgb.astype(np.float32) - 127.5) / 127.5
        blob = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]

        log(f"    Blob shape: {blob.shape}")
        log(f"    Blob dtype: {blob.dtype}")
        log(f"    Blob range: [{blob.min():.2f}, {blob.max():.2f}]")

        t0 = time.perf_counter()
        out = facelivt_sess.run(None, {facelivt_inp: blob})[0]
        dt = (time.perf_counter() - t0) * 1000

        emb_raw = out.flatten()
        norm = np.linalg.norm(emb_raw)
        emb = emb_raw / norm if norm > 1e-8 else emb_raw

        log(f"    Latency:  {dt:.2f}ms")
        log(f"    Output shape: {out.shape}")
        log(f"    Dimension:    {emb.shape[0]}")
        log(f"    L2 norm (raw):{norm:.6f}")
        log(f"    Range (norm): [{emb.min():.6f}, {emb.max():.6f}]")
        log(f"    Mean:         {emb.mean():.6f}")
        log(f"    Std:          {emb.std():.6f}")

        # Lưu full embedding
        emb_path = output_dir / "4a_embedding_facelivt.txt"
        with open(emb_path, "w") as f:
            f.write(f"# FaceLiVT Embedding — {emb.shape[0]}-dim\n")
            f.write(f"# L2 norm (raw): {norm:.6f}\n")
            f.write(f"# Source: {source}\n\n")
            for i, v in enumerate(emb):
                f.write(f"[{i:4d}] {v:+.8f}\n")
        log(f"    → Saved: 4a_embedding_facelivt.txt ({emb.shape[0]} values)")

    # 4b: SFace embedding
    if sface_rec is not None:
        log(f"  [4b] SFace (OpenCV FaceRecognizerSF)")
        log(f"    Model:    face_recognition_sface_2021dec.onnx")
        log(f"    Input:    alignCrop output → feature()")

        t0 = time.perf_counter()
        aligned_sf = sface_rec.alignCrop(frame, det)
        feat = sface_rec.feature(aligned_sf)
        dt = (time.perf_counter() - t0) * 1000

        sf_emb = feat.flatten()
        sf_norm = np.linalg.norm(sf_emb)
        sf_emb_n = sf_emb / sf_norm if sf_norm > 1e-8 else sf_emb

        log(f"    Latency:  {dt:.2f}ms")
        log(f"    Output shape: {feat.shape}")
        log(f"    Dimension:    {sf_emb.shape[0]}")
        log(f"    L2 norm:      {sf_norm:.6f}")
        log(f"    Range (norm): [{sf_emb_n.min():.6f}, {sf_emb_n.max():.6f}]")

        emb_path = output_dir / "4b_embedding_sface.txt"
        with open(emb_path, "w") as f:
            f.write(f"# SFace Embedding — {sf_emb.shape[0]}-dim\n")
            f.write(f"# L2 norm: {sf_norm:.6f}\n\n")
            for i, v in enumerate(sf_emb_n):
                f.write(f"[{i:4d}] {v:+.8f}\n")
        log(f"    → Saved: 4b_embedding_sface.txt ({sf_emb.shape[0]} values)")

    # ═══════════════════════════════════════════════════════
    #  BƯỚC 5: Matching (KNN Top-5)
    # ═══════════════════════════════════════════════════════
    log("")
    log("─" * 70)
    log("  BƯỚC 5: MATCHING — KNN Top-5 Voting")
    log("─" * 70)

    if facelivt_sess is not None:
        emb_query = emb.reshape(1, -1)
    elif sface_rec is not None:
        emb_query = sf_emb_n.reshape(1, -1)
    else:
        emb_query = None

    if emb_query is not None:
        log(f"  Input:      Query embedding ({emb_query.shape[1]}-dim)")

        t0 = time.perf_counter()
        match = match_embedding(emb_query)
        dt = (time.perf_counter() - t0) * 1000

        log(f"  Latency:    {dt:.2f}ms")
        if match:
            log(f"  Output:")
            log(f"    Status:       MATCH FOUND ✅")
            log(f"    Employee:     {match.get('full_name', 'N/A')} ({match.get('employee_code', 'N/A')})")
            log(f"    Confidence:   {match.get('confidence', 0):.4f}")
            log(f"    KNN Votes:    {match.get('knn_votes', 'N/A')}")
        else:
            log(f"  Output:     NO MATCH (DB trống hoặc dưới threshold)")

        # Lưu matching result
        with open(output_dir / "5_matching_result.txt", "w") as f:
            f.write(f"Query dim: {emb_query.shape[1]}\n")
            f.write(f"Latency: {dt:.2f}ms\n")
            if match:
                for k, v in match.items():
                    if k != "embedding":
                        f.write(f"{k}: {v}\n")
            else:
                f.write("Result: NO MATCH\n")
        log(f"  → Saved: 5_matching_result.txt")

    # ═══════════════════════════════════════════════════════
    #  Summary
    # ═══════════════════════════════════════════════════════
    log("")
    log("=" * 70)
    log("  ✅ PIPELINE HOÀN TẤT")
    log("=" * 70)

    # Pipeline summary table
    log("")
    log(f"  {'Bước':<30} │ {'Input':<25} │ {'Output':<25}")
    log(f"  {'─'*30}─┼─{'─'*25}─┼─{'─'*25}")
    log(f"  {'0. Original':<30} │ {'Image file':<25} │ {'BGR ' + str(w) + '×' + str(h):<25}")
    log(f"  {'1. YuNet Detection':<30} │ {'BGR ' + str(w) + '×' + str(h):<25} │ {'BBox+5 landmarks+score':<25}")
    log(f"  {'2. Best Frame Selector':<30} │ {'Frame+BBox+Landmarks':<25} │ {'Score: ' + f'{best_score:.3f}':<25}")
    log(f"  {'3. Face Alignment':<30} │ {'Frame+Landmarks':<25} │ {'BGR 112×112 aligned':<25}")
    if facelivt_sess:
        log(f"  {'4a. FaceLiVT Embedding':<30} │ {'(1,3,112,112) float32':<25} │ {str(facelivt_dim) + '-dim vector':<25}")
    if sface_rec:
        log(f"  {'4b. SFace Embedding':<30} │ {'alignCrop BGR':<25} │ {'128-dim vector':<25}")
    log(f"  {'5. KNN Matching':<30} │ {'Query embedding':<25} │ {'Match + confidence':<25}")

    # Lưu summary
    with open(output_dir / "pipeline_summary.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(summary))

    log(f"\n  📁 Tất cả output: {output_dir}")


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Visualize pipeline I/O")
    parser.add_argument("--image", type=str, default="", help="Đường dẫn ảnh")
    parser.add_argument("--camera", type=int, default=-1, help="Camera index")
    parser.add_argument("--output", type=str, default="", help="Thư mục output")
    args = parser.parse_args()

    out = Path(args.output) if args.output else PROJECT_ROOT / "pipeline_output"

    if args.camera >= 0:
        run_pipeline("", out, use_camera=True, camera_idx=args.camera)
    elif args.image:
        img_path = Path(args.image)
        if not img_path.is_absolute():
            img_path = PROJECT_ROOT / img_path
        run_pipeline(str(img_path), out)
    else:
        # Auto-find
        for folder in [PROJECT_ROOT / "captures", PROJECT_ROOT / "dataset_clean"]:
            if folder.exists():
                for f in folder.rglob("*.jpg"):
                    run_pipeline(str(f), out)
                    return
        print("Cần chỉ định --image hoặc --camera")

if __name__ == "__main__":
    main()
