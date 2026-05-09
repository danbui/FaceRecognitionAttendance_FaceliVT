"""
Face embedding – Tự động chọn model phù hợp:
  1. FaceLiVT (512-dim) via ONNX Runtime – Ưu tiên (chính xác hơn)
  2. SFace (128-dim) via OpenCV FaceRecognizerSF – Fallback khi không có ONNX Runtime

Thứ tự ưu tiên mặc định: FaceLiVT → SFace
Có thể ép backend qua biến môi trường: FACE_BACKEND=sface hoặc FACE_BACKEND=facelivt
"""
import cv2
import numpy as np
from typing import Optional

from . import config
from .config import (
    FACELIVT_MODEL, SFACE_MODEL, PREFERRED_BACKEND,
    SFACE_COSINE_THRESHOLD, FACELIVT_COSINE_THRESHOLD,
)

# Tọa độ chuẩn 5 điểm cho khung ảnh 112x112 (ArcFace standard)
ARCFACE_DST = np.array([
    [38.2946, 51.6963],
    [73.5318, 51.5014],
    [56.0252, 71.7366],
    [41.5493, 92.3655],
    [70.7299, 92.2041]
], dtype=np.float32)


def align_face_arcface(img, landmarks, image_size=112):
    """Căn chỉnh khuôn mặt theo chuẩn ArcFace (dùng cho FaceLiVT)."""
    dst = ARCFACE_DST * (float(image_size) / 112.0)
    M, _ = cv2.estimateAffinePartial2D(landmarks, dst)
    if M is None:
        M = cv2.getAffineTransform(landmarks[:3], dst[:3])
    return cv2.warpAffine(img, M, (image_size, image_size), borderValue=0.0)


