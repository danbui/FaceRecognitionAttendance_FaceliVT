"""
Kiosk main loop for the Edge Attendance system.

Architecture (optimized for Raspberry Pi 4, 4GB RAM):
  - Camera Thread:  grabs frames continuously, stores latest in shared var.
  - Main Thread:    renders GUI, runs lightweight YuNet face detection.
  - AI Worker Thread: runs heavy SFace embedding + matching + DB write.

The kiosk has two screens:
  1. MODE SELECTION: User chooses one of three modes:
     - [1] Ghi danh (Enroll)
     - [2] Diem danh vao (Check-in)
     - [3] Diem danh ra (Check-out)

  2. CAMERA SCAN: Camera runs face detection + recognition/enrollment.
     Press ESC to return to mode selection screen.
     Press Q to quit entirely.

For enrollment mode, employee info is passed via CLI arguments.
"""
import argparse
import time
import threading
import queue
import cv2
import numpy as np

from .camera_service import CameraService
from .face_detector import FaceDetector, is_face_inside_guide
from .face_embedder import FaceEmbedder
from .attendance_service import (
    enroll_employee, recognize_and_attend,
    confirm_enroll_update, enroll_new_with_embedding,
)
from .database import init_db
from .config import STABLE_FACE_SECONDS


# ── Colors ──────────────────────────────────────────────
COLOR_YELLOW = (0, 255, 255)
COLOR_GREEN = (0, 255, 0)
COLOR_RED = (0, 0, 255)
COLOR_WHITE = (255, 255, 255)
COLOR_GRAY = (180, 180, 180)
COLOR_DARK_BG = (30, 30, 30)
COLOR_BLUE = (255, 160, 50)
COLOR_ORANGE = (0, 140, 255)

WINDOW_NAME = "Edge Attendance Kiosk"


# ═══════════════════════════════════════════════════════════
#  Camera Thread  (Producer)
# ═══════════════════════════════════════════════════════════

class CameraThread:
    """
    Runs camera capture in a separate thread so the main loop never
    blocks on I/O.  Always holds the latest frame only (no queue
    buildup = no lag accumulation).
    """

    def __init__(self, cam: CameraService):
        self._cam = cam
        self._frame = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def get_frame(self):
        """Return the latest frame (or None if not ready yet)."""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def _capture_loop(self):
        for frame in self._cam.frames():
            if not self._running:
                break
            with self._lock:
                self._frame = frame


# ═══════════════════════════════════════════════════════════
#  AI Worker Thread  (Consumer)
# ═══════════════════════════════════════════════════════════

class AIWorker:
    """
    Runs SFace embedding + matching + DB write in a background thread.
    Main thread sends requests via submit(), picks up results via get_result().
    """

    def __init__(self, embedder: FaceEmbedder):
        self._embedder = embedder
        self._request_q: queue.Queue = queue.Queue(maxsize=1)
        self._result_q: queue.Queue = queue.Queue(maxsize=1)
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        # Unblock the worker if waiting
        try:
            self._request_q.put_nowait(None)
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=3)

    @property
    def busy(self) -> bool:
        """True if a request is being processed or queued."""
        return not self._request_q.empty()

    def submit(self, task: dict) -> bool:
        """
        Submit a recognition/enrollment task.  Returns False if worker
        is already busy (non-blocking).
        """
        try:
            self._request_q.put_nowait(task)
            return True
        except queue.Full:
            return False

    def get_result(self):
        """Non-blocking: return result dict or None."""
        try:
            return self._result_q.get_nowait()
        except queue.Empty:
            return None

    def _worker_loop(self):
        while self._running:
            try:
                task = self._request_q.get(timeout=0.5)
            except queue.Empty:
                continue

            if task is None:
                continue

            try:
                if task["action"] == "enroll":
                    result = enroll_employee(
                        task["employee_code"],
                        task["full_name"],
                        task["department"],
                        task["frame"],
                        task["face_raw"],
                        self._embedder,
                    )
                elif task["action"] == "enroll_add":
                    confirm_enroll_update(
                        task["employee_id"],
                        task["embedding"],
                        task["image_path"],
                    )
                    result = {
                        "status": "enrolled",
                        "employee_id": task["employee_id"],
                        "employee_code": task["employee_code"],
                        "full_name": task["full_name"],
                        "image_path": task["image_path"],
                    }
                elif task["action"] == "enroll_force":
                    result = enroll_new_with_embedding(
                        task["employee_code"],
                        task["full_name"],
                        task["department"],
                        task["embedding"],
                        task["image_path"],
                    )
                else:
                    result = recognize_and_attend(
                        task["frame"],
                        task["face_raw"],
                        self._embedder,
                        check_type=task["check_type"],
                        threshold=task.get("threshold"),
                    )
            except Exception as e:
                result = {
                    "status": "error",
                    "message": str(e),
                }

            # Push result (drop old if main thread hasn't consumed)
            try:
                self._result_q.put_nowait(result)
            except queue.Full:
                try:
                    self._result_q.get_nowait()
                except queue.Empty:
                    pass
                self._result_q.put_nowait(result)


