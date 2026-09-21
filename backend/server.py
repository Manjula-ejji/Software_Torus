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
        res.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, X-Haptic-Agent-Secret"
        return res

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, X-Haptic-Agent-Secret"
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

@app.route("/api/agora/config", methods=["GET", "OPTIONS"])
def api_agora_config():
    if request.method == "OPTIONS":
        return Response(status=204)
    database.load_env_file()
    token = os.environ.get("AGORA_TOKEN", "").strip()
    app_id = os.environ.get("AGORA_APP_ID", "f320d3475b6d4b70ba512b06d09849d7").strip()
    channel = os.environ.get("AGORA_CHANNEL", "torus").strip()
    return jsonify({
        "appId": app_id,
        "token": token,
        "channel": channel
    })

# -------------------- HAPTIC PAD HARDWARE LINK & AUTO-DETECTION --------------------
import serial
import serial.tools.list_ports
import threading
import time

HAPTIC_AGENT_SECRET = os.environ.get("HAPTIC_AGENT_SECRET", "torus_haptic_sec_2026")
HAPTIC_HEARTBEAT_TIMEOUT = 4.0  # seconds
HAPTIC_BAUD_RATE = 115200

haptic_device_state = {
    "connected": False,
    "status": "NOT_CONNECTED",
    "port": None,
    "device": None,
    "packets_rx": 0,
    "last_packet_time": 0.0,
    "last_heartbeat": 0.0,
    "telemetry": {}
}
haptic_state_lock = threading.Lock()

ST_VID_HEX = "0483"
ST_VID_INT = 1155
ST_DESCRIPTIONS = (
    "stmicroelectronics",
    "stlink",
    "stm32",
    "virtual com port",
    "doctor station",
    "usb serial device",
)
SKIP_TOKENS = ("===", "BOOT", "LOOP", "ERROR", "OK:", "HX711", "BNO")

def parse_haptic_packet(line: str) -> dict | None:
    line = line.strip()
    if not line or any(t in line for t in SKIP_TOKENS):
        return None
    data = {}
    try:
        for field in line.split("|"):
            if ":" not in field:
                continue
            key, _, value = field.partition(":")
            key, value = key.strip(), value.strip()

            if key in ("JX", "JY", "JZ"):
                data[key] = int(value)
            elif key == "SW":
                try:
                    sw_val = int(value)
                    data["SW_M"] = "ON" if (sw_val & 1) else "OFF"
                    data["SW_L"] = "ON" if (sw_val & 2) else "OFF"
                except ValueError:
                    data["SW"] = value
            elif key == "SWM":
                data["SW_M"] = value
            elif key == "SWL":
                data["SW_L"] = value
            elif key in ("IMU1", "I1"):
                data["I1"] = "1.0,0.0,0.0,0.0" if value == "ERR" else value
            elif key in ("IMU2", "I2"):
                data["I2"] = "1.0,0.0,0.0,0.0" if value == "ERR" else value
            elif key == "HX":
                data["HX"] = "NOT READY" if value == "NOT_READY" else value
            else:
                data[key] = value

        if not {"JX", "JY", "JZ"}.issubset(data):
            return None
        return data
    except Exception:
        return None

def find_candidate_ports() -> list[str]:
    ports = []
    try:
        for p in serial.tools.list_ports.comports():
            hwid = (p.hwid or "").lower()
            desc = (p.description or "").lower()
            vid = p.vid
            if (vid == ST_VID_INT) or (ST_VID_HEX in hwid) or any(d in desc for d in ST_DESCRIPTIONS):
                ports.append(p.device)
        for p in serial.tools.list_ports.comports():
            if p.device not in ports:
                ports.append(p.device)
    except Exception:
        pass
    return ports

