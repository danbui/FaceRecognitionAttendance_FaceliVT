"""
In output embedding của FP32 và INT8 cho 1 ảnh.

  python benchmarks/print_model_output.py
  python benchmarks/print_model_output.py --image "dataset_clean/ca sĩ Sơn Tùng/001.jpg"
"""
import sys, random
from pathlib import Path
import cv2, numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.face_detector import FaceDetector
from app.config import FACELIVT_MODEL, MODELS_DIR

FACELIVT_INT8_MODEL = MODELS_DIR / "facelivtv2_s_512_int8.onnx"
IMG_EXTS = {".jpg", ".jpeg", ".png"}

ARCFACE_DST = np.array([
    [38.2946, 51.6963], [73.5318, 51.5014],
    [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]
], dtype=np.float32)

def imread_u(p):
    return cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)

def align_face(frame, det):
    lm = det[4:14].reshape((5, 2))
    dst = ARCFACE_DST.copy()
    M, _ = cv2.estimateAffinePartial2D(lm, dst)
    if M is None: M = cv2.getAffineTransform(lm[:3], dst[:3])
    return cv2.warpAffine(frame, M, (112, 112), borderValue=0.0)

def infer(sess, aligned):
    rgb = cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB)
    blob = (rgb.astype(np.float32) - 127.5) / 127.5
    blob = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]
    inp = sess.get_inputs()[0].name
    raw = sess.run(None, {inp: blob})[0].flatten()
    normed = raw / (np.linalg.norm(raw) + 1e-8)
    return raw, normed

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=str, default="")
    parser.add_argument("--dataset", type=str, default="dataset_clean")
    args = parser.parse_args()

    # Find image
    if args.image:
        img_path = Path(args.image)
        if not img_path.is_absolute(): img_path = PROJECT_ROOT / img_path
    else:
        ds = PROJECT_ROOT / args.dataset
        for pdir in sorted(ds.iterdir()):
            if pdir.is_dir():
                imgs = [f for f in pdir.iterdir() if f.suffix.lower() in IMG_EXTS]
                if imgs:
                    img_path = imgs[0]
                    break

    print(f"📸 Ảnh: {img_path}")
    print(f"👤 Người: {img_path.parent.name}")

    img = imread_u(img_path)
    detector = FaceDetector()
    dets = detector.detect_all(img)
    det = dets[int(np.argmax(dets[:, 2] * dets[:, 3]))]
    aligned = align_face(img, det)

    import onnxruntime as ort

    # FP32
    print(f"\n{'='*70}")
    print(f"  MODEL: FaceLiVT2_S FP32")
    print(f"  File : {FACELIVT_MODEL.name}")
    print(f"{'='*70}")
    sess_fp32 = ort.InferenceSession(str(FACELIVT_MODEL), providers=['CPUExecutionProvider'])
    raw_fp32, norm_fp32 = infer(sess_fp32, aligned)
    print(f"  Input : aligned face 112×112×3, float32, normalized [-1, 1]")
    print(f"  Output: {raw_fp32.shape} float32 vector")
    print(f"  L2 norm (before normalize): {np.linalg.norm(raw_fp32):.6f}")
    print(f"\n  Raw output (first 20 dims):")
    print(f"  {raw_fp32[:20]}")
    print(f"\n  L2-normalized (first 20 dims):")
    print(f"  {norm_fp32[:20]}")
    print(f"\n  Stats: min={raw_fp32.min():.5f}  max={raw_fp32.max():.5f}  mean={raw_fp32.mean():.5f}  std={raw_fp32.std():.5f}")

    # INT8
    print(f"\n{'='*70}")
    print(f"  MODEL: FaceLiVT2_S INT8 (Quantized)")
    print(f"  File : {FACELIVT_INT8_MODEL.name}")
    print(f"{'='*70}")
    sess_int8 = ort.InferenceSession(str(FACELIVT_INT8_MODEL), providers=['CPUExecutionProvider'])
    raw_int8, norm_int8 = infer(sess_int8, aligned)
    print(f"  Input : aligned face 112×112×3, float32, normalized [-1, 1]")
    print(f"  Output: {raw_int8.shape} float32 vector (dequantized)")
    print(f"  L2 norm (before normalize): {np.linalg.norm(raw_int8):.6f}")
    print(f"\n  Raw output (first 20 dims):")
    print(f"  {raw_int8[:20]}")
    print(f"\n  L2-normalized (first 20 dims):")
    print(f"  {norm_int8[:20]}")
    print(f"\n  Stats: min={raw_int8.min():.5f}  max={raw_int8.max():.5f}  mean={raw_int8.mean():.5f}  std={raw_int8.std():.5f}")

    # Quick comparison
    cos = float(np.dot(norm_fp32, norm_int8))
    print(f"\n{'='*70}")
    print(f"  Cosine(FP32, INT8) = {cos:.6f}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
