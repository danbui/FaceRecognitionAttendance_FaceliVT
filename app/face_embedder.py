"""
Face embedding using ONNX Runtime with FaceLiVT model.

FaceLiVT produces a 512-dimensional face embedding vector from a 112x112 face image.
Because FaceLiVT uses advanced layers (Linear Attention) that OpenCV DNN doesn't support,
we use the official ONNX Runtime engine.

Model: facelivtv2-xs.onnx
"""
import cv2
import numpy as np
from typing import Optional
from skimage import transform as trans

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
    Sử dụng skimage.SimilarityTransform (least-squares) thay vì
    cv2.estimateAffinePartial2D (LMEDS) để khớp chính xác với
    cách align lúc training FaceLiVT.
    """
    dst = ARCFACE_DST * (float(image_size) / 112.0)
    tform = trans.SimilarityTransform()
    tform.estimate(landmarks, dst)
    M = tform.params[0:2, :]
    warped = cv2.warpAffine(img, M, (image_size, image_size), borderValue=0.0)
    return warped


class FaceEmbedder:
    """
    Face embedder using FaceLiVT via ONNX Runtime.
    """

    def __init__(self):
        model_path = str(FACELIVT_MODEL)
        if not FACELIVT_MODEL.exists():
            raise FileNotFoundError(
                f"FaceLiVT model not found at {model_path}. "
                "Please run scripts/convert_facelivt_onnx.py to convert the .pt model."
            )

        try:
            import onnxruntime as ort
        except ImportError:
            raise ImportError("Please install onnxruntime using: pip install onnxruntime")

        # onnxruntime supports Unicode paths perfectly
        providers = ['CPUExecutionProvider']
        self.session = ort.InferenceSession(model_path, providers=providers)
        self.input_name = self.session.get_inputs()[0].name

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
        
        # Run inference via ONNX Runtime
        out = self.session.run(None, {self.input_name: blob})[0]
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