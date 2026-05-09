import os
import cv2
import sys
import numpy as np
from pathlib import Path

# Đảm bảo đường dẫn thư mục gốc được nhận diện (lùi lại 1 cấp từ thư mục scripts)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import init_db, create_employee, save_embedding
from app.face_detector import FaceDetector
from app.face_embedder import FaceEmbedder

def slugify(text: str) -> str:
    """Tạo employee_code đơn giản từ tên thư mục."""
    import unicodedata
    import re
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    return re.sub(r'[-\s]+', '_', text)

def main():
    data_dir = PROJECT_ROOT / "data_faces"
    if not data_dir.exists():
        print(f"Lỗi: Thư mục {data_dir} không tồn tại!")
        return

    print("Khởi tạo Database và nạp Model AI...")
    init_db()
    detector = FaceDetector()
    embedder = FaceEmbedder()

    total_persons = 0
    total_faces_saved = 0

    # Duyệt qua các thư mục con trong data_faces
    for person_folder in data_dir.iterdir():
        if not person_folder.is_dir():
            continue
            
        full_name = person_folder.name
        # Dùng tên thư mục tạo mã nhân viên (Vd: "ca sĩ Chi Pu" -> "ca_si_chi_pu")
        employee_code = slugify(full_name) 
        
        # Nếu thư mục có ký tự lạ không sinh được mã, dùng tên thư mục làm mã luôn
        if not employee_code:
            employee_code = full_name.replace(" ", "_")
            
        # Tạo nhân viên trong Database
        emp_id = create_employee(employee_code=employee_code, full_name=full_name, department="Celebrity")
        
        print(f"\n[{total_persons + 1}] Đang xử lý: {full_name} (Mã: {employee_code})")
        
        faces_for_person = 0
        # Đọc tất cả ảnh trong thư mục của người đó
        for img_path in person_folder.iterdir():
            if img_path.is_file() and img_path.suffix.lower() in ['.jpg', '.jpeg', '.png']:
                # Sửa lỗi OpenCV không đọc được đường dẫn tiếng Việt trên Windows
                img_array = np.fromfile(str(img_path), np.uint8)
                img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                
                if img is None:
                    print(f"  - Lỗi đọc file: {img_path.name}")
                    continue
                
                # Phát hiện khuôn mặt (lấy khuôn mặt to nhất)
                box, raw_detection = detector.detect_largest_with_raw(img)
                
                if raw_detection is not None:
                    # Trích xuất 512-dim vector bằng FaceLiVT
                    embedding = embedder.get_embedding(img, raw_detection)
                    
                    # Lưu vào Database
                    save_embedding(employee_id=emp_id, embedding=embedding, image_path=str(img_path))
                    faces_for_person += 1
                    total_faces_saved += 1
                    print(f"  + Trích xuất thành công: {img_path.name}")
                else:
                    print(f"  - Không tìm thấy khuôn mặt nào trong ảnh: {img_path.name}")
                    
        total_persons += 1
        print(f"  => Đã lưu {faces_for_person} ảnh cho {full_name}.")

    print("\n" + "="*50)
    print(f"HOÀN THÀNH!")
    print(f"Đã xử lý {total_persons} người.")
    print(f"Đã trích xuất và lưu tổng cộng {total_faces_saved} khuôn mặt vào Database.")
    print("="*50)

if __name__ == "__main__":
    main()
