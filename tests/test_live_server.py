import urllib.request
import urllib.error
import json
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

import database

BASE_URL = "http://127.0.0.1:3000"

def post_json(path, data):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        res = urllib.request.urlopen(req)
        return res.code, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))

def test_live_server_endpoints():
    print("--- 1. Testing Live Server Health ---")
    req = urllib.request.Request(f"{BASE_URL}/api/health")
    res = urllib.request.urlopen(req)
    assert res.code == 200
    health_data = json.loads(res.read().decode())
    print("Health response:", health_data)
    assert health_data["status"] == "healthy"

    print("\n--- 2. Testing Doctor Login with Real DB ---")
    code, data = post_json("/api/doctors/login", {"login_id": "3001", "password": "admin123"})
    print("Login result:", code, data)
    assert code == 200 or code == 400

    print("\n--- 3. Testing Non-Existent User on Forgot Password ---")
    code, data = post_json("/api/doctors/forgot-password/send-otp", {"identifier": "fake_user_9999@domain.com"})
    print("Non-existent send-otp result:", code, data)
    assert code == 400
    assert "No account found" in data["error"]

    print("\n--- 4. Directly Testing DB-backed OTP Verification & Password Reset Flow ---")
    # Generate OTP directly in DB to simulate email delivery in test
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, uid FROM doctors WHERE email = 'admin@gmail.com'")
    doc = cursor.fetchone()
    assert doc is not None

    test_otp = "889977"
    cursor.execute("UPDATE password_reset_otps SET used = 2 WHERE doctor_id = ?", (doc["id"],))
    cursor.execute("""
        INSERT INTO password_reset_otps (doctor_id, identifier, email, otp, expires_at, used)
        VALUES (?, 'admin@gmail.com', 'admin@gmail.com', ?, datetime('now', '+10 minutes'), 0)
    """, (doc["id"], test_otp))
    conn.commit()
    conn.close()

    print("\n--- 5. Verifying OTP via Live Server API ---")
    code, data = post_json("/api/doctors/forgot-password/verify-otp", {"identifier": "admin@gmail.com", "otp": test_otp})
    print("Verify OTP result:", code, data)
    assert code == 200
    assert data["success"] is True
    reset_token = data["reset_token"]

    print("\n--- 6. Resetting Password via Live Server API ---")
    new_admin_pass = "Admin@NewPass2026!"
    code, data = post_json("/api/doctors/forgot-password/reset", {
        "identifier": "3001",
        "reset_token": reset_token,
        "new_password": new_admin_pass
    })
    print("Reset Password result:", code, data)
    assert code == 200
    assert data["success"] is True

    print("\n--- 7. Logging in with New Password via Live Server API ---")
    code, data = post_json("/api/doctors/login", {"login_id": "admin@gmail.com", "password": new_admin_pass})
    print("New Login result:", code, data)
    assert code == 200
    assert data["success"] is True
    assert data["doctor"]["email"] == "admin@gmail.com"

    print("\n--- 8. Restoring Default Doctor Password (admin123) ---")
    # Restore the default password so the default login credentials still work after tests.
    import sys
    from pathlib import Path
    backend_dir = Path(__file__).resolve().parent.parent / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    import database as _db
    conn = _db.get_db()
    cursor = conn.cursor()
    restored_hash = _db.hash_password("admin123")
    cursor.execute("UPDATE doctors SET password_hash=? WHERE LOWER(email)=?", (restored_hash, "admin@gmail.com"))
    conn.commit()
    conn.close()
    # Verify restore
    verify = _db.authenticate_doctor("admin@gmail.com", "admin123")
    assert verify["success"] is True, "Default password restore failed!"
    print("Default Doctor password restored to admin123 successfully.")

    print("\n=========================================")
    print("=== ALL LIVE SERVER INTEGRATION TESTS PASSED! ===")
    print("=========================================")

if __name__ == "__main__":
    test_live_server_endpoints()
