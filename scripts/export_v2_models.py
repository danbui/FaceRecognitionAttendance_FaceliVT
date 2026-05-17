import os
import sys
import torch
import onnx
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import các hàm khởi tạo model từ facelivtv2
from models.facelivtv2 import facelivtv2_m, facelivtv2_l, facelivtv2_s

def export_to_onnx(model_fn, pt_path, out_onnx_path):
    print(f"\n🚀 Đang xử lý: {pt_path.name}")
    if not pt_path.exists():
        print(f"  ❌ Không tìm thấy file: {pt_path}")
        return

    # 1. Khởi tạo model architecture
    model = model_fn(num_classes=512)
    
    # 2. Load pre-trained weights
    print("  Load weights...")
    state_dict = torch.load(str(pt_path), map_location="cpu")
    # Tương thích với các file .pt lưu cả model hay chỉ lưu state_dict
    if "state_dict" in state_dict:
        state_dict = state_dict["state_dict"]
        
    model.load_state_dict(state_dict, strict=False)
    model.eval()

    # 3. Export ONNX (tạo file tạm raw)
    print("  Export ONNX...")
    raw_onnx = str(out_onnx_path).replace(".onnx", "_raw.onnx")
    dummy_input = torch.randn(1, 3, 112, 112)
    
    torch.onnx.export(
        model, dummy_input, raw_onnx,
        input_names=["input"],
        output_names=["embedding"],
        dynamic_axes={"input": {0: "batch"}, "embedding": {0: "batch"}},
        opset_version=14,
        do_constant_folding=True
    )

    # 4. Gom file (Nếu model lớn >2GB sẽ sinh ra file .data bên ngoài)
    print("  Gom file & dọn dẹp...")
    onnx_model = onnx.load(raw_onnx)
    onnx.save(onnx_model, str(out_onnx_path))
    
    os.remove(raw_onnx)
    if os.path.exists(raw_onnx + ".data"):
        os.remove(raw_onnx + ".data")
        
    print(f"  ✅ Đã xuất thành công: {out_onnx_path.name}")


if __name__ == "__main__":
    MODELS_DIR = PROJECT_ROOT / "models"
    
    # Định nghĩa cấu hình các model cần convert
    configs = [
        {"fn": facelivtv2_m, "pt": "facelivtv2-m.pt", "onnx": "facelivtv2_m.onnx"},
        {"fn": facelivtv2_l, "pt": "facelivtv2-l.pt", "onnx": "facelivtv2_l.onnx"},
    ]

    for cfg in configs:
        pt_file = MODELS_DIR / cfg["pt"]
        onnx_file = MODELS_DIR / cfg["onnx"]
        export_to_onnx(cfg["fn"], pt_file, onnx_file)
        
    print("\n🎉 Hoàn tất! Bạn có thể chạy lại script sweep_both_models.py")
