"""
TORUS Clinical Robotics Platform - Backend API Server
Handles Doctor, Patient & Viewer Registration, Authentication, Password Reset, and Real SMTP OTP Dispatch.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from flask import Flask, request, jsonify, Response, send_from_directory

# Add backend directory to sys.path
APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"

sys.path.insert(0, str(APP_DIR))

import database

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
database.init_db()

try:
    from flask_cors import CORS
    CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
except Exception:
    pass

# -------------------- GLOBAL CORS HEADERS --------------------
@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        res = Response(status=204)
        res.headers["Access-Control-Allow-Origin"] = "*"
        res.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        res.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
        return res

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    if request.path.endswith((".html", ".js", ".css")) or request.path in ["/", "/index.html"]:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# -------------------- HEALTH & STATUS CHECKS --------------------
@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({"status": "healthy", "service": "TORUS Healthcare Authentication Engine"})

@app.route("/api/status", methods=["GET", "OPTIONS"])
def api_system_status():
    if request.method == "OPTIONS":
        return Response(status=204)
    return jsonify({
        "status": "STOPPED",
        "voltage": 50.0,
        "gain": 40.0,
        "display": True,
        "tgc_enabled": False,
        "tgc_sliders": [50, 12, 3, 77, 90, 30]
    })

@app.route("/api/remote-input", methods=["POST", "OPTIONS"])
def api_remote_input():
    if request.method == "OPTIONS":
        return Response(status=204)
    return jsonify({"status": "success", "executed": True})

# -------------------- DOCTOR AUTHENTICATION API --------------------
@app.route("/api/doctors/register", methods=["POST", "OPTIONS"])
def api_register_doctor():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "")
    mobile = data.get("mobile", "").strip()
    uid = data.get("uid", "").strip() or data.get("professional_id", "").strip()

    if not name or not email or not password:
        return jsonify({"success": False, "error": "Name, email, and password are required."}), 400

    res = database.register_doctor(name, email, password, mobile=mobile, uid=uid)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/doctors/login", methods=["POST", "OPTIONS"])
def api_login_doctor():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    login_id = data.get("login_id", "").strip() or data.get("email", "").strip()
    password = data.get("password", "")

    if not login_id or not password:
        return jsonify({"success": False, "error": "Email/UID and password are required."}), 400

    res = database.authenticate_doctor(login_id, password)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/doctors/forgot-password/send-otp", methods=["POST", "OPTIONS"])
def api_forgot_password_send_otp():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip() or data.get("login_id", "").strip()

    if not identifier:
        return jsonify({"success": False, "error": "Email or User ID is required."}), 400

    res = database.generate_and_store_reset_otp(identifier)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/doctors/forgot-password/verify-otp", methods=["POST", "OPTIONS"])
def api_forgot_password_verify_otp():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip() or data.get("login_id", "").strip()
    otp = str(data.get("otp", "")).strip()

    if not identifier or not otp:
        return jsonify({"success": False, "error": "Identifier and 6-digit OTP are required."}), 400

    res = database.verify_reset_otp(identifier, otp)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/doctors/forgot-password/reset", methods=["POST", "OPTIONS"])
def api_forgot_password_reset():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip() or data.get("login_id", "").strip()
    reset_token = data.get("reset_token", "").strip() or data.get("otp", "").strip()
    new_password = data.get("new_password", "")

    if not identifier or not reset_token or not new_password:
        return jsonify({"success": False, "error": "Identifier, verification token, and new password are required."}), 400

    res = database.reset_doctor_password_with_token(identifier, reset_token, new_password)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/doctors/forgot-password", methods=["POST", "OPTIONS"])
def api_forgot_password():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip()
    new_password = data.get("new_password", "")
    reset_token = data.get("reset_token", "").strip()

    if new_password and reset_token:
        res = database.reset_doctor_password_with_token(identifier, reset_token, new_password)
    elif identifier:
        res = database.generate_and_store_reset_otp(identifier)
    else:
        return jsonify({"success": False, "error": "Email or User ID is required."}), 400

    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

# -------------------- PATIENT AUTHENTICATION API --------------------
@app.route("/api/patients/register", methods=["POST", "OPTIONS"])
def api_register_patient():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "")
    mobile = data.get("mobile", "").strip()
    uid = data.get("uid", "").strip() or data.get("patient_id", "").strip()

    if not name or not email or not password:
        return jsonify({"success": False, "error": "Name, email, and password are required."}), 400

    res = database.register_patient(name, email, password, mobile=mobile, uid=uid)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/patients/login", methods=["POST", "OPTIONS"])
def api_login_patient():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    login_id = data.get("login_id", "").strip() or data.get("email", "").strip()
    password = data.get("password", "")

    if not login_id or not password:
        return jsonify({"success": False, "error": "Email/Patient ID and password are required."}), 400

    res = database.authenticate_patient(login_id, password)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/patients/forgot-password/send-otp", methods=["POST", "OPTIONS"])
def api_patient_forgot_password_send_otp():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip() or data.get("login_id", "").strip()

    if not identifier:
        return jsonify({"success": False, "error": "Email or Patient ID is required."}), 400

    res = database.generate_and_store_patient_reset_otp(identifier)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/patients/forgot-password/verify-otp", methods=["POST", "OPTIONS"])
def api_patient_forgot_password_verify_otp():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip() or data.get("login_id", "").strip()
    otp = str(data.get("otp", "")).strip()

    if not identifier or not otp:
        return jsonify({"success": False, "error": "Identifier and 6-digit OTP are required."}), 400

    res = database.verify_patient_reset_otp(identifier, otp)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/patients/forgot-password/reset", methods=["POST", "OPTIONS"])
def api_patient_forgot_password_reset():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip() or data.get("login_id", "").strip()
    reset_token = data.get("reset_token", "").strip() or data.get("otp", "").strip()
    new_password = data.get("new_password", "")

    if not identifier or not reset_token or not new_password:
        return jsonify({"success": False, "error": "Identifier, verification token, and new password are required."}), 400

    res = database.reset_patient_password_with_token(identifier, reset_token, new_password)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/patients/forgot-password", methods=["POST", "OPTIONS"])
def api_patient_forgot_password():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip()
    new_password = data.get("new_password", "")
    reset_token = data.get("reset_token", "").strip()

    if new_password and reset_token:
        res = database.reset_patient_password_with_token(identifier, reset_token, new_password)
    elif identifier:
        res = database.generate_and_store_patient_reset_otp(identifier)
    else:
        return jsonify({"success": False, "error": "Email or Patient ID is required."}), 400

    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

# -------------------- VIEWER AUTHENTICATION API --------------------
@app.route("/api/viewers/register", methods=["POST", "OPTIONS"])
def api_register_viewer():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "")
    mobile = data.get("mobile", "").strip()
    uid = data.get("uid", "").strip() or data.get("viewer_id", "").strip()

    if not name or not email or not password:
        return jsonify({"success": False, "error": "Name, email, and password are required."}), 400

    res = database.register_viewer(name, email, password, mobile=mobile, uid=uid)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/viewers/login", methods=["POST", "OPTIONS"])
def api_login_viewer():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    login_id = data.get("login_id", "").strip() or data.get("email", "").strip()
    password = data.get("password", "")

    if not login_id or not password:
        return jsonify({"success": False, "error": "Email/Viewer ID and password are required."}), 400

    res = database.authenticate_viewer(login_id, password)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/viewers/forgot-password/send-otp", methods=["POST", "OPTIONS"])
def api_viewer_forgot_password_send_otp():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip() or data.get("login_id", "").strip()

    if not identifier:
        return jsonify({"success": False, "error": "Email or Viewer ID is required."}), 400

    res = database.generate_and_store_viewer_reset_otp(identifier)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/viewers/forgot-password/verify-otp", methods=["POST", "OPTIONS"])
def api_viewer_forgot_password_verify_otp():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip() or data.get("login_id", "").strip()
    otp = str(data.get("otp", "")).strip()

    if not identifier or not otp:
        return jsonify({"success": False, "error": "Identifier and 6-digit OTP are required."}), 400

    res = database.verify_viewer_reset_otp(identifier, otp)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/viewers/forgot-password/reset", methods=["POST", "OPTIONS"])
def api_viewer_forgot_password_reset():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip() or data.get("login_id", "").strip()
    reset_token = data.get("reset_token", "").strip() or data.get("otp", "").strip()
    new_password = data.get("new_password", "")

    if not identifier or not reset_token or not new_password:
        return jsonify({"success": False, "error": "Identifier, verification token, and new password are required."}), 400

    res = database.reset_viewer_password_with_token(identifier, reset_token, new_password)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/viewers/forgot-password", methods=["POST", "OPTIONS"])
def api_viewer_forgot_password():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip()
    new_password = data.get("new_password", "")
    reset_token = data.get("reset_token", "").strip()

    if new_password and reset_token:
        res = database.reset_viewer_password_with_token(identifier, reset_token, new_password)
    elif identifier:
        res = database.generate_and_store_viewer_reset_otp(identifier)
    else:
        return jsonify({"success": False, "error": "Email or Viewer ID is required."}), 400

    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

# -------------------- UNIFIED ROLE-BASED AUTHENTICATION API --------------------
@app.route("/api/auth/register", methods=["POST", "OPTIONS"])
@app.route("/api/register", methods=["POST", "OPTIONS"])
def api_unified_register():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    role = data.get("role", "doctor").strip().lower()
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "")
    mobile = data.get("mobile", "").strip()
    uid = data.get("uid", "").strip()

    if not name or not email or not password:
        return jsonify({"success": False, "error": "Name, email, and password are required."}), 400

    res = database.register_for_role(name, email, password, mobile=mobile, uid=uid, role=role)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/auth/login", methods=["POST", "OPTIONS"])
@app.route("/api/login", methods=["POST", "OPTIONS"])
def api_unified_login():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    role = data.get("role", "doctor").strip().lower()
    login_id = data.get("login_id", "").strip() or data.get("email", "").strip()
    password = data.get("password", "")

    if not login_id or not password:
        return jsonify({"success": False, "error": "Email/User ID and password are required."}), 400

    res = database.authenticate_for_role(login_id, password, role=role)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/forgot-password/send-otp", methods=["POST", "OPTIONS"])
@app.route("/api/auth/forgot-password/send-otp", methods=["POST", "OPTIONS"])
def api_unified_forgot_password_send_otp():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    role = data.get("role", "doctor").strip().lower()
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip() or data.get("login_id", "").strip()

    if not identifier:
        return jsonify({"success": False, "error": "Email or User ID is required."}), 400

    res = database.generate_and_store_otp_for_role(identifier, role=role)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/forgot-password/verify-otp", methods=["POST", "OPTIONS"])
@app.route("/api/auth/forgot-password/verify-otp", methods=["POST", "OPTIONS"])
def api_unified_forgot_password_verify_otp():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    role = data.get("role", "doctor").strip().lower()
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip() or data.get("login_id", "").strip()
    otp = str(data.get("otp", "")).strip()

    if not identifier or not otp:
        return jsonify({"success": False, "error": "Identifier and 6-digit OTP are required."}), 400

    res = database.verify_otp_for_role(identifier, otp, role=role)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/forgot-password/reset", methods=["POST", "OPTIONS"])
@app.route("/api/auth/forgot-password/reset", methods=["POST", "OPTIONS"])
def api_unified_forgot_password_reset():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    role = data.get("role", "doctor").strip().lower()
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip() or data.get("login_id", "").strip()
    reset_token = data.get("reset_token", "").strip() or data.get("otp", "").strip()
    new_password = data.get("new_password", "")

    if not identifier or not reset_token or not new_password:
        return jsonify({"success": False, "error": "Identifier, verification token, and new password are required."}), 400

    res = database.reset_password_for_role(identifier, reset_token, new_password, role=role)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

# -------------------- REAL BIOMETRIC HARDWARE & SERIAL API --------------------
import biometrics

@app.route("/api/biometrics/status", methods=["GET", "OPTIONS"])
def api_biometrics_status():
    if request.method == "OPTIONS":
        return Response(status=204)
    status = biometrics.hardware_manager.get_status()
    return jsonify(status)

@app.route("/api/biometrics/enroll", methods=["POST", "OPTIONS"])
def api_biometrics_enroll():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip() or data.get("uid", "").strip()

    if not identifier:
        return jsonify({"success": False, "error": "Doctor Email or User ID is required for biometric registration."}), 400

    res = biometrics.hardware_manager.enroll_fingerprint(identifier)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/biometrics/verify", methods=["POST", "OPTIONS"])
def api_biometrics_verify():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip() or data.get("uid", "").strip()

    res = biometrics.hardware_manager.verify_fingerprint(identifier or None)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

# -------------------- CLINICAL SESSIONS API --------------------
@app.route("/api/sessions/create", methods=["POST", "OPTIONS"])
def api_create_session():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    doctor_id = data.get("doctor_id")
    doctor_uid = str(data.get("doctor_uid") or data.get("uid") or "").strip()
    doctor_name = str(data.get("doctor_name") or data.get("name") or "").strip()
    doctor_email = str(data.get("doctor_email") or data.get("email") or "").strip()
    channel_name = str(data.get("channel_name") or data.get("channel") or "torus").strip() or "torus"

    res = database.create_clinical_session(
        doctor_id=doctor_id,
        doctor_uid=doctor_uid,
        doctor_name=doctor_name,
        doctor_email=doctor_email,
        channel_name=channel_name
    )
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/sessions/join", methods=["POST", "OPTIONS"])
def api_join_session():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    session_code = str(data.get("session_code") or data.get("sessionCode") or data.get("code") or "").strip()
    participant_name = str(data.get("participant_name") or data.get("viewer_name") or data.get("name") or "").strip()
    role = str(data.get("role") or "viewer").strip().lower()
    participant_uid = str(data.get("participant_uid") or data.get("uid") or "").strip()

    if not session_code:
        return jsonify({"success": False, "error": "Please enter the session code."}), 400

    res = database.join_clinical_session(
        session_code=session_code,
        participant_name=participant_name,
        role=role,
        participant_uid=participant_uid
    )
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/sessions/validate", methods=["POST", "OPTIONS"])
def api_validate_session():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    session_code = data.get("session_code", "").strip() or data.get("sessionCode", "").strip() or data.get("code", "").strip()

    if not session_code:
        return jsonify({"success": False, "error": "Please enter the session code."}), 400

    res = database.validate_clinical_session(session_code)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/sessions/<session_code>", methods=["GET", "OPTIONS"])
def api_get_session(session_code):
    if request.method == "OPTIONS":
        return Response(status=204)
    session = database.get_clinical_session(session_code)
    if not session:
        return jsonify({"success": False, "error": "Invalid session code."}), 404
    return jsonify({"success": True, "session": session})

@app.route("/api/sessions/close", methods=["POST", "OPTIONS"])
def api_close_session():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    session_code = data.get("session_code", "").strip() or data.get("code", "").strip()
    if not session_code:
        return jsonify({"success": False, "error": "Session code is required."}), 400
    res = database.close_clinical_session(session_code)
    return jsonify(res)

# -------------------- STATIC FILE SERVING --------------------
@app.route("/")
def serve_root():
    return send_from_directory(str(FRONTEND_DIR), "index.html")

@app.route("/frontend/<path:path>")
def serve_frontend_prefix(path):
    file_path = FRONTEND_DIR / path
    if file_path.is_file():
        return send_from_directory(str(FRONTEND_DIR), path)
    return send_from_directory(str(FRONTEND_DIR), "index.html")

@app.route("/<path:path>")
def serve_static_files(path):
    file_path = FRONTEND_DIR / path
    if file_path.is_file():
        return send_from_directory(str(FRONTEND_DIR), path)
    return send_from_directory(str(FRONTEND_DIR), "index.html")

def main():
    host = os.environ.get("SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("SERVER_PORT", "3000"))
    print(f"[TORUS Backend] Server starting on http://127.0.0.1:{port} ...")
    app.run(host=host, port=port, threaded=True)

if __name__ == "__main__":
    main()
