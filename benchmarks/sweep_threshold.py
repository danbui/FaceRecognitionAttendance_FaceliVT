"""
Sweep thresholds to find optimal value.
Reuses existing benchmark.db (skip enroll), only runs test phase.
"""
import sys
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
from app.face_detector import FaceDetector
from app.face_embedder import FaceEmbedder
from app.matcher import embedding_cache
from app.database import init_db
import app.config as cfg

TEST_DIR = PROJECT_ROOT / "benchmarks" / "data_benchmark" / "test"
THRESHOLDS = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]

def slugify(text: str) -> str:
    """Tạo employee_code đơn giản từ tên thư mục, đồng nhất với enroll."""
    import unicodedata
    import re
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    code = re.sub(r'[-\s]+', '_', text)
    if not code:
        code = text.replace(" ", "_")
    return code

def imread_unicode(filepath):
    data = np.fromfile(str(filepath), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def run_test_at_threshold(detector, embedder, threshold):
    """Test all images at a given threshold, return stats."""
    rows, matrix = embedding_cache.get()
    if matrix is None:
        return None

    correct = wrong = not_found = no_face = 0

    for person_dir in sorted(TEST_DIR.iterdir()):
        if not person_dir.is_dir():
            continue

        true_code = slugify(person_dir.name)

        for img_file in sorted(person_dir.glob("*.jpg")):
            frame = imread_unicode(img_file)
            if frame is None:
                continue

            detections = detector.detect_all(frame)
            if detections is None:
                no_face += 1
                continue

            areas = detections[:, 2] * detections[:, 3]
            det = detections[int(np.argmax(areas))]
            embedding = embedder.get_embedding(frame, det)

            # Manual threshold match
            query = embedding.flatten().astype(np.float32)
            q_norm = np.linalg.norm(query)
            if q_norm < 1e-8:
                not_found += 1
                continue
            query = query / q_norm

            scores = matrix @ query
            
            # KNN Top-5
            K = min(5, len(scores))
            top_k_indices = np.argsort(scores)[-K:][::-1]
            
            votes = {}
            best_ind_score = {}
            for idx in top_k_indices:
                score = float(scores[idx])
                if score < threshold:
                    continue
                c = rows[idx]["employee_code"]
                votes[c] = votes.get(c, 0) + 1
                if c not in best_ind_score or score > best_ind_score[c]:
                    best_ind_score[c] = score
                    
            if not votes:
                not_found += 1
            else:
                best_code = max(votes.keys(), key=lambda c: (votes[c], best_ind_score[c]))
                if best_code == true_code:
                    correct += 1
                else:
                    wrong += 1

    tested = correct + wrong + not_found
    return {
        "threshold": threshold,
        "tested": tested,
        "correct": correct,
        "wrong": wrong,
        "not_found": not_found,
        "no_face": no_face,
        "accuracy": correct / tested * 100 if tested else 0,
        "wrong_pct": wrong / tested * 100 if tested else 0,
        "not_found_pct": not_found / tested * 100 if tested else 0,
    }


def main():
    # Use the default attendance.db since we just enrolled into it
    init_db()

    detector = FaceDetector()
    embedder = FaceEmbedder()

    # Force cache load once
    embedding_cache.invalidate()
    embedding_cache.get()

    print(f"{'Threshold':>10} | {'Accuracy':>8} | {'Wrong':>8} | {'Not Found':>10} | {'Correct':>7} | {'Wrong#':>6} | {'NF#':>5}")
    print("-" * 75)

    results = []
    for t in THRESHOLDS:
        r = run_test_at_threshold(detector, embedder, t)
        if r is None:
            print("No embeddings in DB!")
            return
        results.append(r)
        print(f"{t:>10.3f} | {r['accuracy']:>7.2f}% | {r['wrong_pct']:>7.2f}% | {r['not_found_pct']:>9.2f}% | {r['correct']:>7} | {r['wrong']:>6} | {r['not_found']:>5}")

    # Find best accuracy
    best = max(results, key=lambda x: x["accuracy"])
    print(f"\nBest threshold: {best['threshold']} -> Accuracy {best['accuracy']:.2f}%, Wrong {best['wrong_pct']:.2f}%")

    # Find best balance (accuracy - wrong_pct)
    balanced = max(results, key=lambda x: x["accuracy"] - x["wrong_pct"])
    print(f"Best balanced:  {balanced['threshold']} -> Accuracy {balanced['accuracy']:.2f}%, Wrong {balanced['wrong_pct']:.2f}%")


if __name__ == "__main__":
    main()
