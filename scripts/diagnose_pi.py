"""
Chẩn đoán lỗi Illegal Instruction trên Raspberry Pi.
Chạy: python3 scripts/diagnose_pi.py
"""
import sys
import subprocess

tests = [
    ("Python", "print('OK')"),
    ("NumPy", "import numpy; print(numpy.__version__)"),
    ("OpenCV", "import cv2; print(cv2.__version__)"),
    ("bcrypt", "import bcrypt; print(bcrypt.__version__)"),
    ("pydantic", "import pydantic; print(pydantic.__version__)"),
    ("fastapi", "import fastapi; print(fastapi.__version__)"),
    ("jinja2", "import jinja2; print(jinja2.__version__)"),
    ("uvicorn", "import uvicorn; print(uvicorn.__version__)"),
]

print(f"Python: {sys.version}\n")

for name, cmd in tests:
    try:
        result = subprocess.run(
            [sys.executable, "-c", cmd],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            print(f"  {name}: {result.stdout.strip()} ✅")
        elif result.returncode == -4:
            print(f"  {name}: ❌ ILLEGAL INSTRUCTION (SIGILL)")
        else:
            err = result.stderr.strip().split('\n')[-1] if result.stderr else "Unknown"
            print(f"  {name}: ❌ Error (code {result.returncode}): {err}")
    except Exception as e:
        print(f"  {name}: ❌ {e}")

print("\nDone.")
