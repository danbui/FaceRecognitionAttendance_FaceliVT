#!/bin/bash
set -euo pipefail

echo "==================================================="
echo " Edge Attendance - Cài đặt cho Raspberry Pi 4 (64-bit)"
echo "==================================================="

if ! uname -m | grep -q "aarch64"; then
  echo "❌ Hệ điều hành hiện tại không phải 64-bit (aarch64)."
  echo "   Hãy cài Raspberry Pi OS 64-bit mới nhất trước khi tiếp tục."
  exit 1
fi

PYTHON_BIN="python3"

echo "[1/7] Cập nhật hệ thống..."
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  python3 python3-pip python3-venv python3-dev build-essential \
  python3-opencv python3-numpy \
  python3-pyqt5 python3-pyqt5.qtmultimedia \
  libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev \
  libxcb-xinerama0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-render-util0 qtwayland5 libatomic1 curl

echo "[2/7] Tạo môi trường ảo (kế thừa gói apt)..."
$PYTHON_BIN -m venv --system-site-packages venv_pi
source venv_pi/bin/activate

echo "[3/7] Nâng cấp pip/setuptools/wheel..."
pip install --upgrade pip setuptools wheel

echo "[4/7] Cài ONNX Runtime cho ARM64..."
# Ưu tiên piwheels để lấy wheel tối ưu cho Raspberry Pi.
pip install --prefer-binary --extra-index-url https://www.piwheels.org/simple onnxruntime==1.18.1

echo "[5/7] Cài các thư viện Python còn lại..."
pip install 'fastapi>=0.100.0' 'uvicorn>=0.23.0' 'jinja2>=3.1' 'python-multipart>=0.0.6'
pip install 'pydantic>=2.0' 'bcrypt>=4.0' 'itsdangerous>=2.1' 'scikit-image>=0.21.0'

echo "[6/7] Kiểm tra nhanh import..."
python -c "import cv2; print(f'  OpenCV: {cv2.__version__} - OK')"
python -c "import numpy as np; print(f'  NumPy: {np.__version__} - OK')"
python -c "import onnxruntime as ort; print(f'  ONNXRuntime: {ort.__version__} - OK')"

echo "[7/7] In provider khả dụng của ONNX Runtime..."
python - <<'PY'
import onnxruntime as ort
print("  Providers:", ort.get_available_providers())
PY

echo "==================================================="
echo "✅ HOÀN TẤT CÀI ĐẶT THÀNH CÔNG!"
echo "==================================================="
echo "HƯỚNG DẪN CHẠY:"
echo "  source venv_pi/bin/activate"
echo "  python run_cv2.py --source usb --camera 0"
echo "  python run_cv2.py --source picam"
echo "  python run.py --source usb --camera 0"
echo "  uvicorn app.web_api:api --host 0.0.0.0 --port 8000"
