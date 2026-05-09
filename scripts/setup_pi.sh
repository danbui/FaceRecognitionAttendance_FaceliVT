#!/bin/bash
echo "==================================================="
echo " Edge Attendance - Cài đặt cho Raspberry Pi 4 (64-bit)"
echo " Bản OpenCV thuần (KHÔNG cần PyQt5)"
echo "==================================================="

set -e

# 1. Cập nhật hệ thống
echo "[1/5] Cập nhật hệ thống..."
sudo apt-get update

# 2. Cài OpenCV + NumPy bằng APT (biên dịch sẵn cho ARM)
echo "[2/5] Cài OpenCV và NumPy (ARM-native)..."
sudo apt-get install -y python3-opencv python3-numpy python3-pip python3-venv python3-dev wget libatomic1

# 3. Tạo môi trường ảo (kế thừa thư viện hệ thống)
echo "[3/5] Tạo môi trường ảo..."
python3 -m venv --system-site-packages venv_pi
source venv_pi/bin/activate
pip install --upgrade pip

# 4. Cài ONNXRuntime bản BUILD RIÊNG cho Raspberry Pi 4
echo "[4/5] Cài ONNX Runtime (bản Raspberry Pi)..."
PYVER=$(python3 -c "import sys; print(f'cp{sys.version_info.major}{sys.version_info.minor}')")
echo "  Python: ${PYVER}"

ORT_VERSION="1.17.1"
WHL_NAME="onnxruntime-${ORT_VERSION}-${PYVER}-${PYVER}-linux_aarch64.whl"
WHL_URL="https://github.com/nknytk/built-onnxruntime-for-raspberrypi-linux/releases/download/v${ORT_VERSION}/${WHL_NAME}"

echo "  Đang tải: ${WHL_NAME}"
wget -q --show-progress -O "/tmp/${WHL_NAME}" "${WHL_URL}" 2>/dev/null

if [ $? -eq 0 ] && [ -f "/tmp/${WHL_NAME}" ]; then
    pip install "/tmp/${WHL_NAME}"
    rm -f "/tmp/${WHL_NAME}"
    echo "  ✅ ONNX Runtime ${ORT_VERSION} OK!"
else
    echo "  ⚠️ Bản ${ORT_VERSION} không tìm thấy. Thử 1.18.0..."
    ORT_VERSION="1.18.0"
    WHL_NAME="onnxruntime-${ORT_VERSION}-${PYVER}-${PYVER}-linux_aarch64.whl"
    WHL_URL="https://github.com/nknytk/built-onnxruntime-for-raspberrypi-linux/releases/download/v${ORT_VERSION}/${WHL_NAME}"
    wget -q --show-progress -O "/tmp/${WHL_NAME}" "${WHL_URL}" 2>/dev/null
    if [ $? -eq 0 ] && [ -f "/tmp/${WHL_NAME}" ]; then
        pip install "/tmp/${WHL_NAME}"
        rm -f "/tmp/${WHL_NAME}"
        echo "  ✅ ONNX Runtime ${ORT_VERSION} OK!"
    else
        echo "  ❌ Tải thất bại. Vào link sau tải thủ công:"
        echo "  https://github.com/nknytk/built-onnxruntime-for-raspberrypi-linux/releases"
        echo "  Rồi chạy: pip install <tên_file>.whl"
    fi
fi

# 5. Cài thư viện Python nhẹ
echo "[5/5] Cài thư viện Python..."
pip install fastapi uvicorn jinja2 python-multipart pydantic bcrypt itsdangerous scikit-image

# Kiểm tra
echo ""
echo "=== KIỂM TRA ==="
python3 -c "import cv2; print(f'  OpenCV:      {cv2.__version__} ✅')" || echo "  OpenCV:      ❌"
python3 -c "import numpy as np; print(f'  NumPy:       {np.__version__} ✅')" || echo "  NumPy:       ❌"
python3 -c "import onnxruntime as ort; print(f'  ONNXRuntime: {ort.__version__} ✅')" || echo "  ONNXRuntime: ❌"
python3 -c "import fastapi; print(f'  FastAPI:     {fastapi.__version__} ✅')" || echo "  FastAPI:     ❌"
echo ""
echo "==================================================="
echo "CHẠY LỆNH:"
echo "  source venv_pi/bin/activate"
echo "  python3 run_cv2.py --source usb --camera 0"
echo "  python3 run_cv2.py --source picam"
echo "==================================================="
