"""
TORUS Healthcare - Biometric Scanner & Serial Integration Engine
HLK-FPM383C Optical/Capacitive Fingerprint Sensor on STM32F446RE (NUCLEO-F446RE)

Architecture & Hardware Specifications:
  - Microcontroller: STM32F446RE (Nucleo-64)
  - Fingerprint Module: HLK-FPM383C
  - Sensor UART: STM32 USART1 (PA9-TX, PA10-RX) @ 57600 baud, 8-N-1
  - Host Serial: STM32 USART2 via ST-Link VCP @ 57600 / 115200 baud, 8-N-1
  - TOUCHOUT: PB5 / PC0 input
  - Sensor Capacity: 60 fingerprint templates (IDs 0..59)
  - TORUS Slots: R1..R59 mapped 1:1 to hardware IDs 1..59

Firmware Protocols Supported:
  1. Primary: HLK-FPM383C JSON Line Protocol (fpm383c_backend.ino)
     - Requests:
         {"id":"r1","cmd":"verify","user":1,"slot":1,"timeout_ms":10000} (1:1 Exact Match)
         {"id":"r1","cmd":"verify","timeout_ms":10000}                   (1:N Search)
         {"id":"r2","cmd":"enroll","user":"doc@torus.med","slot":1}       (6-Stage Enroll)
         {"id":"r3","cmd":"ping"} / {"id":"r3","cmd":"status"}
         {"id":"r4","cmd":"delete","slot":1}
         {"id":"r5","cmd":"empty"}
     - Replies:
         {"id":"r1","cmd":"verify","ok":true,"matched":true,"slot":1,"score":3961}
         {"id":"r1","cmd":"verify","ok":true,"matched":false}
         {"id":"r2","cmd":"enroll","user":...,"ok":true,"slot":1,"elapsed_ms":...,"press_ms":[...]}
         {"id":"r2","event":"progress","step":"place_finger","press":1,"of":6,"percent":16}
     - Startup banner:
         {"event":"ready","sensor":true}

  2. Fallback: Direct Command Mode (torus_fingerprint_scanner.ino / legacy sketches)
     - Commands: STATUS, ENROLL <id>, MATCH, MATCH <id>, DELETE <id>, EMPTY
"""

from __future__ import annotations

import os
import re
import time
import json
import datetime
import threading
import uuid
from typing import Optional, Dict, Any

try:
    import serial
    import serial.tools.list_ports
    PYSERIAL_AVAILABLE = True
except ImportError:
    PYSERIAL_AVAILABLE = False

import database


