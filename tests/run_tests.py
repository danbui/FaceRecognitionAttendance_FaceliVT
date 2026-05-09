"""
Automated test runner for Edge Attendance System.
Tests: Database, Matcher, Attendance Service, Web API.

Usage:
    cd FaceRecognitionAttendance
    python run_tests.py
"""
import sys
import os
import time
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent))

PASS = 0
FAIL = 0
RESULTS = []


def test(test_id, name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        status = "✅ PASS"
    else:
        FAIL += 1
        status = "❌ FAIL"
    RESULTS.append((test_id, name, status, detail))
    print(f"  {status}  {test_id}: {name}" + (f" ({detail})" if detail else ""))


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ═══════════════════════════════════════════════════════════════
# TC-G: DATABASE TESTS
# ═══════════════════════════════════════════════════════════════
def test_database():
    section("TC-G: Database & Data")

    # Delete old test DB
    test_db = Path("test_attendance.db")
    if test_db.exists():
        os.remove(test_db)

    # Patch config to use test DB
    import app.config as cfg
    original_db = cfg.DB_PATH
    cfg.DB_PATH = test_db

    from app.database import (
        init_db, get_conn, create_employee, save_embedding,
        add_attendance, get_last_attendance_today, list_employees,
        list_attendance, verify_user, create_user, get_attendance_summary,
        get_departments,
    )

    # G01: Init DB creates correct schema
    init_db()
    conn = get_conn()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    conn.close()
    expected_tables = {"employees", "face_embeddings", "attendance_logs", "users"}
    test("G01", "Init DB creates correct schema", expected_tables.issubset(set(tables)),
         f"Tables: {tables}")

    # G03: Password hash bcrypt
    conn = get_conn()
    row = conn.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()
    conn.close()
    is_bcrypt = row and row[0].startswith("$2")
    test("G03", "Password hash is bcrypt", is_bcrypt,
         f"Hash prefix: {row[0][:10]}..." if row else "No admin user")

    # G05: WAL mode
    conn = get_conn()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    test("G05", "Journal mode", mode in ("wal", "delete"), f"journal_mode={mode}")

    # Create test employee
    eid = create_employee("TEST001", "Test Employee", "QA")
    test("G_extra1", "Create employee", eid is not None and eid > 0, f"employee_id={eid}")

    # G02: Embedding stored as BLOB
    fake_emb = np.random.randn(1, 512).astype(np.float32)
    save_embedding(eid, fake_emb, "test.jpg")
    conn = get_conn()
    emb_type = conn.execute("SELECT typeof(embedding) FROM face_embeddings WHERE employee_id=?", (eid,)).fetchone()[0]
    conn.close()
    test("G02", "Embedding stored as BLOB", emb_type == "blob", f"typeof={emb_type}")

    # G04: Attendance uses local time
    add_attendance(eid, 0.85, "CHECK_IN", "")
    conn = get_conn()
    row = conn.execute("SELECT check_time FROM attendance_logs ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    stored_time = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    now = datetime.now()
    diff = abs((now - stored_time).total_seconds())
    test("G04", "Attendance uses local timezone", diff < 5,
         f"stored={row[0]}, now={now.strftime('%H:%M:%S')}, diff={diff:.1f}s")

    # List employees
    employees = list_employees()
    test("G_extra2", "List employees returns data", len(employees) >= 1, f"count={len(employees)}")

    # List attendance
    logs = list_attendance(100)
    test("G_extra3", "List attendance returns data", len(logs) >= 1, f"count={len(logs)}")

    # Verify user
    user = verify_user("admin", "admin123")
    test("G_extra4", "Verify admin login", user is not None and user["role"] == "admin")

    bad_user = verify_user("admin", "wrongpass")
    test("G_extra5", "Reject wrong password", bad_user is None)

    # Summary
    summary = get_attendance_summary()
    test("G_extra6", "Get attendance summary", "total_employees" in summary,
         f"total_employees={summary.get('total_employees')}")

    # Departments
    depts = get_departments()
    test("G_extra7", "Get departments", isinstance(depts, list))

    # Restore config and cleanup
    cfg.DB_PATH = original_db
    if test_db.exists():
        os.remove(test_db)


# ═══════════════════════════════════════════════════════════════
# TC-H: MATCHER TESTS
# ═══════════════════════════════════════════════════════════════
def test_matcher():
    section("TC-H: AI Matcher Tests")

    from app.matcher import match_embedding, embedding_cache
    from app.config import RECOGNITION_COSINE_THRESHOLD

    # Create fake data inside embedding cache for testing
    vec_a = np.random.randn(1, 512).astype(np.float32)
    vec_a = vec_a / (np.linalg.norm(vec_a) + 1e-8)
    
    vec_c = np.random.randn(1, 512).astype(np.float32)
    vec_c = vec_c / (np.linalg.norm(vec_c) + 1e-8)

    # Mock the cache
    embedding_cache._rows = [
        {"id": 1, "employee_id": 1, "employee_code": "NV001", "full_name": "A", "embedding": vec_a},
        {"id": 2, "employee_id": 2, "employee_code": "NV002", "full_name": "B", "embedding": vec_c},
    ]
    embedding_cache._matrix = np.vstack([vec_a, vec_c])
    embedding_cache._dirty = False

    # H03: match_embedding finds correct person
    result = match_embedding(vec_a, threshold=RECOGNITION_COSINE_THRESHOLD)
    test("H_match1", "match_embedding finds correct person",
         result is not None and result["employee_code"] == "NV001",
         f"matched={result['employee_code'] if result else None}")

    test("H_match2", "Confidence is 0~1",
         result is not None and 0 <= result["confidence"] <= 1.0,
         f"confidence={result['confidence']:.4f}" if result else "None")

    # H04: No match below high threshold
    vec_d = np.random.randn(1, 512).astype(np.float32)
    result_none = match_embedding(vec_d, threshold=0.99)
    test("H_match3", "No match below high threshold", result_none is None)

    # match_embedding: empty DB
    embedding_cache._rows = []
    embedding_cache._matrix = None
    embedding_cache._dirty = False
    result_empty = match_embedding(vec_a, threshold=RECOGNITION_COSINE_THRESHOLD)
    test("H_match4", "Empty DB returns None", result_empty is None)
    
    # Restore dirty flag
    embedding_cache.invalidate()


# ═══════════════════════════════════════════════════════════════
# TC-B: ATTENDANCE SERVICE (DUPLICATE DETECTION)
# ═══════════════════════════════════════════════════════════════
def test_duplicate_detection():
    section("TC-B: Duplicate Detection Logic")

    test_db = Path("test_dup.db")
    if test_db.exists():
        os.remove(test_db)

    import app.config as cfg
    original_db = cfg.DB_PATH
    cfg.DB_PATH = test_db

    from app.database import init_db, create_employee, add_attendance, get_last_attendance_today, get_conn

    init_db()
    eid = create_employee("DUP001", "Dup Test", "QA")

    # B01: First check-in should succeed (no prior record)
    last = get_last_attendance_today(eid, "CHECK_IN")
    test("B01", "First check-in → no prior record", last is None)

    # Add a check-in
    add_attendance(eid, 0.85, "CHECK_IN", "")
    time.sleep(0.5)

    # B03: Duplicate check within 5 minutes
    last = get_last_attendance_today(eid, "CHECK_IN")
    test("B03a", "Duplicate detected: last attendance exists", last is not None)

    if last:
        last_time = datetime.strptime(last["check_time"], "%Y-%m-%d %H:%M:%S")
        elapsed = (datetime.now() - last_time).total_seconds()
        is_dup = elapsed < cfg.DUPLICATE_COOLDOWN_MINUTES * 60
        test("B03b", f"Duplicate: elapsed < 5 min", is_dup,
             f"elapsed={elapsed:.1f}s")

    # B06: Different check_type NOT duplicate
    last_out = get_last_attendance_today(eid, "CHECK_OUT")
    test("B06", "CHECK_OUT has no prior record (different type)", last_out is None)

    # Add CHECK_OUT immediately after CHECK_IN
    add_attendance(eid, 0.85, "CHECK_OUT", "")
    last_out = get_last_attendance_today(eid, "CHECK_OUT")
    test("B06b", "CHECK_OUT recorded independently", last_out is not None)

    # Verify both records exist
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM attendance_logs WHERE employee_id=?", (eid,)).fetchone()[0]
    conn.close()
    test("B_records", "Both CHECK_IN and CHECK_OUT recorded", count == 2, f"count={count}")

    # Cleanup
    cfg.DB_PATH = original_db
    if test_db.exists():
        os.remove(test_db)


# ═══════════════════════════════════════════════════════════════
# TC-D: WEB AUTH (via requests if available)
# ═══════════════════════════════════════════════════════════════
def test_web_auth():
    section("TC-D/E/F: Web API Tests")

    try:
        import requests
    except ImportError:
        print("  ⚠️  SKIP: 'requests' library not installed. Install with: pip install requests")
        return

    base = "http://localhost:8000"

    # Check if server is running
    try:
        r = requests.get(f"{base}/login", timeout=3)
    except requests.ConnectionError:
        print("  ⚠️  SKIP: Web server not running. Start with: uvicorn app.web_api:api --host 0.0.0.0 --port 8000")
        return

    # D05: Unauthenticated → redirect to login
    r = requests.get(f"{base}/", allow_redirects=False)
    test("D05", "Unauthenticated → redirect to /login", r.status_code == 302,
         f"status={r.status_code}")

    # D01: Login admin
    s = requests.Session()
    r = s.post(f"{base}/login", data={"username": "admin", "password": "admin123"}, allow_redirects=False)
    test("D01", "Admin login → redirect to /", r.status_code == 302,
         f"status={r.status_code}")

    # D01b: Dashboard accessible after login
    r = s.get(f"{base}/")
    test("D01b", "Admin dashboard loads", r.status_code == 200 and "admin" in r.text.lower())

    # E01: Stat cards visible for admin
    test("E01", "Stat cards visible for admin",
         "Tổng nhân viên" in r.text or "total_employees" in r.text.lower())

    # E07: CHECK IN/OUT badges
    test("E07", "CHECK IN badge visible", "CHECK IN" in r.text or "CHECK_IN" in r.text)

    # E06: CSV export link
    test("E06a", "CSV export link exists", "attendance.csv" in r.text)

    # E06b: CSV download
    r_csv = s.get(f"{base}/export/attendance.csv")
    test("E06b", "CSV download returns file", r_csv.status_code == 200 and "employee_code" in r_csv.text,
         f"status={r_csv.status_code}, size={len(r_csv.text)} bytes")

    # D03: Wrong password
    s2 = requests.Session()
    r = s2.post(f"{base}/login", data={"username": "admin", "password": "wrong"}, allow_redirects=False)
    test("D03", "Wrong password → stay on login", r.status_code == 200,
         f"status={r.status_code}")

    # D04: Unknown user
    r = s2.post(f"{base}/login", data={"username": "ghost", "password": "123"}, allow_redirects=False)
    test("D04", "Unknown user → stay on login", r.status_code == 200)

    # D06: Logout
    r = s.get(f"{base}/logout", allow_redirects=False)
    test("D06", "Logout → redirect to /login", r.status_code == 302)

    r = s.get(f"{base}/", allow_redirects=False)
    test("D06b", "After logout → cannot access dashboard",
         r.status_code == 302 or r.status_code == 401)

    # --- Employee login ---
    s3 = requests.Session()
    r = s3.post(f"{base}/login", data={"username": "nv001", "password": "123456"}, allow_redirects=False)
    if r.status_code == 302:
        test("D02", "Employee login succeeds", True)

        r = s3.get(f"{base}/")
        # F01: Employee cannot see employee list
        test("F01", "Employee cannot see employee management",
             "Thêm nhân viên" not in r.text)

        # F03: No export button
        test("F03", "Employee has no Export CSV button",
             "Xuất CSV" not in r.text)

        # F04: API access denied
        r_api = s3.get(f"{base}/api/employees")
        test("F04", "Employee cannot access /api/employees",
             r_api.status_code == 401 or "Unauthorized" in r_api.text,
             f"status={r_api.status_code}")
    else:
        test("D02", "Employee login succeeds", False,
             "Employee account may not exist. Run: python seed_data.py")

    # --- API endpoints ---
    s_admin = requests.Session()
    s_admin.post(f"{base}/login", data={"username": "admin", "password": "admin123"})

    r = s_admin.get(f"{base}/api/attendance")
    test("E_api1", "API /api/attendance returns JSON", r.status_code == 200)

    r = s_admin.get(f"{base}/api/summary")
    test("E_api2", "API /api/summary returns JSON", r.status_code == 200)

    r = s_admin.get(f"{base}/api/employees")
    test("E_api3", "API /api/employees returns JSON (admin)", r.status_code == 200)


# ═══════════════════════════════════════════════════════════════
# TC-H: MODEL FILES
# ═══════════════════════════════════════════════════════════════
def test_model_files():
    section("TC-H: Model Files")

    from app.config import YUNET_MODEL, FACELIVT_MODEL

    test("H01a", "YuNet model file exists", YUNET_MODEL.exists(),
         str(YUNET_MODEL))
    test("H01b", "FaceLiVT model file exists", FACELIVT_MODEL.exists(),
         str(FACELIVT_MODEL))

    if YUNET_MODEL.exists():
        size_kb = YUNET_MODEL.stat().st_size / 1024
        test("H01c", "YuNet model size ~240KB", 200 < size_kb < 300,
             f"{size_kb:.0f} KB")

    if FACELIVT_MODEL.exists():
        size_mb = FACELIVT_MODEL.stat().st_size / (1024 * 1024)
        test("H01d", "FaceLiVT model size ~16MB", 10 < size_mb < 20,
             f"{size_mb:.1f} MB")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  🧪 Edge Attendance System – Test Runner")
    print("=" * 60)

    test_model_files()
    test_database()
    test_matcher()
    test_duplicate_detection()
    test_web_auth()

    # Summary
    print("\n" + "=" * 60)
    print(f"  📊 RESULTS: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
    print("=" * 60)

    if FAIL > 0:
        print("\n  ❌ Failed tests:")
        for tid, name, status, detail in RESULTS:
            if "FAIL" in status:
                print(f"     {tid}: {name} – {detail}")

    print()
    sys.exit(1 if FAIL > 0 else 0)
