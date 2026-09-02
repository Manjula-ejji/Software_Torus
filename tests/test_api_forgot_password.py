import sys
import json
from flask import Flask, request, jsonify, Response
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

import database

app = Flask(__name__)
database.init_db()

@app.route("/api/doctors/register", methods=["POST"])
def api_register_doctor():
    data = request.get_json() or {}
    name = data.get("name", "")
    email = data.get("email", "")
    password = data.get("password", "")
    mobile = data.get("mobile", "")
    uid = data.get("uid", "") or data.get("professional_id", "")
    if not name or not email or not password:
        return jsonify({"success": False, "error": "Name, email, and password are required."}), 400
    res = database.register_doctor(name, email, password, mobile=mobile, uid=uid)
    return jsonify(res)

@app.route("/api/doctors/login", methods=["POST"])
def api_login_doctor():
    data = request.get_json() or {}
    login_id = data.get("login_id", "")
    password = data.get("password", "")
    if not login_id or not password:
        return jsonify({"success": False, "error": "Email/UID and password are required."}), 400
    res = database.authenticate_doctor(login_id, password)
    return jsonify(res)

@app.route("/api/doctors/forgot-password/send-otp", methods=["POST", "OPTIONS"])
def api_forgot_password_send_otp():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json() or {}
    identifier = data.get("identifier", "") or data.get("email", "") or data.get("login_id", "")
    if not identifier:
        return jsonify({"success": False, "error": "Email or User ID is required."}), 400
    res = database.generate_and_store_reset_otp(identifier)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/doctors/forgot-password/verify-otp", methods=["POST", "OPTIONS"])
def api_forgot_password_verify_otp():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json() or {}
    identifier = data.get("identifier", "") or data.get("email", "") or data.get("login_id", "")
    otp = data.get("otp", "")
    if not identifier or not otp:
        return jsonify({"success": False, "error": "Identifier and 6-digit OTP are required."}), 400
    res = database.verify_reset_otp(identifier, otp)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/doctors/forgot-password/reset", methods=["POST", "OPTIONS"])
def api_forgot_password_reset():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json() or {}
    identifier = data.get("identifier", "") or data.get("email", "") or data.get("login_id", "")
    reset_token = data.get("reset_token", "") or data.get("otp", "")
    new_password = data.get("new_password", "")
    if not identifier or not reset_token or not new_password:
        return jsonify({"success": False, "error": "Identifier, verification token, and new password are required."}), 400
    res = database.reset_doctor_password_with_token(identifier, reset_token, new_password)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

def test_flask_forgot_password_endpoints():
    client = app.test_client()
    database.send_otp_email = lambda email, name, uid, otp: (True, "Delivered")

    print("--- 1. Testing POST /api/doctors/forgot-password/send-otp ---")
    # Non-existent user
    res = client.post("/api/doctors/forgot-password/send-otp",
                      data=json.dumps({"identifier": "fake_doc_999@gmail.com"}),
                      content_type="application/json")
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    print("Non-existent user test passed.")

    # Valid user (admin@gmail.com)
    res = client.post("/api/doctors/forgot-password/send-otp",
                      data=json.dumps({"identifier": "admin@gmail.com"}),
                      content_type="application/json")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "otp" not in data  # No OTP in response
    print("Send OTP test passed for admin@gmail.com.")

    # Get OTP from DB
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT otp FROM password_reset_otps WHERE email = 'admin@gmail.com' AND used = 0 ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    assert row is not None
    otp = row["otp"]
    print(f"Retrieved real OTP from DB: {otp}")

    print("\n--- 2. Testing POST /api/doctors/forgot-password/verify-otp ---")
    # Wrong OTP
    res = client.post("/api/doctors/forgot-password/verify-otp",
                      data=json.dumps({"identifier": "admin@gmail.com", "otp": "999999"}),
                      content_type="application/json")
    assert res.status_code == 400
    assert res.get_json()["success"] is False

    # Correct OTP with UID
    res = client.post("/api/doctors/forgot-password/verify-otp",
                      data=json.dumps({"identifier": "3001", "otp": otp}),
                      content_type="application/json")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    reset_token = data["reset_token"]
    print("Verify OTP test passed.")

    print("\n--- 3. Testing POST /api/doctors/forgot-password/reset ---")
    new_admin_pass = "Doctor@Admin2026!"
    res = client.post("/api/doctors/forgot-password/reset",
                      data=json.dumps({
                          "identifier": "3001",
                          "reset_token": reset_token,
                          "new_password": new_admin_pass
                      }),
                      content_type="application/json")
    assert res.status_code == 200
    assert res.get_json()["success"] is True
    print("Reset Password test passed.")

    print("\n--- 4. Verifying Login with New Password via API ---")
    login_res = client.post("/api/doctors/login",
                            data=json.dumps({"login_id": "admin@gmail.com", "password": new_admin_pass}),
                            content_type="application/json")
    assert login_res.status_code == 200
    assert login_res.get_json()["success"] is True
    print("Login with new password succeeded.")

    print("\n=== ALL FLASK REST API TESTS PASSED! ===")

if __name__ == "__main__":
    test_flask_forgot_password_endpoints()
