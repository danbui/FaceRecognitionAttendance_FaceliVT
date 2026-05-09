#!/bin/bash
echo "==================================================="
echo " Edge Attendance - Cài đặt cho Raspberry Pi 4 (64-bit)"
echo "==================================================="

set -e

# 1. Cập nhật hệ thống
echo "[1/6] Cập nhật hệ thống..."
sudo apt-get update

# 2. Cài OpenCV + NumPy + PyQt5 bằng APT (biên dịch sẵn cho ARM, KHÔNG dùng pip)
echo "[2/6] Cài thư viện hệ thống (ARM-native)..."
sudo apt-get install -y python3-opencv python3-numpy python3-pip
sudo apt-get install -y python3-pyqt5 python3-pyqt5.qtmultimedia
sudo apt-get install -y libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev
sudo apt-get install -y libxcb-xinerama0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0
sudo apt-get install -y python3-venv python3-dev build-essential libatomic1 wget

# 3. Tạo môi trường ảo (kế thừa thư viện hệ thống)
echo "[3/6] Tạo môi trường ảo..."
python3 -m venv --system-site-packages venv_pi
source venv_pi/bin/activate
pip install --upgrade pip

# 4. Cài ONNXRuntime bản BUILD RIÊNG cho Raspberry Pi 4
echo "[4/6] Cài ONNX Runtime (bản Raspberry Pi)..."
PYVER=$(python3 -c "import sys; print(f'cp{sys.version_info.major}{sys.version_info.minor}')")
echo "  Python: ${PYVER}"

# Tải file wheel từ repo cộng đồng (build riêng cho Cortex-A72 / Pi 4)
ORT_VERSION="1.17.1"
WHL_NAME="onnxruntime-${ORT_VERSION}-${PYVER}-${PYVER}-linux_aarch64.whl"
WHL_URL="https://github.com/nknytk/built-onnxruntime-for-raspberrypi-linux/releases/download/v${ORT_VERSION}/${WHL_NAME}"

echo "  Đang tải: ${WHL_NAME}"
wget -q --show-progress -O "/tmp/${WHL_NAME}" "${WHL_URL}" 2>/dev/null

if [ $? -eq 0 ] && [ -f "/tmp/${WHL_NAME}" ]; then
    pip install "/tmp/${WHL_NAME}"
    rm -f "/tmp/${WHL_NAME}"
    echo "  ✅ ONNX Runtime ${ORT_VERSION} cài thành công!"
else
    echo "  ⚠️ Không tải được bản ${ORT_VERSION}."
    echo "  Thử phiên bản khác..."
    
    # Fallback: thử 1.18.0
    ORT_VERSION="1.18.0"
    WHL_NAME="onnxruntime-${ORT_VERSION}-${PYVER}-${PYVER}-linux_aarch64.whl"
    WHL_URL="https://github.com/nknytk/built-onnxruntime-for-raspberrypi-linux/releases/download/v${ORT_VERSION}/${WHL_NAME}"
    
    echo "  Đang tải: ${WHL_NAME}"
    wget -q --show-progress -O "/tmp/${WHL_NAME}" "${WHL_URL}" 2>/dev/null
    
    if [ $? -eq 0 ] && [ -f "/tmp/${WHL_NAME}" ]; then
        pip install "/tmp/${WHL_NAME}"
        rm -f "/tmp/${WHL_NAME}"
        echo "  ✅ ONNX Runtime ${ORT_VERSION} cài thành công!"
    else
        echo ""
        echo "  ❌ Không thể tải tự động."
        echo "  Hãy vào link sau và tải file .whl phù hợp với Python ${PYVER}:"
        echo "  https://github.com/nknytk/built-onnxruntime-for-raspberrypi-linux/releases"
        echo "  Sau đó chạy: pip install <tên_file>.whl"
    fi
fi

# 5. Cài các thư viện Python nhẹ (KHÔNG cài numpy, opencv, onnxruntime ở đây)
echo "[5/6] Cài thư viện Python còn lại..."
pip install --no-deps fastapi uvicorn jinja2 python-multipart pydantic bcrypt itsdangerous
pip install scikit-image

# 6. Kiểm tra
echo ""
echo "[6/6] Kiểm tra thư viện..."
echo "---"
python3 -c "import cv2; print(f'  OpenCV:      {cv2.__version__} ✅')" 2>/dev/null || echo "  OpenCV:      ❌"
python3 -c "import numpy as np; print(f'  NumPy:       {np.__version__} ✅')" 2>/dev/null || echo "  NumPy:       ❌"
python3 -c "import onnxruntime as ort; print(f'  ONNXRuntime: {ort.__version__} ✅')" 2>/dev/null || echo "  ONNXRuntime: ❌"
python3 -c "import fastapi; print(f'  FastAPI:     {fastapi.__version__} ✅')" 2>/dev/null || echo "  FastAPI:     ❌"
echo "---"
echo ""
echo "==================================================="
echo "HƯỚNG DẪN CHẠY:"
echo "  source venv_pi/bin/activate"
echo "  python3 run_cv2.py --source usb --camera 0"
echo "  python3 run_cv2.py --source picam"
echo "==================================================="
