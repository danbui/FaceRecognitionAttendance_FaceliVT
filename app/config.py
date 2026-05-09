"""
Centralized configuration for the Edge Attendance system.
"""
from pathlib import Path

# ── Paths ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"
CAPTURE_DIR = BASE_DIR / "captures"
DB_PATH = BASE_DIR / "attendance.db"

CAPTURE_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)

# ── Model files ────────────────────────────────────────
YUNET_MODEL = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
SFACE_MODEL = MODELS_DIR / "face_recognition_sface_2021dec.onnx"
FACELIVT_MODEL = MODELS_DIR / "facelivtv2_s.onnx"

# ── Face Detection (YuNet) ─────────────────────────────
DETECTION_INPUT_SIZE = (320, 320)
DETECTION_SCORE_THRESHOLD = 0.9
DETECTION_NMS_THRESHOLD = 0.8
DETECTION_TOP_K = 5000

# ── Face Recognition (FaceLiVT) ────────────────────────
# FaceLiVT cosine similarity threshold
# Threshold requires tuning, 0.45 is a safe starting point for highly discriminative models
RECOGNITION_COSINE_THRESHOLD = 0.90

# ── Kiosk ──────────────────────────────────────────────
# Time (seconds) face must be stable inside guide box before action
STABLE_FACE_SECONDS = 1.5
# Cooldown (minutes) between two scans of the SAME action (e.g. IN -> IN)
DUPLICATE_COOLDOWN_MINUTES = 1
# Interval (seconds) to purge expired entries from in-memory cooldown cache
CACHE_CLEANUP_INTERVAL = 60
# Camera resolution
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480

# ── Web / Auth ─────────────────────────────────────────
SECRET_KEY = "edge-attendance-secret-change-in-production"
SESSION_MAX_AGE = 3600 * 8  # 8 hours
