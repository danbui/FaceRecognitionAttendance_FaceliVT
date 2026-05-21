"""
Face detection using OpenCV YuNet (FaceDetectorYN).

YuNet is a lightweight, accurate face detection model included in OpenCV's DNN module.
It provides bounding boxes AND 5 facial landmarks (eyes, nose, mouth corners)
which are essential for face alignment before recognition.

Model: face_detection_yunet_2023mar.onnx (~240 KB)
Source: https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
"""
import cv2
import numpy as np
from typing import Optional, Tuple, Any

from .config import (
    YUNET_MODEL,
    DETECTION_INPUT_SIZE,
    DETECTION_SCORE_THRESHOLD,
    DETECTION_NMS_THRESHOLD,
    DETECTION_TOP_K,
)

Box = Tuple[int, int, int, int]


class FaceDetector:
    """
    Face detector using OpenCV YuNet.

    Returns bounding box + 5 landmarks for the largest detected face.
    Landmarks are used by FaceEmbedder (SFace) for alignment before embedding.
    """

    def __init__(self):
        model_path = str(YUNET_MODEL)
        if not YUNET_MODEL.exists():
            raise FileNotFoundError(
                f"YuNet model not found at {model_path}. "
                "Run: python download_models.py"
            )

        # Thử buffer-based API trước (OpenCV >= 4.9, cần cho Windows Unicode path).
        # Nếu lỗi (OpenCV cũ trên Pi), fallback sang string-path API.
        try:
            model_buffer = np.fromfile(model_path, dtype=np.uint8)
            config_buffer = np.array([], dtype=np.uint8)
            self.detector = cv2.FaceDetectorYN.create(
                framework="onnx",
                bufferModel=model_buffer,
                bufferConfig=config_buffer,
                input_size=DETECTION_INPUT_SIZE,
                score_threshold=DETECTION_SCORE_THRESHOLD,
                nms_threshold=DETECTION_NMS_THRESHOLD,
                top_k=DETECTION_TOP_K,
            )
        except TypeError:
            # OpenCV < 4.9: dùng string path thay vì buffer
            self.detector = cv2.FaceDetectorYN.create(
                model=model_path,
                config="",
                input_size=DETECTION_INPUT_SIZE,
                score_threshold=DETECTION_SCORE_THRESHOLD,
                nms_threshold=DETECTION_NMS_THRESHOLD,
                top_k=DETECTION_TOP_K,
            )

    def detect_all(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        Detect all faces in frame.

        Returns:
            numpy array of detections, each row contains:
            [x, y, w, h, x_re, y_re, x_le, y_le, x_nt, y_nt, x_rcm, y_rcm, x_lcm, y_lcm, score]
            where: re=right_eye, le=left_eye, nt=nose_tip, rcm=right_corner_mouth, lcm=left_corner_mouth.
            Returns None if no faces detected.
        """
        orig_h, orig_w = frame.shape[:2]
        target_w = 320

        if orig_w > target_w:
            scale_x = orig_w / float(target_w)
            target_h = int(round(orig_h / scale_x))
            scale_y = orig_h / float(target_h)
            small_frame = cv2.resize(frame, (target_w, target_h))
        else:
            small_frame = frame
            scale_x = 1.0
            scale_y = 1.0
            target_w = orig_w
            target_h = orig_h

        self.detector.setInputSize((target_w, target_h))
        retval, detections = self.detector.detect(small_frame)

        if detections is None or len(detections) == 0:
            return None

        # Scale detections back to original size
        if scale_x != 1.0 or scale_y != 1.0:
            detections = detections.copy()
            # X-coordinates: x, w, x_re, x_le, x_nt, x_rcm, x_lcm (indices 0, 2, 4, 6, 8, 10, 12)
            detections[:, [0, 2, 4, 6, 8, 10, 12]] *= scale_x
            # Y-coordinates: y, h, y_re, y_le, y_nt, y_rcm, y_lcm (indices 1, 3, 5, 7, 9, 11, 13)
            detections[:, [1, 3, 5, 7, 9, 11, 13]] *= scale_y

        return detections

    def detect_largest(self, frame: np.ndarray) -> Optional[Box]:
        """
        Detect the largest face (by area) and return its bounding box.
        Backward-compatible with the old Haar Cascade interface.
        """
        detections = self.detect_all(frame)
        if detections is None:
            return None

        # Find largest face by w*h
        areas = detections[:, 2] * detections[:, 3]
        idx = np.argmax(areas)
        det = detections[idx]
        x, y, w, h = int(det[0]), int(det[1]), int(det[2]), int(det[3])
        return x, y, w, h

    def detect_largest_with_raw(self, frame: np.ndarray) -> Tuple[Optional[Box], Optional[np.ndarray]]:
        """
        Detect the largest face and return both the bounding box
        and the raw detection row (needed for SFace alignment).

        Returns:
            (box, raw_detection) or (None, None) if no face detected.
            raw_detection is a 1D numpy array with bbox + landmarks + score.
        """
        detections = self.detect_all(frame)
        if detections is None:
            return None, None

        areas = detections[:, 2] * detections[:, 3]
        idx = np.argmax(areas)
        det = detections[idx]

        x, y, w, h = int(det[0]), int(det[1]), int(det[2]), int(det[3])
        return (x, y, w, h), det


def is_face_inside_guide(face: Box, guide: Box, min_ratio: float = 0.40) -> bool:
    """Check if the detected face is properly positioned inside the guide box."""
    x, y, w, h = face
    gx, gy, gw, gh = guide
    
    # Cho phép sai số biên (lệch ra ngoài tối đa 15% kích thước khung hướng dẫn)
    margin_w = int(gw * 0.15)
    margin_h = int(gh * 0.15)
    
    inside = (x > gx - margin_w and 
              y > gy - margin_h and 
              x + w < gx + gw + margin_w and 
              y + h < gy + gh + margin_h)
              
    size_ok = w > gw * min_ratio and h > gh * min_ratio
    return inside and size_ok