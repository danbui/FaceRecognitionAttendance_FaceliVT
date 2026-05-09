"""Quick identify: who is in the Manual test folder?"""
import sys
import numpy as np
import cv2
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import app.config as cfg
cfg.DB_PATH = PROJECT_ROOT / "benchmark.db"

from app.database import init_db
from app.face_detector import FaceDetector
from app.face_embedder import FaceEmbedder
from app.matcher import embedding_cache, match_embedding

TEST_FOLDER = PROJECT_ROOT / "Manual test"


def imread_unicode(filepath):
    data = np.fromfile(str(filepath), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite_unicode(filepath, img):
    """cv2.imwrite fails on Unicode paths. Encode then write raw bytes."""
    ext = Path(str(filepath)).suffix
    _, buf = cv2.imencode(ext, img)
    buf.tofile(str(filepath))


def main():
    init_db()
    detector = FaceDetector()
    embedder = FaceEmbedder()
    embedding_cache.invalidate()

    # Output folder for results
    results_dir = TEST_FOLDER / "results"
    results_dir.mkdir(exist_ok=True)

    for img_file in sorted(TEST_FOLDER.iterdir()):
        if img_file.suffix.lower() not in (".jpg", ".jpeg", ".png", ".jfif", ".bmp", ".webp"):
            continue

        print(f"\n{'='*50}")
        print(f"File: {img_file.name}")

        frame = imread_unicode(img_file)
        if frame is None:
            print("  -> Cannot read image")
            continue

        print(f"  Size: {frame.shape[1]}x{frame.shape[0]}")

        detections = detector.detect_all(frame)
        if detections is None:
            print("  -> No face detected")
            continue

        print(f"  Faces found: {len(detections)}")

        # Copy frame to draw annotations
        annotated = frame.copy()
        stem = img_file.stem

        for fi, det in enumerate(detections):
            x, y, w, h = int(det[0]), int(det[1]), int(det[2]), int(det[3])

            # ── Crop face from original image ──
            y1, y2 = max(0, y), min(frame.shape[0], y + h)
            x1, x2 = max(0, x), min(frame.shape[1], x + w)
            face_crop = frame[y1:y2, x1:x2].copy()

            # Save cropped face
            crop_path = results_dir / f"{stem}_face{fi+1}_crop.jpg"
            imwrite_unicode(crop_path, face_crop)
            print(f"  Face {fi+1} crop saved: {crop_path.name} ({w}x{h})")

            # ── Aligned face (what model actually sees) ──
            from app.face_embedder import align_face_arcface
            aligned = align_face_arcface(frame, det)
            align_path = results_dir / f"{stem}_face{fi+1}_aligned.jpg"
            imwrite_unicode(align_path, aligned)
            print(f"  Face {fi+1} aligned saved: {align_path.name}")

            # ── Recognize ──
            embedding = embedder.get_embedding(frame, det)
            result = match_embedding(embedding, threshold=0.363)

            if result:
                name = result['full_name']
                conf = result['confidence']
                print(f"  Face {fi+1} -> {name} (conf={conf:.4f})")

                # Draw on annotated image
                color = (0, 255, 0)
                cv2.rectangle(annotated, (x, y), (x+w, y+h), color, 2)
                label = f"{name} ({conf:.2f})"
                cv2.putText(annotated, label, (x, y-10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            else:
                print(f"  Face {fi+1} -> Unknown")
                cv2.rectangle(annotated, (x, y), (x+w, y+h), (0, 0, 255), 2)
                cv2.putText(annotated, "Unknown", (x, y-10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

            # Draw landmarks (5 points: eyes, nose, mouth)
            for li in range(5):
                lx = int(det[4 + li * 2])
                ly = int(det[4 + li * 2 + 1])
                cv2.circle(annotated, (lx, ly), 3, (255, 0, 255), -1)

        # Save annotated full image
        annot_path = results_dir / f"{stem}_annotated.jpg"
        imwrite_unicode(annot_path, annotated)
        print(f"  Annotated image saved: {annot_path.name}")

    print(f"\n{'='*50}")
    print(f"All results saved to: {results_dir}")


if __name__ == "__main__":
    main()
