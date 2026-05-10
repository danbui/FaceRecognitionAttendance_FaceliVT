"""
Dataset Cleaner — Lọc ảnh thẳng mặt, sắc nét, đủ sáng.

Đọc ảnh từ thư mục input (mỗi subfolder = 1 người),
lọc theo: kích thước mặt, sharpness, brightness, góc mặt (yaw/roll),
align + crop 112x112, lưu vào output folder.

Cách chạy:
  python scripts/dataset_cleaner.py --input VN-celeb --output VN-celeb-clean
  python scripts/dataset_cleaner.py --input data_faces --output dataset_clean
  python scripts/dataset_cleaner.py --input VN-celeb --output VN-celeb-clean --min-face 60 --max-yaw 20
"""
import sys, argparse
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.face_detector import FaceDetector

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

ARCFACE_DST = np.array([
    [38.2946, 51.6963], [73.5318, 51.5014],
    [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]
], dtype=np.float32)


# ── Tiêu chí lọc ──

def calc_sharpness(gray):
    """Độ sắc nét = phương sai Laplacian."""
    return cv2.Laplacian(gray, cv2.CV_64F).var()


def calc_brightness(gray):
    """Độ sáng trung bình."""
    return float(np.mean(gray))


def estimate_yaw_roll(landmarks_5):
    """
    Ước lượng yaw/roll từ 5 landmarks (mắt phải, mắt trái, mũi, 2 khóe miệng).
    Yaw: góc quay trái-phải.  Roll: góc nghiêng đầu.
    """
    re, le = landmarks_5[0], landmarks_5[1]  # right eye, left eye
    nose = landmarks_5[2]

    # Roll = góc giữa 2 mắt so với đường ngang
    dx = le[0] - re[0]
    dy = le[1] - re[1]
    roll = abs(np.degrees(np.arctan2(dy, dx)))

    # Yaw ước lượng = vị trí mũi so với trung điểm 2 mắt
    mid_eye_x = (re[0] + le[0]) / 2.0
    eye_dist = max(abs(dx), 1e-5)
    yaw_ratio = (nose[0] - mid_eye_x) / eye_dist
    yaw = abs(np.degrees(np.arctan(yaw_ratio * 2)))

    return yaw, roll


def align_and_crop(frame, landmarks_5, size=112):
    """Align khuôn mặt theo chuẩn ArcFace 112x112."""
    dst = ARCFACE_DST * (float(size) / 112.0)
    try:
        M, _ = cv2.estimateAffinePartial2D(landmarks_5, dst)
        if M is None:
            M = cv2.getAffineTransform(landmarks_5[:3], dst[:3])
        return cv2.warpAffine(frame, M, (size, size), borderValue=0.0)
    except Exception:
        return None


def process_image(img_path, detector, args):
    """
    Xử lý 1 ảnh. Trả về (aligned_face, reason) hoặc (None, reason).
    """
    buf = np.fromfile(str(img_path), dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        return None, "read_error"

    dets = detector.detect_all(img)
    if dets is None:
        return None, "no_face"

    # Lấy mặt lớn nhất
    areas = dets[:, 2] * dets[:, 3]
    idx = int(np.argmax(areas))
    det = dets[idx]
    x, y, w, h = det[:4].astype(int)

    # 1. Kiểm tra kích thước mặt
    if w < args.min_face or h < args.min_face:
        return None, f"small_face({w}x{h})"

    # 2. Lấy landmarks
    lm = det[4:14].reshape((5, 2))

    # 3. Kiểm tra góc mặt (yaw, roll)
    yaw, roll = estimate_yaw_roll(lm)
    if yaw > args.max_yaw:
        return None, f"yaw({yaw:.1f}>{args.max_yaw})"
    if roll > args.max_roll:
        return None, f"roll({roll:.1f}>{args.max_roll})"

    # 4. Crop vùng mặt để tính sharpness + brightness
    fy, fy2 = max(0, y), min(img.shape[0], y + h)
    fx, fx2 = max(0, x), min(img.shape[1], x + w)
    face_crop = img[fy:fy2, fx:fx2]
    if face_crop.size == 0:
        return None, "empty_crop"

    gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)

    # 5. Kiểm tra sharpness
    sharp = calc_sharpness(gray)
    if sharp < args.min_sharpness:
        return None, f"blur({sharp:.0f}<{args.min_sharpness})"

    # 6. Kiểm tra brightness
    bright = calc_brightness(gray)
    if bright < args.min_brightness or bright > args.max_brightness:
        return None, f"brightness({bright:.0f})"

    # 7. Passed all checks — giữ nguyên ảnh gốc
    return img_path, "ok"


