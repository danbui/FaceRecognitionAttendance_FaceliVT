"""Xuất embedding đầy đủ từ FaceLiVT ONNX model."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import onnxruntime as ort
import cv2

MODEL = Path(__file__).resolve().parent.parent / "models" / "facelivtv2_s.onnx"
OUTPUT = Path(__file__).resolve().parent / "embedding_sample.txt"

# Tìm 1 ảnh thật
img_path = None
for folder in [Path(__file__).resolve().parent.parent / "captures",
               Path(__file__).resolve().parent.parent / "dataset_clean"]:
    if folder.exists():
        for f in folder.rglob("*.jpg"):
            img_path = f
            break
    if img_path:
        break

# Load model
session = ort.InferenceSession(str(MODEL), providers=['CPUExecutionProvider'])
inp = session.get_inputs()[0]
out_meta = session.get_outputs()[0]

print(f"Model : {MODEL.name}")
print(f"Input : name={inp.name}, shape={inp.shape}, type={inp.type}")
print(f"Output: name={out_meta.name}, shape={out_meta.shape}, type={out_meta.type}")

# Chuẩn bị input
if img_path:
    print(f"\nẢnh test: {img_path.name}")
    buf = np.fromfile(str(img_path), dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    img = cv2.resize(img, (112, 112))
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    blob = (rgb.astype(np.float32) - 127.5) / 127.5
    blob = np.transpose(blob, (2, 0, 1))
    blob = np.expand_dims(blob, axis=0)
else:
    print("\nKhông tìm thấy ảnh thật, dùng random noise")
    blob = np.random.randn(1, 3, 112, 112).astype(np.float32)

# Inference
result = session.run(None, {inp.name: blob})[0]
emb = result.flatten()
norm = np.linalg.norm(emb)
emb_norm = emb / norm

# In tóm tắt
print(f"\n{'='*50}")
print(f"Output shape : {result.shape}")
print(f"Flatten dim  : {emb.shape[0]}")
print(f"L2 norm (raw): {norm:.6f}")
print(f"Min          : {emb.min():.6f}")
print(f"Max          : {emb.max():.6f}")
print(f"Mean         : {emb.mean():.6f}")
print(f"Std          : {emb.std():.6f}")
print(f"{'='*50}")

# Ghi đầy đủ ra file
with open(OUTPUT, "w") as f:
    f.write(f"# FaceLiVT ONNX Embedding Output\n")
    f.write(f"# Model: {MODEL.name}\n")
    f.write(f"# Input shape: {inp.shape}\n")
    f.write(f"# Output shape: {result.shape}\n")
    f.write(f"# Dimension: {emb.shape[0]}\n")
    f.write(f"# L2 norm (raw): {norm:.6f}\n")
    f.write(f"# Image: {img_path.name if img_path else 'random_noise'}\n\n")

    f.write(f"# === RAW EMBEDDING ({emb.shape[0]} values) ===\n")
    for i, v in enumerate(emb):
        f.write(f"[{i:4d}] {v:+.8f}\n")

    f.write(f"\n# === L2-NORMALIZED EMBEDDING ({emb_norm.shape[0]} values) ===\n")
    for i, v in enumerate(emb_norm):
        f.write(f"[{i:4d}] {v:+.8f}\n")

print(f"\n✅ Đã xuất đầy đủ {emb.shape[0]} chiều → {OUTPUT}")
print(f"   Mở file để xem: {OUTPUT}")