class LocalHapticPadMonitor(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="HapticPadHardwareMonitor")
        self.running = True
        self.ser: serial.Serial | None = None
        self.active_port: str | None = None

    def run(self):
        print("[HAPTIC HARDWARE] Real USB Haptic Pad background monitor service active.", flush=True)
        while self.running:
            candidate_ports = find_candidate_ports()
            found_port = None
            
            for port_name in candidate_ports:
                try:
                    ser = serial.Serial(port_name, HAPTIC_BAUD_RATE, timeout=0.3)
                    t_end = time.time() + 1.2
                    has_haptic_data = False
                    first_packet = None
                    while time.time() < t_end:
                        raw = ser.readline().decode("utf-8", errors="ignore").strip()
                        if raw and ("JX:" in raw or "JY:" in raw or "JZ:" in raw):
                            pkt = parse_haptic_packet(raw)
                            if pkt:
                                has_haptic_data = True
                                first_packet = pkt
                                break
                    if has_haptic_data:
                        found_port = port_name
                        self.ser = ser
                        self.active_port = port_name
                        with haptic_state_lock:
                            haptic_device_state["connected"] = True
                            haptic_device_state["status"] = "CONNECTED"
                            haptic_device_state["port"] = port_name
                            haptic_device_state["device"] = "STM32 Haptic Pad"
                            haptic_device_state["last_heartbeat"] = time.time()
                            haptic_device_state["last_packet_time"] = time.time()
                            haptic_device_state["packets_rx"] += 1
                            if first_packet:
                                haptic_device_state["telemetry"] = first_packet
                        print(f"[HAPTIC HARDWARE] Real STM32 Haptic Pad online & synchronized on {port_name}", flush=True)
                        break
                    else:
                        ser.close()
                except Exception:
                    continue

            if not found_port:
                time.sleep(1.0)
                continue

            # Active packet reading loop
            while self.running and self.ser and self.ser.is_open:
                try:
                    raw = self.ser.readline().decode("utf-8", errors="ignore").strip()
                    if not raw:
                        continue

                    pkt = parse_haptic_packet(raw)
                    now = time.time()
                    if pkt:
                        with haptic_state_lock:
                            haptic_device_state["connected"] = True
                            haptic_device_state["status"] = "CONNECTED"
                            haptic_device_state["port"] = self.active_port
                            haptic_device_state["device"] = "STM32 Haptic Pad"
                            haptic_device_state["last_heartbeat"] = now
                            haptic_device_state["last_packet_time"] = now
                            haptic_device_state["packets_rx"] += 1
                            haptic_device_state["telemetry"] = pkt
                    else:
                        with haptic_state_lock:
                            haptic_device_state["last_heartbeat"] = now
                except (serial.SerialException, OSError) as err:
                    print(f"[HAPTIC HARDWARE] USB Disconnect / I/O error on {self.active_port}: {err}", flush=True)
                    break
                except Exception as ex:
                    print(f"[HAPTIC HARDWARE] Packet parsing error on {self.active_port}: {ex}", flush=True)
                    break

            # Handle disconnection cleanly
            with haptic_state_lock:
                haptic_device_state["connected"] = False
                haptic_device_state["status"] = "NOT_CONNECTED"
                haptic_device_state["device"] = None
            if self.ser:
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
            self.active_port = None
            print("[HAPTIC HARDWARE] Haptic Pad disconnected. Retrying scan for reconnect...", flush=True)
            time.sleep(1.0)

# Start background real hardware monitor automatically with server
_haptic_monitor = LocalHapticPadMonitor()
_haptic_monitor.start()

def verify_agent_auth():
    secret_header = request.headers.get("X-Haptic-Agent-Secret", "")
    auth_header = request.headers.get("Authorization", "")
    bearer_token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else ""
    return (secret_header == HAPTIC_AGENT_SECRET) or (bearer_token == HAPTIC_AGENT_SECRET)

def get_verified_haptic_status():
    now = time.time()
    with haptic_state_lock:
        if haptic_device_state["connected"]:
            if (now - haptic_device_state["last_heartbeat"]) > HAPTIC_HEARTBEAT_TIMEOUT:
                haptic_device_state["connected"] = False
                haptic_device_state["status"] = "NOT_CONNECTED"
                haptic_device_state["device"] = None
        return dict(haptic_device_state)

@app.route("/api/haptic-pad/report", methods=["POST", "OPTIONS"])
def api_haptic_pad_report():
    if request.method == "OPTIONS":
        return Response(status=204)
    if not verify_agent_auth():
        return jsonify({"success": False, "error": "Unauthorized agent link"}), 401
    
    data = request.get_json(silent=True) or {}
    is_connected = bool(data.get("connected", False))
    now = time.time()

    with haptic_state_lock:
        haptic_device_state["connected"] = is_connected
        haptic_device_state["status"] = "CONNECTED" if is_connected else "NOT_CONNECTED"
        haptic_device_state["port"] = data.get("port")
        haptic_device_state["device"] = data.get("device", "STM32 Haptic Pad") if is_connected else None
        haptic_device_state["packets_rx"] = int(data.get("packets_rx", 0))
        haptic_device_state["last_heartbeat"] = now
        if is_connected:
            haptic_device_state["last_packet_time"] = now
        if "telemetry" in data and isinstance(data["telemetry"], dict):
            haptic_device_state["telemetry"] = data["telemetry"]

    return jsonify({"success": True, "status": haptic_device_state["status"]})

