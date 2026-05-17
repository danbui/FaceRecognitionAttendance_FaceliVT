"""
Fine-tune FaceLiVT2 trên dataset_clean bằng ArcFace Loss.

Workflow:
  1. Load pretrained FaceLiVT2-S (hoặc XS) từ file .pt
  2. Thêm ArcFace classification head (num_identities = số người trong dataset)
  3. Train với ArcFace loss + data augmentation
  4. Export embedding model (không có ArcFace head) ra ONNX

Cách chạy:
  # Fine-tune FaceLiVT2-S (mặc định)
  python scripts/finetune_facelivt.py

  # Fine-tune FaceLiVT2-XS (nhẹ hơn)
  python scripts/finetune_facelivt.py --variant xs

  # Tuỳ chỉnh
  python scripts/finetune_facelivt.py --epochs 30 --lr 1e-4 --batch-size 32 --freeze-stages 2

Yêu cầu thêm:
  pip install torch torchvision timm
"""

import sys
import math
import argparse
import random
from pathlib import Path
from datetime import datetime

import numpy as np

# ── Project paths ──────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "models"))

# ── Lazy imports (kiểm tra trước khi chạy) ────────────
def check_dependencies():
    missing = []
    try:
        import torch
    except ImportError:
        missing.append("torch")
    try:
        import torchvision
    except ImportError:
        missing.append("torchvision")
    try:
        import timm
    except ImportError:
        missing.append("timm")
    if missing:
        print(f"❌ Thiếu thư viện: {', '.join(missing)}")
        print(f"   Cài đặt: pip install {' '.join(missing)}")
        sys.exit(1)

check_dependencies()

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
import torchvision.transforms as T
from torch.optim.lr_scheduler import CosineAnnealingLR
import cv2

from facelivtv2 import facelivtv2_s, facelivtv2_xs, reparameterize


# ═══════════════════════════════════════════════════════════
#  ArcFace Loss Head
# ═══════════════════════════════════════════════════════════

class ArcFaceHead(nn.Module):
    """
    ArcFace (Additive Angular Margin) classification head.
    Đây là loss function chuẩn cho face recognition training.

    - s: scale factor (thường 32-64)
    - m: angular margin (thường 0.5 cho ArcFace)
    """
    def __init__(self, embed_dim, num_classes, s=32.0, m=0.50):
        super().__init__()
        self.s = s
        self.m = m
        self.weight = nn.Parameter(torch.FloatTensor(num_classes, embed_dim))
        nn.init.xavier_uniform_(self.weight)

        self.cos_m = math.cos(m)
        self.sin_m = math.sin(m)
        self.th = math.cos(math.pi - m)  # threshold
        self.mm = math.sin(math.pi - m) * m

    def forward(self, embeddings, labels):
        # Normalize
        cosine = F.linear(F.normalize(embeddings), F.normalize(self.weight))
        sine = torch.sqrt(1.0 - torch.pow(cosine, 2).clamp(0, 1))

        # cos(theta + m)
        phi = cosine * self.cos_m - sine * self.sin_m

        # Numerical stability
        phi = torch.where(cosine > self.th, phi, cosine - self.mm)

        # One-hot
        one_hot = torch.zeros_like(cosine)
        one_hot.scatter_(1, labels.view(-1, 1).long(), 1)

        output = (one_hot * phi) + ((1.0 - one_hot) * cosine)
        output *= self.s

        return output


# ═══════════════════════════════════════════════════════════
#  Face Dataset
# ═══════════════════════════════════════════════════════════

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}

