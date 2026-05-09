#!/bin/bash
echo "==================================================="
echo " Edge Attendance - Cài đặt cho Raspberry Pi 4 (64-bit)"
echo "==================================================="

# 1. Cập nhật hệ thống
echo "[1/6] Cập nhật thư viện hệ thống..."
sudo apt-get update

# 2. Cài đặt OpenCV và PyQt5 bằng APT (QUAN TRỌNG NHẤT)
# Các gói này đã được biên dịch sẵn cho chip ARM của Pi, tránh lỗi "Illegal instruction"
echo "[2/6] Cài đặt OpenCV, PyQt5 và thư viện đồ họa..."
sudo apt-get install -y python3-opencv python3-numpy
sudo apt-get install -y python3-pyqt5 python3-pyqt5.qtmultimedia
sudo apt-get install -y libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev
sudo apt-get install -y libxcb-xinerama0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 qtwayland5
sudo apt-get install -y python3-venv python3-dev build-essential

# 3. Cài đặt ONNX Runtime phiên bản dành riêng cho ARM64
echo "[3/6] Cài đặt ONNX Runtime cho ARM64..."
# Thử cài từ piwheels (kho thư viện chuyên cho Raspberry Pi)
sudo apt-get install -y libatomic1
pip3 install --break-system-packages onnxruntime==1.17.1 || pip3 install --break-system-packages onnxruntime

# 4. Tạo môi trường ảo (kế thừa thư viện hệ thống)
echo "[4/6] Tạo môi trường ảo Python..."
# --system-site-packages cho phép dùng OpenCV/numpy/PyQt5 đã cài từ apt
python3 -m venv --system-site-packages venv_pi

# 5. Kích hoạt và cài đặt các thư viện còn lại
echo "[5/6] Cài đặt các thư viện Python..."
source venv_pi/bin/activate
pip install --upgrade pip

# Cài các thư viện nhẹ (FastAPI, bcrypt...) - KHÔNG cài opencv/numpy/onnxruntime ở đây
pip install fastapi>=0.100.0 uvicorn>=0.23.0 jinja2>=3.1 python-multipart>=0.0.6
pip install pydantic>=2.0 bcrypt>=4.0 itsdangerous>=2.1 scikit-image>=0.21.0

# 6. Kiểm tra xem mọi thứ đã hoạt động chưa
echo "[6/6] Kiểm tra thư viện..."
python3 -c "import cv2; print(f'  OpenCV: {cv2.__version__} - OK')"
python3 -c "import numpy as np; print(f'  NumPy: {np.__version__} - OK')"
python3 -c "import onnxruntime as ort; print(f'  ONNXRuntime: {ort.__version__} - OK')"

echo "==================================================="
echo "✅ HOÀN TẤT CÀI ĐẶT THÀNH CÔNG!"
echo "==================================================="
echo ""
echo "HƯỚNG DẪN CHẠY:"
echo "  source venv_pi/bin/activate"
echo ""
echo "  # Bản OpenCV (không cần PyQt5, chạy ổn định nhất):"
echo "  python3 run_cv2.py --source usb --camera 0"
echo "  python3 run_cv2.py --source picam"
echo ""
echo "  # Bản PyQt5 (nếu muốn thử):"
echo "  python3 run.py --source usb --camera 0"
echo ""
echo "  # Web Admin:"
echo "  uvicorn app.web_api:api --host 0.0.0.0 --port 8000"
echo "==================================================="