@app.route("/api/haptic-pad/disconnect", methods=["POST", "OPTIONS"])
def api_haptic_pad_disconnect():
    if request.method == "OPTIONS":
        return Response(status=204)
    if not verify_agent_auth():
        return jsonify({"success": False, "error": "Unauthorized agent link"}), 401

    with haptic_state_lock:
        haptic_device_state["connected"] = False
        haptic_device_state["status"] = "NOT_CONNECTED"
        haptic_device_state["device"] = None
    return jsonify({"success": True, "status": "NOT_CONNECTED"})

@app.route("/api/haptic-pad/status", methods=["GET", "OPTIONS"])
def api_haptic_pad_status():
    if request.method == "OPTIONS":
        return Response(status=204)
    
    state = get_verified_haptic_status()
    now = time.time()
    last_seen = round(now - state["last_heartbeat"], 2) if state["last_heartbeat"] > 0 else None

    return jsonify({
        "success": True,
        "connected": state["connected"],
        "status": state["status"],
        "port": state["port"],
        "device": state["device"],
        "packets_rx": state["packets_rx"],
        "last_seen_seconds_ago": last_seen,
        "message": f"Real STM32 Haptic Pad online on {state['port']}" if state["connected"] else "Haptic Pad device not detected. Please verify hardware link.",
        "telemetry": state["telemetry"]
    })

# -------------------- HAPTIC PAD SESSION-BASED ROUTING ENGINE --------------------
# Active Consultation Session Routing mapping:
# Maps Doctor Physical Haptic Pad -> Active Consultation Session ID -> Authorized Patient ONLY
active_haptic_routing = {
    "session_id": None,
    "session_code": None,
    "doctor_id": None,
    "doctor_name": None,
    "patient_id": None,
    "patient_name": None,
    "device_id": None,
    "status": "UNBOUND",  # "ACTIVE" | "UNBOUND"
    "bound_at": 0.0,
    "updated_at": 0.0
}
haptic_routing_lock = threading.Lock()

@app.route("/api/haptic-pad/session/bind", methods=["POST", "OPTIONS"])
def api_haptic_pad_session_bind():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    session_id = str(data.get("session_id") or data.get("sessionId") or "").strip()
    session_code = str(data.get("session_code") or data.get("sessionCode") or "").strip()
    doctor_id = str(data.get("doctor_id") or data.get("doctorId") or "").strip()
    doctor_name = str(data.get("doctor_name") or data.get("doctorName") or "").strip()
    patient_id = str(data.get("patient_id") or data.get("patientId") or "").strip()
    patient_name = str(data.get("patient_name") or data.get("patientName") or "").strip()
    device_id = str(data.get("device_id") or data.get("deviceId") or "").strip()

    if not session_id and not patient_id:
        return jsonify({"success": False, "error": "session_id and/or patient_id are required to bind consultation."}), 400

    now = time.time()
    with haptic_routing_lock:
        active_haptic_routing["session_id"] = session_id
        active_haptic_routing["session_code"] = session_code or f"TORUS-CLI-{patient_id}"
        active_haptic_routing["doctor_id"] = doctor_id
        active_haptic_routing["doctor_name"] = doctor_name
        active_haptic_routing["patient_id"] = patient_id
        active_haptic_routing["patient_name"] = patient_name
        active_haptic_routing["device_id"] = device_id
        active_haptic_routing["status"] = "ACTIVE"
        active_haptic_routing["bound_at"] = now
        active_haptic_routing["updated_at"] = now

    print(f"[HAPTIC ROUTING] Bound Haptic Pad signals exclusively to Session '{session_id}' -> Patient '{patient_name}' (ID: {patient_id})", flush=True)
    return jsonify({
        "success": True,
        "message": f"Haptic Pad telemetry routing active for {patient_name or patient_id}",
        "routing": dict(active_haptic_routing)
    })