class FaceDataset(Dataset):
    """
    Load ảnh từ dataset_clean (cấu trúc: dataset_clean/<person_name>/*.jpg)
    Trả về (tensor 3x112x112, label_index)
    """
    def __init__(self, root_dir, transform=None, min_images=2):
        self.root = Path(root_dir)
        self.transform = transform
        self.samples = []   # [(path, label_idx), ...]
        self.classes = []   # [person_name, ...]
        self.class_to_idx = {}

        # Scan directories
        people = sorted([d for d in self.root.iterdir() if d.is_dir()])
        idx = 0
        for person_dir in people:
            imgs = [f for f in person_dir.iterdir() if f.suffix.lower() in IMG_EXTS]
            if len(imgs) < min_images:
                continue
            self.classes.append(person_dir.name)
            self.class_to_idx[person_dir.name] = idx
            for img_path in imgs:
                self.samples.append((img_path, idx))
            idx += 1

        random.shuffle(self.samples)
        print(f"  📂 Dataset: {len(self.classes)} người, {len(self.samples)} ảnh")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index):
        path, label = self.samples[index]

        # Đọc ảnh (hỗ trợ Unicode path)
        buf = np.fromfile(str(path), dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)

        if img is None:
            # Fallback: ảnh lỗi → black image
            img = np.zeros((112, 112, 3), dtype=np.uint8)

        # Resize nếu cần
        if img.shape[0] != 112 or img.shape[1] != 112:
            img = cv2.resize(img, (112, 112))

        # BGR → RGB
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # Numpy HWC → PIL-like → transform
        if self.transform:
            from PIL import Image
            pil_img = Image.fromarray(img)
            tensor = self.transform(pil_img)
        else:
            tensor = torch.from_numpy(img).permute(2, 0, 1).float()
            tensor = (tensor - 127.5) / 127.5

        return tensor, label


def get_transforms(is_train=True):
    """Data augmentation cho training."""
    if is_train:
        return T.Compose([
            T.RandomHorizontalFlip(p=0.5),
            T.RandomRotation(degrees=10),
            T.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.1),
            T.RandomGrayscale(p=0.05),
            T.ToTensor(),
            T.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),  # → [-1, 1]
            T.RandomErasing(p=0.1, scale=(0.02, 0.1)),
        ])
    else:
        return T.Compose([
            T.ToTensor(),
            T.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
        ])


# ═══════════════════════════════════════════════════════════
#  Training Model Wrapper
# ═══════════════════════════════════════════════════════════

class FaceLiVTTrainer(nn.Module):
    """
    Wrapper kết hợp:
      - FaceLiVT2 backbone (pretrained) → 512-dim embedding
      - ArcFace head → classification logits
    """
    def __init__(self, backbone, embed_dim, num_classes, arcface_s=32.0, arcface_m=0.50):
        super().__init__()
        self.backbone = backbone
        self.arcface = ArcFaceHead(embed_dim, num_classes, s=arcface_s, m=arcface_m)

    def forward(self, x, labels=None):
        # Lấy embedding từ backbone
        feat = self.backbone.forward_feature(x)
        feat = self.backbone.pre_head(feat).flatten(1)
        embeddings = self.backbone.head(feat)

        if labels is not None:
            # Training mode: trả logits qua ArcFace
            logits = self.arcface(embeddings, labels)
            return logits, embeddings
        else:
            # Inference mode: chỉ trả embedding
            return embeddings

    def get_backbone(self):
        """Trả về backbone riêng (dùng để export ONNX)."""
        return self.backbone


# ═══════════════════════════════════════════════════════════
#  Freeze/Unfreeze helpers
# ═══════════════════════════════════════════════════════════

def freeze_backbone_stages(model, num_stages_to_freeze=2):
    """
    Freeze N stage đầu tiên của backbone.
    Giữ các stage sau + pre_head + head có thể train.
    
    num_stages_to_freeze:
      0 = train tất cả (full fine-tune)
      1 = freeze stage 0 (stem + stage0)
      2 = freeze stage 0-1 (khuyến nghị cho dataset nhỏ)
      3 = freeze stage 0-2 (chỉ train stage cuối)
    """
    backbone = model.backbone

    # Freeze patch embeddings (stem)
    if num_stages_to_freeze >= 1:
        for i in range(min(num_stages_to_freeze, len(backbone.patch_embedds))):
            for param in backbone.patch_embedds[i].parameters():
                param.requires_grad = False

    # Freeze stages
    for i in range(min(num_stages_to_freeze, len(backbone.stages))):
        for param in backbone.stages[i].parameters():
            param.requires_grad = False

    # Count trainable params
    total = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    frozen = total - trainable
    print(f"  🧊 Freeze {num_stages_to_freeze} stages: "
          f"{trainable:,} trainable / {frozen:,} frozen / {total:,} total params")


