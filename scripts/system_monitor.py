import time
import threading
from pathlib import Path

# Thử import psutil để lấy CPU % và RAM chính xác.
# Nếu không có, sẽ tự động dùng fallback (chỉ hỗ trợ Linux/Raspberry Pi).
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

class SystemMonitor:
    def __init__(self, interval=1.0, log_path=None):
        """
        Khởi tạo bộ giám sát hệ thống.
        :param interval: Thời gian giữa các lần đo (giây)
        :param log_path: Đường dẫn lưu file CSV kết quả (nếu có)
        """
        self.interval = interval
        self.log_path = Path(log_path) if log_path else None
        self.records = []
        self.running = False
        self.thread = None
        
        if not HAS_PSUTIL:
            print("⚠️ Cảnh báo: Thư viện 'psutil' chưa được cài đặt.")
            print("   -> Sẽ sử dụng fallback đọc trực tiếp từ hệ thống Linux/Raspberry Pi.")
            print("   -> Bạn có thể cài đặt bằng lệnh: pip install psutil")

    def _get_cpu_temp(self):
        """Đọc nhiệt độ CPU (chỉ hoạt động trên Linux/Raspberry Pi)"""
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                return float(f.read()) / 1000.0
        except FileNotFoundError:
            # Fallback cho macOS/Windows hoặc thiết bị không hỗ trợ
            return 0.0

    def _get_ram_usage(self):
        """Lấy dung lượng RAM đã sử dụng (MB) và tỷ lệ (%)"""
        if HAS_PSUTIL:
            mem = psutil.virtual_memory()
            return mem.used / (1024 * 1024), mem.percent
        else:
            # Fallback đọc /proc/meminfo trên Linux/Raspberry Pi
            try:
                meminfo = {}
                with open('/proc/meminfo', 'r') as f:
                    for line in f:
                        parts = line.split()
                        meminfo[parts[0].replace(':', '')] = int(parts[1])
                total = meminfo['MemTotal']
                free = meminfo['MemFree']
                buffers = meminfo.get('Buffers', 0)
                cached = meminfo.get('Cached', 0)
                used = total - free - buffers - cached
                used_mb = used / 1024.0
                percent = (used / total) * 100.0
                return used_mb, percent
            except Exception:
                return 0.0, 0.0

    def _get_cpu_usage(self):
        """Lấy tỷ lệ sử dụng CPU (%)"""
        if HAS_PSUTIL:
            return psutil.cpu_percent(interval=None)
        else:
            # Fallback đơn giản đọc từ /proc/loadavg trên Linux
            try:
                with open('/proc/loadavg', 'r') as f:
                    load = float(f.read().split()[0])
                    # Quy đổi ước lượng dựa trên số core (giả định 4 core trên Pi 4)
                    return min(100.0, (load / 4.0) * 100.0)
            except Exception:
                return 0.0

    def _monitor_loop(self):
        # Lấy mốc thời gian bắt đầu
        start_time = time.perf_counter()
        while self.running:
            t_elapsed = time.perf_counter() - start_time
            temp = self._get_cpu_temp()
            ram_mb, ram_pct = self._get_ram_usage()
            cpu_pct = self._get_cpu_usage()
            
            self.records.append({
                "elapsed_sec": t_elapsed,
                "cpu_percent": cpu_pct,
                "ram_used_mb": ram_mb,
                "ram_percent": ram_pct,
                "cpu_temp": temp
            })
            
            time.sleep(self.interval)

    def start(self):
        """Bắt đầu giám sát trong một luồng phụ (background thread)"""
        if self.running:
            return
        self.running = True
        self.records = []
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        print("▶️ Bắt đầu giám sát hệ thống (CPU%, RAM, Nhiệt độ CPU)...")

    def stop(self):
        """Dừng giám sát và xuất kết quả ra file nếu có cấu hình log_path"""
        if not self.running:
            return
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        print("⏹️ Đã dừng giám sát hệ thống.")
        
        if self.log_path and self.records:
            self.save_to_csv(self.log_path)
            
        # In tóm tắt ra màn hình
        if self.records:
            temps = [r["cpu_temp"] for r in self.records if r["cpu_temp"] > 0]
            cpus = [r["cpu_percent"] for r in self.records]
            rams = [r["ram_used_mb"] for r in self.records]
            
            print("\n📊 BÁO CÁO THÔNG SỐ HỆ THỐNG TRONG QUÁ TRÌNH CHẠY:")
            if temps:
                print(f"  🌡️ Nhiệt độ CPU: Trung bình {sum(temps)/len(temps):.1f}°C | Cao nhất {max(temps):.1f}°C")
            print(f"  💻 Sử dụng CPU:  Trung bình {sum(cpus)/len(cpus):.1f}% | Cao nhất {max(cpus):.1f}%")
            print(f"  🐏 Sử dụng RAM:  Trung bình {sum(rams)/len(rams):.1f} MB | Cao nhất {max(rams):.1f} MB")
            print("-" * 50)

    def save_to_csv(self, path):
        """Xuất dữ liệu đo đạc ra file CSV"""
        import csv
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Elapsed_Seconds", "CPU_Usage_Percent", "RAM_Used_MB", "RAM_Usage_Percent", "CPU_Temp_C"])
                for r in self.records:
                    writer.writerow([
                        f"{r['elapsed_sec']:.1f}",
                        f"{r['cpu_percent']:.1f}",
                        f"{r['ram_used_mb']:.1f}",
                        f"{r['ram_percent']:.1f}",
                        f"{r['cpu_temp']:.1f}"
                    ])
            print(f"💾 Đã lưu log hệ thống ra: {path}")
        except Exception as e:
            print(f"❌ Lỗi khi ghi file CSV: {e}")

# ── HƯỚNG DẪN SỬ DỤNG NHANH ─────────────────────────────────────
if __name__ == "__main__":
    # Test thử độc lập trong 5 giây
    monitor = SystemMonitor(interval=0.5, log_path="benchmarks/system_test_log.csv")
    monitor.start()
    
    # Giả lập công việc nặng
    print("Đang giả lập tải CPU...")
    for _ in range(5):
        # Heavy computation
        [x**2 for x in range(2000000)]
        time.sleep(0.5)
        
    monitor.stop()