@app.route("/api/haptic-pad/session/unbind", methods=["POST", "OPTIONS"])
def api_haptic_pad_session_unbind():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    session_id = str(data.get("session_id") or data.get("sessionId") or "").strip()

    with haptic_routing_lock:
        prev_session = active_haptic_routing.get("session_id")
        prev_patient = active_haptic_routing.get("patient_name") or active_haptic_routing.get("patient_id")
        # If session_id provided, only unbind if matching or if unbind all
        if not session_id or session_id == prev_session:
            active_haptic_routing["session_id"] = None
            active_haptic_routing["session_code"] = None
            active_haptic_routing["patient_id"] = None
            active_haptic_routing["patient_name"] = None
            active_haptic_routing["device_id"] = None
            active_haptic_routing["status"] = "UNBOUND"
            active_haptic_routing["updated_at"] = time.time()
            print(f"[HAPTIC ROUTING] Unbound Haptic Pad from previous session '{prev_session}' ({prev_patient}). Signals stopped.", flush=True)

    return jsonify({"success": True, "status": "UNBOUND"})

@app.route("/api/haptic-pad/session/active", methods=["GET", "OPTIONS"])
def api_haptic_pad_session_active():
    if request.method == "OPTIONS":
        return Response(status=204)
    with haptic_routing_lock:
        routing = dict(active_haptic_routing)
    hw_state = get_verified_haptic_status()
    return jsonify({
        "success": True,
        "active": routing["status"] == "ACTIVE" and bool(routing.get("session_id")),
        "routing": routing,
        "haptic_connected": hw_state["connected"]
    })

@app.route("/api/haptic-pad/patient/telemetry", methods=["GET", "OPTIONS"])
def api_haptic_pad_patient_telemetry():
    if request.method == "OPTIONS":
        return Response(status=204)
    
    hw_state = get_verified_haptic_status()
    with haptic_routing_lock:
        routing = dict(active_haptic_routing)

    # 1. Verify if an active consultation session is bound
    if routing["status"] != "ACTIVE" or not routing.get("session_id"):
        return jsonify({
            "authorized": False,
            "routing_status": "NO_ACTIVE_CONSULTATION",
            "error": "No consultation session is currently active with the doctor.",
            "haptic_connected": hw_state["connected"],
            "telemetry": None
        })

    # 2. Strict Session & Patient Validation
    req_patient_id = (request.args.get("patient_id") or request.args.get("patientId") or "").strip().lower()
    req_session_id = (request.args.get("session_id") or request.args.get("sessionId") or "").strip().lower()
    req_patient_name = (request.args.get("patient_name") or request.args.get("patientName") or "").strip().lower()

    bound_patient_id = str(routing.get("patient_id") or "").strip().lower()
    bound_session_id = str(routing.get("session_id") or "").strip().lower()
    bound_patient_name = str(routing.get("patient_name") or "").strip().lower()

    is_authorized = False
    if req_session_id and req_session_id == bound_session_id:
        is_authorized = True
    elif req_patient_id and req_patient_id == bound_patient_id:
        is_authorized = True
    elif req_patient_name and req_patient_name == bound_patient_name:
        is_authorized = True

    if not is_authorized:
        return jsonify({
            "authorized": False,
            "routing_status": "BLOCKED_UNAUTHORIZED_PATIENT",
            "error": "Access denied: Haptic signals are strictly routed to the doctor's currently active consultation session.",
            "active_session_id": routing.get("session_id"),
            "haptic_connected": hw_state["connected"],
            "telemetry": None
        })

    # Authorized: Deliver real STM32 Haptic Pad telemetry
    return jsonify({
        "authorized": True,
        "routing_status": "ROUTED_ACTIVE_SESSION",
        "session_id": routing.get("session_id"),
        "session_code": routing.get("session_code"),
        "patient_id": routing.get("patient_id"),
        "patient_name": routing.get("patient_name"),
        "device_id": routing.get("device_id"),
        "haptic_connected": hw_state["connected"],
        "packets_rx": hw_state["packets_rx"],
        "telemetry": hw_state["telemetry"],
        "timestamp": time.time()
    })

