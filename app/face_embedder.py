"""
Face embedding using FaceLiVT model.

Hỗ trợ 2 backend:
  1. ONNX Runtime (ưu tiên, nhanh hơn trên PC)
  2. OpenCV DNN (fallback, chạy được trên MỌI thiết bị ARM/Pi mà không cần onnxruntime)

Model: facelivtv2_s.onnx hoặc facelivtv2-xs.onnx
"""
import cv2
import numpy as np
from typing import Optional

from .config import FACELIVT_MODEL

# Tọa độ chuẩn 5 điểm của mắt, mũi, miệng cho khung ảnh 112x112 (ArcFace/FaceLiVT standard)
ARCFACE_DST = np.array([
    [38.2946, 51.6963],  # Mắt phải (trên ảnh là bên trái)
    [73.5318, 51.5014],  # Mắt trái (trên ảnh là bên phải)
    [56.0252, 71.7366],  # Mũi
    [41.5493, 92.3655],  # Khóe miệng phải
    [70.7299, 92.2041]   # Khóe miệng trái
], dtype=np.float32)


def align_face_arcface(img, landmarks, image_size=112):
    """
    Căn chỉnh khuôn mặt theo chuẩn InsightFace/ArcFace.
    Dùng cv2.estimateAffinePartial2D (thuần OpenCV, không cần scikit-image).
    """
    dst = ARCFACE_DST * (float(image_size) / 112.0)
    M, _ = cv2.estimateAffinePartial2D(landmarks, dst)
    if M is None:
        # Fallback nếu không tính được ma trận
        M = cv2.getAffineTransform(landmarks[:3], dst[:3])
    warped = cv2.warpAffine(img, M, (image_size, image_size), borderValue=0.0)
    return warped


class FaceEmbedder:
    """
    Face embedder using FaceLiVT.
    Tự động chọn backend: ONNX Runtime (nếu có) hoặc OpenCV DNN (fallback cho Pi).
    """

    def __init__(self):
        model_path = str(FACELIVT_MODEL)
        if not FACELIVT_MODEL.exists():
            raise FileNotFoundError(
                f"FaceLiVT model not found at {model_path}. "
                "Please copy the .onnx model file to the models/ directory."
            )

        self.backend = None
        self.session = None
        self.net = None
        self.input_name = None

        # Thử dùng ONNX Runtime trước (nhanh hơn trên PC)
        try:
            import onnxruntime as ort
            providers = ['CPUExecutionProvider']
            self.session = ort.InferenceSession(model_path, providers=providers)
            self.input_name = self.session.get_inputs()[0].name
            self.backend = "onnxruntime"
            print(f"[FaceEmbedder] Backend: ONNX Runtime {ort.__version__}")
        except Exception as e:
            print(f"[FaceEmbedder] ONNX Runtime không khả dụng ({e})")
            print(f"[FaceEmbedder] Chuyển sang dùng OpenCV DNN...")

            # Fallback: dùng OpenCV DNN (chạy được trên mọi ARM/Pi)
            try:
                # Đọc file model vào bộ nhớ để tránh lỗi Unicode path trên Windows
                model_buffer = np.fromfile(model_path, dtype=np.uint8)
                self.net = cv2.dnn.readNetFromONNX(model_buffer)
                self.backend = "opencv_dnn"
                print(f"[FaceEmbedder] Backend: OpenCV DNN {cv2.__version__}")
            except Exception as e2:
                raise RuntimeError(
                    f"Không thể load model FaceLiVT bằng cả ONNX Runtime lẫn OpenCV DNN.\n"
                    f"  ONNX Runtime error: {e}\n"
                    f"  OpenCV DNN error: {e2}"
                )

    def get_embedding(self, frame: np.ndarray, face_detection: np.ndarray) -> np.ndarray:
        """
        Extract a 512-dim face embedding from the frame using face detection info.
        """
        if face_detection is None:
             return np.zeros((1, 512), dtype=np.float32)
             
        try:
            # Lấy 5 điểm landmarks từ YuNet (từ index 4 đến 13)
            landmarks = face_detection[4:14].reshape((5, 2))
            
            # Căn chỉnh khuôn mặt theo chuẩn InsightFace (SimilarityTransform)
            face_crop = align_face_arcface(frame, landmarks)
        except Exception:
            # Fallback: Cắt Bounding Box thông thường nếu landmarks lỗi
            x, y, w, h = face_detection[:4].astype(int)
            face_crop = frame[max(0, y):min(frame.shape[0], y+h), max(0, x):min(frame.shape[1], x+w)]
            if face_crop.size > 0:
                face_crop = cv2.resize(face_crop, (112, 112))
                
        if face_crop is None or face_crop.size == 0:
            return np.zeros((1, 512), dtype=np.float32)

        return self.get_embedding_from_crop(face_crop)

    def get_embedding_from_crop(self, face_crop: np.ndarray) -> np.ndarray:
        """
        Extract embedding from a cropped face image.
        """
        # Ensure it is exactly 112x112
        if face_crop.shape[0] != 112 or face_crop.shape[1] != 112:
            face_crop = cv2.resize(face_crop, (112, 112))
        
        # OpenCV reads in BGR. We swap to RGB.
        rgb = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
        
        # Preprocessing: standard scaling (pixel - 127.5) / 127.5 -> [-1, 1]
        blob = (rgb.astype(np.float32) - 127.5) / 127.5
        
        # HWC to CHW format (required by PyTorch/ONNX models)
        blob = np.transpose(blob, (2, 0, 1))
        
        # Add batch dimension (1, C, H, W)
        blob = np.expand_dims(blob, axis=0)
        
        # ── Chạy inference tùy theo backend ──
        if self.backend == "onnxruntime":
            out = self.session.run(None, {self.input_name: blob})[0]
        else:
            # OpenCV DNN
            self.net.setInput(blob)
            out = self.net.forward()
        
        embedding = out.flatten()
        
        # L2-normalize so that Cosine Similarity = Dot Product
        norm = np.linalg.norm(embedding)
        if norm > 1e-8:
            embedding = embedding / norm
            
        return embedding.reshape(1, -1)

    def match(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """
        Compute cosine similarity between two embeddings.
        """
        return float(np.dot(emb1.flatten(), emb2.flatten()))