"""
Business logic for enrollment and attendance recognition.

Supports three kiosk modes:
  - ENROLL:    Register a new employee face
  - CHECK_IN:  Record arrival
  - CHECK_OUT: Record departure

Optimizations for Raspberry Pi 4:
  - Sliding-window in-memory cooldown cache: duplicate check in O(1) RAM
    instead of querying SQLite on every frame.
  - EmbeddingCache: matcher loads DB embeddings once, kept in RAM.
  - DB is still the source of truth; cache is just a fast-path guard.
"""
from pathlib import Path
from datetime import datetime, timedelta
import time
import threading
import cv2
import numpy as np
from typing import Optional, Dict, Tuple

from .config import CAPTURE_DIR, DUPLICATE_COOLDOWN_MINUTES
from .database import (
    create_employee, save_embedding,
    add_attendance, get_last_attendance_today_any,
)
from .matcher import match_embedding, embedding_cache
from .face_embedder import align_face_arcface


# ═══════════════════════════════════════════════════════════
#  Trạng thái điểm danh (State Machine Cache)
# ═══════════════════════════════════════════════════════════

class AttendanceStateCache:
    """
    In-memory cache lưu trạng thái điểm danh cuối cùng trong ngày của mỗi nhân viên.
    Giúp kiểm tra logic: IN -> OUT -> IN -> OUT mà không cần query SQLite liên tục.
    """

    def __init__(self):
        # Format: {employee_id: {"check_type": "CHECK_IN", "last_time": datetime}}
        self._cache: Dict[int, dict] = {}
        # Cooldown lấy từ tham số config (thường là 1 phút)
        self._cooldown = timedelta(minutes=DUPLICATE_COOLDOWN_MINUTES)

    def get_last_state(self, employee_id: int) -> Optional[dict]:
        """Lấy trạng thái cuối cùng. Nếu RAM trống thì load từ DB lên."""
        if employee_id in self._cache:
            return self._cache[employee_id]

        last_log = get_last_attendance_today_any(employee_id)
        if last_log:
            dt = datetime.strptime(last_log["check_time"], "%Y-%m-%d %H:%M:%S")
            state = {"check_type": last_log["check_type"], "last_time": dt}
            self._cache[employee_id] = state
            return state

        return None

    def record_state(self, employee_id: int, check_type: str):
        """Cập nhật trạng thái sau khi điểm danh thành công."""
        self._cache[employee_id] = {"check_type": check_type, "last_time": datetime.now()}

    def check_logic(self, employee_id: int, current_type: str) -> Optional[str]:
        """
        Kiểm tra xem hành động 'current_type' có hợp lệ không.
        Trả về chuỗi lỗi nếu vi phạm logic, trả về None nếu hợp lệ.
        """
        last_state = self.get_last_state(employee_id)
        
        # Chưa có bản ghi nào trong ngày
        if not last_state:
            if current_type == "CHECK_OUT":
                return "Bạn chưa Check In, không thể Check Out!"
            return None # CHECK_IN hợp lệ

        last_type = last_state["check_type"]
        last_time = last_state["last_time"]
        
        # Nếu người dùng làm đúng logic: IN -> OUT -> IN -> OUT thì cho phép ngay lập tức
        if current_type != last_type:
            return None

        # Nếu người dùng vi phạm logic (IN -> IN hoặc OUT -> OUT)
        elapsed = datetime.now() - last_time
        time_str = last_time.strftime("%H:%M:%S")

        # 1. Trùng lặp tức thì (do camera quét liên tục)
        if elapsed < self._cooldown:
            mins = max(1, int(self._cooldown.total_seconds() / 60))
            return f"Vui lòng đợi {mins} phút giữa các lần {current_type} trùng lặp!"

        # 2. Trùng lặp sau một khoảng thời gian (quên Check Out)
        if current_type == "CHECK_IN":
            return f"Bạn đã Check In lúc {time_str}. Bạn cần Check Out trước!"
        else:
            return f"Bạn đã Check Out lúc {time_str}. Bạn cần Check In lại!"


# Module-level singleton
_state_cache = AttendanceStateCache()


# ═══════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════

def save_face_image(face_crop: np.ndarray, prefix: str) -> str:
    """Save cropped face image and return the file path."""
    filename = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    path = CAPTURE_DIR / filename
    
    # Khắc phục lỗi OpenCV không lưu được ảnh nếu đường dẫn có chứa tiếng Việt (Unicode) trên Windows
    is_success, buffer = cv2.imencode(".jpg", face_crop)
    if is_success:
        with open(path, "wb") as f:
            f.write(buffer.tobytes())
            
    return str(path)


# ═══════════════════════════════════════════════════════════
#  Enrollment
# ═══════════════════════════════════════════════════════════

