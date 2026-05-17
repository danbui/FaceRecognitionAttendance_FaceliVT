"""
So sánh output embedding giữa FP32 và INT8 trên cùng ảnh.

Hiển thị:
  - Vector embedding (first 50 dims)
  - Cosine similarity giữa FP32 vs INT8
  - L2 distance
  - Bar chart so sánh

Cách chạy:
  python benchmarks/compare_fp32_int8_output.py
  python benchmarks/compare_fp32_int8_output.py --dataset dataset_clean --num 10
"""
import sys, random, argparse
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.face_detector import FaceDetector
from app.config import FACELIVT_MODEL, MODELS_DIR

FACELIVT_INT8_MODEL = MODELS_DIR / "facelivtv2_s_512_int8.onnx"
IMG_EXTS = {".jpg", ".jpeg", ".png"}
SEED = 42

ARCFACE_DST = np.array([
    [38.2946, 51.6963], [73.5318, 51.5014],
    [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]
], dtype=np.float32)


def imread_u(path):
    buf = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)

def align_face(frame, det, size=112):
    try:
        lm = det[4:14].reshape((5, 2))
        dst = ARCFACE_DST * (float(size) / 112.0)
        M, _ = cv2.estimateAffinePartial2D(lm, dst)
        if M is None:
            M = cv2.getAffineTransform(lm[:3], dst[:3])
        return cv2.warpAffine(frame, M, (size, size), borderValue=0.0)
    except Exception:
        return None

def get_embedding(sess, inp_name, aligned):
    rgb = cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB)
    blob = (rgb.astype(np.float32) - 127.5) / 127.5
    blob = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]
    emb = sess.run(None, {inp_name: blob})[0].flatten()
    n = np.linalg.norm(emb)
    return emb / n if n > 1e-8 else emb


