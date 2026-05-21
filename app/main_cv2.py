"""
Edge Attendance Kiosk – Pure OpenCV UI (No PyQt5 required).

Thay thế main_qt.py cho Raspberry Pi khi PyQt5 bị lỗi XCB/Wayland.
Sử dụng cv2.imshow() + cv2.waitKey() để hiển thị camera và nhận phím bấm.

Cách chạy:
  python3 run_cv2.py --source usb --camera 0
  python3 run_cv2.py --source picam
  python3 run_cv2.py --demo
"""
import sys
import time
import threading
import cv2
import numpy as np
import argparse

from .camera_service import CameraService
from .face_detector import FaceDetector, is_face_inside_guide
from .face_embedder import FaceEmbedder
from .attendance_service import (
    enroll_employee, recognize_and_attend,
    confirm_enroll_update, enroll_new_with_embedding,
)
from .database import init_db
from .best_frame_selector import BestFrameSelector
from .config import STABLE_FACE_SECONDS

# ── Colors (BGR) ────────────────────────────────────────
COLOR_YELLOW = (0, 255, 255)
COLOR_GREEN = (0, 255, 0)
COLOR_RED = (0, 0, 255)
COLOR_WHITE = (255, 255, 255)
COLOR_GRAY = (180, 180, 180)
COLOR_ORANGE = (0, 140, 255)
COLOR_DARK = (30, 30, 30)

WINDOW_NAME = "Edge Attendance Kiosk"


# ═══════════════════════════════════════════════════════════
#  Helper: Vẽ text có nền bán trong suốt
# ═══════════════════════════════════════════════════════════

