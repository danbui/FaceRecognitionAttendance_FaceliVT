#!/bin/bash
echo "==================================================="
echo " Edge Attendance - Cài đặt cho Raspberry Pi 4 (64-bit)"
echo "==================================================="

# 1. Cập nhật hệ thống
echo "[1/6] Cập nhật thư viện hệ thống..."
sudo apt-get update

# 2. Cài đặt OpenCV, NumPy, PyQt5 bằng APT (đã biên dịch sẵn cho ARM)
echo "[2/6] Cài đặt OpenCV, NumPy và thư viện đồ họa..."
sudo apt-get install -y python3-opencv python3-numpy
sudo apt-get install -y python3-pyqt5 python3-pyqt5.qtmultimedia
sudo apt-get install -y libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev
sudo apt-get install -y libxcb-xinerama0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 qtwayland5
sudo apt-get install -y python3-venv python3-dev build-essential libatomic1
sudo apt-get install -y python3-pip

# 3. Tạo môi trường ảo (kế thừa thư viện hệ thống)
echo "[3/6] Tạo môi trường ảo Python..."
python3 -m venv --system-site-packages venv_pi

# 4. Kích hoạt môi trường ảo
echo "[4/6] Kích hoạt môi trường ảo..."
source venv_pi/bin/activate
pip install --upgrade pip

# 5. Cài đặt các thư viện Python (bên trong venv)
echo "[5/6] Cài đặt các thư viện Python..."
pip install fastapi>=0.100.0 uvicorn>=0.23.0 jinja2>=3.1 python-multipart>=0.0.6
pip install pydantic>=2.0 bcrypt>=4.0 itsdangerous>=2.1 scikit-image>=0.21.0

# Cài đặt ONNX Runtime cho ARM64 (thử nhiều cách)
echo "[5b/6] Cài đặt ONNX Runtime cho ARM64..."
PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  Python version: ${PYTHON_VER}"

# Cách 1: Thử cài từ PyPI (có thể có wheel cho aarch64)
pip install onnxruntime 2>/dev/null && echo "  ONNX Runtime cài thành công từ PyPI!" && ORT_OK=1

# Cách 2: Nếu thất bại, thử bản cũ hơn
if [ -z "$ORT_OK" ]; then
    echo "  Thử phiên bản 1.17.1..."
    pip install onnxruntime==1.17.1 2>/dev/null && echo "  ONNX Runtime 1.17.1 OK!" && ORT_OK=1
fi

if [ -z "$ORT_OK" ]; then
    echo "  Thử phiên bản 1.16.3..."
    pip install onnxruntime==1.16.3 2>/dev/null && echo "  ONNX Runtime 1.16.3 OK!" && ORT_OK=1
fi

# Cách 3: Thử cài từ piwheels (kho riêng cho Raspberry Pi)
if [ -z "$ORT_OK" ]; then
    echo "  Thử cài từ piwheels..."
    pip install onnxruntime --extra-index-url https://www.piwheels.org/simple 2>/dev/null && echo "  ONNX Runtime từ piwheels OK!" && ORT_OK=1
fi

# Cách 4: Nếu tất cả đều thất bại, hướng dẫn cài thủ công
if [ -z "$ORT_OK" ]; then
    echo ""
    echo "⚠️  KHÔNG THỂ CÀI TỰ ĐỘNG ONNX RUNTIME!"
    echo "  Hãy tải file .whl thủ công từ:"
    echo "  https://github.com/nknytk/built-onnxruntime-for-raspberrypi-linux/releases"
    echo "  Chọn file phù hợp với Python ${PYTHON_VER} và aarch64"
    echo "  Sau đó chạy: pip install <tên_file>.whl"
    echo ""
fi

# 6. Kiểm tra tất cả thư viện
echo "[6/6] Kiểm tra thư viện..."
echo "---"
python3 -c "import cv2; print(f'  OpenCV:      {cv2.__version__} ✅')" 2>/dev/null || echo "  OpenCV:      ❌ LỖI"
python3 -c "import numpy as np; print(f'  NumPy:       {np.__version__} ✅')" 2>/dev/null || echo "  NumPy:       ❌ LỖI"
python3 -c "import onnxruntime as ort; print(f'  ONNXRuntime: {ort.__version__} ✅')" 2>/dev/null || echo "  ONNXRuntime: ❌ LỖI (xem hướng dẫn ở trên)"
python3 -c "import fastapi; print(f'  FastAPI:     {fastapi.__version__} ✅')" 2>/dev/null || echo "  FastAPI:     ❌ LỖI"
echo "---"

echo "==================================================="
echo "HƯỚNG DẪN CHẠY:"
echo "  source venv_pi/bin/activate"
echo ""
echo "  # Bản OpenCV (ổn định nhất trên Pi):"
echo "  python3 run_cv2.py --source usb --camera 0"
echo "  python3 run_cv2.py --source picam"
echo ""
echo "  # Web Admin:"
echo "  uvicorn app.web_api:api --host 0.0.0.0 --port 8000"
echo "==================================================="
