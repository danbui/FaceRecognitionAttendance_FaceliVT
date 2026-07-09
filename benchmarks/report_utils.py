"""Utilities for benchmark reporting and model/version metadata."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


def compute_model_sha256(model_path: Path) -> Optional[str]:
    if not model_path.exists():
        return None
    h = hashlib.sha256()
    with open(model_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get_git_commit(root: Path) -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out
    except Exception:
        return None


def classification_metrics(y_true: Sequence[str], y_pred: Sequence[str]) -> Dict[str, object]:
    labels = sorted(set(y_true) | set(y_pred))
    support = Counter(y_true)

    per_class: Dict[str, Dict[str, float]] = {}
    precisions, recalls, f1s = [], [], []
    weighted_prec, weighted_rec, weighted_f1 = 0.0, 0.0, 0.0
    total_support = sum(support.values())

    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)

        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support[label],
        }

        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)

        w = support[label]
        weighted_prec += precision * w
        weighted_rec += recall * w
        weighted_f1 += f1 * w

    macro = {
        "precision": float(np.mean(precisions)) if precisions else 0.0,
        "recall": float(np.mean(recalls)) if recalls else 0.0,
        "f1": float(np.mean(f1s)) if f1s else 0.0,
    }
    weighted = {
        "precision": weighted_prec / total_support if total_support else 0.0,
        "recall": weighted_rec / total_support if total_support else 0.0,
        "f1": weighted_f1 / total_support if total_support else 0.0,
    }

    return {
        "labels": labels,
        "per_class": per_class,
        "macro": macro,
        "weighted": weighted,
    }


def confusion_top_n(y_true: Sequence[str], y_pred: Sequence[str], top_n: int = 10) -> List[Dict[str, object]]:
    confusion = defaultdict(int)
    for t, p in zip(y_true, y_pred):
        if t != p:
            confusion[(t, p)] += 1

    ranked = sorted(confusion.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [{"true": t, "predicted": p, "count": c} for (t, p), c in ranked]


def write_confusion_csv(path: Path, confusion_rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["true", "predicted", "count"])
        writer.writeheader()
        writer.writerows(confusion_rows)


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_markdown(path: Path, summary: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = summary["run_info"]["timestamp"]
    metrics = summary["metrics"]
    macro = summary["classification"]["macro"]
    weighted = summary["classification"]["weighted"]

    lines = [
        "# Benchmark Report",
        "",
        f"- Timestamp: `{ts}`",
        f"- Git commit: `{summary['run_info'].get('git_commit')}`",
        f"- Threshold: `{summary['model'].get('threshold')}`",
        "",
        "## Core Metrics",
        f"- Accuracy (Top-1): **{metrics['accuracy_top1']:.4f}**",
        f"- Precision (macro): **{macro['precision']:.4f}**",
        f"- Recall (macro): **{macro['recall']:.4f}**",
        f"- F1 (macro): **{macro['f1']:.4f}**",
        f"- Precision (weighted): **{weighted['precision']:.4f}**",
        f"- Recall (weighted): **{weighted['recall']:.4f}**",
        f"- F1 (weighted): **{weighted['f1']:.4f}**",
        "",
        "## Top Confusions",
    ]

    top_conf = summary.get("confusion_top_n", [])
    if not top_conf:
        lines.append("- No confusion pairs.")
    else:
        for row in top_conf:
            lines.append(f"- {row['true']} → {row['predicted']}: {row['count']}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def now_utc_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
