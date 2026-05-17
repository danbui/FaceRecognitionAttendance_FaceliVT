# ============================================================
# CELL 1: Cài đặt thư viện
# ============================================================
# !pip install timm onnxruntime opencv-python-headless onnx

# ============================================================
# CELL 2: Mount Google Drive + chuẩn bị
# ============================================================
# Trước khi chạy cell này, upload lên Google Drive thư mục:
#   My Drive/FaceLiVT_Finetune/
#     ├── facelivtv2.py          
#     ├── facelivtv2-l.pt        
#     ├── VN-celeb-clean.zip
#     └── dataset_clean.zip
#
"""
from google.colab import drive
drive.mount('/content/drive')

import os, shutil

# ĐỔI TÊN DATASET Ở ĐÂY (không cần có đuôi .zip)
# Chọn 1 trong 2: "VN-celeb-clean" hoặc "dataset_clean"
DATASET_NAME = "VN-celeb-clean"

DRIVE_DIR = "/content/drive/MyDrive/FaceLiVT_Finetune"
WORK_DIR = "/content/finetune"
os.makedirs(WORK_DIR, exist_ok=True)

# Copy model files
shutil.copy(f"{DRIVE_DIR}/facelivtv2.py", f"{WORK_DIR}/facelivtv2.py")
shutil.copy(f"{DRIVE_DIR}/facelivtv2-l.pt", f"{WORK_DIR}/facelivtv2-l.pt")

# Giải nén dataset
if not os.path.exists(f"{WORK_DIR}/{DATASET_NAME}"):
    print(f"Đang giải nén {DATASET_NAME}.zip...")
    shutil.unpack_archive(f"{DRIVE_DIR}/{DATASET_NAME}.zip", WORK_DIR)
    print("Xong!")

# Đếm
people = [d for d in os.listdir(f"{WORK_DIR}/{DATASET_NAME}")
          if os.path.isdir(f"{WORK_DIR}/{DATASET_NAME}/{d}")]
total_imgs = sum(len([f for f in os.listdir(f"{WORK_DIR}/{DATASET_NAME}/{p}")
                      if f.lower().endswith(('.jpg','.jpeg','.png'))])
                 for p in people)
print(f"Dataset: {len(people)} người, {total_imgs} ảnh")
"""

# ============================================================
# CELL 2.5: Align faces — Tiền xử lý quan trọng!
# ============================================================
# Align tất cả ảnh theo chuẩn ArcFace 5 landmarks.
# Đảm bảo train data đồng nhất với inference pipeline.
# Chỉ cần chạy 1 lần, kết quả lưu vào dataset_aligned/
"""
import cv2
import numpy as np
from pathlib import Path

# Nhớ chạy Cell 2 trước để có biến DATASET_NAME
WORK_DIR = "/content/finetune"
SRC_DIR = f"{WORK_DIR}/{DATASET_NAME}"
DST_DIR = f"{WORK_DIR}/{DATASET_NAME}_aligned"
IMG_EXTS = {'.jpg', '.jpeg', '.png', '.bmp'}

# Download YuNet model nếu chưa có
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
YUNET_PATH = f"{WORK_DIR}/face_detection_yunet_2023mar.onnx"
if not os.path.exists(YUNET_PATH):
    import urllib.request
    print("Downloading YuNet...")
    urllib.request.urlretrieve(YUNET_URL, YUNET_PATH)
    print("Done!")

# ArcFace standard 5-point landmarks for 112x112
ARCFACE_DST = np.array([
    [38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
    [41.5493, 92.3655], [70.7299, 92.2041]
], dtype=np.float32)

def align_face_arcface(img, landmarks, size=112):
    dst = ARCFACE_DST * (float(size) / 112.0)
    M, _ = cv2.estimateAffinePartial2D(landmarks, dst)
    if M is None:
        M = cv2.getAffineTransform(landmarks[:3], dst[:3])
    return cv2.warpAffine(img, M, (size, size), borderValue=0.0)

# Load YuNet detector
detector = cv2.FaceDetectorYN.create(YUNET_PATH, "", (320, 320),
                                      score_threshold=0.9, nms_threshold=0.8)

# Process all images
total, aligned, failed = 0, 0, 0
for person_dir in sorted(Path(SRC_DIR).iterdir()):
    if not person_dir.is_dir():
        continue
    dst_person = Path(DST_DIR) / person_dir.name
    dst_person.mkdir(parents=True, exist_ok=True)

    for img_path in sorted(person_dir.iterdir()):
        if img_path.suffix.lower() not in IMG_EXTS:
            continue
        total += 1
        dst_path = dst_person / img_path.name

        # Skip if already aligned
        if dst_path.exists():
            aligned += 1
            continue

        img = cv2.imread(str(img_path))
        if img is None:
            failed += 1
            continue

        h, w = img.shape[:2]
        detector.setInputSize((w, h))
        _, dets = detector.detect(img)

        if dets is not None and len(dets) > 0:
            # Largest face
            areas = dets[:, 2] * dets[:, 3]
            det = dets[np.argmax(areas)]
            landmarks = det[4:14].reshape((5, 2))
            face_aligned = align_face_arcface(img, landmarks)
        else:
            # Fallback: center crop + resize (no face detected)
            face_aligned = cv2.resize(img, (112, 112))

        cv2.imwrite(str(dst_path), face_aligned)
        aligned += 1

    if total % 500 == 0:
        print(f"  {total} processed, {aligned} aligned, {failed} failed")

print(f"\n✅ Alignment hoàn tất!")
print(f"  Total: {total}, Aligned: {aligned}, Failed: {failed}")
print(f"  Output: {DST_DIR}")
"""

