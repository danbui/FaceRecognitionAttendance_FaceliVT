"""
Download Vietnamese Celebrity Face dataset from HuggingFace.
Source: https://huggingface.co/datasets/fptudsc/face-celeb-vietnamese

Saves ~8,500 images organized by person name:
  data_faces/
    ├── Son_Tung_MTP/
    │   ├── 0001.jpg
    │   └── ...
    ├── My_Tam/
    └── ...

Usage:
    pip install datasets
    python download_faces.py
"""
import os
import re
from datasets import load_dataset
from collections import Counter


def sanitize_folder_name(name: str) -> str:
    """Convert Vietnamese label to safe folder name."""
    # Replace spaces and special chars with underscores
    safe = re.sub(r'[\\/:*?"<>|]', '_', name.strip())
    # Collapse multiple underscores
    safe = re.sub(r'_+', '_', safe).strip('_')
    return safe if safe else "unknown"


def main():
    save_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data_faces"
    )
    os.makedirs(save_dir, exist_ok=True)

    print("Loading dataset from HuggingFace (first time may take a while)...")
    dataset = load_dataset("fptudsc/face-celeb-vietnamese")
    train = dataset["train"]

    print(f"Total samples: {len(train)}")

    # Count per-person for progress tracking
    labels = [s["label"] for s in train]
    label_counts = Counter(labels)
    print(f"Total persons: {len(label_counts)}")
    print()

    # Track per-person image index
    person_idx = Counter()
    saved = 0
    errors = 0

    for i, sample in enumerate(train):
        label = sample["label"]
        img = sample["image"]

        folder_name = sanitize_folder_name(label)
        person_dir = os.path.join(save_dir, folder_name)
        os.makedirs(person_dir, exist_ok=True)

        person_idx[folder_name] += 1
        idx = person_idx[folder_name]
        filename = f"{idx:04d}.jpg"

        try:
            img.save(os.path.join(person_dir, filename))
            saved += 1
        except Exception as e:
            errors += 1
            print(f"  ERROR saving {folder_name}/{filename}: {e}")

        # Progress every 500 images
        if (i + 1) % 500 == 0:
            print(f"  [{i+1}/{len(train)}] saved {saved} images...")

    print(f"\nDone! Saved {saved} images, {errors} errors.")
    print(f"Output: {save_dir}")
    print(f"Persons: {len(person_idx)}")

    # Print top 10 persons by count
    print("\nTop 10 persons by image count:")
    for name, count in label_counts.most_common(10):
        print(f"  {name}: {count} images")


if __name__ == "__main__":
    main()
