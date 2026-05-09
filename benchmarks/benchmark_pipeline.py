"""
Benchmark pipeline: Split dataset 80/20, enroll 80% into DB, test 20%.

Workflow:
  1. Load dataset from HuggingFace (or local data_faces/ folder)
  2. Split 80% train / 20% test per person (stratified)
  3. ENROLL: Embed all train images → save to SQLite database
  4. TEST:   Run recognition on test images → report accuracy

Usage:
    python benchmark_pipeline.py                    # from HuggingFace
    python benchmark_pipeline.py --local data_faces # from local folder
    python benchmark_pipeline.py --max-persons 20   # limit to 20 people (quick test)

Output:
    - data_benchmark/train/  (80% images)
    - data_benchmark/test/   (20% images)
    - benchmark_results.txt  (accuracy report)
"""
import os
import re
import sys
import time
import random
import cv2
import numpy as np
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import DB_PATH, RECOGNITION_COSINE_THRESHOLD
from app.database import init_db, create_employee, save_embedding, load_embeddings
from app.face_detector import FaceDetector
from app.face_embedder import FaceEmbedder
from app.matcher import match_embedding, embedding_cache


# ═══════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════

SPLIT_RATIO = 0.8  # 80% train, 20% test
RANDOM_SEED = 42
BENCHMARK_DIR = PROJECT_ROOT / "data_benchmark"
TRAIN_DIR = BENCHMARK_DIR / "train"
TEST_DIR = BENCHMARK_DIR / "test"


def sanitize_name(name: str) -> str:
    """Convert label to safe folder/code name."""
    safe = re.sub(r'[\\/:*?"<>|]', '_', name.strip())
    safe = re.sub(r'_+', '_', safe).strip('_')
    return safe if safe else "unknown"