def main():
    parser = argparse.ArgumentParser(description="Compare FP32 vs INT8 embedding output")
    parser.add_argument("--dataset", type=str, default="dataset_clean")
    parser.add_argument("--num", type=int, default=10, help="Số ảnh so sánh")
    args = parser.parse_args()

    ds = Path(args.dataset)
    if not ds.is_absolute():
        ds = PROJECT_ROOT / ds
    out_dir = PROJECT_ROOT / "benchmarks"

    print("=" * 70)
    print("  🔬 SO SÁNH OUTPUT: FaceLiVT2_S FP32 vs INT8")
    print("=" * 70)

    # Init
    import onnxruntime as ort
    detector = FaceDetector()

    sess_fp32 = ort.InferenceSession(str(FACELIVT_MODEL), providers=['CPUExecutionProvider'])
    sess_int8 = ort.InferenceSession(str(FACELIVT_INT8_MODEL), providers=['CPUExecutionProvider'])
    inp_fp32 = sess_fp32.get_inputs()[0].name
    inp_int8 = sess_int8.get_inputs()[0].name
    dim = sess_fp32.run(None, {inp_fp32: np.random.randn(1,3,112,112).astype(np.float32)})[0].flatten().shape[0]

    print(f"  FP32: {FACELIVT_MODEL.name} ({dim}d)")
    print(f"  INT8: {FACELIVT_INT8_MODEL.name} ({dim}d)")

    # Collect images
    rng = random.Random(SEED)
    people = sorted([d for d in ds.iterdir() if d.is_dir()])
    rng.shuffle(people)

    samples = []
    for pdir in people:
        imgs = sorted(f for f in pdir.iterdir() if f.suffix.lower() in IMG_EXTS)
        if imgs:
            samples.append((pdir.name, imgs[0]))
        if len(samples) >= args.num:
            break

    print(f"  Số ảnh: {len(samples)}")

    # Compare
    cos_sims = []
    l2_dists = []
    max_diffs = []
    results = []

    print(f"\n  {'#':<3} {'Người':<30} │ {'Cosine':>8} │ {'L2 Dist':>8} │ {'Max Δ':>8}")
    print(f"  {'─'*3} {'─'*30}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*8}")

    for i, (name, path) in enumerate(samples):
        img = imread_u(path)
        if img is None:
            continue
        dets = detector.detect_all(img)
        if dets is None:
            continue
        det = dets[int(np.argmax(dets[:, 2] * dets[:, 3]))]
        aligned = align_face(img, det)
        if aligned is None:
            continue

        emb_fp32 = get_embedding(sess_fp32, inp_fp32, aligned)
        emb_int8 = get_embedding(sess_int8, inp_int8, aligned)

        cos = float(np.dot(emb_fp32, emb_int8))
        l2 = float(np.linalg.norm(emb_fp32 - emb_int8))
        max_d = float(np.max(np.abs(emb_fp32 - emb_int8)))

        cos_sims.append(cos)
        l2_dists.append(l2)
        max_diffs.append(max_d)
        results.append((name, emb_fp32, emb_int8, cos, l2))

        short_name = name[:28] + ".." if len(name) > 30 else name
        print(f"  {i+1:<3} {short_name:<30} │ {cos:>8.5f} │ {l2:>8.5f} │ {max_d:>8.5f}")

    # Summary
    print(f"\n{'='*70}")
    print(f"  📊 TỔNG KẾT")
    print(f"{'='*70}")
    print(f"  Cosine Similarity (FP32 vs INT8):")
    print(f"    Mean  : {np.mean(cos_sims):.6f}")
    print(f"    Min   : {np.min(cos_sims):.6f}")
    print(f"    Max   : {np.max(cos_sims):.6f}")
    print(f"    Std   : {np.std(cos_sims):.6f}")
    print(f"  L2 Distance:")
    print(f"    Mean  : {np.mean(l2_dists):.6f}")
    print(f"  Max element-wise Δ:")
    print(f"    Mean  : {np.mean(max_diffs):.6f}")

    mean_cos = np.mean(cos_sims)
    if mean_cos > 0.99:
        verdict = "✅ RẤT TỐT — embedding gần như giữ nguyên"
    elif mean_cos > 0.95:
        verdict = "✅ TỐT — sai số nhỏ, chấp nhận được"
    elif mean_cos > 0.90:
        verdict = "⚠️ TRUNG BÌNH — cần test kỹ threshold"
    else:
        verdict = "❌ THẤP — cần cải thiện calibration"
    print(f"\n  Đánh giá: {verdict}")
    print(f"{'='*70}")

    # Plot
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from datetime import datetime

        fig, axes = plt.subplots(2, 2, figsize=(14, 10))

        # 1. Bar chart: first sample embedding comparison (first 50 dims)
        ax = axes[0, 0]
        if results:
            name0, fp32_0, int8_0 = results[0][0], results[0][1], results[0][2]
            n_show = 50
            x = np.arange(n_show)
            ax.bar(x - 0.2, fp32_0[:n_show], 0.4, label='FP32', color='#2196F3', alpha=0.7)
            ax.bar(x + 0.2, int8_0[:n_show], 0.4, label='INT8', color='#FF5722', alpha=0.7)
            ax.set_title(f'Embedding Vector (first {n_show} dims)\n{name0[:40]}', fontweight='bold')
            ax.set_xlabel('Dimension index')
            ax.set_ylabel('Value')
            ax.legend()
            ax.grid(True, alpha=0.3, axis='y')

        # 2. Difference per dimension (first 100 dims)
        ax = axes[0, 1]
        if results:
            diff = fp32_0 - int8_0
            n_show2 = min(100, len(diff))
            colors_d = ['#4CAF50' if d >= 0 else '#F44336' for d in diff[:n_show2]]
            ax.bar(range(n_show2), diff[:n_show2], color=colors_d, alpha=0.7)
            ax.set_title(f'Difference (FP32 - INT8) per dim\nMean Δ = {np.mean(np.abs(diff)):.5f}', fontweight='bold')
            ax.set_xlabel('Dimension index')
            ax.set_ylabel('Δ Value')
            ax.axhline(0, color='black', linewidth=0.5)
            ax.grid(True, alpha=0.3, axis='y')

        # 3. Cosine similarity distribution
        ax = axes[1, 0]
        ax.bar(range(len(cos_sims)), cos_sims, color='#2196F3', alpha=0.8)
        ax.axhline(np.mean(cos_sims), color='red', linestyle='--', linewidth=2,
                   label=f'Mean = {np.mean(cos_sims):.5f}')
        ax.set_title('Cosine Similarity (FP32 vs INT8) per image', fontweight='bold')
        ax.set_xlabel('Image index')
        ax.set_ylabel('Cosine Similarity')
        ax.set_ylim(min(0.8, min(cos_sims) - 0.02), 1.01)
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')

        # 4. L2 distance distribution
        ax = axes[1, 1]
        ax.bar(range(len(l2_dists)), l2_dists, color='#FF9800', alpha=0.8)
        ax.axhline(np.mean(l2_dists), color='red', linestyle='--', linewidth=2,
                   label=f'Mean = {np.mean(l2_dists):.5f}')
        ax.set_title('L2 Distance (FP32 vs INT8) per image', fontweight='bold')
        ax.set_xlabel('Image index')
        ax.set_ylabel('L2 Distance')
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')

        plt.suptitle(f'FP32 vs INT8 Output Comparison — {len(results)} images\n'
                     f'Mean Cosine = {np.mean(cos_sims):.5f} | Mean L2 = {np.mean(l2_dists):.5f}',
                     fontsize=14, fontweight='bold')
        plt.tight_layout()

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        plot_path = out_dir / f"fp32_vs_int8_comparison_{ts}.png"
        plt.savefig(str(plot_path), dpi=150, bbox_inches='tight')
        print(f"\n  📊 Plot: {plot_path}")
    except ImportError:
        print("  ⚠️ matplotlib chưa cài, bỏ qua vẽ biểu đồ.")

    print(f"  ✅ Hoàn tất!")


if __name__ == "__main__":
    main()
