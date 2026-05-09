"""
Khởi động Kiosk giao diện OpenCV (không cần PyQt5).
Dùng khi chạy trên Raspberry Pi bị lỗi PyQt5/XCB.

Cách chạy:
  python3 run_cv2.py --source usb --camera 0
  python3 run_cv2.py --source picam
  python3 run_cv2.py --fullscreen --source usb
"""
from app.main_cv2 import main

if __name__ == "__main__":
    main()