# ============================================================
# CELL 3: Import và định nghĩa model + ArcFace + Dataset
# ============================================================
"""
import sys, math, random, os
from pathlib import Path
from datetime import datetime

import numpy as np
import cv2
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader, Subset
import torchvision.transforms as T
from torch.optim.lr_scheduler import CosineAnnealingLR
from PIL import Image

WORK_DIR = "/content/finetune"
sys.path.insert(0, WORK_DIR)
from facelivtv2 import facelivtv2_s, facelivtv2_xs, facelivtv2_l

# ── ArcFace Head ──
class ArcFaceHead(nn.Module):
    def __init__(self, embed_dim, num_classes, s=32.0, m=0.50):
        super().__init__()
        self.s, self.m = s, m
        self.weight = nn.Parameter(torch.FloatTensor(num_classes, embed_dim))
        nn.init.xavier_uniform_(self.weight)
        self.cos_m = math.cos(m)
        self.sin_m = math.sin(m)
        self.th = math.cos(math.pi - m)
        self.mm = math.sin(math.pi - m) * m

    def forward(self, embeddings, labels):
        cosine = F.linear(F.normalize(embeddings), F.normalize(self.weight))
        sine = torch.sqrt(1.0 - cosine.pow(2).clamp(0, 1))
        phi = cosine * self.cos_m - sine * self.sin_m
        phi = torch.where(cosine > self.th, phi, cosine - self.mm)
        one_hot = torch.zeros_like(cosine)
        one_hot.scatter_(1, labels.view(-1, 1).long(), 1)
        return self.s * ((one_hot * phi) + ((1.0 - one_hot) * cosine))

# ── Training Wrapper ──
class FaceLiVTTrainer(nn.Module):
    def __init__(self, backbone, embed_dim, num_classes, s=32.0, m=0.50):
        super().__init__()
        self.backbone = backbone
        self.arcface = ArcFaceHead(embed_dim, num_classes, s, m)

    def forward(self, x, labels=None):
        feat = self.backbone.forward_feature(x)
        feat = self.backbone.pre_head(feat).flatten(1)
        emb = self.backbone.head(feat)
        if labels is not None:
            return self.arcface(emb, labels), emb
        return emb

# ── Dataset ──
# Dùng ảnh đã align từ Cell 2.5 (dataset_aligned/)
# Ảnh đã là 112x112, đã căn chỉnh ArcFace → đồng nhất với inference
IMG_EXTS = {'.jpg', '.jpeg', '.png', '.bmp'}

class FaceDataset(Dataset):
    def __init__(self, root_dir, transform=None):
        self.transform = transform
        self.samples, self.classes = [], []
        self.class_to_indices = {}  # label_idx -> [sample_indices] (cho split theo identity)
        root = Path(root_dir)
        idx = 0
        for d in sorted(root.iterdir()):
            if not d.is_dir(): continue
            imgs = sorted(f for f in d.iterdir() if f.suffix.lower() in IMG_EXTS)
            if len(imgs) < 2: continue
            self.classes.append(d.name)
            self.class_to_indices[idx] = []
            for f in imgs:
                self.class_to_indices[idx].append(len(self.samples))
                self.samples.append((str(f), idx))
            idx += 1
        # NOTE: Không shuffle ở đây — shuffle sẽ do DataLoader đảm nhiệm.

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, i):
        path, label = self.samples[i]
        # Ảnh đã align 112x112 từ Cell 2.5
        img = cv2.imread(path)
        if img is None:
            img = np.zeros((112, 112, 3), dtype=np.uint8)
        if img.shape[:2] != (112, 112):
            img = cv2.resize(img, (112, 112))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if self.transform:
            img = self.transform(Image.fromarray(img))
        else:
            img = torch.from_numpy(img).permute(2,0,1).float()
            img = (img - 127.5) / 127.5
        return img, label

class TransformSubset(Dataset):
    """Subset với transform riêng — tránh data leakage khi dùng 2 Dataset."""
    def __init__(self, dataset, indices, transform):
        self.dataset = dataset
        self.indices = indices
        self.transform = transform
    def __len__(self):
        return len(self.indices)
    def __getitem__(self, i):
        path, label = self.dataset.samples[self.indices[i]]
        img = cv2.imread(path)
        if img is None:
            img = np.zeros((112, 112, 3), dtype=np.uint8)
        if img.shape[:2] != (112, 112):
            img = cv2.resize(img, (112, 112))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = self.transform(Image.fromarray(img))
        return img, label

def get_transforms(train=True):
    if train:
        return T.Compose([
            T.RandomHorizontalFlip(0.5),
            T.RandomRotation(10),
            T.ColorJitter(0.2, 0.2, 0.1),
            T.RandomGrayscale(0.05),
            T.ToTensor(),
            T.Normalize([0.5]*3, [0.5]*3),
            T.RandomErasing(0.1, scale=(0.02, 0.1)),
        ])
    return T.Compose([T.ToTensor(), T.Normalize([0.5]*3, [0.5]*3)])

# ── Freeze helper ──
def freeze_stages(model, n=2):
    bb = model.backbone
    for i in range(min(n, len(bb.patch_embedds))):
        for p in bb.patch_embedds[i].parameters(): p.requires_grad = False
    for i in range(min(n, len(bb.stages))):
        for p in bb.stages[i].parameters(): p.requires_grad = False
    total = sum(p.numel() for p in model.parameters())
    train = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  Params: {train:,} trainable / {total:,} total")

print("✅ Định nghĩa xong!")
"""

