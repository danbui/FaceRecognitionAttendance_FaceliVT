"""
Camera service with auto-detection for Pi Camera or USB webcam.

Priority:
  1. If picamera2 is available (Raspberry Pi) → use Pi Camera
  2. Otherwise → use OpenCV VideoCapture (USB / laptop camera)
  3. If --demo flag → generate blank frames (no camera needed)
"""
import cv2
import numpy as np
from typing import Iterator

from .config import CAMERA_WIDTH, CAMERA_HEIGHT

# Try importing picamera2 (only available on Raspberry Pi)
try:
    from picamera2 import Picamera2
    HAS_PICAMERA = True
except ImportError:
    HAS_PICAMERA = False


class CameraService:
    def __init__(self, camera_index: int = 0, source: str = "auto", demo: bool = False):
        self.camera_index = camera_index
        self.source = source
        self.demo = demo
        self.cap = None
        self.picam = None
        self.using_picamera = False

    def start(self):
        if self.demo:
            return self

        # 1. Thử dùng Pi Camera nếu source là auto hoặc picam
        if self.source in ("auto", "picam") and HAS_PICAMERA:
            try:
                self.picam = Picamera2()
                config = self.picam.create_preview_configuration(
                    main={"size": (CAMERA_WIDTH, CAMERA_HEIGHT), "format": "RGB888"}
                )
                self.picam.configure(config)
                self.picam.start()
                self.using_picamera = True
                print("[Camera] Đang sử dụng Pi Camera (picamera2)")
                return self
            except Exception as e:
                print(f"[Camera] Lỗi khởi động Pi Camera: {e}")
                self.picam = None
                if self.source == "picam":
                    raise RuntimeError("Bắt buộc dùng Pi Camera nhưng khởi động thất bại!")

        # 2. Chuyển sang USB Camera (hoặc ép dùng USB nếu source == "usb")
        if self.source == "picam":
            raise RuntimeError("Hệ thống không tìm thấy thư viện picamera2 cho Pi Camera!")

        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            raise RuntimeError(
                f"Không thể mở USB camera ở cổng (index = {self.camera_index}). Hãy kiểm tra lại cắm cáp."
            )
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        print(f"[Camera] Đang sử dụng USB Camera (index = {self.camera_index})")
        return self

    def frames(self) -> Iterator[np.ndarray]:
        if self.demo:
            while True:
                frame = np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)
                cv2.putText(
                    frame, "DEMO MODE - No Camera", (110, 220),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2,
                )
                cv2.putText(
                    frame, "Press Q to quit", (220, 270),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2,
                )
                yield frame

        elif self.using_picamera:
            while True:
                frame = self.picam.capture_array()
                # picamera2 with RGB888 returns RGB, convert to BGR for OpenCV
                yield cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        else:
            while True:
                ok, frame = self.cap.read()
                if not ok:
                    break
                yield cv2.flip(frame, 1)  # Mirror for natural interaction

    def release(self):
        if self.cap:
            self.cap.release()
        if self.picam:
            try:
                self.picam.stop()
            except Exception:
                pass