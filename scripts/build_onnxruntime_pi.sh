#!/bin/bash
echo "==================================================="
echo " Build ONNX Runtime từ source cho Raspberry Pi 4"
echo " (Cortex-A72 / ARMv8.0 / aarch64)"
echo " ⏱️  Thời gian ước tính: 2-4 giờ"
echo "==================================================="

set -e

# 1. Cài đặt các công cụ build
echo "[1/5] Cài đặt công cụ biên dịch..."
sudo apt-get update
sudo apt-get install -y cmake build-essential git python3-dev python3-pip python3-numpy
sudo apt-get install -y protobuf-compiler libprotobuf-dev libprotoc-dev

# Tăng swap để tránh hết RAM khi biên dịch (Pi 4 chỉ có 4GB)
echo "[2/5] Tăng swap lên 4GB..."
sudo dphys-swapfile swapoff
sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=4096/' /etc/dphys-swapfile
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
echo "  Swap hiện tại: $(free -h | grep Swap | awk '{print $2}')"

# 3. Tải mã nguồn ONNX Runtime
ORT_VERSION="1.17.1"
echo "[3/5] Tải mã nguồn ONNX Runtime v${ORT_VERSION}..."
cd /tmp
rm -rf onnxruntime
git clone --depth 1 --branch v${ORT_VERSION} --recursive https://github.com/microsoft/onnxruntime.git
cd onnxruntime

# 4. Build (CHỈ dùng CPU, tắt các tính năng cao cấp để tương thích Cortex-A72)
echo "[4/5] Bắt đầu build (mất 2-4 giờ)..."
echo "  Bạn có thể để máy chạy qua đêm."
./build.sh \
    --config Release \
    --build_wheel \
    --update \
    --build \
    --parallel \
    --skip_tests \
    --cmake_extra_defines CMAKE_SYSTEM_PROCESSOR=aarch64 \
    --cmake_extra_defines onnxruntime_ENABLE_CPUINFO=OFF

# 5. Cài đặt wheel vừa build
echo "[5/5] Cài đặt ONNX Runtime..."
WHEEL_FILE=$(find build -name "onnxruntime-*.whl" | head -1)
if [ -n "$WHEEL_FILE" ]; then
    pip3 install "$WHEEL_FILE" --break-system-packages
    echo ""
    echo "==================================================="
    echo "✅ ONNX Runtime ${ORT_VERSION} build và cài đặt thành công!"
    echo "==================================================="
    python3 -c "import onnxruntime as ort; print(f'  Version: {ort.__version__}')"
else
    echo "❌ Không tìm thấy file .whl sau khi build!"
    echo "  Kiểm tra log lỗi ở trên."
fi

# Khôi phục swap về mặc định
echo "Khôi phục swap..."
sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=256/' /etc/dphys-swapfile
sudo dphys-swapfile setup

echo ""
echo "Sau khi build xong, quay lại thư mục dự án:"
echo "  cd ~/FaceRecognitionAttendance_FaceliVT"
echo "  source venv_pi/bin/activate"
echo "  python3 run_cv2.py --source usb --camera 0"
echo ""
echo "Hệ thống sẽ tự động dùng FaceLiVT (512-dim) thay vì SFace!"