def put_text_with_bg(frame, text, pos, font_scale=0.7, color=COLOR_WHITE,
                     thickness=2, bg_color=(0, 0, 0), bg_alpha=0.6, padding=8):
    """Vẽ text trên nền bán trong suốt để dễ đọc."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    x, y = pos
    # Vẽ nền
    overlay = frame.copy()
    cv2.rectangle(overlay,
                  (x - padding, y - th - padding),
                  (x + tw + padding, y + baseline + padding),
                  bg_color, -1)
    cv2.addWeighted(overlay, bg_alpha, frame, 1 - bg_alpha, 0, frame)
    # Vẽ chữ
    cv2.putText(frame, text, (x, y), font, font_scale, color, thickness, cv2.LINE_AA)


def put_centered_text(frame, text, y, font_scale=1.0, color=COLOR_WHITE,
                      thickness=2, bg_alpha=0.6):
    """Vẽ text căn giữa theo chiều ngang."""
    h, w = frame.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    x = (w - tw) // 2
    put_text_with_bg(frame, text, (x, y), font_scale, color, thickness,
                     bg_alpha=bg_alpha)


def draw_guide_box(frame, guide_color):
    """Vẽ khung hướng dẫn (guide box) ở giữa màn hình."""
    h, w, _ = frame.shape
    gw, gh = int(w * 0.35), int(h * 0.50)
    gx, gy = (w - gw) // 2, (h - gh) // 2

    # Vẽ 4 góc
    corner_len = 25
    corners = [
        ((gx, gy), (gx + corner_len, gy), (gx, gy + corner_len)),
        ((gx + gw, gy), (gx + gw - corner_len, gy), (gx + gw, gy + corner_len)),
        ((gx, gy + gh), (gx + corner_len, gy + gh), (gx, gy + gh - corner_len)),
        ((gx + gw, gy + gh), (gx + gw - corner_len, gy + gh), (gx + gw, gy + gh - corner_len)),
    ]
    for pt, pt_h, pt_v in corners:
        cv2.line(frame, pt, pt_h, guide_color, 4)
        cv2.line(frame, pt, pt_v, guide_color, 4)

    return gx, gy, gw, gh


# ═══════════════════════════════════════════════════════════
#  AI Worker Thread (Non-blocking)
# ═══════════════════════════════════════════════════════════

class AIWorkerThread:
    """Chạy AI inference (FaceLiVT) trong thread riêng để không block camera."""

    def __init__(self, embedder: FaceEmbedder):
        self.embedder = embedder
        self._task = None
        self._result = None
        self._busy = False
        self._lock = threading.Lock()

    @property
    def busy(self):
        return self._busy

    def submit(self, task: dict):
        """Gửi task vào hàng đợi."""
        with self._lock:
            self._task = task
            self._result = None
            self._busy = True
        threading.Thread(target=self._run, daemon=True).start()

    def get_result(self):
        """Lấy kết quả (None nếu chưa xong)."""
        with self._lock:
            r = self._result
            if r is not None:
                self._result = None
            return r

    def _run(self):
        task = self._task
        try:
            if task["action"] == "enroll":
                res = enroll_employee(
                    task["employee_code"], task["full_name"], task["department"],
                    task["frame"], task["face_raw"], self.embedder,
                )
            elif task["action"] == "enroll_add":
                confirm_enroll_update(
                    task["employee_id"], task["embedding"], task["image_path"],
                )
                res = {
                    "status": "enrolled",
                    "employee_id": task["employee_id"],
                    "employee_code": task["employee_code"],
                    "full_name": task["full_name"],
                    "image_path": task["image_path"],
                }
            elif task["action"] == "enroll_force":
                res = enroll_new_with_embedding(
                    task["employee_code"], task["full_name"], task["department"],
                    task["embedding"], task["image_path"],
                )
            elif task["action"] == "attend":
                res = recognize_and_attend(
                    task["frame"], task["face_raw"], self.embedder,
                    check_type=task["check_type"],
                )
            else:
                res = {"status": "error", "message": f"Unknown action: {task['action']}"}
        except Exception as e:
            res = {"status": "error", "message": str(e)}

        with self._lock:
            self._result = res
            self._busy = False


# ═══════════════════════════════════════════════════════════
#  Màn hình Menu (vẽ bằng OpenCV)
# ═══════════════════════════════════════════════════════════

def draw_menu_screen(width=640, height=480):
    """Tạo ảnh nền cho màn hình chọn chế độ."""
    screen = np.zeros((height, width, 3), dtype=np.uint8)
    screen[:] = COLOR_DARK

    put_centered_text(screen, "EDGE ATTENDANCE SYSTEM", height // 5,
                      font_scale=1.0, color=COLOR_WHITE, thickness=2, bg_alpha=0)

    put_centered_text(screen, "[1] GHI DANH", height // 5 + 80,
                      font_scale=0.8, color=(50, 160, 255), thickness=2, bg_alpha=0)
    put_centered_text(screen, "[2] DIEM DANH VAO", height // 5 + 130,
                      font_scale=0.8, color=COLOR_GREEN, thickness=2, bg_alpha=0)
    put_centered_text(screen, "[3] DIEM DANH RA", height // 5 + 180,
                      font_scale=0.8, color=COLOR_ORANGE, thickness=2, bg_alpha=0)
    put_centered_text(screen, "[Q] THOAT", height // 5 + 250,
                      font_scale=0.6, color=COLOR_GRAY, thickness=1, bg_alpha=0)

    return screen


def draw_enroll_input_screen(code, name, dept, cursor_field, width=640, height=480):
    """Tạo ảnh nền cho màn hình nhập thông tin ghi danh."""
    screen = np.zeros((height, width, 3), dtype=np.uint8)
    screen[:] = COLOR_DARK

    put_centered_text(screen, "NHAP THONG TIN NHAN VIEN", 60,
                      font_scale=0.8, color=COLOR_WHITE, thickness=2, bg_alpha=0)

    fields = [
        ("Ma NV:    ", code, 0),
        ("Ho ten:   ", name, 1),
        ("Phong ban:", dept, 2),
    ]
    y_start = 140
    for label, value, idx in fields:
        color = COLOR_GREEN if cursor_field == idx else COLOR_WHITE
        marker = ">" if cursor_field == idx else " "
        display_val = value + ("|" if cursor_field == idx else "")
        put_text_with_bg(screen, f"{marker} {label} {display_val}", (40, y_start + idx * 60),
                         font_scale=0.7, color=color, thickness=2, bg_alpha=0)

    put_centered_text(screen, "[Enter] Tiep tuc  |  [Tab] Chuyen o  |  [ESC] Huy", height - 40,
                      font_scale=0.5, color=COLOR_GRAY, thickness=1, bg_alpha=0)

    return screen


# ═══════════════════════════════════════════════════════════
#  Màn hình xác nhận trùng lặp
# ═══════════════════════════════════════════════════════════

def draw_confirm_screen(result, width=640, height=480):
    """Tạo ảnh nền cho màn hình xác nhận nhân viên trùng."""
    screen = np.zeros((height, width, 3), dtype=np.uint8)
    screen[:] = COLOR_DARK

    put_centered_text(screen, "!! CANH BAO TRUNG LAP !!", 80,
                      font_scale=0.9, color=COLOR_RED, thickness=2, bg_alpha=0)

    info_lines = [
        f"Khuon mat nay giong voi NV da co:",
        f"  Ten: {result.get('existing_full_name', '???')}",
        f"  Ma NV: {result.get('existing_employee_code', '???')}",
        f"  Do tin cay: {result.get('confidence', 0):.3f}",
    ]
    for i, line in enumerate(info_lines):
        put_text_with_bg(screen, line, (40, 150 + i * 40),
                         font_scale=0.6, color=COLOR_WHITE, thickness=1, bg_alpha=0)

    put_centered_text(screen, "[Y] Cap nhat NV cu  |  [N] Tao NV moi  |  [ESC] Huy", height - 40,
                      font_scale=0.5, color=COLOR_GRAY, thickness=1, bg_alpha=0)

    return screen


# ═══════════════════════════════════════════════════════════
#  Main Loop
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Edge Attendance Kiosk (OpenCV Version)")
    parser.add_argument("--camera", type=int, default=0, help="Camera index cho USB camera")
    parser.add_argument("--source", type=str, choices=["auto", "picam", "usb"], default="auto",
                        help="Nguon camera: auto, picam, usb")
    parser.add_argument("--demo", action="store_true", help="Chay khong can camera")
    parser.add_argument("--fullscreen", action="store_true", help="Chay toan man hinh")
    args = parser.parse_args()

    # ── Khởi tạo hệ thống ──
    print("[System] Khoi tao co so du lieu...")
    init_db()

    print("[System] Khoi dong camera...")
    cam = CameraService(camera_index=args.camera, source=args.source, demo=args.demo).start()

    print("[System] Tai model AI (YuNet + FaceLiVT)...")
    detector = FaceDetector()
    embedder = FaceEmbedder()
    ai_worker = AIWorkerThread(embedder)
    frame_selector = BestFrameSelector()

    # ── Tạo cửa sổ OpenCV ──
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    if args.fullscreen:
        cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    # ── State Machine ──
    STATE_MENU = "menu"
    STATE_ENROLL_INPUT = "enroll_input"
    STATE_CAMERA = "camera"
    STATE_CONFIRM = "confirm"

    state = STATE_MENU
    current_mode = None  # "enroll", "check_in", "check_out"

    # Enroll input fields
    enroll_code = ""
    enroll_name = ""
    enroll_dept = ""
    cursor_field = 0  # 0=code, 1=name, 2=dept

    # Camera state
    stable_start = None
    last_result = None
    result_display_until = 0
    pending_confirm = None

    mode_labels = {
        "enroll": "GHI DANH",
        "check_in": "DIEM DANH VAO",
        "check_out": "DIEM DANH RA",
    }

    print("[System] === HE THONG SAN SANG ===")

    frame_count = 0
    for frame in cam.frames():
        now = time.time()
        frame_count += 1

        # ── Kiểm tra kết quả AI (non-blocking) ──
        ai_result = ai_worker.get_result()
        if ai_result:
            if ai_result.get("status") == "confirm_duplicate":
                pending_confirm = ai_result
                state = STATE_CONFIRM
            else:
                last_result = ai_result
                result_display_until = now + 4.0

        # ──────────────────────────────────────────
        #  STATE: MENU
        # ──────────────────────────────────────────
        if state == STATE_MENU:
            screen = draw_menu_screen(frame.shape[1], frame.shape[0])
            cv2.imshow(WINDOW_NAME, screen)
            key = cv2.waitKey(30) & 0xFF

            if key == ord('1'):
                enroll_code, enroll_name, enroll_dept = "", "", ""
                cursor_field = 0
                state = STATE_ENROLL_INPUT
            elif key == ord('2'):
                current_mode = "check_in"
                stable_start = None
                last_result = None
                frame_selector.reset()
                state = STATE_CAMERA
            elif key == ord('3'):
                current_mode = "check_out"
                stable_start = None
                last_result = None
                frame_selector.reset()
                state = STATE_CAMERA
            elif key == ord('q') or key == ord('Q'):
                break

        # ──────────────────────────────────────────
        #  STATE: ENROLL INPUT (Nhập thông tin NV)
        # ──────────────────────────────────────────
        elif state == STATE_ENROLL_INPUT:
            screen = draw_enroll_input_screen(enroll_code, enroll_name, enroll_dept,
                                              cursor_field, frame.shape[1], frame.shape[0])
            cv2.imshow(WINDOW_NAME, screen)
            key = cv2.waitKey(30) & 0xFF

            if key == 27:  # ESC
                state = STATE_MENU
            elif key == 9:  # Tab → chuyển ô nhập
                cursor_field = (cursor_field + 1) % 3
            elif key == 13:  # Enter → tiếp tục
                if enroll_code.strip() and enroll_name.strip():
                    current_mode = "enroll"
                    stable_start = None
                    last_result = None
                    frame_selector.reset()
                    state = STATE_CAMERA
            elif key == 8:  # Backspace
                if cursor_field == 0:
                    enroll_code = enroll_code[:-1]
                elif cursor_field == 1:
                    enroll_name = enroll_name[:-1]
                else:
                    enroll_dept = enroll_dept[:-1]
            elif 32 <= key <= 126:  # Printable ASCII
                ch = chr(key)
                if cursor_field == 0:
                    enroll_code += ch
                elif cursor_field == 1:
                    enroll_name += ch
                else:
                    enroll_dept += ch

        # ──────────────────────────────────────────
        #  STATE: CONFIRM (Xác nhận trùng lặp)
        # ──────────────────────────────────────────
        elif state == STATE_CONFIRM and pending_confirm:
            screen = draw_confirm_screen(pending_confirm, frame.shape[1], frame.shape[0])
            cv2.imshow(WINDOW_NAME, screen)
            key = cv2.waitKey(30) & 0xFF

            if key == ord('y') or key == ord('Y'):
                # Cập nhật cho nhân viên cũ
                ai_worker.submit({
                    "action": "enroll_add",
                    "employee_id": pending_confirm["existing_employee_id"],
                    "employee_code": pending_confirm["existing_employee_code"],
                    "full_name": pending_confirm["existing_full_name"],
                    "embedding": pending_confirm["embedding"],
                    "image_path": pending_confirm["image_path"],
                })
                pending_confirm = None
                state = STATE_CAMERA
            elif key == ord('n') or key == ord('N'):
                # Tạo nhân viên mới
                ai_worker.submit({
                    "action": "enroll_force",
                    "employee_code": pending_confirm["new_employee_code"],
                    "full_name": pending_confirm["new_full_name"],
                    "department": pending_confirm["new_department"],
                    "embedding": pending_confirm["embedding"],
                    "image_path": pending_confirm["image_path"],
                })
                pending_confirm = None
                state = STATE_CAMERA
            elif key == 27:  # ESC → Hủy
                pending_confirm = None
                enroll_code, enroll_name, enroll_dept = "", "", ""
                cursor_field = 0
                state = STATE_ENROLL_INPUT

        # ──────────────────────────────────────────
        #  STATE: CAMERA (Quét khuôn mặt)
        # ──────────────────────────────────────────
        elif state == STATE_CAMERA:
            guide_color = COLOR_YELLOW
            status_text = "Dua mat vao khung vang"

            showing_result = last_result and now < result_display_until
            skip_detection = showing_result or ai_worker.busy

            face_box, face_raw = None, None
            clean_frame = frame.copy()

            if not skip_detection:
                # Kiểm tra nếu hết thời gian hiển thị kết quả
                if last_result and now >= result_display_until:
                    if current_mode == "enroll" and last_result.get("status") == "enrolled":
                        # Quay lại màn hình nhập sau khi ghi danh thành công
                        enroll_code, enroll_name, enroll_dept = "", "", ""
                        cursor_field = 0
                        state = STATE_ENROLL_INPUT
                        cv2.imshow(WINDOW_NAME, frame)
                        cv2.waitKey(1)
                        continue
                    last_result = None

                # Bỏ qua 2 trong 3 khung hình nếu không có khuôn mặt ổn định trong khung hướng dẫn
                should_detect = True
                if stable_start is None and frame_count % 3 != 0:
                    should_detect = False

                if should_detect:
                    face_box, face_raw = detector.detect_largest_with_raw(clean_frame)
            else:
                stable_start = None
                frame_selector.reset()

            # Vẽ Guide Box
            gx, gy, gw, gh = draw_guide_box(frame, guide_color if not showing_result else COLOR_GRAY)

            if face_box and not skip_detection:
                fx, fy, fw, fh = face_box
                cv2.rectangle(frame, (fx, fy), (fx + fw, fy + fh), COLOR_YELLOW, 2)

                if is_face_inside_guide(face_box, (gx, gy, gw, gh)):
                    guide_color = COLOR_GREEN
                    # Vẽ lại Guide Box với màu xanh
                    draw_guide_box(frame, guide_color)

                    if stable_start is None:
                        stable_start = now
                        frame_selector.reset()

                    # Cập nhật BestFrameSelector
                    landmarks = face_raw[4:14]
                    frame_selector.update(clean_frame, face_box, landmarks, face_raw)

                    elapsed = now - stable_start
                    if elapsed >= STABLE_FACE_SECONDS:
                        # Lấy frame tốt nhất và gửi cho AI
                        best_frame, best_face_raw, _ = frame_selector.get_best()
                        if best_frame is None:
                            best_frame = clean_frame
                            best_face_raw = face_raw

                        if current_mode == "enroll":
                            ai_worker.submit({
                                "action": "enroll",
                                "employee_code": enroll_code,
                                "full_name": enroll_name,
                                "department": enroll_dept,
                                "frame": best_frame,
                                "face_raw": best_face_raw,
                            })
                        else:
                            check_type = "CHECK_IN" if current_mode == "check_in" else "CHECK_OUT"
                            ai_worker.submit({
                                "action": "attend",
                                "frame": best_frame,
                                "face_raw": best_face_raw,
                                "check_type": check_type,
                            })

                        stable_start = None
                        frame_selector.reset()
                    else:
                        progress = elapsed / STABLE_FACE_SECONDS
                        status_text = f"Giu yen... {progress * 100:.0f}%"
                        # Thanh tiến trình
                        bar_x, bar_y = gx, gy + gh + 10
                        bar_w = int(gw * progress)
                        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + gw, bar_y + 8), (50, 50, 50), -1)
                        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + 8), COLOR_GREEN, -1)
                else:
                    stable_start = None
                    status_text = "Can chinh mat vao giua khung"
            elif not skip_detection:
                stable_start = None

            if ai_worker.busy:
                status_text = "Dang xu ly..."

            # ── Vẽ thanh trạng thái (Status bar) ──
            overlay = frame.copy()
            cv2.rectangle(overlay, (0, 0), (frame.shape[1], 50), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

            mode_text = f"[{mode_labels.get(current_mode, '')}] {status_text}"
            cv2.putText(frame, mode_text, (15, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, guide_color, 2, cv2.LINE_AA)

            # ── Vẽ kết quả overlay ──
            if showing_result:
                r = last_result
                h_frame, w_frame = frame.shape[:2]

                # Nền bán trong suốt
                overlay = frame.copy()
                cv2.rectangle(overlay, (0, h_frame // 3), (w_frame, 2 * h_frame // 3), (0, 0, 0), -1)
                cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

                main_txt, sub_txt = "", ""
                main_color = COLOR_WHITE

                if r["status"] == "enrolled":
                    main_txt = f"Da ghi danh: {r['full_name']}"
                    sub_txt = f"Ma NV: {r['employee_code']}"
                    main_color = COLOR_GREEN
                elif r["status"] == "success":
                    main_txt = f"{r['full_name']}"
                    sub_txt = f"{r['check_type']} - Do tin cay: {r['confidence']:.3f}"
                    main_color = COLOR_GREEN
                elif r["status"] == "duplicate":
                    main_txt = f"CANH BAO: {r['full_name']}"
                    sub_txt = r.get("message", "")
                    main_color = COLOR_ORANGE
                elif r["status"] == "not_found":
                    main_txt = "Khong tim thay nhan vien"
                    sub_txt = "Vui long ghi danh truoc"
                    main_color = COLOR_RED
                elif r["status"] == "error":
                    main_txt = "LOI HE THONG"
                    sub_txt = r.get("message", "")
                    main_color = COLOR_RED

                put_centered_text(frame, main_txt, h_frame // 2 - 10,
                                  font_scale=0.9, color=main_color, thickness=2, bg_alpha=0)
                if sub_txt:
                    put_centered_text(frame, sub_txt, h_frame // 2 + 30,
                                      font_scale=0.6, color=COLOR_GRAY, thickness=1, bg_alpha=0)

            # Footer
            cv2.putText(frame, "ESC: Quay lai", (10, frame.shape[0] - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_GRAY, 1, cv2.LINE_AA)

            cv2.imshow(WINDOW_NAME, frame)
            key = cv2.waitKey(1) & 0xFF

            if key == 27:  # ESC
                state = STATE_MENU
                stable_start = None
                frame_selector.reset()
                last_result = None

    # ── Cleanup ──
    cam.release()
    cv2.destroyAllWindows()
    print("[System] Da dong he thong.")


if __name__ == "__main__":
    main()
