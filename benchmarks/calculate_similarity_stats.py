import sys
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.matcher import embedding_cache
from app.database import init_db
import app.config as cfg


def main():
    print("Khởi tạo Database và đọc bộ nhớ đệm (cache)...")
    # Đọc từ database mặc định (attendance.db)
    init_db()
    
    # Bắt buộc load lại cache từ database
    embedding_cache.invalidate()
    rows, embeddings_matrix = embedding_cache.get()

    if embeddings_matrix is None or len(rows) < 2:
        print("Không đủ dữ liệu trong database để thống kê (cần ít nhất 2 khuôn mặt).")
        return

    num_faces = len(rows)
    print(f"Đã load thành công {num_faces} embeddings từ database.")

    # Lấy nhãn (employee_code) từ rows
    labels = [row["employee_code"] for row in rows]

    # 2. Compute pairwise cosine similarities
    print("Đang tính toán ma trận Cosine Similarity...")
    
    # Cosine similarity matrix: (N, N)
    sim_matrix = np.dot(embeddings_matrix, embeddings_matrix.T)
    
    same_person_scores = []
    diff_person_scores = []

    # Iterate upper triangle to avoid duplicates and self-comparison
    for i in range(num_faces):
        for j in range(i + 1, num_faces):
            score = sim_matrix[i, j]
            if labels[i] == labels[j]:
                same_person_scores.append(score)
            else:
                diff_person_scores.append(score)

    # 3. Print Statistics
    print("\n" + "=" * 50)
    print("COSINE SIMILARITY STATISTICS (TỪ DATABASE)")
    print("=" * 50)
    
    if same_person_scores:
        same_person_scores = np.array(same_person_scores)
        print(f"\n[CÙNG MỘT NGƯỜI (Same Person)] - Số lượng cặp: {len(same_person_scores)}")
        print(f"  - Trung bình (Mean) : {np.mean(same_person_scores):.4f}")
        print(f"  - Độ lệch chuẩn (Std): {np.std(same_person_scores):.4f}")
        print(f"  - Nhỏ nhất (Min)    : {np.min(same_person_scores):.4f}")
        print(f"  - Lớn nhất (Max)    : {np.max(same_person_scores):.4f}")
        print(f"  - Percentile 1%     : {np.percentile(same_person_scores, 1):.4f} (99% cặp cùng người có điểm >= mức này)")
        print(f"  - Percentile 5%     : {np.percentile(same_person_scores, 5):.4f}")
    else:
        print("\n[CÙNG MỘT NGƯỜI (Same Person)] - Không có dữ liệu (không có ai có >= 2 ảnh trong DB).")

    if diff_person_scores:
        diff_person_scores = np.array(diff_person_scores)
        print(f"\n[KHÁC NGƯỜI (Different People)] - Số lượng cặp: {len(diff_person_scores)}")
        print(f"  - Trung bình (Mean) : {np.mean(diff_person_scores):.4f}")
        print(f"  - Độ lệch chuẩn (Std): {np.std(diff_person_scores):.4f}")
        print(f"  - Nhỏ nhất (Min)    : {np.min(diff_person_scores):.4f}")
        print(f"  - Lớn nhất (Max)    : {np.max(diff_person_scores):.4f}")
        print(f"  - Percentile 99%    : {np.percentile(diff_person_scores, 99):.4f} (99% cặp khác người có điểm <= mức này)")
        print(f"  - Percentile 95%    : {np.percentile(diff_person_scores, 95):.4f}")
    else:
        print("\n[KHÁC NGƯỜI (Different People)] - Không có dữ liệu.")

    print("=" * 50)
    
    # Gợi ý threshold
    if same_person_scores.size > 0 and diff_person_scores.size > 0:
        p1_same = np.percentile(same_person_scores, 1)
        p99_diff = np.percentile(diff_person_scores, 99)
        print(f"\nGợi ý khoảng Threshold tốt nhất:")
        if p99_diff < p1_same:
            print(f"Threshold lý tưởng nằm giữa: {p99_diff:.4f} và {p1_same:.4f}")
            suggested = (p99_diff + p1_same) / 2
            print(f"-> Gợi ý cấu hình RECOGNITION_COSINE_THRESHOLD: {suggested:.4f}")
        else:
            print(f"CẢNH BÁO: Có sự trùng lặp (Overlap) giữa hai phân bố!")
            print(f"  - 99% người khác nhau <= {p99_diff:.4f}")
            print(f"  - 99% người giống nhau >= {p1_same:.4f}")
            print("\nVới sự trùng lặp này:")
            print(f"  - Nếu set ngưỡng > {p99_diff:.4f}: Sẽ hiếm khi nhận diện nhầm người, nhưng dễ từ chối người thật (False Negative).")
            print(f"  - Nếu set ngưỡng < {p1_same:.4f}: Dễ dàng nhận ra người thật, nhưng nguy cơ nhận nhầm người khác (False Positive) tăng cao.")

if __name__ == "__main__":
    main()