# ============================================================
# CELL 4: Load model + chuẩn bị data
# ============================================================
"""
# ═══ CẤU HÌNH ═══════════════════════════════════════
VARIANT       = "l"        # "s", "xs", hoặc "l"
EPOCHS        = 20
LR            = 1e-4
BATCH_SIZE    = 32
FREEZE_STAGES = 2          # 0=full finetune, 2=khuyến nghị
ARCFACE_S     = 32.0
ARCFACE_M     = 0.50
VAL_RATIO     = 0.15
# ════════════════════════════════════════════════════

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {device}")

# Load backbone
if VARIANT == "xs":
    backbone = facelivtv2_xs(num_classes=512, pretrained=False)
    pt_path = f"{WORK_DIR}/facelivtv2-xs.pt"
elif VARIANT == "l":
    backbone = facelivtv2_l(num_classes=512, pretrained=False)
    pt_path = f"{WORK_DIR}/facelivtv2-l.pt"
else:
    backbone = facelivtv2_s(num_classes=512, pretrained=False)
    pt_path = f"{WORK_DIR}/facelivtv2_s.pt"

state = torch.load(pt_path, map_location="cpu") # Tắt weights_only vì file có thể lưu cả metadata
if "state_dict" in state:
    state = state["state_dict"]
if any(k.startswith("module.") for k in state):
    state = {k.replace("module.", ""): v for k, v in state.items()}
missing, unexpected = backbone.load_state_dict(state, strict=False)
print(f"✅ Loaded {pt_path}")
if missing: print(f"  Missing keys: {len(missing)}")

# Dataset — dùng ảnh đã align
ds_path = f"{WORK_DIR}/{DATASET_NAME}_aligned"  # ← tự động lấy thư mục đã align
base_ds = FaceDataset(ds_path)
num_classes = len(base_ds.classes)
print(f"📂 {num_classes} người, {len(base_ds)} ảnh")

# ── Split theo ẢNH trong mỗi người (đúng cho bài toán attendance) ──
# Mỗi người có ảnh trong CẢ train VÀ val, nhưng ảnh cụ thể chỉ nằm 1 bên.
# Giống thực tế: enrollment (gallery) + chấm công (probe) = cùng người, khác ảnh.
rng = random.Random(42)
train_indices = []
val_indices = []
for class_id, sample_indices in base_ds.class_to_indices.items():
    indices = sample_indices.copy()
    rng.shuffle(indices)
    n_val = max(1, int(len(indices) * VAL_RATIO))  # Ít nhất 1 ảnh val
    val_indices.extend(indices[:n_val])
    train_indices.extend(indices[n_val:])

print(f"  Split by IMAGE (per person): mỗi người có ảnh ở cả train+val")
print(f"  Train: {len(train_indices)} imgs | Val: {len(val_indices)} imgs")
print(f"  Tất cả {num_classes} người đều có trong cả 2 set")

# TransformSubset đảm bảo cùng index → cùng ảnh, chỉ khác transform
train_loader = DataLoader(
    TransformSubset(base_ds, train_indices, get_transforms(True)),
    batch_size=BATCH_SIZE, shuffle=True, num_workers=2, pin_memory=True, drop_last=True)
val_loader = DataLoader(
    TransformSubset(base_ds, val_indices, get_transforms(False)),
    batch_size=BATCH_SIZE, shuffle=False, num_workers=2, pin_memory=True)

# Build model
model = FaceLiVTTrainer(backbone, 512, num_classes, ARCFACE_S, ARCFACE_M)
if FREEZE_STAGES > 0:
    freeze_stages(model, FREEZE_STAGES)
model = model.to(device)

# Optimizer: ArcFace head cần LR cao hơn 100x (random init)
arcface_lr = LR * 100  # 1e-4 * 100 = 1e-2
bb_params = [p for n, p in model.named_parameters()
             if p.requires_grad and not n.startswith("arcface")]
af_params = [p for n, p in model.named_parameters()
             if p.requires_grad and n.startswith("arcface")]
optimizer = torch.optim.AdamW([
    {"params": bb_params, "lr": LR},
    {"params": af_params, "lr": arcface_lr},
], weight_decay=5e-4)
scheduler = CosineAnnealingLR(optimizer, T_max=EPOCHS, eta_min=LR*0.01)
criterion = nn.CrossEntropyLoss()

print(f"  Backbone LR: {LR} | ArcFace LR: {arcface_lr}")
print("✅ Sẵn sàng training!")
"""