def enroll_employee(
    employee_code: str,
    full_name: str,
    department: str,
    frame: np.ndarray,
    face_detection: np.ndarray,
    embedder,
    force_new: bool = False,
) -> dict:
    """
    Enroll a new employee: save their face embedding + photo to database.

    If a similar face already exists in the DB (and force_new is False),
    returns status 'confirm_duplicate' so the UI can ask the user whether
    to update the existing employee or create a new one.

    Args:
        employee_code: Unique employee code (e.g., 'E001')
        full_name: Employee full name
        department: Department name
        frame: Original full frame (BGR)
        face_detection: Raw YuNet detection row (bbox + landmarks)
        embedder: FaceEmbedder instance
        force_new: If True, skip duplicate check and create new employee
    """
    # Extract embedding FIRST (before creating employee)
    embedding = embedder.get_embedding(frame, face_detection)

    # Crop face for saving image (Dùng ảnh đã được căn chỉnh 112x112 chuẩn InsightFace)
    try:
        landmarks = face_detection[4:14].reshape((5, 2))
        face_crop = align_face_arcface(frame, landmarks)
    except Exception:
        x, y, w, h = int(face_detection[0]), int(face_detection[1]), int(face_detection[2]), int(face_detection[3])
        face_crop = frame[max(0, y):min(frame.shape[0], y+h), max(0, x):min(frame.shape[1], x+w)].copy()
        
    image_path = save_face_image(face_crop, f"enroll_{employee_code}")

    # ── Check for similar existing face ──
    if not force_new:
        match = match_embedding(embedding)
        if match is not None:
            return {
                "status": "confirm_duplicate",
                "existing_employee_id": match["employee_id"],
                "existing_employee_code": match["employee_code"],
                "existing_full_name": match["full_name"],
                "confidence": match["confidence"],
                # Carry forward for later use by confirm actions
                "embedding": embedding,
                "image_path": image_path,
                "new_employee_code": employee_code,
                "new_full_name": full_name,
                "new_department": department,
            }

    # ── No match (or forced) → create new employee ──
    employee_id = create_employee(employee_code, full_name, department)
    save_embedding(employee_id, embedding, image_path)

    # ── Invalidate embedding cache so new enrollment is picked up ──
    embedding_cache.invalidate()

    return {
        "status": "enrolled",
        "employee_id": employee_id,
        "employee_code": employee_code,
        "full_name": full_name,
        "image_path": image_path,
    }


def confirm_enroll_update(employee_id: int, embedding: np.ndarray, image_path: str) -> dict:
    """Add a new embedding to an existing employee (user confirmed Y)."""
    save_embedding(employee_id, embedding, image_path)
    embedding_cache.invalidate()


def enroll_new_with_embedding(
    employee_code: str, full_name: str, department: str,
    embedding: np.ndarray, image_path: str,
) -> dict:
    """Create a new employee with a pre-computed embedding (user confirmed N)."""
    employee_id = create_employee(employee_code, full_name, department)
    save_embedding(employee_id, embedding, image_path)
    embedding_cache.invalidate()
    return {
        "status": "enrolled",
        "employee_id": employee_id,
        "employee_code": employee_code,
        "full_name": full_name,
        "image_path": image_path,
    }


# ═══════════════════════════════════════════════════════════
#  Recognition + Attendance
# ═══════════════════════════════════════════════════════════

def recognize_and_attend(
    frame: np.ndarray,
    face_detection: np.ndarray,
    embedder,
    check_type: str = "CHECK_IN",
    threshold: Optional[float] = None,
) -> dict:
    """
    Recognize a face and record attendance (CHECK_IN or CHECK_OUT).

    Pipeline (optimized for Pi 4):
      1. Embed face → 128-dim vector           (~40ms on Pi 4)
      2. Vectorized match against RAM cache     (~0.3ms)
      3. Sliding-window duplicate check in RAM  (~0us)
      4. Write DB only if not duplicate          (~5ms)

    Returns dict with status:
      - 'success':    matched and recorded
      - 'duplicate':  already recorded within DUPLICATE_COOLDOWN_MINUTES
      - 'not_found':  no matching face in database
    """
    embedding = embedder.get_embedding(frame, face_detection)

    kwargs = {}
    if threshold is not None:
        kwargs["threshold"] = threshold

    match = match_embedding(embedding, **kwargs)

    if match is None:
        return {
            "status": "not_found",
            "message": "Không tìm thấy nhân viên trong cơ sở dữ liệu",
        }

    # ── Logic kiểm tra IN -> OUT -> IN -> OUT ──
    error_msg = _state_cache.check_logic(match["employee_id"], check_type)
    if error_msg:
        return {
            "status": "duplicate", # Giữ nguyên status 'duplicate' để UI hiển thị popup cảnh báo
            "employee_id": match["employee_id"],
            "employee_code": match["employee_code"],
            "full_name": match["full_name"],
            "check_type": check_type,
            "message": error_msg,
        }

    # ── Record attendance (DB write in background daemon thread) ──
    try:
        landmarks = face_detection[4:14].reshape((5, 2))
        face_crop = align_face_arcface(frame, landmarks)
    except Exception:
        x, y, w, h = int(face_detection[0]), int(face_detection[1]), int(face_detection[2]), int(face_detection[3])
        face_crop = frame[max(0, y):min(frame.shape[0], y+h), max(0, x):min(frame.shape[1], x+w)].copy()
        
    filename = f"attend_{match['employee_code']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    image_path = str(CAPTURE_DIR / filename)

    # Chạy ngầm việc nén/lưu ảnh vật lý và ghi log SQLite
    def save_and_log_async(crop, img_path, emp_id, conf, c_type):
        try:
            CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
            is_success, buffer = cv2.imencode(".jpg", crop)
            if is_success:
                with open(img_path, "wb") as f:
                    f.write(buffer.tobytes())
        except Exception as e:
            print(f"[Attendance Async] Cảnh báo: Không thể lưu ảnh điểm danh: {e}")
            
        try:
            add_attendance(emp_id, conf, c_type, img_path)
        except Exception as e:
            print(f"[Attendance Async] Lỗi: Không thể thêm log điểm danh vào SQLite: {e}")

    threading.Thread(
        target=save_and_log_async,
        args=(face_crop, image_path, match["employee_id"], match["confidence"], check_type),
        daemon=True
    ).start()

    # ── Update RAM cache ──
    _state_cache.record_state(match["employee_id"], check_type)

    return {
        "status": "success",
        "employee_id": match["employee_id"],
        "employee_code": match["employee_code"],
        "full_name": match["full_name"],
        "confidence": match["confidence"],
        "check_type": check_type,
        "image_path": image_path,
    }