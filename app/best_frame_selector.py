import cv2
import numpy as np

class BestFrameSelector:
    """
    Online Best Frame Selection for Face Recognition

    Mục tiêu:
    - KHÔNG lưu toàn bộ frames
    - chỉ giữ frame tốt nhất hiện tại
    - tối ưu cho Raspberry Pi / Edge AI
    """

    def __init__(
        self,
        sharpness_weight=0.4,
        frontal_weight=0.3,
        face_size_weight=0.2,
        brightness_weight=0.1,
    ):
        self.best_frame = None
        self.best_face = None
        self.best_face_raw = None
        self.best_score = -1

        self.sw = sharpness_weight
        self.fw = frontal_weight
        self.fs = face_size_weight
        self.bw = brightness_weight

    # =========================================================
    # PUBLIC
    # =========================================================

    def update(self, frame, face_bbox, landmarks, face_raw):
        """
        Update best frame nếu frame hiện tại tốt hơn.
        """
        x, y, w, h = face_bbox
        face_crop = frame[y:y+h, x:x+w]

        if face_crop.size == 0:
            return

        score = self.compute_quality_score(
            frame=frame,
            face_crop=face_crop,
            bbox=face_bbox,
            landmarks=landmarks
        )

        if score > self.best_score:
            self.best_score = score
            self.best_frame = frame.copy()
            self.best_face = face_crop.copy()
            self.best_face_raw = face_raw.copy()

    def get_best(self):
        """
        Returns
        -------
        best_frame
        best_face_raw
        best_score
        """
        return self.best_frame, self.best_face_raw, self.best_score

    def reset(self):
        self.best_frame = None
        self.best_face = None
        self.best_face_raw = None
        self.best_score = -1

    # =========================================================
    # QUALITY SCORE
    # =========================================================

    def compute_quality_score(self, frame, face_crop, bbox, landmarks=None):
        sharpness = self.compute_sharpness(face_crop)
        brightness = self.compute_brightness(face_crop)
        face_size = self.compute_face_size(frame, bbox)
        frontalness = 0.5

        if landmarks is not None:
            frontalness = self.compute_frontalness(landmarks)

        score = (
            sharpness * self.sw +
            frontalness * self.fw +
            face_size * self.fs +
            brightness * self.bw
        )
        return score

    # =========================================================
    # METRICS
    # =========================================================

    def compute_sharpness(self, img):
        """
        Variance of Laplacian
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        score = cv2.Laplacian(gray, cv2.CV_64F).var()
        # normalize
        score = min(score / 1000.0, 1.0)
        return score

    def compute_brightness(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        mean = np.mean(gray)
        # ideal brightness ~120-180
        score = 1.0 - abs(mean - 150) / 150.0
        score = max(0.0, min(score, 1.0))
        return score

    def compute_face_size(self, frame, bbox):
        x, y, w, h = bbox
        frame_area = frame.shape[0] * frame.shape[1]
        face_area = w * h
        ratio = face_area / frame_area
        # normalize
        score = min(ratio * 20.0, 1.0)
        return score

    def compute_frontalness(self, landmarks):
        """
        landmarks:
        [left_eye_x, left_eye_y,
         right_eye_x, right_eye_y,
         nose_x, nose_y,
         mouth_left_x, mouth_left_y,
         mouth_right_x, mouth_right_y]
        """
        le_x, le_y = landmarks[0], landmarks[1]
        re_x, re_y = landmarks[2], landmarks[3]

        eye_diff = abs(le_y - re_y)
        # mắt càng ngang → càng frontal
        score = 1.0 - min(eye_diff / 20.0, 1.0)
        return score