class BiometricHardwareManager:
    """
    Manages communication with the STM32F446RE + HLK-FPM383C fingerprint sensor.
    Supports both the backend-driven JSON protocol (fpm383c_backend.ino) and legacy text mode.
    """

    def __init__(self):
        self.serial_port: Optional[str] = (
            os.environ.get("BIOMETRIC_SERIAL_PORT", "").strip() or None
        )
        self.baud_rate: int = int(os.environ.get("BIOMETRIC_BAUD_RATE", "57600"))
        self._serial_conn: Optional[Any] = None
        self._lock = threading.RLock()
        self._progress_lock = threading.Lock()
        self._last_probe_time: float = 0.0
        self._probe_cooldown: float = 1.0
        self.is_connected: bool = False
        self.scanner_model: str = "STM32 / HLK-FPM383C Fingerprint Scanner"
        self.protocol_type: str = "fpm383c_json"
        self.last_error: Optional[str] = None
        self.template_count: int = 0
        self.max_templates: int = 60
        self._is_busy: bool = False

        # Thread-safe dictionary to track live enrollment progress (stage 1..6)
        self._enroll_progress: Dict[str, Any] = {
            "in_progress": False,
            "identifier": None,
            "slot": None,
            "stage": 0,
            "progress": 0,
            "message": "Idle"
        }

        self._probe_hardware()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _close_serial(self) -> None:
        """Safely closes serial connection without leaving zombie handles."""
        if self._serial_conn:
            try:
                self._serial_conn.close()
            except Exception:
                pass
        self._serial_conn = None
        self.serial_port = None
        self.is_connected = False

    def _drain_serial_buffer(self) -> None:
        """Flushes input/output OS buffers and discards any pending bytes on the wire."""
        if not self._serial_conn:
            return
        try:
            self._serial_conn.reset_input_buffer()
            self._serial_conn.reset_output_buffer()
            while self._serial_conn and self._serial_conn.in_waiting:
                self._serial_conn.read(self._serial_conn.in_waiting)
        except Exception:
            pass

    def _drain_trailing_bytes(self, window_seconds: float = 0.005) -> None:
        """Drains any trailing lines/bytes emitted by hardware after command completion."""
        if not self._serial_conn:
            return
        try:
            if window_seconds > 0:
                time.sleep(window_seconds)
            while self._serial_conn and self._serial_conn.in_waiting:
                self._serial_conn.read(self._serial_conn.in_waiting)
        except Exception:
            pass

    def _open_port(self, port_name: str, baud: int) -> Optional[Any]:
        """Opens serial port with clean terminal settings and low latency."""
        try:
            conn = serial.Serial(
                port_name, baud,
                timeout=0.15,
                write_timeout=0.5,
                dsrdtr=False,
                rtscts=False
            )
            time.sleep(0.02)  # Fast settle time (20ms)
            return conn
        except Exception:
            return None

    def _probe_hardware(self, force: bool = False) -> bool:
        """
        Probes serial ports dynamically and validates the STM32 HLK-FPM383C controller.
        Supports both fpm383c_backend JSON protocol and legacy text commands.
        Fast-path: tries configured/last known port first.
        """
        now = time.perf_counter()
        if not force and not self.is_connected and (now - self._last_probe_time) < self._probe_cooldown:
            return False
        self._last_probe_time = now

        if not PYSERIAL_AVAILABLE:
            self.last_error = "pyserial not installed. Cannot communicate with biometric scanner."
            self.is_connected = False
            return False

        try:
            all_ports = list(serial.tools.list_ports.comports())
            available_ports = [
                p for p in all_ports
                if not any(b in (p.description or "").lower() or b in (p.hwid or "").lower() for b in ["bluetooth", "bthenum"])
            ]
            if not available_ports and not self.serial_port:
                self.is_connected = False
                self.last_error = "Fingerprint scanner not connected. No serial ports found."
                return False

            candidate_ports = []
            if self.serial_port and any(p.device == self.serial_port for p in available_ports):
                candidate_ports.append(self.serial_port)

            # Prioritize STLink or Nucleo COM port
            for p in available_ports:
                desc = (p.description or "").lower()
                mfg = (p.manufacturer or "").lower()
                hwid = (p.hwid or "").lower()
                vid = getattr(p, "vid", 0) or 0
                if "stlink" in desc or "stm32" in desc or "stmicro" in mfg or "nucleo" in desc or vid in (1155, 0x0483) or p.device in ("COM8", "COM9"):
                    if p.device not in candidate_ports:
                        candidate_ports.append(p.device)

            priority_keywords = ["virtual com port", "ch340", "cp210", "ftdi", "usb serial", "usb-serial", "cdc"]
            for p in available_ports:
                desc = (p.description or "").lower()
                mfg = (p.manufacturer or "").lower()
                hwid = (p.hwid or "").lower()
                if any(k in desc or k in mfg or k in hwid for k in priority_keywords):
                    if p.device not in candidate_ports:
                        candidate_ports.append(p.device)

            for p in available_ports:
                if p.device not in candidate_ports:
                    candidate_ports.append(p.device)

            # fpm383c_backend.ino defaults to 57600 baud; STM32 main.c defaults to 115200
            baud_candidates = [57600, 115200]
            if self.baud_rate not in baud_candidates:
                baud_candidates.insert(0, self.baud_rate)

            for port_name in candidate_ports:
                # Find matching port object to inspect hardware VID
                port_obj = next((p for p in available_ports if p.device == port_name), None)
                is_st_hw = False
                if port_obj:
                    p_desc = (port_obj.description or "").lower()
                    p_hwid = (port_obj.hwid or "").lower()
                    p_vid = getattr(port_obj, "vid", 0) or 0
                    is_st_hw = (p_vid in (1155, 0x0483)) or ("stlink" in p_desc) or ("stm32" in p_desc) or ("0483" in p_hwid)

                for baud in baud_candidates:
                    conn = self._open_port(port_name, baud)
                    if not conn:
                        continue
                    try:
                        conn.reset_input_buffer()
                        conn.reset_output_buffer()

                        validated = False
                        detected_model = "STM32 / HLK-FPM383C Fingerprint Scanner"
                        detected_proto = "fpm383c_json"

                        # Check 1: Startup banner already in buffer
                        deadline = time.time() + 0.15
                        while time.time() < deadline:
                            if conn.in_waiting:
                                raw_line = conn.readline()
                                if raw_line:
                                    line = raw_line.decode("utf-8", errors="ignore").strip()
                                    if "ready" in line.lower() and "sensor" in line.lower():
                                        validated = True
                                        detected_proto = "fpm383c_json"
                                        break
                                    if any(sig in line for sig in ["Boot OK", "Waiting for ENROLL", "ERR:UNKNOWN_CMD"]):
                                        validated = True
                                        detected_proto = "stm32_fpm383c"
                                        break
                            time.sleep(0.01)

                        # Check 2: Probe with JSON ping
                        if not validated:
                            conn.write(b'{"id":"probe_ping","cmd":"ping"}\n')
                            conn.flush()
                            p_deadline = time.time() + 0.35
                            while time.time() < p_deadline:
                                if conn.in_waiting:
                                    raw_line = conn.readline()
                                    if raw_line:
                                        line = raw_line.decode("utf-8", errors="ignore").strip()
                                        if "probe_ping" in line or ("ready" in line.lower() and "sensor" in line.lower()) or "bad_json" in line.lower():
                                            validated = True
                                            detected_proto = "fpm383c_json"
                                            if line.startswith("{") and line.endswith("}"):
                                                try:
                                                    obj = json.loads(line)
                                                    if "count" in obj:
                                                        self.template_count = int(obj["count"])
                                                    if "capacity" in obj:
                                                        self.max_templates = int(obj["capacity"])
                                                except Exception:
                                                    pass
                                            break
                                        if any(sig in line for sig in ["ERR:UNKNOWN_CMD", "Boot OK", "Waiting"]):
                                            validated = True
                                            detected_proto = "stm32_fpm383c"
                                            break
                                time.sleep(0.01)

                        # Check 3: Probe with STATUS (Text protocol fallback & bad_json detection)
                        if not validated:
                            conn.write(b"STATUS\r\n")
                            conn.flush()
                            s_deadline = time.time() + 0.35
                            while time.time() < s_deadline:
                                if conn.in_waiting:
                                    raw_line = conn.readline()
                                    if not raw_line:
                                        continue
                                    line = raw_line.decode("utf-8", errors="ignore").strip()
                                    if not line:
                                        continue

                                    # If device rejected STATUS with bad_json, it IS the JSON firmware!
                                    if "bad_json" in line.lower():
                                        validated = True
                                        detected_proto = "fpm383c_json"
                                        break

                                    if "STATUS:READY" in line.upper() or "ERR:UNKNOWN_CMD" in line:
                                        validated = True
                                        detected_proto = "stm32_fpm383c"
                                        break

                                    line_upper = line.upper()
                                    m = re.search(r"STORED FINGERPRINTS:\s*(\d+)/(\d+)", line_upper)
                                    if m:
                                        validated = True
                                        self.template_count = int(m.group(1))
                                        self.max_templates = int(m.group(2))
                                        detected_proto = "stm32_fpm383c"
                                        break

                                    if any(sig in line_upper for sig in ["FPM383C", "HLK-FPM383C", "COMMANDS", "ENROLL", "MATCH"]):
                                        validated = True
                                        detected_proto = "stm32_fpm383c"
                                        break
                                time.sleep(0.01)

                        # Check 4: Fallback query HELP
                        if not validated:
                            conn.write(b"HELP\r\n")
                            conn.flush()
                            h_deadline = time.time() + 0.3
                            while time.time() < h_deadline:
                                if conn.in_waiting:
                                    raw_line = conn.readline()
                                    if not raw_line:
                                        continue
                                    line = raw_line.decode("utf-8", errors="ignore").strip()
                                    if "bad_json" in line.lower():
                                        validated = True
                                        detected_proto = "fpm383c_json"
                                        break
                                    if "ERR:UNKNOWN_CMD" in line or "STATUS:READY" in line:
                                        validated = True
                                        detected_proto = "stm32_fpm383c"
                                        break
                                    line_upper = line.upper()
                                    if any(sig in line_upper for sig in ["FPM383C", "HLK-FPM383C", "ENROLL", "MATCH"]):
                                        validated = True
                                        detected_proto = "stm32_fpm383c"
                                        break
                                time.sleep(0.01)

                        # Check 5: Hardware identity verification for genuine STMicroelectronics ST-Link Nucleo
                        if not validated and is_st_hw:
                            # STMicroelectronics Nucleo is physically connected and opened cleanly
                            validated = True
                            detected_proto = "fpm383c_json"

                        if validated:
                            self._serial_conn = conn
                            self.serial_port = port_name
                            self.baud_rate = baud
                            self.scanner_model = detected_model
                            self.protocol_type = detected_proto
                            self.is_connected = True
                            self.last_error = None
                            print(
                                f"[Biometric Scanner] Connected: {port_name} @ {baud} baud "
                                f"({detected_model}, Protocol: {detected_proto}, Stored: {self.template_count}/{self.max_templates})",
                                flush=True
                            )
                            return True
                        else:
                            conn.close()

                    except Exception:
                        try:
                            conn.close()
                        except Exception:
                            pass

            self.is_connected = False
            self.last_error = "Fingerprint scanner not found. Please check the USB connection."
            return False

        except Exception as e:
            self.is_connected = False
            self.last_error = f"Error detecting serial ports: {e}"
            return False

    def _send_line(self, command: str) -> None:
        """Send a single command line with CR/LF to the microcontroller."""
        if not self._serial_conn:
            raise serial.SerialException("Serial port is not open.")
        self._serial_conn.write((command + "\r\n").encode("utf-8"))
        self._serial_conn.flush()

    def _send_json(self, data: dict) -> None:
        """Send a single JSON line to the microcontroller (fpm383c_backend protocol)."""
        if not self._serial_conn:
            raise serial.SerialException("Serial port is not open.")
        payload = (json.dumps(data) + "\n").encode("utf-8")
        self._serial_conn.write(payload)
        self._serial_conn.flush()

    def _read_line(self, timeout: float = 0.08) -> str:
        """Read one line from the microcontroller with a responsive deadline."""
        if not self._serial_conn:
            return ""
        try:
            deadline = time.perf_counter() + timeout
            while time.perf_counter() < deadline:
                if self._serial_conn.in_waiting:
                    raw = self._serial_conn.readline()
                    if raw:
                        line = raw.decode("utf-8", errors="ignore").strip()
                        if line:
                            return line
                time.sleep(0.002)
            if self._serial_conn.in_waiting:
                raw = self._serial_conn.readline()
                if raw:
                    return raw.decode("utf-8", errors="ignore").strip()
            return ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Returns hardware connection status, validating physical presence and re-probing on reconnect."""
        if getattr(self, "_is_busy", False) and self.is_connected:
            return {
                "connected": True,
                "status": "ready",
                "device": self.scanner_model,
                "port": self.serial_port,
                "baud_rate": self.baud_rate,
                "protocol": self.protocol_type,
                "template_count": self.template_count,
                "max_templates": self.max_templates,
                "status_title": "Fingerprint scanner ready",
                "status_subtitle": "Place your finger on the scanner to register."
            }

        acquired = self._lock.acquire(timeout=0.25)
        if not acquired:
            return {
                "connected": bool(self.is_connected and self.serial_port),
                "status": "ready" if self.is_connected else "disconnected",
                "device": self.scanner_model,
                "port": self.serial_port,
                "baud_rate": self.baud_rate,
                "protocol": self.protocol_type,
                "template_count": self.template_count,
                "max_templates": self.max_templates,
                "status_title": "Fingerprint scanner ready" if self.is_connected else "Fingerprint scanner is not ready",
                "status_subtitle": "Place your finger on the scanner to register." if self.is_connected else "Please check the scanner connection."
            }

        try:
            active_ports = [p.device for p in serial.tools.list_ports.comports()] if (PYSERIAL_AVAILABLE and hasattr(serial.tools.list_ports, "comports")) else []
            if self.is_connected and self._serial_conn:
                if self.serial_port and active_ports and (self.serial_port not in active_ports):
                    self._close_serial()
                else:
                    try:
                        if not getattr(self._serial_conn, "is_open", False):
                            self._close_serial()
                    except Exception:
                        self._close_serial()

            if not self.is_connected or not self._serial_conn:
                self._probe_hardware(force=True)

            if self.is_connected and self._serial_conn:
                return {
                    "connected": True,
                    "status": "ready",
                    "device": self.scanner_model,
                    "port": self.serial_port,
                    "baud_rate": self.baud_rate,
                    "protocol": self.protocol_type,
                    "template_count": self.template_count,
                    "max_templates": self.max_templates,
                    "status_title": "Fingerprint scanner ready",
                    "status_subtitle": "Place your finger on the scanner to register."
                }
            else:
                return {
                    "connected": False,
                    "status": "disconnected",
                    "device": self.scanner_model,
                    "port": None,
                    "error": self.last_error or "Fingerprint scanner not connected.",
                    "status_title": "Fingerprint scanner is not ready",
                    "status_subtitle": "Please check the scanner connection."
                }
        finally:
            self._lock.release()

    def get_enroll_progress(self) -> Dict[str, Any]:
        """Returns the current enrollment progress for UI polling without serial lock contention."""
        with self._progress_lock:
            return dict(self._enroll_progress)

    # ------------------------------------------------------------------
    # Enrollment
    # ------------------------------------------------------------------

    def enroll_fingerprint(self, identifier: str, timeout_seconds: float = 60.0) -> Dict[str, Any]:
        """
        Enrolls a doctor's fingerprint using the HLK-FPM383C auto-enrollment sequence.
        Streams 6 capture stages in real time to the frontend UI via self._enroll_progress.
        """
        t_start = time.perf_counter()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"\n[BIOMETRIC TIMER] [{now_str}] API request: enroll_fingerprint(identifier='{identifier}')", flush=True)

        hw = self.get_status()
        if not hw["connected"]:
            print(f"[BIOMETRIC TIMER] Hardware not connected: {hw.get('error')}", flush=True)
            return {
                "success": False,
                "error": "Fingerprint scanner is not ready. Please check the scanner connection.",
                "code": "SCANNER_NOT_READY",
                "timing": {"total_duration_ms": round((time.perf_counter() - t_start) * 1000, 1)}
            }

        with self._lock:
            self._is_busy = True
            try:
                conn = self._serial_conn
                self._drain_serial_buffer()

                # Step 1: Pre-validation of doctor account and slot allocation
                t_val0 = time.perf_counter()
                doctor_check = self._validate_doctor_for_enrollment(identifier)
                t_val1 = time.perf_counter()
                print(f"[BIOMETRIC TIMER] Doctor validation completed in {(t_val1-t_val0)*1000:.2f}ms", flush=True)

                if not doctor_check["ok"]:
                    return {
                        "success": False,
                        "error": doctor_check["error"],
                        "already_registered": doctor_check.get("already_registered", False),
                        "fingerprint_id": doctor_check.get("fingerprint_id"),
                        "code": doctor_check.get("code", "VALIDATION_ERROR"),
                        "timing": {"total_duration_ms": round((time.perf_counter() - t_start) * 1000, 1)}
                    }

                slot_label = doctor_check["slot_label"]   # e.g. "R1"
                slot_num   = doctor_check["slot_num"]     # e.g. 1

                print(f"[BIOMETRIC ENROLL] Initiating enrollment for '{identifier}' into slot {slot_label} (ID: {slot_num})", flush=True)

                with self._progress_lock:
                    self._enroll_progress = {
                        "in_progress": True,
                        "identifier": identifier,
                        "slot": slot_label,
                        "stage": 0,
                        "progress": 5,
                        "message": f"Starting enrollment for {slot_label}. Follow the sensor LED prompts."
                    }

                # Step 2: Dispatch command
                token = f"enr_{uuid.uuid4().hex[:6]}"
                is_json_mode = (self.protocol_type == "fpm383c_json")
                timeout_ms = int(timeout_seconds * 1000)

                if is_json_mode:
                    req_payload = {
                        "id": token,
                        "cmd": "enroll",
                        "user": identifier,
                        "slot": slot_num,
                        "timeout_ms": timeout_ms
                    }
                    self._send_json(req_payload)
                    print(f"[BIOMETRIC ENROLL] Dispatched JSON enrollment: {req_payload}", flush=True)
                else:
                    cmd = f"ENROLL {slot_num}"
                    self._send_line(cmd)
                    print(f"[BIOMETRIC ENROLL] Dispatched text enrollment: '{cmd}'", flush=True)

                t_cmd_sent = time.perf_counter()
                enroll_result = None
                confirmed_slot = None
                max_enroll_seconds = timeout_seconds
                stage_times = {}

                while time.perf_counter() - t_cmd_sent < max_enroll_seconds:
                    line = self._read_line(timeout=0.08)
                    if not line:
                        continue

                    # Handle JSON protocol lines from fpm383c_backend.ino
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            obj = json.loads(line)
                            # Progress updates: {"id":"r2","event":"progress","step":"captured","msg":"...","press":1,"of":6,"percent":16}
                            if obj.get("event") == "progress":
                                press = int(obj.get("press") or 1)
                                stage_pct_map = {1: 16, 2: 33, 3: 50, 4: 66, 5: 83, 6: 100}
                                raw_pct = obj.get("percent")
                                pct = stage_pct_map.get(press, 100 if press >= 6 else int(round(press * 16.6))) if (raw_pct is None or raw_pct == 0) else int(raw_pct)

                                step = (obj.get("step") or "").lower()
                                firmware_msg = obj.get("msg") or ""

                                if step in ("place_finger", "started"):
                                    effective_stage = max(0, press - 1)
                                    effective_pct = stage_pct_map.get(effective_stage, 0)
                                    if press == 1:
                                        msg = "Place your finger on the scanner (Capture 1/6)..."
                                    else:
                                        msg = f"Place same finger again, slightly moved (Capture {press}/6)..."
                                elif step == "captured":
                                    effective_stage = press
                                    effective_pct = pct
                                    msg = f"Fingerprint capture {press}/6 successful ({pct}%). Lift your finger."
                                elif step == "lift_finger":
                                    effective_stage = press
                                    effective_pct = pct
                                    msg = f"Lift your finger from sensor ({press}/6 complete)..."
                                elif step == "retry":
                                    effective_stage = max(0, press - 1)
                                    effective_pct = stage_pct_map.get(effective_stage, 0)
                                    msg = f"Capture failed. Please lift and place same finger again ({press}/6)..."
                                elif step == "saving":
                                    effective_stage = 6
                                    effective_pct = 100
                                    msg = "All 6 captures recorded (100%). Saving template in secure hardware..."
                                else:
                                    effective_stage = max(0, press - 1)
                                    effective_pct = stage_pct_map.get(effective_stage, 0)
                                    msg = firmware_msg or f"Capture stage {press}/6 ({pct}%)..."

                                now_t = time.perf_counter()
                                stage_times[press] = round((now_t - t_cmd_sent), 2)
                                with self._progress_lock:
                                    self._enroll_progress = {
                                        "in_progress": True,
                                        "identifier": identifier,
                                        "slot": slot_label,
                                        "stage": effective_stage,
                                        "progress": effective_pct,
                                        "message": msg
                                    }
                                print(f"[FPM383C JSON PROGRESS] Press {press}/6 ({effective_pct}%) [{step}]: {msg}", flush=True)
                                continue

                            # Final reply: {"id":"...","cmd":"enroll","user":...,"ok":true,"slot":12}
                            if obj.get("cmd") == "enroll" or (obj.get("id") == token and "ok" in obj):
                                if obj.get("ok"):
                                    confirmed_slot = obj.get("slot", slot_num)
                                    enroll_result = "SUCCESS"
                                    with self._progress_lock:
                                        self._enroll_progress = {
                                            "in_progress": False,
                                            "identifier": identifier,
                                            "slot": f"R{confirmed_slot}",
                                            "stage": 6,
                                            "progress": 100,
                                            "message": f"Fingerprint registered successfully as R{confirmed_slot}!"
                                        }
                                    break
                                else:
                                    err_str = (obj.get("error") or "FAIL").upper()
                                    if "DUPLICATE" in err_str:
                                        enroll_result = "DUPLICATE"
                                    elif "STORAGE" in err_str or "FULL" in err_str:
                                        enroll_result = "STORAGE_FULL"
                                    elif "TIMEOUT" in err_str:
                                        enroll_result = "TIMEOUT"
                                    elif "POOR" in err_str or "IMAGE" in err_str:
                                        enroll_result = "POOR_IMAGE"
                                    else:
                                        enroll_result = err_str or "FAIL"
                                    break
                        except Exception:
                            pass

                    # Fallback text protocol parsing
                    line_upper = line.upper()
                    if "TOUCHOUT" in line_upper:
                        continue

                    print(f"[STM32 ENROLL RX] {line}", flush=True)

                    prog_match = re.search(r"PROGRESS\s*(\d+)%.*?STAGE\s*(\d+)", line_upper)
                    pct = None
                    stage = None
                    if prog_match:
                        pct = int(prog_match.group(1))
                        stage = int(prog_match.group(2))
                    else:
                        alt_match = re.search(r"STAGE\s*(\d+).*?(\d+)%", line_upper)
                        if alt_match:
                            stage = int(alt_match.group(1))
                            pct = int(alt_match.group(2))

                    if stage is not None and pct is not None:
                        now_t = time.perf_counter()
                        stage_times[stage] = round((now_t - t_cmd_sent), 2)
                        msg = f"Capture stage {stage}/6 recorded ({pct}%). Lift finger and place again..." if stage < 6 else "All 6 captures completed (100%). Saving template..."
                        with self._progress_lock:
                            self._enroll_progress = {
                                "in_progress": True,
                                "identifier": identifier,
                                "slot": slot_label,
                                "stage": stage,
                                "progress": pct,
                                "message": msg
                            }
                        continue

                    if any(k in line_upper for k in ["ENROLLMENT SUCCESS", "ENROLL:SUCCESS", "ENROLL_OK", "ENROLLED OK"]) or line_upper == "SAVED":
                        m_id = re.search(r"(?:SAVED AS ID|SUCCESS:|ID)\s*(\d+)", line_upper)
                        confirmed_slot = int(m_id.group(1)) if m_id else slot_num
                        enroll_result = "SUCCESS"
                        with self._progress_lock:
                            self._enroll_progress = {
                                "in_progress": False,
                                "identifier": identifier,
                                "slot": slot_label,
                                "stage": 6,
                                "progress": 100,
                                "message": f"Fingerprint registered successfully as {slot_label}!"
                            }
                        break

                    if "ALREADY ENROLLED" in line_upper:
                        enroll_result = "ALREADY_OCCUPIED"
                        break
                    if "DUPLICATE FINGERPRINT" in line_upper or "ENROLLMISMATCH" in line_upper:
                        enroll_result = "DUPLICATE"
                        break
                    if "FINGERPRINT LIMIT REACHED" in line_upper or "STORAGE_FULL" in line_upper:
                        enroll_result = "STORAGE_FULL"
                        break
                    if "ENROLLMENT TIMED OUT" in line_upper or "TIMEOUT" in line_upper:
                        enroll_result = "TIMEOUT"
                        break
                    if "ENROLLMENT FAILED" in line_upper or "TRANSMIT FAILED" in line_upper or "ERROR:STORAGE_FAILED" in line_upper:
                        enroll_result = "FAIL"
                        break

                # Step 3: Handle result and database persistence
                if enroll_result == "SUCCESS" and confirmed_slot is not None:
                    template_ref = f"HLK_FPM383C_SLOT_{confirmed_slot}"
                    assigned_label = f"R{confirmed_slot}"

                    t_db_start = time.perf_counter()
                    db_res = database.register_doctor_biometric(
                        identifier=identifier,
                        fingerprint_slot=assigned_label,
                        template_data=template_ref,
                        scanner_model=self.scanner_model
                    )
                    t_db_end = time.perf_counter()

                    t_total = t_db_end - t_start
                    print(f"[BIOMETRIC TIMER] Database biometric mapping saved in {(t_db_end-t_db_start)*1000:.2f}ms", flush=True)
                    print(f"[BIOMETRIC TIMER] [TOTAL DURATION] Enrollment completed in {t_total:.2f}s", flush=True)

                    if not db_res.get("success"):
                        print(f"[Biometric Scanner] DB save failed after enroll. Rolling back hardware slot {assigned_label}...", flush=True)
                        try:
                            self.delete_slot(assigned_label)
                        except Exception as rb_err:
                            print(f"[Biometric Scanner] Rollback error: {rb_err}", flush=True)
                        db_res["timing"] = {"total_duration_ms": round(t_total * 1000, 1)}
                        return db_res

                    self.template_count += 1
                    db_res["fingerprint_id"] = assigned_label
                    db_res["slot_number"] = confirmed_slot
                    db_res["hardware_slot"] = confirmed_slot
                    db_res["message"] = f"Fingerprint registered successfully! Assigned slot: {assigned_label}."
                    db_res["subtitle"] = f"Your fingerprint has been securely saved in sensor memory as {assigned_label}."
                    db_res["timing"] = {
                        "serial_dispatch_ms": round((t_cmd_sent - t_start) * 1000, 1),
                        "stages": stage_times,
                        "db_save_ms": round((t_db_end - t_db_start) * 1000, 1),
                        "total_duration_ms": round(t_total * 1000, 1),
                        "total_seconds": round(t_total, 2)
                    }
                    return db_res

                # Error mappings
                t_total = time.perf_counter() - t_start
                timing_data = {
                    "serial_dispatch_ms": round((t_cmd_sent - t_start) * 1000, 1),
                    "total_duration_ms": round(t_total * 1000, 1),
                    "total_seconds": round(t_total, 2)
                }

                error_map = {
                    "ALREADY_OCCUPIED": f"Hardware slot {slot_label} is already occupied. Please clear the slot or try another.",
                    "DUPLICATE":        "This fingerprint is already enrolled on the sensor. Please use a different finger.",
                    "STORAGE_FULL":     "Fingerprint storage is full (60/60 templates). Please delete an existing fingerprint.",
                    "TIMEOUT":          "Enrollment timed out. Please place your finger firmly and follow the prompts.",
                    "POOR_IMAGE":       "Fingerprint image capture failed due to poor contact. Please reposition your finger and try again.",
                    "FAIL":             "Fingerprint capture failed on hardware. Please reposition your finger and try again."
                }
                err_msg = error_map.get(enroll_result, "Fingerprint enrollment failed. Please try again.")

                with self._progress_lock:
                    self._enroll_progress = {
                        "in_progress": False,
                        "identifier": identifier,
                        "slot": slot_label,
                        "stage": 0,
                        "progress": 0,
                        "message": err_msg
                    }
                print(f"[BIOMETRIC TIMER] Enrollment failed: {enroll_result} in {t_total:.2f}s", flush=True)

                return {
                    "success": False,
                    "error": err_msg,
                    "code": enroll_result or "TIMEOUT",
                    "timing": timing_data
                }

            except (serial.SerialException, OSError) as se:
                print(f"[Biometric Scanner] Serial error during enroll: {se}", flush=True)
                self._close_serial()
                self._enroll_progress["in_progress"] = False
                return {
                    "success": False,
                    "error": f"Fingerprint scanner communication error: {se}",
                    "code": "SCANNER_COMM_ERROR",
                    "timing": {"total_duration_ms": round((time.perf_counter() - t_start) * 1000, 1)}
                }
            except Exception as e:
                print(f"[Biometric Scanner] Unexpected enrollment error: {e}", flush=True)
                self._enroll_progress["in_progress"] = False
                return {
                    "success": False,
                    "error": f"Fingerprint enrollment error: {e}",
                    "code": "ENROLL_ERROR",
                    "timing": {"total_duration_ms": round((time.perf_counter() - t_start) * 1000, 1)}
                }
            finally:
                self._is_busy = False
                self._drain_trailing_bytes(0.005)

    def _validate_doctor_for_enrollment(self, identifier: str) -> Dict[str, Any]:
        """
        Pre-enrollment validation:
        1. Checks doctor exists in DB; if not, auto-provisions a doctor account.
        2. Blocks if doctor already has an active biometric registration.
        3. Allocates lowest free slot (R1..R59).
        """
        clean_id = identifier.strip().lower()

        existing_slot = database.get_doctor_biometric_slot(clean_id)
        if existing_slot:
            return {
                "ok": False,
                "already_registered": True,
                "fingerprint_id": existing_slot,
                "error": f"Fingerprint is already registered for this account ({existing_slot}). Please use that fingerprint to log in.",
                "code": "ALREADY_REGISTERED"
            }

        next_slot_label = database.get_next_available_biometric_slot()
        if next_slot_label is None:
            return {
                "ok": False,
                "error": f"All {database.MAX_BIOMETRIC_SLOTS} fingerprint slots are occupied. Please remove an existing registration before adding a new one.",
                "code": "ALL_SLOTS_FULL"
            }

        # Auto-provision doctor record if not present
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, uid, name, email FROM doctors WHERE LOWER(email) = ? OR LOWER(uid) = ?",
            (clean_id, clean_id)
        )
        doctor = cursor.fetchone()
        if not doctor:
            temp_name = clean_id.split("@")[0].replace(".", " ").replace("_", " ").title()
            temp_uid = f"DOC{uuid.uuid4().hex[:6].upper()}"
            hashed_pw = database.hash_password("TorusDoctor@2026")
            cursor.execute(
                """
                INSERT INTO doctors (uid, name, email, password_hash, role, mobile)
                VALUES (?, ?, ?, ?, 'doctor', '')
                """,
                (temp_uid, f"Dr. {temp_name}", clean_id, hashed_pw)
            )
            conn.commit()
            print(f"[Biometric Pre-Validation] Auto-provisioned doctor record for {clean_id} (UID: {temp_uid})", flush=True)
        conn.close()

        slot_num = database._slot_label_to_int(next_slot_label)
        return {
            "ok": True,
            "slot_label": next_slot_label,
            "slot_num": slot_num
        }

    # ------------------------------------------------------------------
    # Verification / Exact Matching
    # ------------------------------------------------------------------

    def verify_fingerprint(self, identifier: Optional[str] = None, timeout_seconds: float = 12.0) -> Dict[str, Any]:
        """
        Verifies a fingerprint against sensor templates using EXACT matching.

        Workflow:
        1. Checks physical scanner is connected.
        2. If identifier (email/UID) is provided:
           - Verifies doctor has an active biometric registration in DB.
           - Targets 1:1 verify command: {"cmd": "verify", "slot": <target_slot>, "user": <id>}.
           - fpm383c_backend firmware checks ONLY that person's slot!
           - If another finger touches, firmware reports matched=False (no slot revealed).
        3. If no identifier provided:
           - 1:N open search command: {"cmd": "verify"}.
           - Hardware searches all enrolled templates and reports matching slot.
        4. Doctor places registered finger on sensor.
        5. Python confirms matched ID against authenticated doctor's registered slot.
        6. Returns authenticated doctor record on success; rejects unauthorized attempts.
        """
        t_start = time.perf_counter()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"\n[BIOMETRIC TIMER] [{now_str}] API request: verify_fingerprint(identifier={identifier})", flush=True)

        hw = self.get_status()
        if not hw["connected"]:
            print(f"[BIOMETRIC TIMER] Hardware not ready: {hw.get('error')}", flush=True)
            return {
                "success": False,
                "matched": False,
                "error": "Fingerprint scanner is not ready. Please check the scanner connection.",
                "code": "SCANNER_NOT_READY",
                "timing": {"total_duration_ms": round((time.perf_counter() - t_start) * 1000, 1)}
            }

        with self._lock:
            self._is_busy = True
            try:
                conn = self._serial_conn
                self._drain_serial_buffer()

                target_slot_num: Optional[int] = None
                registered_slot_label: Optional[str] = None

                # 1:1 Exact Match: If identifier provided, lookup doctor's registered slot
                if identifier and identifier.strip():
                    clean_id = identifier.strip().lower()
                    t_db0 = time.perf_counter()
                    registered_slot_label = database.get_doctor_biometric_slot(clean_id)
                    t_db1 = time.perf_counter()
                    print(f"[BIOMETRIC TIMER] Doctor slot lookup completed in {(t_db1-t_db0)*1000:.2f}ms: slot={registered_slot_label}", flush=True)
                    if not registered_slot_label:
                        return {
                            "success": False,
                            "matched": False,
                            "error": "No fingerprint registered for this account. Please complete biometric registration.",
                            "code": "NOT_ENROLLED",
                            "timing": {"total_duration_ms": round((time.perf_counter() - t_start) * 1000, 1)}
                        }
                    target_slot_num = database._slot_label_to_int(registered_slot_label)

                token = f"ver_{uuid.uuid4().hex[:6]}"
                is_json_mode = (self.protocol_type == "fpm383c_json")
                timeout_ms = int(timeout_seconds * 1000)

                # Send targeted verify command for exact match
                if is_json_mode:
                    req_payload = {
                        "id": token,
                        "cmd": "verify",
                        "timeout_ms": timeout_ms
                    }
                    if target_slot_num is not None:
                        req_payload["slot"] = target_slot_num
                        req_payload["user"] = identifier
                        print(f"[BIOMETRIC VERIFY] 1:1 Exact Match JSON: {req_payload}", flush=True)
                    else:
                        print(f"[BIOMETRIC VERIFY] 1:N Open Search JSON: {req_payload}", flush=True)
                    self._send_json(req_payload)
                else:
                    if target_slot_num is not None:
                        cmd = f"MATCH {target_slot_num}"
                        print(f"[BIOMETRIC VERIFY] Targeted text verification: '{cmd}' for slot {registered_slot_label}", flush=True)
                    else:
                        cmd = "MATCH"
                        print("[BIOMETRIC VERIFY] 1:N open search text command: 'MATCH'", flush=True)
                    self._send_line(cmd)

                t_cmd_sent = time.perf_counter()
                verify_result = None
                matched_id = None
                match_score = 0
                max_verify_seconds = timeout_seconds
                t_match_done = None

                while time.perf_counter() - t_cmd_sent < max_verify_seconds:
                    line = self._read_line(timeout=0.08)
                    if not line:
                        continue

                    # Handle JSON responses from fpm383c_backend.ino
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            obj = json.loads(line)
                            if obj.get("cmd") == "verify" or (obj.get("id") == token and "ok" in obj) or "matched" in obj:
                                t_match_done = time.perf_counter()
                                if obj.get("ok"):
                                    if obj.get("matched"):
                                        res_slot = obj.get("slot")
                                        res_score = obj.get("score", 100)
                                        print(f"[FPM383C JSON MATCH] Matched slot={res_slot}, score={res_score}", flush=True)

                                        # Exact 1:1 matching validation:
                                        if target_slot_num is not None and res_slot is not None and res_slot != target_slot_num:
                                            verify_result = "WRONG_DOCTOR"
                                        else:
                                            matched_id = res_slot if res_slot is not None else target_slot_num
                                            match_score = res_score
                                            verify_result = "SUCCESS"
                                        break
                                    else:
                                        print("[FPM383C JSON MATCH] Firmware returned matched: false", flush=True)
                                        verify_result = "NO_MATCH"
                                        break
                                else:
                                    err_code = (obj.get("error") or "").upper()
                                    print(f"[FPM383C JSON ERROR] Error: {err_code}", flush=True)
                                    if "TIMEOUT" in err_code:
                                        verify_result = "TIMEOUT"
                                    elif "EMPTY" in err_code or "NO_TEMPLATES" in err_code:
                                        verify_result = "NO_TEMPLATES"
                                    elif "BAD_SLOT" in err_code:
                                        verify_result = "BAD_SLOT"
                                    else:
                                        verify_result = "NO_MATCH"
                                    break
                        except Exception:
                            pass

                    # Text protocol parsing fallback
                    line_upper = line.upper()
                    if "NO FINGER DETECTED" in line_upper or "NO MATCH RESPONSE" in line_upper or "TIMEOUT_NO_FINGER" in line_upper:
                        t_match_done = time.perf_counter()
                        verify_result = "TIMEOUT"
                        break

                    if line_upper.startswith("TOUCHOUT PC0 CHANGED") or line_upper.startswith("TOUCHOUT:"):
                        continue

                    if "TOUCH THE SENSOR" in line_upper or "HOLD YOUR FINGER" in line_upper:
                        continue
                    if "FINGER DETECTED" in line_upper:
                        continue

                    print(f"[STM32 MATCH RX] {line}", flush=True)

                    m_res = re.search(r"MATCH RESULT\s*=\s*(\d+)\s*,\s*ID\s*=\s*(\d+)\s*,\s*SCORE\s*=\s*(\d+)", line_upper)
                    if m_res:
                        t_match_done = time.perf_counter()
                        res_code = int(m_res.group(1))
                        res_id = int(m_res.group(2))
                        res_score = int(m_res.group(3))
                        if res_code == 1 and res_score > 0:
                            if target_slot_num is not None and res_id != target_slot_num:
                                verify_result = "WRONG_DOCTOR"
                            else:
                                matched_id = res_id
                                match_score = res_score
                                verify_result = "SUCCESS"
                            break
                        else:
                            verify_result = "NO_MATCH"
                            break

                    m_ard = re.search(r"(?:VERIFY:SUCCESS:|MATCHED ID\s*#?|FOUND ID\s*#)\s*(\d+)(?::(\d+))?", line_upper)
                    if m_ard:
                        t_match_done = time.perf_counter()
                        res_id = int(m_ard.group(1))
                        res_score = int(m_ard.group(2)) if m_ard.group(2) else 80
                        if target_slot_num is not None and res_id != target_slot_num:
                            verify_result = "WRONG_DOCTOR"
                        else:
                            matched_id = res_id
                            match_score = res_score
                            verify_result = "SUCCESS"
                        break

                    if line_upper.startswith("MATCHED:"):
                        t_match_done = time.perf_counter()
                        m1 = re.search(r"ID\s*(\d+).*?SCORE\s*(\d+)", line_upper)
                        if m1:
                            matched_id = int(m1.group(1))
                            match_score = int(m1.group(2))
                        elif target_slot_num is not None:
                            matched_id = target_slot_num
                        verify_result = "SUCCESS"
                        break

                    if "NOT MATCHED TO ID" in line_upper or "RECOGNIZED ID" in line_upper:
                        t_match_done = time.perf_counter()
                        verify_result = "WRONG_DOCTOR"
                        break

                    if "NOT MATCHED" in line_upper or "VERIFY:NO_MATCH" in line_upper:
                        t_match_done = time.perf_counter()
                        verify_result = "NO_MATCH"
                        break

                    if any(sig in line_upper for sig in ["NO FINGERPRINTS", "NO FIGERPRINTS", "NO TEMPLATES"]):
                        t_match_done = time.perf_counter()
                        verify_result = "NO_TEMPLATES"
                        break

                t_eval = time.perf_counter()

                # Evaluate verification result and query database
                if verify_result == "SUCCESS" and matched_id is not None:
                    logical_slot = f"R{matched_id}"
                    t_db_start = time.perf_counter()
                    if identifier and identifier.strip():
                        db_res = database.verify_doctor_biometric_by_email(
                            identifier=identifier,
                            matched_slot_id=matched_id
                        )
                    else:
                        db_res = database.verify_doctor_biometric_by_slot(
                            matched_slot_id=matched_id
                        )
                    t_db_end = time.perf_counter()
                    t_total = t_db_end - t_start

                    print(f"[BIOMETRIC TIMER] Database verification completed in {(t_db_end-t_db_start)*1000:.2f}ms", flush=True)
                    print(f"[BIOMETRIC TIMER] [TOTAL DURATION] Verification completed in {t_total:.3f}s", flush=True)

                    if db_res.get("matched"):
                        db_res["message"] = f"Fingerprint verified successfully ({logical_slot})."
                    else:
                        db_res["message"] = "Fingerprint not recognized for this account."

                    db_res["timing"] = {
                        "serial_dispatch_ms": round((t_cmd_sent - t_start) * 1000, 1),
                        "sensor_match_ms": round(((t_match_done or t_eval) - t_cmd_sent) * 1000, 1),
                        "db_lookup_ms": round((t_db_end - t_db_start) * 1000, 1),
                        "total_duration_ms": round(t_total * 1000, 1)
                    }
                    return db_res

                # Handle failure results with accurate timing
                t_total = time.perf_counter() - t_start
                timing_data = {
                    "serial_dispatch_ms": round((t_cmd_sent - t_start) * 1000, 1),
                    "total_duration_ms": round(t_total * 1000, 1)
                }

                if verify_result == "WRONG_DOCTOR":
                    print(f"[BIOMETRIC TIMER] Verification result: WRONG_DOCTOR in {t_total:.3f}s", flush=True)
                    return {
                        "success": False,
                        "matched": False,
                        "error": "Fingerprint belongs to a different doctor account. Access denied.",
                        "code": "CROSS_USER_MISMATCH",
                        "timing": timing_data
                    }
                elif verify_result == "NO_MATCH":
                    print(f"[BIOMETRIC TIMER] Verification result: NO_MATCH in {t_total:.3f}s", flush=True)
                    return {
                        "success": False,
                        "matched": False,
                        "error": "Fingerprint not recognized. Please place your registered finger firmly and try again.",
                        "code": "NO_MATCH",
                        "timing": timing_data
                    }
                elif verify_result == "NO_TEMPLATES":
                    print(f"[BIOMETRIC TIMER] Verification result: NO_TEMPLATES in {t_total:.3f}s", flush=True)
                    return {
                        "success": False,
                        "matched": False,
                        "error": "No fingerprint registered on scanner. Please complete biometric registration.",
                        "code": "NO_TEMPLATES",
                        "timing": timing_data
                    }
                elif verify_result == "TIMEOUT":
                    print(f"[BIOMETRIC TIMER] Verification result: TIMEOUT in {t_total:.3f}s", flush=True)
                    return {
                        "success": False,
                        "matched": False,
                        "error": "Verification timed out. Please place your registered finger firmly on the scanner.",
                        "code": "TIMEOUT",
                        "timing": timing_data
                    }
                else:
                    print(f"[BIOMETRIC TIMER] Verification result: READ_ERROR in {t_total:.3f}s", flush=True)
                    return {
                        "success": False,
                        "matched": False,
                        "error": "Fingerprint not recognized. Please place your registered finger firmly and try again.",
                        "code": "READ_ERROR",
                        "timing": timing_data
                    }

            except (serial.SerialException, OSError) as se:
                print(f"[Biometric Scanner] Serial error during verify: {se}", flush=True)
                self._close_serial()
                return {
                    "success": False,
                    "matched": False,
                    "error": f"Fingerprint scanner communication error: {se}",
                    "code": "SCANNER_COMM_ERROR",
                    "timing": {"total_duration_ms": round((time.perf_counter() - t_start) * 1000, 1)}
                }
            except Exception as e:
                print(f"[Biometric Scanner] Verification exception: {e}", flush=True)
                return {
                    "success": False,
                    "matched": False,
                    "error": f"Fingerprint verification error: {e}",
                    "code": "VERIFY_ERROR",
                    "timing": {"total_duration_ms": round((time.perf_counter() - t_start) * 1000, 1)}
                }
            finally:
                self._is_busy = False
                self._drain_trailing_bytes(0.005)

    # ------------------------------------------------------------------
    # Slot Management
    # ------------------------------------------------------------------

    def delete_slot(self, slot_label: str) -> Dict[str, Any]:
        """Deletes a fingerprint template from the sensor memory."""
        slot_num = database._slot_label_to_int(slot_label)
        if slot_num < 0 or slot_num > 59:
            return {"success": False, "error": f"Invalid slot label: {slot_label}"}

        with self._lock:
            if not self.is_connected or not self._serial_conn:
                return {
                    "success": False,
                    "error": "Fingerprint scanner not connected.",
                    "code": "SCANNER_NOT_READY"
                }
            try:
                self._drain_serial_buffer()
                if self.protocol_type == "fpm383c_json":
                    del_token = f"del_{uuid.uuid4().hex[:6]}"
                    self._send_json({"id": del_token, "cmd": "delete", "slot": slot_num})
                self._send_line(f"DELETE {slot_num}")

                deadline = time.time() + 1.0
                while time.time() < deadline:
                    line = self._read_line(timeout=0.08)
                    if not line:
                        continue
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            obj = json.loads(line)
                            if obj.get("ok"):
                                if self.template_count > 0:
                                    self.template_count -= 1
                                self._drain_trailing_bytes(0.005)
                                return {
                                    "success": True,
                                    "slot": slot_label,
                                    "message": f"Slot {slot_label} removed from sensor."
                                }
                        except Exception:
                            pass

                    line_upper = line.upper()
                    if "DELETED FINGERPRINT" in line_upper or "NO FINGERPRINT IS STORED" in line_upper or "DELETE:SUCCESS" in line_upper or "DELETED ID" in line_upper:
                        if self.template_count > 0:
                            self.template_count -= 1
                        self._drain_trailing_bytes(0.005)
                        return {
                            "success": True,
                            "slot": slot_label,
                            "message": f"Slot {slot_label} removed from sensor."
                        }
                    if "DELETE FAILED" in line_upper or "DELETE_FAILED" in line_upper:
                        return {
                            "success": False,
                            "error": f"Sensor could not delete slot {slot_label}.",
                            "code": "DELETE_FAILED"
                        }

                return {
                    "success": True,
                    "slot": slot_label,
                    "message": f"Slot {slot_label} delete command issued."
                }

            except Exception as e:
                self._close_serial()
                return {"success": False, "error": str(e), "code": "SCANNER_COMM_ERROR"}
            finally:
                self._is_busy = False
                self._drain_trailing_bytes(0.005)

    def reset_hardware(self) -> Dict[str, Any]:
        """Clears all fingerprint templates from hardware slots."""
        hw = self.get_status()
        if not hw["connected"]:
            return {
                "success": False,
                "error": "Fingerprint scanner not connected.",
                "code": "SCANNER_NOT_READY"
            }

        with self._lock:
            try:
                print("[Biometric Scanner] Resetting hardware: clearing sensor database...", flush=True)
                if self.protocol_type == "fpm383c_json":
                    rst_token = f"rst_{uuid.uuid4().hex[:6]}"
                    self._send_json({"id": rst_token, "cmd": "empty"})
                self._send_line("EMPTY")
                time.sleep(0.05)
                for s in range(0, 60):
                    self._send_line(f"DELETE {s}")
                    time.sleep(0.002)

                self.template_count = 0
                return {"success": True, "message": "All sensor templates cleared."}

            except Exception as e:
                self.is_connected = False
                self._serial_conn = None
                return {"success": False, "error": str(e), "code": "SCANNER_COMM_ERROR"}

    def get_slot_info(self) -> Dict[str, Any]:
        """Returns current slot allocation summary from the database and sensor."""
        next_slot = database.get_next_available_biometric_slot()
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.fingerprint_slot, b.hardware_slot, d.email, d.name, b.enrolled_at
            FROM doctor_biometrics b
            JOIN doctors d ON b.doctor_id = d.id
            WHERE b.is_active = 1 AND b.fingerprint_slot IS NOT NULL
            ORDER BY b.hardware_slot ASC
        """)
        rows = cursor.fetchall()
        conn.close()

        registrations = [
            {
                "slot": row["fingerprint_slot"],
                "hardware_slot": row["hardware_slot"],
                "email": row["email"],
                "name": row["name"],
                "enrolled_at": row["enrolled_at"]
            }
            for row in rows
        ]

        return {
            "total_slots": database.MAX_BIOMETRIC_SLOTS,
            "used_slots": len(registrations),
            "available_slots": database.MAX_BIOMETRIC_SLOTS - len(registrations),
            "next_available_slot": next_slot,
            "hardware_template_count": self.template_count,
            "registrations": registrations
        }


# Global singleton instance
hardware_manager = BiometricHardwareManager()