# ============================================================
# CELL 5: TRAINING
# ============================================================
"""
best_acc, best_epoch = 0, 0
save_dir = f"{WORK_DIR}/checkpoints"
os.makedirs(save_dir, exist_ok=True)

for epoch in range(EPOCHS):
    # ── Train ──
    model.train()
    t_loss, t_correct, t_total = 0, 0, 0
    for imgs, labels in train_loader:
        imgs, labels = imgs.to(device), labels.to(device)
        optimizer.zero_grad()
        logits, _ = model(imgs, labels)
        loss = criterion(logits, labels)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
        t_loss += loss.item() * imgs.size(0)
        t_correct += logits.argmax(1).eq(labels).sum().item()
        t_total += labels.size(0)

    # ── Val ──
    model.eval()
    v_loss, v_correct, v_total = 0, 0, 0
    with torch.no_grad():
        for imgs, labels in val_loader:
            imgs, labels = imgs.to(device), labels.to(device)
            logits, _ = model(imgs, labels)
            loss = criterion(logits, labels)
            v_loss += loss.item() * imgs.size(0)
            v_correct += logits.argmax(1).eq(labels).sum().item()
            v_total += labels.size(0)

    scheduler.step()
    t_acc = 100*t_correct/t_total
    v_acc = 100*v_correct/v_total if v_total > 0 else 0

    print(f"Epoch {epoch+1}/{EPOCHS}  "
          f"Train: Loss={t_loss/t_total:.4f} Acc={t_acc:.1f}%  "
          f"Val: Loss={v_loss/max(v_total,1):.4f} Acc={v_acc:.1f}%  "
          f"LR={optimizer.param_groups[0]['lr']:.2e}")

    if v_acc > best_acc:
        best_acc, best_epoch = v_acc, epoch+1
        torch.save(backbone.state_dict(), f"{save_dir}/best.pt")
        print(f"  💾 Best saved! (Val Acc={v_acc:.1f}%)")

print(f"\n✅ Hoàn tất! Best: Epoch {best_epoch}, Val Acc={best_acc:.1f}%")
"""