# ═══════════════════════════════════════════════════════════
#  Drawing helpers
# ═══════════════════════════════════════════════════════════

def guide_box(frame):
    """Calculate the guide frame rectangle (center of screen)."""
    h, w, _ = frame.shape
    gw, gh = int(w * 0.35), int(h * 0.50)
    gx, gy = (w - gw) // 2, (h - gh) // 2
    return gx, gy, gw, gh


def draw_text_centered(frame, text, y, font_scale=0.8, color=COLOR_WHITE, thickness=2):
    """Draw text centered horizontally on the frame."""
    h, w = frame.shape[:2]
    text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)[0]
    x = (w - text_size[0]) // 2
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness)


def draw_mode_selection(frame):
    """Draw the mode selection screen on the frame."""
    h, w = frame.shape[:2]
    # Dark overlay
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, h), COLOR_DARK_BG, -1)
    cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, frame)

    # Title
    draw_text_centered(frame, "EDGE ATTENDANCE SYSTEM", h // 6, 1.0, COLOR_WHITE, 2)
    draw_text_centered(frame, "Chon che do:", h // 6 + 50, 0.7, COLOR_GRAY, 1)

    # Mode options - draw as boxes
    box_w, box_h = 350, 55
    start_y = h // 3
    gap = 75

    modes = [
        ("1", "GHI DANH (Enroll)", COLOR_BLUE),
        ("2", "DIEM DANH VAO (Check-in)", COLOR_GREEN),
        ("3", "DIEM DANH RA (Check-out)", COLOR_ORANGE),
    ]

    for i, (key, label, color) in enumerate(modes):
        by = start_y + i * gap
        bx = (w - box_w) // 2

        # Box background
        cv2.rectangle(frame, (bx, by), (bx + box_w, by + box_h), color, -1)
        cv2.rectangle(frame, (bx, by), (bx + box_w, by + box_h), COLOR_WHITE, 2)

        # Key circle
        cx, cy = bx + 30, by + box_h // 2
        cv2.circle(frame, (cx, cy), 18, COLOR_DARK_BG, -1)
        cv2.putText(frame, key, (cx - 7, cy + 7), cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_WHITE, 2)

        # Label
        cv2.putText(frame, label, (bx + 60, by + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_DARK_BG, 2)

    # Footer
    draw_text_centered(frame, "Nhan Q de thoat", h - 40, 0.5, COLOR_GRAY, 1)


def draw_status_bar(frame, text, color, bg_alpha=0.7):
    """Draw a status bar at the top of the screen."""
    h, w = frame.shape[:2]
    bar_h = 60

    # Semi-transparent background
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, bar_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, bg_alpha, frame, 1 - bg_alpha, 0, frame)

    # Status text
    cv2.putText(frame, text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)


def draw_result_overlay(frame, text, color, sub_text=""):
    """Draw a large centered result overlay (for success/error/duplicate)."""
    h, w = frame.shape[:2]
    # Dark overlay
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, h // 3), (w, 2 * h // 3), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

    draw_text_centered(frame, text, h // 2 - 10, 0.9, color, 2)
    if sub_text:
        draw_text_centered(frame, sub_text, h // 2 + 30, 0.6, COLOR_GRAY, 1)


# ── Enrollment input field config ───────────────────────
ENROLL_KEYS = ["employee_code", "full_name", "department"]
ENROLL_LABELS = ["Ma nhan vien:", "Ho va ten:", "Phong ban:"]
ENROLL_MAX_LEN = 30


def draw_enrollment_input(frame, values, field_idx, error_msg=""):
    """Draw the enrollment info input screen with interactive text fields."""
    h, w = frame.shape[:2]

    # Dark overlay
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, h), COLOR_DARK_BG, -1)
    cv2.addWeighted(overlay, 0.90, frame, 0.10, 0, frame)

    # Title
    draw_text_centered(frame, "NHAP THONG TIN NHAN VIEN", h // 7, 0.9, COLOR_WHITE, 2)

    # Fields
    field_w = min(400, w - 80)
    field_h = 40
    start_y = h // 3 - 20
    gap = 80

    for i, (label, key) in enumerate(zip(ENROLL_LABELS, ENROLL_KEYS)):
        y = start_y + i * gap
        x = (w - field_w) // 2

        # Label (red if empty and error shown)
        label_color = COLOR_RED if (error_msg and not values[key].strip()) else COLOR_GRAY
        cv2.putText(frame, label, (x, y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, label_color, 1)

        # Input box
        is_active = (i == field_idx)
        box_color = COLOR_GREEN if is_active else (100, 100, 100)
        bg_color = (50, 50, 50) if is_active else (40, 40, 40)
        cv2.rectangle(frame, (x, y), (x + field_w, y + field_h), bg_color, -1)
        cv2.rectangle(frame, (x, y), (x + field_w, y + field_h), box_color, 2)

        # Text value
        text = values[key]
        cv2.putText(frame, text, (x + 10, y + 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_WHITE, 1)

        # Blinking cursor on active field
        if is_active:
            text_w = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0][0]
            cursor_x = x + 12 + text_w
            if int(time.time() * 2) % 2 == 0:
                cv2.line(frame, (cursor_x, y + 8), (cursor_x, y + 32), COLOR_GREEN, 2)

    # Error message
    if error_msg:
        draw_text_centered(frame, error_msg, start_y + len(ENROLL_KEYS) * gap + 10,
                           0.5, COLOR_RED, 1)

    # Footer
    draw_text_centered(frame, "TAB: Chuyen truong | ENTER: Xac nhan | ESC: Quay lai",
                       h - 40, 0.45, COLOR_GRAY, 1)


def draw_enroll_confirm(frame, info):
    """Draw duplicate confirmation screen during enrollment."""
    h, w = frame.shape[:2]

    # Dark overlay
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, h), COLOR_DARK_BG, -1)
    cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, frame)

    # Warning title
    draw_text_centered(frame, "CANH BAO: KHUON MAT TUONG TU", h // 6, 0.8, COLOR_ORANGE, 2)

    # Match info
    cy = h // 3
    draw_text_centered(frame, "Giong voi nhan vien da co:", cy, 0.55, COLOR_GRAY, 1)
    draw_text_centered(frame, f"{info['existing_full_name']}", cy + 40, 0.8, COLOR_WHITE, 2)
    draw_text_centered(frame, f"Ma NV: {info['existing_employee_code']}", cy + 75, 0.6, COLOR_GRAY, 1)
    draw_text_centered(frame, f"Do tin cay: {info['confidence']:.3f}", cy + 105, 0.6, COLOR_YELLOW, 1)

    # Options
    oy = cy + 160
    box_w, box_h = 380, 45
    bx = (w - box_w) // 2

    # Y option
    cv2.rectangle(frame, (bx, oy), (bx + box_w, oy + box_h), COLOR_GREEN, -1)
    cv2.rectangle(frame, (bx, oy), (bx + box_w, oy + box_h), COLOR_WHITE, 2)
    cv2.putText(frame, "Y: Cap nhat embedding cho NV nay",
                (bx + 15, oy + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_DARK_BG, 2)

    # N option
    ny = oy + 60
    cv2.rectangle(frame, (bx, ny), (bx + box_w, ny + box_h), COLOR_BLUE, -1)
    cv2.rectangle(frame, (bx, ny), (bx + box_w, ny + box_h), COLOR_WHITE, 2)
    cv2.putText(frame, "N: Ghi danh nhan vien moi",
                (bx + 15, ny + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_DARK_BG, 2)

    # Footer
    draw_text_centered(frame, "ESC: Huy ghi danh", h - 40, 0.45, COLOR_GRAY, 1)


# ═══════════════════════════════════════════════════════════
#  Main kiosk loop
# ═══════════════════════════════════════════════════════════

def run_kiosk(args):
    init_db()
    cam = CameraService(args.camera, demo=args.demo).start()
    detector = FaceDetector()
    embedder = FaceEmbedder()

    # ── Start background threads ──
    cam_thread = CameraThread(cam)
    cam_thread.start()

    ai_worker = AIWorker(embedder)
    ai_worker.start()

    current_mode = None  # None = mode selection screen
    stable_start = None
    last_result = None
    result_display_until = 0
    ai_busy = False  # prevent double-submit

    # ── Enrollment input state ──
    enroll_info = {"employee_code": "", "full_name": "", "department": ""}
    enroll_field_idx = 0
    enroll_error = ""
    pending_confirm = None  # holds confirm_duplicate data

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

    mode_labels = {
        "enroll": "GHI DANH",
        "check_in": "DIEM DANH VAO",
        "check_out": "DIEM DANH RA",
    }

    try:
        frame_count = 0
        while True:
            now = time.time()
            key = cv2.waitKey(1) & 0xFF

            # ── Q = Quit ──
            if key == ord("q"):
                break

            # ── Grab latest frame from camera thread ──
            frame = cam_thread.get_frame()
            if frame is None:
                time.sleep(0.01)
                continue

            frame_count += 1

            # ── Check for AI worker results (non-blocking) ──
            ai_result = ai_worker.get_result()
            if ai_result is not None:
                ai_busy = False
                if ai_result.get("status") == "confirm_duplicate":
                    # Switch to confirmation screen instead of result display
                    pending_confirm = ai_result
                    current_mode = "enroll_confirm"
                else:
                    last_result = ai_result
                    result_display_until = now + 4.0

            # ═══════════════════════════════════════════════
            # MODE SELECTION SCREEN
            # ═══════════════════════════════════════════════
            if current_mode is None:
                draw_mode_selection(frame)
                cv2.imshow(WINDOW_NAME, frame)

                if key == ord("1"):
                    current_mode = "enroll_input"
                    enroll_info = {"employee_code": "", "full_name": "", "department": ""}
                    enroll_field_idx = 0
                    enroll_error = ""
                elif key == ord("2"):
                    current_mode = "check_in"
                    stable_start = None
                    last_result = None
                elif key == ord("3"):
                    current_mode = "check_out"
                    stable_start = None
                    last_result = None
                continue

            # ═══════════════════════════════════════════════
            # ENROLLMENT INPUT SCREEN
            # ═══════════════════════════════════════════════
            if current_mode == "enroll_input":
                draw_enrollment_input(frame, enroll_info, enroll_field_idx, enroll_error)
                cv2.imshow(WINDOW_NAME, frame)

                if key == 27:  # ESC → back to mode selection
                    current_mode = None
                    enroll_error = ""
                elif key == 9:  # TAB → next field
                    enroll_field_idx = (enroll_field_idx + 1) % len(ENROLL_KEYS)
                    enroll_error = ""
                elif key == 13:  # ENTER
                    if enroll_field_idx < len(ENROLL_KEYS) - 1:
                        enroll_field_idx += 1
                        enroll_error = ""
                    else:
                        if all(enroll_info[k].strip() for k in ENROLL_KEYS):
                            current_mode = "enroll"
                            stable_start = None
                            last_result = None
                            enroll_error = ""
                        else:
                            enroll_error = "Vui long dien day du thong tin!"
                elif key == 8 or key == 127:  # Backspace
                    k = ENROLL_KEYS[enroll_field_idx]
                    enroll_info[k] = enroll_info[k][:-1]
                    enroll_error = ""
                elif 32 <= key <= 126:  # Printable ASCII
                    k = ENROLL_KEYS[enroll_field_idx]
                    if len(enroll_info[k]) < ENROLL_MAX_LEN:
                        enroll_info[k] += chr(key)
                    enroll_error = ""
                continue

            # ═══════════════════════════════════════════════
            # ENROLLMENT CONFIRM SCREEN (duplicate detected)
            # ═══════════════════════════════════════════════
            if current_mode == "enroll_confirm" and pending_confirm:
                draw_enroll_confirm(frame, pending_confirm)
                cv2.imshow(WINDOW_NAME, frame)

                if key == ord("y") or key == ord("Y"):
                    # Add embedding to existing employee
                    task = {
                        "action": "enroll_add",
                        "employee_id": pending_confirm["existing_employee_id"],
                        "employee_code": pending_confirm["existing_employee_code"],
                        "full_name": pending_confirm["existing_full_name"],
                        "embedding": pending_confirm["embedding"],
                        "image_path": pending_confirm["image_path"],
                    }
                    ai_worker.submit(task)
                    ai_busy = True
                    current_mode = "enroll"
                    pending_confirm = None
                elif key == ord("n") or key == ord("N"):
                    # Force create new employee
                    task = {
                        "action": "enroll_force",
                        "employee_code": pending_confirm["new_employee_code"],
                        "full_name": pending_confirm["new_full_name"],
                        "department": pending_confirm["new_department"],
                        "embedding": pending_confirm["embedding"],
                        "image_path": pending_confirm["image_path"],
                    }
                    ai_worker.submit(task)
                    ai_busy = True
                    current_mode = "enroll"
                    pending_confirm = None
                elif key == 27:  # ESC → cancel enrollment
                    current_mode = "enroll_input"
                    pending_confirm = None
                continue

            # ═══════════════════════════════════════════════
            # CAMERA SCAN SCREEN
            # ═══════════════════════════════════════════════

            # ESC = Back to mode selection
            if key == 27:  # ESC
                current_mode = None
                stable_start = None
                last_result = None
                ai_busy = False
                continue

            guide = guide_box(frame)
            gx, gy, gw, gh = guide

            guide_color = COLOR_YELLOW
            status = "Dua mat vao khung vang"

            # ── Block re-scan while showing result (4s) or AI busy ──
            showing_result = last_result and now < result_display_until
            if showing_result or ai_busy:
                face_box, face_raw = None, None
                stable_start = None
            else:
                # Frame skipping: Bỏ qua 2 trong 3 khung hình khi chưa định vị được mặt trong guide box
                should_detect = True
                if stable_start is None and frame_count % 3 != 0:
                    should_detect = False

                if should_detect:
                    face_box, face_raw = detector.detect_largest_with_raw(frame)
                else:
                    face_box, face_raw = None, None
                # Clear expired result
                if last_result and now >= result_display_until:
                    # After enrollment, auto-return to input screen
                    if current_mode == "enroll" and last_result.get("status") == "enrolled":
                        current_mode = "enroll_input"
                        enroll_info = {"employee_code": "", "full_name": "", "department": ""}
                        enroll_field_idx = 0
                    last_result = None

            if face_box:
                fx, fy, fw, fh = face_box
                cv2.rectangle(frame, (fx, fy), (fx + fw, fy + fh), (255, 255, 0), 2)

                if is_face_inside_guide(face_box, guide):
                    guide_color = COLOR_GREEN

                    if stable_start is None:
                        stable_start = now

                    elapsed = now - stable_start

                    if elapsed >= STABLE_FACE_SECONDS:
                        # ── Submit to AI worker (non-blocking) ──
                        if current_mode == "enroll":
                            task = {
                                "action": "enroll",
                                "employee_code": enroll_info["employee_code"],
                                "full_name": enroll_info["full_name"],
                                "department": enroll_info["department"],
                                "frame": frame.copy(),
                                "face_raw": face_raw.copy(),
                            }
                        else:
                            check_type = "CHECK_IN" if current_mode == "check_in" else "CHECK_OUT"
                            task = {
                                "action": "attend",
                                "frame": frame.copy(),
                                "face_raw": face_raw.copy(),
                                "check_type": check_type,
                                "threshold": args.threshold,
                            }

                        if ai_worker.submit(task):
                            ai_busy = True

                        stable_start = None
                    else:
                        # Progress indicator
                        progress = elapsed / STABLE_FACE_SECONDS
                        status = f"Giu yen... {progress * 100:.0f}%"

                        # Draw progress bar
                        bar_x = gx
                        bar_y = gy + gh + 10
                        bar_w = int(gw * progress)
                        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + gw, bar_y + 8), (50, 50, 50), -1)
                        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + 8), COLOR_GREEN, -1)
                else:
                    stable_start = None
                    status = "Can chinh mat vao giua khung"
            else:
                stable_start = None

            # Draw guide box
            cv2.rectangle(frame, (gx, gy), (gx + gw, gy + gh), guide_color, 3)

            # Draw guide corner decorations
            corner_len = 20
            corners = [
                ((gx, gy), (gx + corner_len, gy), (gx, gy + corner_len)),
                ((gx + gw, gy), (gx + gw - corner_len, gy), (gx + gw, gy + corner_len)),
                ((gx, gy + gh), (gx + corner_len, gy + gh), (gx, gy + gh - corner_len)),
                ((gx + gw, gy + gh), (gx + gw - corner_len, gy + gh), (gx + gw, gy + gh - corner_len)),
            ]
            for pt, pt_h, pt_v in corners:
                cv2.line(frame, pt, pt_h, guide_color, 4)
                cv2.line(frame, pt, pt_v, guide_color, 4)

            # ── Show result overlay (4 seconds) ──
            if last_result and now < result_display_until:
                r = last_result

                if r["status"] == "enrolled":
                    draw_result_overlay(
                        frame,
                        f"Da ghi danh: {r['full_name']}",
                        COLOR_GREEN,
                        f"Ma NV: {r['employee_code']}",
                    )
                elif r["status"] == "success":
                    draw_result_overlay(
                        frame,
                        f"{r['full_name']}",
                        COLOR_GREEN,
                        f"{r['check_type']} - Do tin cay: {r['confidence']:.3f}",
                    )
                elif r["status"] == "duplicate":
                    draw_result_overlay(
                        frame,
                        f"Da ghi nhan: {r['full_name']}",
                        COLOR_ORANGE,
                        r["message"],
                    )
                elif r["status"] == "not_found":
                    draw_result_overlay(
                        frame,
                        "Khong tim thay nhan vien",
                        COLOR_RED,
                        "Vui long ghi danh truoc",
                    )
                elif r["status"] == "error":
                    draw_result_overlay(
                        frame,
                        "LOI HE THONG",
                        COLOR_RED,
                        r.get("message", ""),
                    )

                status = ""

            # ── AI processing indicator ──
            if ai_busy:
                status = "Dang xu ly..."

            # Mode indicator (top-right)
            mode_text = mode_labels.get(current_mode, "")
            draw_status_bar(frame, f"[{mode_text}]  {status}", guide_color)

            # Footer: ESC instruction
            h, w = frame.shape[:2]
            cv2.putText(
                frame, "ESC: Quay lai | Q: Thoat", (10, h - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_GRAY, 1,
            )

            cv2.imshow(WINDOW_NAME, frame)

    finally:
        # ── Cleanup ──
        ai_worker.stop()
        cam_thread.stop()
        cam.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Edge Attendance Kiosk")
    parser.add_argument("--camera", type=int, default=0, help="Camera index")
    parser.add_argument("--demo", action="store_true", help="Run without camera")
    parser.add_argument("--employee-code", default="E001", help="Employee code for enrollment")
    parser.add_argument("--full-name", default="Demo Employee", help="Full name for enrollment")
    parser.add_argument("--department", default="Demo", help="Department for enrollment")
    parser.add_argument("--threshold", type=float, default=None, help="Recognition threshold override")
    args = parser.parse_args()
    run_kiosk(args)