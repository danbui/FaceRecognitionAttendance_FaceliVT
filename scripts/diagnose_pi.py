"""
Script chẩn đoán lỗi Illegal Instruction trên Raspberry Pi.
Chạy: python3 scripts/diagnose_pi.py
"""
import sys
print(f"[1] Python: {sys.version}")

# Test NumPy
print("\n[2] Test NumPy...")
try:
    import numpy as np
    a = np.random.randn(1, 512).astype(np.float32)
    b = a @ a.T
    print(f"    NumPy {np.__version__} ✅ (dot product OK)")
except Exception as e:
    print(f"    NumPy ❌ LỖI: {e}")

# Test OpenCV cơ bản
print("\n[3] Test OpenCV (cơ bản)...")
try:
    import cv2
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    print(f"    OpenCV {cv2.__version__} ✅ (basic OK)")
except Exception as e:
    print(f"    OpenCV ❌ LỖI: {e}")

# Test OpenCV DNN (YuNet)
print("\n[4] Test OpenCV DNN + YuNet...")
try:
    from pathlib import Path
    model_path = Path(__file__).resolve().parent.parent / "models" / "face_detection_yunet_2023mar.onnx"
    if not model_path.exists():
        print(f"    ⚠️ File model không tồn tại: {model_path}")
    else:
        model_buffer = np.fromfile(str(model_path), dtype=np.uint8)
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
        test_img = np.zeros((320, 320, 3), dtype=np.uint8)
        detector.setInputSize((320, 320))
        retval, dets = detector.detect(test_img)
        print(f"    YuNet qua OpenCV DNN ✅ (detect OK)")
except Exception as e:
    print(f"    YuNet ❌ LỖI: {e}")

# Test ONNX Runtime
print("\n[5] Test ONNX Runtime (import)...")
try:
    import onnxruntime as ort
    print(f"    onnxruntime {ort.__version__} ✅ (import OK)")
    print(f"    Providers: {ort.get_available_providers()}")
except Exception as e:
    print(f"    onnxruntime ❌ LỖI: {e}")

# Test ONNX Runtime + FaceLiVT
print("\n[6] Test ONNX Runtime + FaceLiVT model...")
try:
    import onnxruntime as ort
    model_path = Path(__file__).resolve().parent.parent / "models" / "facelivtv2_s.onnx"
    if not model_path.exists():
        # Thử tên khác
        model_path = Path(__file__).resolve().parent.parent / "models" / "facelivtv2-xs.onnx"
    
    if not model_path.exists():
        print(f"    ⚠️ Không tìm thấy file FaceLiVT model trong thư mục models/")
    else:
        print(f"    Đang load model: {model_path.name} ...")
        sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        inp = sess.get_inputs()[0]
        print(f"    Input: {inp.name}, shape={inp.shape}, type={inp.type}")
        
        # Thử chạy inference với ảnh giả
        dummy = np.random.randn(1, 3, 112, 112).astype(np.float32)
        out = sess.run(None, {inp.name: dummy})
        print(f"    Output shape: {out[0].shape}")
        print(f"    FaceLiVT ✅ (inference OK)")
except Exception as e:
    print(f"    FaceLiVT ❌ LỖI: {e}")

print("\n=== KẾT THÚC CHẨN ĐOÁN ===")