def imread_unicode(filepath) -> np.ndarray:
    """Read image from path with Unicode characters (Vietnamese, etc.).
    cv2.imread() uses C++ fopen which fails on non-ASCII paths on Windows.
    Workaround: read raw bytes with numpy, then decode with OpenCV.
    """
    data = np.fromfile(str(filepath), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return img


# ═══════════════════════════════════════════════════════════
#  Step 1: Load & Split dataset
# ═══════════════════════════════════════════════════════════

def load_from_huggingface(max_persons=None):
    """Load dataset from HuggingFace and return {label: [PIL images]}."""
    from datasets import load_dataset

    print("Loading dataset from HuggingFace...")
    dataset = load_dataset("fptudsc/face-celeb-vietnamese")
    train = dataset["train"]

    persons = defaultdict(list)
    for sample in train:
        persons[sample["label"]].append(sample["image"])

    if max_persons:
        # Keep top N persons by image count
        sorted_persons = sorted(persons.items(), key=lambda x: -len(x[1]))
        persons = dict(sorted_persons[:max_persons])

    print(f"Loaded {sum(len(v) for v in persons.values())} images, {len(persons)} persons")
    return persons


def load_from_local(local_dir: str, max_persons=None):
    """Load from local data_faces/ folder. Returns {label: [PIL images]}."""
    from PIL import Image

    local_path = Path(local_dir)
    if not local_path.exists():
        raise FileNotFoundError(f"Folder not found: {local_dir}")

    persons = {}
    for person_dir in sorted(local_path.iterdir()):
        if not person_dir.is_dir():
            continue
        images = []
        for img_file in sorted(person_dir.glob("*.jpg")):
            try:
                images.append(Image.open(img_file))
            except Exception:
                pass
        if images:
            persons[person_dir.name] = images

    if max_persons:
        sorted_persons = sorted(persons.items(), key=lambda x: -len(x[1]))
        persons = dict(sorted_persons[:max_persons])

    print(f"Loaded {sum(len(v) for v in persons.values())} images, {len(persons)} persons from {local_dir}")
    return persons


def split_and_save(persons: dict):
    """Split 80/20 per person and save to disk."""
    random.seed(RANDOM_SEED)

    # Clean output dirs
    for d in [TRAIN_DIR, TEST_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    train_count = 0
    test_count = 0
    skipped = 0

    for label, images in persons.items():
        safe_name = sanitize_name(label)

        # Need at least 2 images to split
        if len(images) < 2:
            skipped += 1
            continue

        # Shuffle and split
        indices = list(range(len(images)))
        random.shuffle(indices)
        split_idx = max(1, int(len(indices) * SPLIT_RATIO))

        train_indices = indices[:split_idx]
        test_indices = indices[split_idx:]

        # Ensure at least 1 test image
        if not test_indices:
            test_indices = [train_indices.pop()]

        # Save train images
        person_train = TRAIN_DIR / safe_name
        person_train.mkdir(exist_ok=True)
        for i, idx in enumerate(train_indices):
            img = images[idx]
            img.save(str(person_train / f"{i+1:04d}.jpg"))
            train_count += 1

        # Save test images
        person_test = TEST_DIR / safe_name
        person_test.mkdir(exist_ok=True)
        for i, idx in enumerate(test_indices):
            img = images[idx]
            img.save(str(person_test / f"{i+1:04d}.jpg"))
            test_count += 1

    print(f"\nSplit complete:")
    print(f"  Train: {train_count} images in {TRAIN_DIR}")
    print(f"  Test:  {test_count} images in {TEST_DIR}")
    print(f"  Skipped: {skipped} persons (< 2 images)")
    return train_count, test_count


# ═══════════════════════════════════════════════════════════
#  Step 2: Enroll train images into DB
# ═══════════════════════════════════════════════════════════

def enroll_train_images(detector: FaceDetector, embedder: FaceEmbedder):
    """Detect face + embed all train images → save to SQLite."""
    print("\n" + "=" * 60)
    print("ENROLLING train images into database...")
    print("=" * 60)

    enrolled = 0
    no_face = 0
    errors = 0

    person_dirs = sorted(TRAIN_DIR.iterdir())
    total_persons = len([d for d in person_dirs if d.is_dir()])

    for pi, person_dir in enumerate(person_dirs):
        if not person_dir.is_dir():
            continue

        person_name = person_dir.name
        employee_code = f"CELEB_{person_name[:20]}"

        # Create employee in DB
        try:
            employee_id = create_employee(employee_code, person_name, "Celebrity")
        except Exception as e:
            print(f"  ERROR creating employee {person_name}: {e}")
            errors += 1
            continue

        person_enrolled = 0
        for img_file in sorted(person_dir.glob("*.jpg")):
            try:
                frame = imread_unicode(img_file)
                if frame is None:
                    continue

                # Detect face
                detections = detector.detect_all(frame)
                if detections is None:
                    no_face += 1
                    continue

                # Use largest face
                areas = detections[:, 2] * detections[:, 3]
                idx = np.argmax(areas)
                det = detections[idx]

                # Get embedding
                embedding = embedder.get_embedding(frame, det)
                save_embedding(employee_id, embedding, str(img_file))
                enrolled += 1
                person_enrolled += 1

            except Exception as e:
                errors += 1

        if (pi + 1) % 10 == 0 or (pi + 1) == total_persons:
            print(f"  [{pi+1}/{total_persons}] {person_name}: {person_enrolled} embeddings")

    # Invalidate cache so test uses fresh data
    embedding_cache.invalidate()

    print(f"\nEnrollment done:")
    print(f"  Enrolled: {enrolled} embeddings")
    print(f"  No face detected: {no_face}")
    print(f"  Errors: {errors}")
    return enrolled


# ═══════════════════════════════════════════════════════════
#  Step 3: Test recognition on test images
# ═══════════════════════════════════════════════════════════

def test_recognition(detector: FaceDetector, embedder: FaceEmbedder):
    """Run recognition on all test images and report accuracy."""
    print("\n" + "=" * 60)
    print("TESTING recognition on test images...")
    print("=" * 60)

    correct = 0
    wrong = 0
    not_found = 0
    no_face = 0
    total = 0

    # Confusion details
    wrong_details = []
    confidences_correct = []
    confidences_wrong = []

    person_dirs = sorted(TEST_DIR.iterdir())
    total_persons = len([d for d in person_dirs if d.is_dir()])

    for pi, person_dir in enumerate(person_dirs):
        if not person_dir.is_dir():
            continue

        true_name = person_dir.name
        true_code = f"CELEB_{true_name[:20]}"

        person_correct = 0
        person_total = 0

        for img_file in sorted(person_dir.glob("*.jpg")):
            try:
                frame = imread_unicode(img_file)
                if frame is None:
                    continue

                total += 1
                person_total += 1

                # Detect face
                detections = detector.detect_all(frame)
                if detections is None:
                    no_face += 1
                    continue

                areas = detections[:, 2] * detections[:, 3]
                idx = np.argmax(areas)
                det = detections[idx]

                # Get embedding and match
                embedding = embedder.get_embedding(frame, det)
                result = match_embedding(embedding)

                if result is None:
                    not_found += 1
                elif result["employee_code"] == true_code:
                    correct += 1
                    person_correct += 1
                    confidences_correct.append(result["confidence"])
                else:
                    wrong += 1
                    confidences_wrong.append(result["confidence"])
                    wrong_details.append({
                        "true": true_name,
                        "predicted": result["full_name"],
                        "confidence": result["confidence"],
                        "file": img_file.name,
                    })

            except Exception:
                pass

        if (pi + 1) % 10 == 0 or (pi + 1) == total_persons:
            acc = person_correct / person_total * 100 if person_total > 0 else 0
            print(f"  [{pi+1}/{total_persons}] {true_name}: {person_correct}/{person_total} ({acc:.0f}%)")

    # ── Report ──
    tested = correct + wrong + not_found
    accuracy = correct / tested * 100 if tested > 0 else 0

    report = []
    report.append("=" * 60)
    report.append("BENCHMARK RESULTS")
    report.append("=" * 60)
    report.append(f"Date:        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"Threshold:   {RECOGNITION_COSINE_THRESHOLD}")
    report.append(f"Total test:  {total}")
    report.append(f"No face:     {no_face}")
    report.append(f"Tested:      {tested}")
    report.append(f"")
    report.append(f"  Correct:     {correct} ({correct/tested*100:.1f}%)" if tested else "  Correct: 0")
    report.append(f"  Wrong:       {wrong} ({wrong/tested*100:.1f}%)" if tested else "  Wrong: 0")
    report.append(f"  Not found:   {not_found} ({not_found/tested*100:.1f}%)" if tested else "  Not found: 0")
    report.append(f"")
    report.append(f"ACCURACY:    {accuracy:.2f}%")
    report.append(f"")

    if confidences_correct:
        report.append(f"Confidence (correct): mean={np.mean(confidences_correct):.4f}, "
                      f"min={np.min(confidences_correct):.4f}, max={np.max(confidences_correct):.4f}")
    if confidences_wrong:
        report.append(f"Confidence (wrong):   mean={np.mean(confidences_wrong):.4f}, "
                      f"min={np.min(confidences_wrong):.4f}, max={np.max(confidences_wrong):.4f}")

    if wrong_details:
        report.append(f"\nTop 10 mismatches:")
        for d in wrong_details[:10]:
            report.append(f"  {d['true']} -> {d['predicted']} (conf={d['confidence']:.4f})")

    report.append("=" * 60)

    report_text = "\n".join(report)
    print(f"\n{report_text}")

    # Save report
    report_path = PROJECT_ROOT / "benchmark_results.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\nReport saved to: {report_path}")

    return accuracy


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Benchmark face recognition pipeline")
    parser.add_argument("--local", type=str, default=None,
                        help="Path to local data_faces/ folder (skip HuggingFace download)")
    parser.add_argument("--max-persons", type=int, default=None,
                        help="Limit number of persons (for quick testing)")
    parser.add_argument("--skip-split", action="store_true",
                        help="Skip download/split, use existing data_benchmark/")
    parser.add_argument("--skip-enroll", action="store_true",
                        help="Skip enrollment, use existing DB")
    args = parser.parse_args()

    # ── Step 1: Load & Split ──
    if not args.skip_split:
        if args.local:
            persons = load_from_local(args.local, args.max_persons)
        else:
            persons = load_from_huggingface(args.max_persons)
        split_and_save(persons)
    else:
        print("Skipping split, using existing data_benchmark/")

    # ── Step 2: Enroll ──
    # Use a separate DB for benchmark to not pollute production
    import app.config as cfg
    original_db = cfg.DB_PATH
    cfg.DB_PATH = PROJECT_ROOT / "benchmark.db"

    # Remove old benchmark DB for clean run
    if not args.skip_enroll:
        if cfg.DB_PATH.exists():
            os.remove(cfg.DB_PATH)

    init_db()
    detector = FaceDetector()
    embedder = FaceEmbedder()

    if not args.skip_enroll:
        t0 = time.time()
        enroll_train_images(detector, embedder)
        print(f"Enrollment time: {time.time()-t0:.1f}s")

    # ── Step 3: Test ──
    t0 = time.time()
    accuracy = test_recognition(detector, embedder)
    print(f"Test time: {time.time()-t0:.1f}s")

    # Restore original DB path
    cfg.DB_PATH = original_db


if __name__ == "__main__":
    main()