@app.route("/api/haptic-pad/patient/stream", methods=["GET", "OPTIONS"])
def api_haptic_pad_patient_stream():
    if request.method == "OPTIONS":
        return Response(status=204)

    req_patient_id = (request.args.get("patient_id") or request.args.get("patientId") or "").strip().lower()
    req_session_id = (request.args.get("session_id") or request.args.get("sessionId") or "").strip().lower()
    req_patient_name = (request.args.get("patient_name") or request.args.get("patientName") or "").strip().lower()

    import json

    def generate_patient_events():
        while True:
            hw_state = get_verified_haptic_status()
            with haptic_routing_lock:
                routing = dict(active_haptic_routing)

            bound_patient_id = str(routing.get("patient_id") or "").strip().lower()
            bound_session_id = str(routing.get("session_id") or "").strip().lower()
            bound_patient_name = str(routing.get("patient_name") or "").strip().lower()

            is_active = (routing["status"] == "ACTIVE" and bool(routing.get("session_id")))
            is_auth = False
            if is_active:
                if req_session_id and req_session_id == bound_session_id:
                    is_auth = True
                elif req_patient_id and req_patient_id == bound_patient_id:
                    is_auth = True
                elif req_patient_name and req_patient_name == bound_patient_name:
                    is_auth = True

            if not is_active:
                payload = {
                    "authorized": False,
                    "routing_status": "NO_ACTIVE_CONSULTATION",
                    "telemetry": None,
                    "haptic_connected": hw_state["connected"]
                }
            elif not is_auth:
                payload = {
                    "authorized": False,
                    "routing_status": "BLOCKED_UNAUTHORIZED_PATIENT",
                    "active_session_id": routing.get("session_id"),
                    "telemetry": None,
                    "haptic_connected": hw_state["connected"]
                }
            else:
                payload = {
                    "authorized": True,
                    "routing_status": "ROUTED_ACTIVE_SESSION",
                    "session_id": routing.get("session_id"),
                    "patient_id": routing.get("patient_id"),
                    "patient_name": routing.get("patient_name"),
                    "device_id": routing.get("device_id"),
                    "haptic_connected": hw_state["connected"],
                    "packets_rx": hw_state["packets_rx"],
                    "telemetry": hw_state["telemetry"],
                    "timestamp": time.time()
                }

            yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(0.05)  # 20Hz update rate

    return Response(generate_patient_events(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Access-Control-Allow-Origin": "*"
    })

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

@app.route("/api/doctors/profile", methods=["GET", "OPTIONS"])
def api_get_doctor_profile():
    if request.method == "OPTIONS":
        return Response(status=204)
    identifier = request.args.get("identifier", "").strip() or request.args.get("email", "").strip() or request.args.get("uid", "").strip()
    if not identifier:
        return jsonify({"success": False, "error": "Doctor identifier is required."}), 400
    res = database.get_doctor_profile(identifier)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/doctors/profile/update", methods=["POST", "OPTIONS"])
def api_update_doctor_profile():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier", "").strip() or data.get("email", "").strip() or data.get("uid", "").strip()
    name = data.get("name", "").strip()
    mobile = data.get("mobile", "").strip()
    if not identifier:
        return jsonify({"success": False, "error": "Doctor identifier (email or UID) is required."}), 400
    res = database.update_doctor_profile(identifier, name=name, mobile=mobile)
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

# -------------------- CLINICAL PATIENTS & APPOINTMENTS API --------------------
@app.route("/api/patients/clinical-register", methods=["POST", "OPTIONS"])
def api_clinical_register_patient():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    name = (data.get("name", "") or data.get("full_name", "")).strip()
    age = data.get("age", "")
    gender = data.get("gender", "Male")
    mobile = data.get("mobile", "").strip()
    email = data.get("email", "").strip()
    scan_type = data.get("scan_type", "").strip()
    appointment_date = data.get("appointment_date", "").strip()
    blood_group = data.get("blood_group", "").strip()

    res = database.register_clinical_patient(
        name=name, age=age, gender=gender, mobile=mobile,
        email=email, scan_type=scan_type,
        appointment_date=appointment_date, blood_group=blood_group
    )
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/patients/clinical-list", methods=["GET", "OPTIONS"])
def api_clinical_patients_list():
    if request.method == "OPTIONS":
        return Response(status=204)
    patients = database.get_clinical_patients()
    return jsonify({"success": True, "patients": patients})

@app.route("/api/doctors/list", methods=["GET", "OPTIONS"])
def api_doctors_list():
    if request.method == "OPTIONS":
        return Response(status=204)
    doctors = database.get_all_doctors_list()
    return jsonify({"success": True, "doctors": doctors})

