#!/bin/bash
echo "==================================================="
echo " Edge Attendance - Cài đặt cho Raspberry Pi 4 (64-bit)"
echo "==================================================="

# 1. Cập nhật hệ thống
echo "[1/5] Cập nhật thư viện hệ thống..."
sudo apt-get update

# 2. Cài đặt các thư viện lõi bằng C++ (QUAN TRỌNG NHẤT)
echo "[2/5] Cài đặt PyQt5 và OpenCV Dependencies..."
# Bắt buộc cài PyQt5 bằng apt để tránh lỗi biên dịch C++ mất 40 phút trên Pi
sudo apt-get install -y python3-pyqt5 python3-pyqt5.qtmultimedia
# Các thư viện phụ trợ cho OpenCV và thư viện vẽ giao diện X11/XCB/Wayland (Sửa lỗi Qt platform xcb)
sudo apt-get install -y libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev
sudo apt-get install -y libxcb-xinerama0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 qtwayland5
# Công cụ tạo môi trường ảo Python
sudo apt-get install -y python3-venv python3-dev build-essential

# 3. Tạo môi trường ảo
echo "[3/5] Tạo môi trường ảo Python (Virtual Environment)..."
# Dùng cờ --system-site-packages để môi trường ảo có thể sử dụng PyQt5 cài từ hệ thống
python3 -m venv --system-site-packages venv_pi

# 4. Kích hoạt và cài đặt Pip
echo "[4/5] Đang cài đặt các thư viện AI..."
source venv_pi/bin/activate
pip install --upgrade pip

# 5. Cài đặt các thư viện từ requirements riêng cho Pi
pip install -r requirements_pi.txt

echo "==================================================="
echo "✅ HOÀN TẤT CÀI ĐẶT THÀNH CÔNG!"
echo "==================================================="
echo "HƯỚNG DẪN CHẠY:"
echo "1. Chép 2 file model (YuNet và FaceLiVT) vào thư mục models/ bằng USB"
echo "2. Kích hoạt môi trường bằng lệnh: source venv_pi/bin/activate"
echo "3. Chạy giao diện Kiosk: python run.py"
echo "4. Mở Web Admin ở terminal khác: uvicorn app.web_api:api --host 0.0.0.0 --port 8000"
echo "==================================================="
