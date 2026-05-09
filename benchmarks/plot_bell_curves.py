import sys
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.matcher import embedding_cache
from app.database import init_db
import app.config as cfg

def main():
    print("Khởi tạo Database và đọc bộ nhớ đệm (cache)...")
    init_db()
    
    embedding_cache.invalidate()
    rows, embeddings_matrix = embedding_cache.get()

    if embeddings_matrix is None or len(rows) < 2:
        print("Không đủ dữ liệu trong database để thống kê (cần ít nhất 2 khuôn mặt).")
        return

    num_faces = len(rows)
    print(f"Đã load thành công {num_faces} embeddings từ database.")

    labels = [row["employee_code"] for row in rows]
    print("Đang tính toán ma trận Cosine Similarity...")
    
    sim_matrix = np.dot(embeddings_matrix, embeddings_matrix.T)
    
    same_person_scores = []
    diff_person_scores = []

    for i in range(num_faces):
        for j in range(i + 1, num_faces):
            score = sim_matrix[i, j]
            if labels[i] == labels[j]:
                same_person_scores.append(score)
            else:
                diff_person_scores.append(score)

    # Nếu không có đủ dữ liệu cùng người thì bỏ qua
    if not same_person_scores or not diff_person_scores:
        print("Lỗi: Phải có cả dữ liệu 'Cùng người' và 'Khác người' để vẽ biểu đồ!")
        print(f"Số cặp cùng người: {len(same_person_scores)}")
        print(f"Số cặp khác người: {len(diff_person_scores)}")
        return

    print("Đang vẽ biểu đồ phân bố (Bell Curves)...")
    
    # Thiết lập matplotlib
    plt.figure(figsize=(10, 6))
    
    # Dùng numpy để tính histogram và chuyển thành dạng line (hoặc dùng KDE nếu có scipy, nhưng plot hist là an toàn nhất)
    # Khác người (Impostor)
    weights_diff = np.ones_like(diff_person_scores) / len(diff_person_scores)
    plt.hist(diff_person_scores, bins=50, alpha=0.6, color='red', weights=weights_diff, label=f'Khác người (Impostor) - {len(diff_person_scores)} cặp')
    
    # Cùng người (Genuine)
    weights_same = np.ones_like(same_person_scores) / len(same_person_scores)
    plt.hist(same_person_scores, bins=30, alpha=0.6, color='green', weights=weights_same, label=f'Cùng người (Genuine) - {len(same_person_scores)} cặp')

    # Vẽ đường trung bình
    mean_diff = np.mean(diff_person_scores)
    mean_same = np.mean(same_person_scores)
    plt.axvline(mean_diff, color='darkred', linestyle='dashed', linewidth=2)
    plt.axvline(mean_same, color='darkgreen', linestyle='dashed', linewidth=2)

    # Đánh dấu Threshold tiêu chuẩn hiện tại
    current_threshold = cfg.RECOGNITION_COSINE_THRESHOLD
    plt.axvline(current_threshold, color='blue', linestyle='dotted', linewidth=2, label=f'Current Threshold ({current_threshold})')

    # Tìm giao điểm gần đúng (EER point approximation)
    p1_same = np.percentile(same_person_scores, 1)
    p99_diff = np.percentile(diff_person_scores, 99)
    suggested = (p99_diff + p1_same) / 2
    if p99_diff < p1_same:
        plt.axvline(suggested, color='purple', linestyle='solid', linewidth=3, label=f'Gợi ý ngưỡng lý tưởng (~{suggested:.3f})')

    plt.title('Phân bố Cosine Similarity (Genuine vs Impostor)', fontsize=14, fontweight='bold')
    plt.xlabel('Cosine Similarity Score (Điểm càng cao càng giống nhau)', fontsize=12)
    plt.ylabel('Tần suất (Tỷ lệ %)', fontsize=12)
    plt.xlim(-1.0, 1.0) # Cosine dao động từ -1 đến 1
    plt.legend(loc='upper right', fontsize=10)
    plt.grid(True, linestyle='--', alpha=0.5)

    # Lưu và hiển thị
    output_path = PROJECT_ROOT / "similarity_distribution_plot.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"Đã lưu biểu đồ thành công tại: {output_path}")
    
    try:
        plt.show()
    except Exception as e:
        print("Môi trường không hỗ trợ hiển thị cửa sổ đồ họa. Vui lòng mở file ảnh đã lưu để xem.")

if __name__ == "__main__":
    main()