@app.route("/api/appointments/schedule", methods=["POST", "OPTIONS"])
def api_schedule_appointment():
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    patient = data.get("patient", "").strip() or data.get("patient_id", "").strip() or data.get("patient_name", "").strip()
    scan_type = data.get("scan_type", "").strip()
    doctor = data.get("doctor", "").strip() or data.get("doctor_id", "").strip() or data.get("doctor_name", "").strip()
    slot_day = str(data.get("slot_day", "")).strip()
    slot_month = str(data.get("slot_month", "")).strip()
    slot_year = str(data.get("slot_year", "")).strip()
    slot_time = str(data.get("slot_time", "")).strip()

    if (not slot_day or not slot_month or not slot_year) and data.get("appointment_date"):
        parts = str(data.get("appointment_date")).split("-")
        if len(parts) == 3:
            slot_year, slot_month, slot_day = parts[0], parts[1], parts[2]
    if not slot_time and data.get("appointment_time"):
        slot_time = str(data.get("appointment_time")).strip()

    res = database.schedule_scan_appointment(
        patient_identifier=patient, scan_type=scan_type, doctor_identifier=doctor,
        slot_day=slot_day, slot_month=slot_month, slot_year=slot_year, slot_time=slot_time
    )
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/appointments/list", methods=["GET", "OPTIONS"])
def api_appointments_list():
    if request.method == "OPTIONS":
        return Response(status=204)
    appts = database.get_scheduled_appointments()
    return jsonify({"success": True, "appointments": appts})


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

@app.route("/api/biometrics/slots", methods=["GET", "OPTIONS"])
def api_biometrics_slots():
    """Returns current R1-R20 slot allocation: who is registered in each slot."""
    if request.method == "OPTIONS":
        return Response(status=204)
    info = biometrics.hardware_manager.get_slot_info()
    return jsonify(info)

@app.route("/api/biometrics/enroll", methods=["POST", "OPTIONS"])
def api_biometrics_enroll():
    """
    Enroll a doctor's fingerprint. Automatically assigns the next available slot (R1-R20).
    Request body: { "identifier": "email_or_uid" }
    Response: { "success": true, "fingerprint_id": "R3", "message": "..." }
    """
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    raw_ident = data.get("identifier") or data.get("email") or data.get("uid") or ""
    identifier = str(raw_ident).strip()

    if not identifier:
        return jsonify({
            "success": False,
            "error": "Doctor Email or User ID is required for biometric registration."
        }), 400

    res = biometrics.hardware_manager.enroll_fingerprint(identifier)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/biometrics/verify", methods=["POST", "OPTIONS"])
def api_biometrics_verify():
    """
    Verify fingerprint via 1:N hardware search.
    If identifier is provided: confirms the fingerprint belongs specifically to THAT doctor.
    If no identifier: looks up whoever owns the matched slot.
    Request body: { "identifier": "email_or_uid" }  (optional)
    Response: { "success": true, "matched": true, "fingerprint_id": "R2", "doctor": {...} }
    """
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    raw_ident = data.get("identifier") or data.get("email") or data.get("uid") or ""
    identifier = str(raw_ident).strip() if raw_ident else None

    res = biometrics.hardware_manager.verify_fingerprint(identifier)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/api/biometrics/reset", methods=["POST", "DELETE", "OPTIONS"])
def api_biometrics_reset():
    """
    Clears all active biometric registrations from the database.
    Frees all 20 slots (R1..R20) for fresh registrations.
    """
    if request.method == "OPTIONS":
        return Response(status=204)
    res = database.reset_all_biometrics()
    return jsonify(res), 200

@app.route("/api/biometrics/delete", methods=["POST", "DELETE", "OPTIONS"])
def api_biometrics_delete():
    """
    Deletes a specific doctor's biometric registration by email or UID.
    Request body: { "identifier": "admin@gmail.com" }
    """
    if request.method == "OPTIONS":
        return Response(status=204)
    data = request.get_json(silent=True) or {}
    identifier = (
        data.get("identifier", "").strip()
        or data.get("email", "").strip()
        or data.get("uid", "").strip()
    )
    if not identifier:
        return jsonify({"success": False, "error": "Identifier (email or UID) is required."}), 400
    res = database.delete_doctor_biometric(identifier)
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
    port = int(os.environ.get("PORT", os.environ.get("SERVER_PORT", "3000")))
    print(f"[TORUS Backend] Server starting on http://127.0.0.1:{port} ...")
    app.run(host=host, port=port, threaded=True)

if __name__ == "__main__":
    main()