class FaceEmbedder:
    """
    Face embedder tự động chọn backend:
      - FaceLiVT + ONNX Runtime → 512-dim (ưu tiên)
      - SFace + OpenCV           → 128-dim (fallback)

    Thứ tự được điều khiển bởi config.PREFERRED_BACKEND:
      - "auto"     → FaceLiVT trước, SFace fallback
      - "facelivt" → Chỉ FaceLiVT
      - "sface"    → Chỉ SFace
    """

    def __init__(self):
        self.backend = None
        self.session = None
        self.recognizer = None
        self.input_name = None
        self.embed_dim = 128  # Mặc định SFace

        pref = PREFERRED_BACKEND.lower().strip()

        if pref == "sface":
            # Ép dùng SFace
            self._try_sface(required=True)
        elif pref == "facelivt":
            # Ép dùng FaceLiVT
            self._try_facelivt(required=True)
        else:
            # Auto: thử FaceLiVT trước, SFace fallback
            if not self._try_facelivt():
                if not self._try_sface():
                    raise RuntimeError(
                        "Không thể load model nhận diện khuôn mặt nào!\n"
                        f"  FaceLiVT: {FACELIVT_MODEL} (exists={FACELIVT_MODEL.exists()})\n"
                        f"  SFace: {SFACE_MODEL} (exists={SFACE_MODEL.exists()})"
                    )

        # ── Cập nhật threshold toàn cục theo backend đang dùng ──
        if self.backend == "facelivt":
            config.RECOGNITION_COSINE_THRESHOLD = FACELIVT_COSINE_THRESHOLD
        else:
            config.RECOGNITION_COSINE_THRESHOLD = SFACE_COSINE_THRESHOLD

        print(f"[FaceEmbedder] Threshold: {config.RECOGNITION_COSINE_THRESHOLD}")

    # ── Backend loaders ───────────────────────────────────

    def _try_facelivt(self, required=False) -> bool:
        """Thử load FaceLiVT + ONNX Runtime. Trả về True nếu thành công."""
        if not FACELIVT_MODEL.exists():
            msg = f"FaceLiVT model không tồn tại: {FACELIVT_MODEL}"
            if required:
                raise FileNotFoundError(msg)
            print(f"[FaceEmbedder] {msg}")
            return False

        try:
            import onnxruntime as ort
            providers = ['CPUExecutionProvider']
            self.session = ort.InferenceSession(str(FACELIVT_MODEL), providers=providers)
            self.input_name = self.session.get_inputs()[0].name
            self.backend = "facelivt"
            self.embed_dim = 512
            print(f"[FaceEmbedder] Backend: FaceLiVT + ONNX Runtime {ort.__version__} (512-dim)")
            return True
        except Exception as e:
            msg = f"FaceLiVT không khả dụng: {e}"
            if required:
                raise RuntimeError(msg)
            print(f"[FaceEmbedder] {msg}")
            return False

    def _try_sface(self, required=False) -> bool:
        """Thử load SFace + OpenCV. Trả về True nếu thành công."""
        if not SFACE_MODEL.exists():
            msg = f"SFace model không tồn tại: {SFACE_MODEL}"
            if required:
                raise FileNotFoundError(msg)
            print(f"[FaceEmbedder] {msg}")
            return False

        # Thử buffer-based API (OpenCV >= 4.9, cần cho Windows Unicode path)
        try:
            model_buffer = np.fromfile(str(SFACE_MODEL), dtype=np.uint8)
            config_buffer = np.array([], dtype=np.uint8)
            self.recognizer = cv2.FaceRecognizerSF.create(
                framework="onnx",
                bufferModel=model_buffer,
                bufferConfig=config_buffer,
            )
            self.backend = "sface"
            self.embed_dim = 128
            print(f"[FaceEmbedder] Backend: SFace + OpenCV {cv2.__version__} (128-dim, buffer API)")
            return True
        except TypeError:
            pass
        except Exception as e:
            print(f"[FaceEmbedder] SFace buffer API lỗi: {e}")

        # Fallback: string-path API (OpenCV < 4.9, Pi)
        try:
            self.recognizer = cv2.FaceRecognizerSF.create(
                model=str(SFACE_MODEL),
                config="",
            )
            self.backend = "sface"
            self.embed_dim = 128
            print(f"[FaceEmbedder] Backend: SFace + OpenCV {cv2.__version__} (128-dim, path API)")
            return True
        except Exception as e:
            msg = f"SFace lỗi: {e}"
            if required:
                raise RuntimeError(msg)
            print(f"[FaceEmbedder] {msg}")
            return False

    # ── Public API ────────────────────────────────────────

    def get_embedding(self, frame: np.ndarray, face_detection: np.ndarray) -> np.ndarray:
        """Extract face embedding from frame + detection info."""
        if face_detection is None:
            return np.zeros((1, self.embed_dim), dtype=np.float32)

        if self.backend == "sface":
            return self._get_embedding_sface(frame, face_detection)
        else:
            return self._get_embedding_facelivt(frame, face_detection)

    # ── SFace path (OpenCV native) ────────────────────────

    def _get_embedding_sface(self, frame, face_detection):
        try:
            aligned = self.recognizer.alignCrop(frame, face_detection)
            embedding = self.recognizer.feature(aligned)
            emb = embedding.flatten()
            norm = np.linalg.norm(emb)
            if norm > 1e-8:
                emb = emb / norm
            return emb.reshape(1, -1)
        except Exception as e:
            print(f"[FaceEmbedder] WARNING: SFace embedding failed: {e}")
            return np.zeros((1, 128), dtype=np.float32)

    # ── FaceLiVT path (ONNX Runtime) ─────────────────────

    def _get_embedding_facelivt(self, frame, face_detection):
        try:
            landmarks = face_detection[4:14].reshape((5, 2))
            face_crop = align_face_arcface(frame, landmarks)
        except Exception:
            x, y, w, h = face_detection[:4].astype(int)
            face_crop = frame[max(0,y):min(frame.shape[0],y+h), max(0,x):min(frame.shape[1],x+w)]
            if face_crop.size > 0:
                face_crop = cv2.resize(face_crop, (112, 112))

        if face_crop is None or face_crop.size == 0:
            return np.zeros((1, 512), dtype=np.float32)

        return self._infer_facelivt(face_crop)

    def _infer_facelivt(self, face_crop):
        if face_crop.shape[0] != 112 or face_crop.shape[1] != 112:
            face_crop = cv2.resize(face_crop, (112, 112))

        rgb = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
        blob = (rgb.astype(np.float32) - 127.5) / 127.5
        blob = np.transpose(blob, (2, 0, 1))
        blob = np.expand_dims(blob, axis=0)

        out = self.session.run(None, {self.input_name: blob})[0]
        embedding = out.flatten()
        norm = np.linalg.norm(embedding)
        if norm > 1e-8:
            embedding = embedding / norm
        return embedding.reshape(1, -1)

    def match(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """Compute cosine similarity between two embeddings."""
        return float(np.dot(emb1.flatten(), emb2.flatten()))