# ═══════════════════════════════════════════════════════════
#  Training Loop
# ═══════════════════════════════════════════════════════════

def train_one_epoch(model, dataloader, optimizer, criterion, device, epoch, total_epochs):
    model.train()
    total_loss = 0
    correct = 0
    total = 0

    for batch_idx, (images, labels) in enumerate(dataloader):
        images = images.to(device)
        labels = labels.to(device)

        optimizer.zero_grad()
        logits, embeddings = model(images, labels)

        loss = criterion(logits, labels)
        loss.backward()

        # Gradient clipping
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)

        optimizer.step()

        total_loss += loss.item() * images.size(0)
        _, predicted = logits.max(1)
        correct += predicted.eq(labels).sum().item()
        total += labels.size(0)

        if (batch_idx + 1) % 20 == 0 or (batch_idx + 1) == len(dataloader):
            acc = 100.0 * correct / total
            avg_loss = total_loss / total
            print(f"    Epoch [{epoch+1}/{total_epochs}] "
                  f"Batch [{batch_idx+1}/{len(dataloader)}] "
                  f"Loss: {avg_loss:.4f}  Acc: {acc:.1f}%")

    return total_loss / total, 100.0 * correct / total


@torch.no_grad()
def validate(model, dataloader, criterion, device):
    model.eval()
    total_loss = 0
    correct = 0
    total = 0

    for images, labels in dataloader:
        images = images.to(device)
        labels = labels.to(device)

        logits, _ = model(images, labels)
        loss = criterion(logits, labels)

        total_loss += loss.item() * images.size(0)
        _, predicted = logits.max(1)
        correct += predicted.eq(labels).sum().item()
        total += labels.size(0)

    return total_loss / total, 100.0 * correct / total


# ═══════════════════════════════════════════════════════════
#  ONNX Export
# ═══════════════════════════════════════════════════════════

