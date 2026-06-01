"""
Face embedding matcher – vectorized cosine similarity search.

Optimization for Raspberry Pi 4 (4GB RAM):
  - EmbeddingCache: loads embeddings from DB once, keeps in RAM as NumPy matrix.
  - Vectorized matching: single np.dot() call instead of Python loop.
  - SFace outputs L2-normalized vectors, so cosine_sim = dot product directly.

For < 1000 employees, this runs in < 0.5 ms on Pi 4.
If scaling beyond 5000, consider FAISS or Annoy for ANN search.
"""
import numpy as np
import time
from typing import List, Dict, Any, Optional

from . import config
from .database import load_embeddings


class EmbeddingCache:
    """
    In-memory cache for face embeddings.

    Loads all embeddings from SQLite once and stores them as a pre-built
    NumPy matrix (N, D) for vectorized matching (D=128 for SFace, 512 for FaceLiVT).
    Call invalidate()
    after enrolling a new employee to force a reload on next match.
    """

    def __init__(self):
        self._rows: List[Dict[str, Any]] = []
        self._matrix: Optional[np.ndarray] = None   # shape (N, D)
        self._dirty: bool = True                      # needs reload
        self._last_load: float = 0.0

    # ── public API ────────────────────────────────────────

    def invalidate(self):
        """Mark cache as stale – will reload from DB on next get()."""
        self._dirty = True

    def get(self):
        """Return (rows, matrix).  Reloads from DB only if dirty."""
        if self._dirty:
            self._reload()
        return self._rows, self._matrix

    # ── internal ──────────────────────────────────────────

    def _reload(self):
        self._rows = load_embeddings()
        if self._rows:
            # Stack all (1, D) arrays into (N, D) matrix
            self._matrix = np.vstack(
                [r["embedding"].reshape(1, -1) for r in self._rows]
            ).astype(np.float32)
            # Pre-normalize rows (SFace should already be L2-normed, but guard)
            norms = np.linalg.norm(self._matrix, axis=1, keepdims=True)
            norms[norms < 1e-8] = 1.0
            self._matrix = self._matrix / norms
        else:
            self._matrix = None
        self._dirty = False
        self._last_load = time.time()


# ── Module-level singleton ────────────────────────────────
embedding_cache = EmbeddingCache()


def match_embedding(
    query_embedding: np.ndarray,
    threshold: float = None,
) -> Optional[Dict[str, Any]]:
    """
    Find the best matching face embedding using vectorized cosine similarity.

    Args:
        query_embedding: numpy array shape (1, D) from FaceEmbedder (D=128 or 512).
        threshold: Minimum cosine similarity to consider a match.

    Returns:
        Best matching dict with added 'confidence' key, or None.
    """
    if threshold is None:
        threshold = config.RECOGNITION_COSINE_THRESHOLD

    rows, matrix = embedding_cache.get()

    if matrix is None or len(rows) == 0:
        return None

    # Flatten & normalize query
    query = query_embedding.flatten().astype(np.float32)
    q_norm = np.linalg.norm(query)
    if q_norm < 1e-8:
        return None
    query = query / q_norm

    # ── Kiểm tra dimension ──
    # Nếu DB chứa embedding cũ (128-dim) mà model mới là 512-dim → không match được
    if matrix.shape[1] != query.shape[0]:
        print(f"[Matcher] WARNING: Dimension mismatch! "
              f"DB embeddings={matrix.shape[1]}-dim, query={query.shape[0]}-dim. "
              f"Cần xóa DB cũ và enroll lại với model mới.")
        return None

    # ── Vectorized cosine similarity in one shot ──
    # matrix is (N, D), query is (D,) → scores is (N,)
    scores = matrix @ query

    # ── Thuật toán KNN Top-5 (K-Nearest Neighbors) ──
    K = 5
    K = min(K, len(scores))
    # Lấy ra K index có điểm cao nhất (sắp xếp giảm dần)
    top_k_indices = np.argsort(scores)[-K:][::-1]

    votes = {}
    best_individual_score = {}
    best_row = {}

    for idx in top_k_indices:
        score = float(scores[idx])
        # Bỏ qua các vector không đạt ngưỡng tối thiểu
        if score < threshold:
            continue
            
        code = rows[idx]["employee_code"]
        
        # Trọng số mũ để ưu tiên láng giềng cực gần
        weight = np.exp(score * 5.0)
        
        if code not in votes:
            votes[code] = 0.0
            best_individual_score[code] = score
            best_row[code] = rows[idx]
            
        votes[code] += weight
        # Cập nhật điểm cao nhất nếu người này có nhiều vector trong Top K
        if score > best_individual_score[code]:
            best_individual_score[code] = score

    # Nếu không có ai qua được threshold
    if not votes:
        return None

    # Tìm người có tổng trọng số phiếu (votes) lớn nhất. 
    # Nếu bằng Vote (ví dụ A: 2.1 vote, B: 2.1 vote), ai có điểm số cá nhân cao hơn sẽ thắng
    best_code = max(votes.keys(), key=lambda c: (votes[c], best_individual_score[c]))

    result = dict(best_row[best_code])
    result["confidence"] = best_individual_score[best_code]  # Điểm cao nhất của người chiến thắng
    result["knn_votes"] = votes[best_code]                   # Lưu lại số vote để theo dõi
    
    return result