def main():
    parser = argparse.ArgumentParser(description="Dataset Cleaner — Lọc ảnh thẳng mặt")
    parser.add_argument("--input", type=str, required=True, help="Thư mục input (mỗi subfolder = 1 người)")
    parser.add_argument("--output", type=str, default="dataset_clean", help="Thư mục output")
    parser.add_argument("--min-face", type=int, default=50, help="Kích thước mặt tối thiểu (px)")
    parser.add_argument("--max-yaw", type=float, default=25.0, help="Góc quay trái/phải tối đa (độ)")
    parser.add_argument("--max-roll", type=float, default=20.0, help="Góc nghiêng đầu tối đa (độ)")
    parser.add_argument("--min-sharpness", type=float, default=30.0, help="Ngưỡng sharpness (Laplacian var)")
    parser.add_argument("--min-brightness", type=float, default=40.0, help="Độ sáng tối thiểu")
    parser.add_argument("--max-brightness", type=float, default=220.0, help="Độ sáng tối đa")
    parser.add_argument("--min-per-person", type=int, default=2, help="Số ảnh tối thiểu mỗi người (bỏ nếu ít hơn)")
    args = parser.parse_args()

    inp = Path(args.input)
    if not inp.is_absolute(): inp = PROJECT_ROOT / inp
    out = Path(args.output)
    if not out.is_absolute(): out = PROJECT_ROOT / out

    print("=" * 65)
    print("  🧹 Dataset Cleaner — Lọc ảnh thẳng mặt")
    print("=" * 65)
    print(f"  Input : {inp}")
    print(f"  Output: {out}")
    print(f"  Filters: face>={args.min_face}px, yaw<={args.max_yaw}°, roll<={args.max_roll}°")
    print(f"           sharpness>={args.min_sharpness}, brightness=[{args.min_brightness}-{args.max_brightness}]")

    detector = FaceDetector()

    people = sorted([d for d in inp.iterdir() if d.is_dir()])
    print(f"\n  📁 {len(people)} thư mục người\n")

    stats = {"total": 0, "ok": 0, "rejected": 0, "people_ok": 0, "people_skip": 0}
    reject_reasons = {}

    for pi, pdir in enumerate(people):
        imgs = sorted(f for f in pdir.iterdir() if f.is_file() and f.suffix.lower() in IMG_EXTS)
        if not imgs:
            continue

        person_ok = 0
        person_out = out / pdir.name
        passed_files = []

        for img_path in imgs:
            stats["total"] += 1
            result, reason = process_image(img_path, detector, args)
            if result is not None:
                passed_files.append(result)  # result = original file path
                person_ok += 1
            else:
                stats["rejected"] += 1
                reject_reasons[reason] = reject_reasons.get(reason, 0) + 1

        # Kiểm tra đủ ảnh tối thiểu
        if len(passed_files) >= args.min_per_person:
            person_out.mkdir(parents=True, exist_ok=True)
            for src_path in passed_files:
                import shutil
                dst_path = person_out / src_path.name
                shutil.copy2(str(src_path), str(dst_path))
            stats["ok"] += len(passed_files)
            stats["people_ok"] += 1
        else:
            stats["rejected"] += len(passed_files)
            stats["people_skip"] += 1
            reject_reasons[f"too_few(<{args.min_per_person})"] = \
                reject_reasons.get(f"too_few(<{args.min_per_person})", 0) + len(passed_files)

        if (pi + 1) % 20 == 0 or (pi + 1) == len(people):
            print(f"  [{pi+1}/{len(people)}] ok={stats['ok']} rejected={stats['rejected']}")

    # Report
    print(f"\n{'='*65}")
    print(f"  📊 KẾT QUẢ")
    print(f"{'='*65}")
    print(f"  Tổng ảnh xử lý    : {stats['total']}")
    print(f"  Ảnh đạt chuẩn     : {stats['ok']} ({stats['ok']/max(stats['total'],1)*100:.1f}%)")
    print(f"  Ảnh bị loại       : {stats['rejected']}")
    print(f"  Người đạt chuẩn   : {stats['people_ok']}")
    print(f"  Người bị loại     : {stats['people_skip']}")
    print(f"\n  Lý do loại:")
    for reason, count in sorted(reject_reasons.items(), key=lambda x: -x[1]):
        print(f"    {reason:<30} {count:>5}")
    print(f"\n  📁 Output: {out}")
    print(f"  ✅ Hoàn tất!")


if __name__ == "__main__":
    main()