def export_onnx(backbone, output_path, embed_dim=512, opset=14):
    """Export backbone (không có ArcFace head) ra file ONNX."""
    backbone.eval()
    dummy = torch.randn(1, 3, 112, 112)

    torch.onnx.export(
        backbone,
        dummy,
        str(output_path),
        input_names=["input"],
        output_names=["embedding"],
        dynamic_axes={"input": {0: "batch"}, "embedding": {0: "batch"}},
        opset_version=opset,
        do_constant_folding=True,
    )

    # Verify
    import onnxruntime as ort
    sess = ort.InferenceSession(str(output_path), providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0].name
    out = sess.run(None, {inp: dummy.numpy()})[0]
    print(f"  ✅ ONNX exported: {output_path}")
    print(f"     Input: {dummy.shape} → Output: {out.shape}")
    print(f"     File size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Fine-tune FaceLiVT2 trên dataset_clean")
    parser.add_argument("--variant", choices=["s", "xs"], default="s",
                        help="Model variant: s (18MB) hoặc xs (12MB)")
    parser.add_argument("--dataset", type=str, default="dataset_clean",
                        help="Đường dẫn dataset (mặc định: dataset_clean)")
    parser.add_argument("--epochs", type=int, default=20,
                        help="Số epoch training")
    parser.add_argument("--batch-size", type=int, default=32,
                        help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-4,
                        help="Learning rate")
    parser.add_argument("--freeze-stages", type=int, default=2,
                        help="Số stage đầu cần freeze (0=full finetune, 2=khuyến nghị)")
    parser.add_argument("--arcface-s", type=float, default=32.0,
                        help="ArcFace scale factor")
    parser.add_argument("--arcface-m", type=float, default=0.5,
                        help="ArcFace angular margin")
    parser.add_argument("--val-ratio", type=float, default=0.15,
                        help="Tỷ lệ validation set")
    parser.add_argument("--workers", type=int, default=2,
                        help="Số DataLoader workers")
    parser.add_argument("--no-export", action="store_true",
                        help="Không export ONNX sau training")
    parser.add_argument("--weight-decay", type=float, default=5e-4,
                        help="Weight decay (L2 regularization)")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    print("=" * 70)
    print(f"  🎯 Fine-tune FaceLiVT2-{args.variant.upper()} trên dataset_clean")
    print(f"  📱 Device: {device}")
    print("=" * 70)

    # ── 1. Dataset ────────────────────────────────────────
    ds_path = Path(args.dataset)
    if not ds_path.is_absolute():
        ds_path = PROJECT_ROOT / ds_path

    print(f"\n[1/5] Chuẩn bị dataset...")
    full_dataset = FaceDataset(ds_path, transform=None, min_images=2)
    num_classes = len(full_dataset.classes)
    print(f"  👥 Số người (classes): {num_classes}")

    # Train/Val split
    n_total = len(full_dataset)
    n_val = int(n_total * args.val_ratio)
    n_train = n_total - n_val

    # Tạo 2 dataset riêng biệt với transform khác nhau
    train_dataset = FaceDataset(ds_path, transform=get_transforms(is_train=True))
    val_dataset = FaceDataset(ds_path, transform=get_transforms(is_train=False))

    # Split indices
    indices = list(range(n_total))
    random.seed(42)
    random.shuffle(indices)
    train_idx = indices[:n_train]
    val_idx = indices[n_train:]

    train_subset = torch.utils.data.Subset(train_dataset, train_idx)
    val_subset = torch.utils.data.Subset(val_dataset, val_idx)

    use_pin = torch.cuda.is_available()
    train_loader = DataLoader(train_subset, batch_size=args.batch_size,
                              shuffle=True, num_workers=args.workers,
                              pin_memory=use_pin, drop_last=True)
    val_loader = DataLoader(val_subset, batch_size=args.batch_size,
                            shuffle=False, num_workers=args.workers,
                            pin_memory=use_pin)

    print(f"  Train: {len(train_subset)} | Val: {len(val_subset)}")

    # ── 2. Load pretrained model ──────────────────────────
    print(f"\n[2/5] Load pretrained FaceLiVT2-{args.variant.upper()}...")

    if args.variant == "xs":
        backbone = facelivtv2_xs(num_classes=512, pretrained=False)
        pt_path = PROJECT_ROOT / "models" / "facelivtv2-xs.pt"
    else:
        backbone = facelivtv2_s(num_classes=512, pretrained=False)
        pt_path = PROJECT_ROOT / "models" / "facelivtv2_s.pt"

    if pt_path.exists():
        state_dict = torch.load(str(pt_path), map_location="cpu", weights_only=True)
        # Xử lý key prefix nếu cần (một số checkpoint có "module." prefix)
        if any(k.startswith("module.") for k in state_dict.keys()):
            state_dict = {k.replace("module.", ""): v for k, v in state_dict.items()}
        missing, unexpected = backbone.load_state_dict(state_dict, strict=False)
        print(f"  ✅ Loaded: {pt_path.name}")
        if missing:
            print(f"  ⚠️  Missing keys: {len(missing)} (có thể bình thường)")
        if unexpected:
            print(f"  ⚠️  Unexpected keys: {len(unexpected)}")
    else:
        print(f"  ⚠️  Không tìm thấy {pt_path.name}, train từ đầu (random init)")

    embed_dim = 512  # FaceLiVT2 output dimension

    # ── 3. Build training model ───────────────────────────
    print(f"\n[3/5] Cấu hình training model...")
    model = FaceLiVTTrainer(
        backbone=backbone,
        embed_dim=embed_dim,
        num_classes=num_classes,
        arcface_s=args.arcface_s,
        arcface_m=args.arcface_m,
    )

    # Freeze early stages
    if args.freeze_stages > 0:
        freeze_backbone_stages(model, args.freeze_stages)

    model = model.to(device)

    # Optimizer: LR khác nhau cho backbone (pretrained) vs ArcFace head (random)
    # ArcFace head cần LR cao hơn 100x vì khởi tạo random
    arcface_lr = args.lr * 100  # 1e-4 * 100 = 1e-2
    backbone_params = [p for n, p in model.named_parameters()
                       if p.requires_grad and not n.startswith("arcface")]
    arcface_params = [p for n, p in model.named_parameters()
                      if p.requires_grad and n.startswith("arcface")]

    param_groups = [
        {"params": backbone_params, "lr": args.lr},
        {"params": arcface_params,  "lr": arcface_lr},
    ]
    optimizer = torch.optim.AdamW(param_groups, weight_decay=args.weight_decay)

    scheduler = CosineAnnealingLR(optimizer, T_max=args.epochs, eta_min=args.lr * 0.01)
    criterion = nn.CrossEntropyLoss()

    print(f"  Optimizer: AdamW")
    print(f"    Backbone LR: {args.lr}  |  ArcFace LR: {arcface_lr}")
    print(f"    Backbone params: {sum(p.numel() for p in backbone_params):,}")
    print(f"    ArcFace params:  {sum(p.numel() for p in arcface_params):,}")
    print(f"  Scheduler: CosineAnnealing → {args.lr * 0.01:.1e}")
    print(f"  ArcFace: s={args.arcface_s}, m={args.arcface_m}")

    # ── 4. Training loop ──────────────────────────────────
    print(f"\n[4/5] Training {args.epochs} epochs...")
    print("-" * 70)

    best_val_acc = 0
    best_epoch = 0
    save_dir = PROJECT_ROOT / "models" / "finetuned"
    save_dir.mkdir(exist_ok=True)

    for epoch in range(args.epochs):
        # Train
        train_loss, train_acc = train_one_epoch(
            model, train_loader, optimizer, criterion, device, epoch, args.epochs
        )

        # Validate
        val_loss, val_acc = validate(model, val_loader, criterion, device)

        scheduler.step()
        lr_now = optimizer.param_groups[0]["lr"]

        print(f"  ── Epoch {epoch+1}/{args.epochs} ──"
              f"  Train: Loss={train_loss:.4f} Acc={train_acc:.1f}%"
              f"  Val: Loss={val_loss:.4f} Acc={val_acc:.1f}%"
              f"  LR={lr_now:.2e}")

        # Save best
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_epoch = epoch + 1
            best_path = save_dir / f"facelivtv2_{args.variant}_finetuned_best.pt"
            torch.save(backbone.state_dict(), str(best_path))
            print(f"  💾 Best model saved: {best_path.name} (Val Acc={val_acc:.1f}%)")

    # Save final
    final_path = save_dir / f"facelivtv2_{args.variant}_finetuned_{timestamp}.pt"
    torch.save(backbone.state_dict(), str(final_path))

    print(f"\n{'=' * 70}")
    print(f"  ✅ Training hoàn tất!")
    print(f"  Best: Epoch {best_epoch}, Val Acc = {best_val_acc:.1f}%")
    print(f"  Saved: {final_path}")
    print(f"{'=' * 70}")

    # ── 5. Export ONNX ────────────────────────────────────
    if not args.no_export:
        print(f"\n[5/5] Export ONNX...")

        # Load best weights
        backbone.load_state_dict(torch.load(str(best_path), map_location="cpu", weights_only=True))
        backbone.eval()
        backbone = backbone.cpu()

        onnx_path = save_dir / f"facelivtv2_{args.variant}_finetuned.onnx"
        export_onnx(backbone, onnx_path, embed_dim=embed_dim)

        print(f"\n  📋 Để dùng model mới, copy file ONNX vào thư mục models:")
        print(f"     copy \"{onnx_path}\" \"{PROJECT_ROOT / 'models'}\"")
        print(f"     Và cập nhật FACELIVT_MODEL trong app/config.py")


if __name__ == "__main__":
    main()
