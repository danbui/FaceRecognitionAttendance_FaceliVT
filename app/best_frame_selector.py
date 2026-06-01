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
        if face_crop.size == 0:
            return 0.0
        face_gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        sharpness = self.compute_sharpness(face_gray)
        brightness = self.compute_brightness(face_gray)
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
        if len(img.shape) == 3 and img.shape[2] == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
        score = cv2.Laplacian(gray, cv2.CV_64F).var()
        # normalize
        score = min(score / 1000.0, 1.0)
        return score

    def compute_brightness(self, img):
        if len(img.shape) == 3 and img.shape[2] == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
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
        Ước lượng góc xoay 3 chiều (Roll, Yaw, Pitch) từ 5 điểm mốc landmarks.
        Landmarks format từ YuNet: [re_x, re_y, le_x, le_y, nt_x, nt_y, rcm_x, rcm_y, lcm_x, lcm_y]
        """
        re_x, re_y = landmarks[0], landmarks[1]
        le_x, le_y = landmarks[2], landmarks[3]
        nt_x, nt_y = landmarks[4], landmarks[5]
        rcm_x, rcm_y = landmarks[6], landmarks[7]
        lcm_x, lcm_y = landmarks[8], landmarks[9]

        # 1. Roll Score (Đầu nghiêng trái/phải)
        eye_diff_y = abs(re_y - le_y)
        roll_score = 1.0 - min(eye_diff_y / 15.0, 1.0)

        # 2. Yaw Score (Quay mặt sang trái/phải)
        d_left = abs(nt_x - le_x)
        d_right = abs(re_x - nt_x)
        max_d_h = max(d_left, d_right)
        yaw_score = min(d_left, d_right) / max_d_h if max_d_h > 0 else 0.0

        # 3. Pitch Score (Cúi/Ngước đầu)
        eyes_mid_y = (re_y + le_y) / 2.0
        mouth_mid_y = (rcm_y + lcm_y) / 2.0
        d_upper = abs(nt_y - eyes_mid_y)
        d_lower = abs(mouth_mid_y - nt_y)
        max_d_v = max(d_upper, d_lower)
        pitch_score = min(d_upper, d_lower) / max_d_v if max_d_v > 0 else 0.0

        # Trọng số kết hợp tối ưu hình học
        frontalness = roll_score * 0.4 + yaw_score * 0.4 + pitch_score * 0.2
        return frontalness