# ============================================================
# CELL 6: Export ONNX + tải về
# ============================================================
"""
import onnx

# Load best weights
backbone.load_state_dict(torch.load(f"{save_dir}/best.pt", map_location="cpu", weights_only=True))
backbone.eval().cpu()

# Export ONNX (may create external .data file)
onnx_path_raw = f"{WORK_DIR}/facelivtv2_{VARIANT}_finetuned_{DATASET_NAME}_raw.onnx"
onnx_path     = f"{WORK_DIR}/facelivtv2_{VARIANT}_finetuned_{DATASET_NAME}.onnx"
dummy = torch.randn(1, 3, 112, 112)

torch.onnx.export(backbone, dummy, onnx_path_raw,
    input_names=["input"], output_names=["embedding"],
    dynamic_axes={"input": {0: "batch"}, "embedding": {0: "batch"}},
    opset_version=14, do_constant_folding=True)

# ── Merge external data into single file ──────────────
# PyTorch ONNX export sometimes creates .data files alongside .onnx
# which causes issues when copying between machines.
# Solution: load with external data, then save as single file.
onnx_model = onnx.load(onnx_path_raw, load_external_data=True)
onnx.save_model(onnx_model, onnx_path,
                save_as_external_data=False)  # Single file!
print(f"✅ ONNX (single file): {onnx_path}")
print(f"   Size: {os.path.getsize(onnx_path)/1024/1024:.1f} MB")

# Clean up raw export
for f in [onnx_path_raw, onnx_path_raw + ".data"]:
    if os.path.exists(f):
        os.remove(f)

# Verify with ONNX Runtime
import onnxruntime as ort
sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
out = sess.run(None, {sess.get_inputs()[0].name: dummy.numpy()})[0]
print(f"   Input:  {dummy.shape}")
print(f"   Output: {out.shape}")
print(f"   Dim:    {out.flatten().shape[0]}")

# Save best .pt checkpoint with proper name
pt_out = f"{WORK_DIR}/facelivtv2_{VARIANT}_finetuned_{DATASET_NAME}_best.pt"
torch.save(backbone.state_dict(), pt_out)

# Copy to Drive
import shutil
drive_out = "/content/drive/MyDrive/FaceLiVT_Finetune"
shutil.copy(onnx_path, f"{drive_out}/facelivtv2_{VARIANT}_finetuned_{DATASET_NAME}.onnx")
shutil.copy(pt_out, f"{drive_out}/facelivtv2_{VARIANT}_finetuned_{DATASET_NAME}_best.pt")
print(f"✅ Đã copy về Google Drive: {drive_out}")

# Tải trực tiếp
from google.colab import files
files.download(onnx_path)
files.download(pt_out)
"""
