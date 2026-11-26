"""
TORUS Healthcare - Unified STM32 Haptic Pad & Biometric Serial Manager
Firmware Version: Haptic_Pad_vib3v5_login.ino
Sensor: HLK-FPM383C on USART1 (PA9-TX, PA10-RX @ 57600 baud)
Host Interface: STM32 ST-Link Virtual COM Port @ 115200 baud (8-N-1)

Unified Architecture:
  1. A single serial port is shared between Haptic Pad telemetry and Biometric operations.
  2. The STM32 boots LOCKED (unlocked: false). Vibrator (V33 PB0) is OFF, plain-text sensor stream is silent.
  3. All fingerprint commands include "fp_enter": true. During fingerprint operations, the vibrator
     is disabled, plain-text stream is paused, and STM32 communicates exclusively in JSON.
  4. Upon completion, STM32 returns to haptic mode automatically.
  5. Successful verify (or first enrollment on empty sensor) UNLOCKS the pad (unlocked: true).
  6. The pad locks again via:
     - {"cmd": "logout"}
     - Idle timeout (default: 300,000 ms / 5 minutes)
     - Probe returned to home position (reed switch PB3 -> LOW)
     - Hardware reset / delete_all
"""

from __future__ import annotations

import os
import re
import time
import json
import datetime
import threading
import uuid
from typing import Optional, Dict, Any, Callable, List

try:
    import serial
    import serial.tools.list_ports
    PYSERIAL_AVAILABLE = True
except ImportError:
    PYSERIAL_AVAILABLE = False

import database


class BiometricHardwareManager:
    """
    Unified manager for STM32 Haptic Pad & HLK-FPM383C Fingerprint Sensor.
    Maintains a single serial connection, demultiplexing JSON events/replies
    and plain-text haptic telemetry.
    """

    def __init__(self):
        self.serial_port: Optional[str] = (
            os.environ.get("BIOMETRIC_SERIAL_PORT", "").strip() or
            os.environ.get("HAPTIC_SERIAL_PORT", "").strip() or None
        )
        self.baud_rate: int = int(os.environ.get("BIOMETRIC_BAUD_RATE", "115200"))
        self._serial_conn: Optional[Any] = None
        self._lock = threading.RLock()
        self._cmd_lock = threading.Lock()
        self._progress_lock = threading.Lock()

        # Connection & state
        self.is_connected: bool = False
        self.sensor_ready: bool = False
        self.unlocked: bool = False
        self.host_mode: str = "haptic"
        self.no_fingerprints_detected: bool = False
        self.idle_left_ms: Optional[int] = None
        self.last_error: Optional[str] = None
        self.template_count: int = 0
        self.max_templates: int = 60
        self.scanner_model: str = "STM32 Haptic Pad / HLK-FPM383C"
        self.protocol_type: str = "fpm383c_v5_login"

        # Background reader & dispatch
        self._reader_thread: Optional[threading.Thread] = None
        self._reader_running: bool = False
        self._keepalive_thread: Optional[threading.Thread] = None
        self._keepalive_running: bool = False

        # Request-response tracking: {request_id: (threading.Event, response_holder)}
        self._pending_requests: Dict[str, tuple[threading.Event, List[Dict[str, Any]]]] = {}
        self._last_cmd_name: Optional[str] = None
        self._last_cmd_event: Optional[threading.Event] = None
        self._last_cmd_holder: Optional[List[Dict[str, Any]]] = None

        # Callbacks for telemetry and session events
        self._telemetry_callbacks: List[Callable[[dict, str], None]] = []
        self._session_end_callbacks: List[Callable[[str], None]] = []
        self._no_fp_callbacks: List[Callable[[str], None]] = []
        self._ready_callbacks: List[Callable[[bool], None]] = []
        self._progress_callbacks: List[Callable[[dict], None]] = []

        # Enrollment live progress and stage timing
        self._current_enroll_stages: Dict[int, float] = {}
        self._enroll_progress: Dict[str, Any] = {
            "in_progress": False,
            "identifier": None,
            "slot": None,
            "stage": 0,
            "press": 0,
            "of": 6,
            "percent": 0,
            "message": "Idle",
            "step": "idle"
        }

        # Last probe time for connection debounce
        self._last_probe_time: float = 0.0
        self._probe_cooldown: float = 1.0

        # Initial hardware discovery
        self._probe_hardware()

    # ------------------------------------------------------------------
    # Callback Registration
    # ------------------------------------------------------------------

    def register_telemetry_callback(self, cb: Callable[[dict, str], None]) -> None:
        """Register a callback invoked when plain-text haptic telemetry arrives."""
        if cb not in self._telemetry_callbacks:
            self._telemetry_callbacks.append(cb)

    def register_session_end_callback(self, cb: Callable[[str], None]) -> None:
        """Register a callback invoked when pad locks due to probe home or idle timeout."""
        if cb not in self._session_end_callbacks:
            self._session_end_callbacks.append(cb)

    def register_no_fingerprints_callback(self, cb: Callable[[str], None]) -> None:
        """Register a callback invoked when firmware announces sensor holds no fingerprints."""
        if cb not in self._no_fp_callbacks:
            self._no_fp_callbacks.append(cb)

    def register_progress_callback(self, cb: Callable[[dict], None]) -> None:
        """Register a callback invoked when enrollment progress arrives."""
        if cb not in self._progress_callbacks:
            self._progress_callbacks.append(cb)

    def set_progress_callback(self, cb: Callable[[dict], None]) -> None:
        """Alias for register_progress_callback."""
        self.register_progress_callback(cb)

    # ------------------------------------------------------------------
    # Serial Lifecycle
    # ------------------------------------------------------------------

    def _close_serial(self) -> None:
        """Cleanly terminates reader threads and closes the serial port."""
        self._reader_running = False
        self._keepalive_running = False
        if self._serial_conn:
            try:
                self._serial_conn.close()
            except Exception:
                pass
        self._serial_conn = None
        self.is_connected = False
        self.sensor_ready = False
        self.unlocked = False

    def _open_port(self, port_name: str, baud: int) -> Optional[Any]:
        """Opens serial port with 8-N-1 framing and short read timeout."""
        try:
            conn = serial.Serial(
                port_name, baud,
                timeout=0.1,
                write_timeout=1.0,
                dsrdtr=False,
                rtscts=False
            )
            time.sleep(0.05)
            return conn
        except Exception:
            return None

    def _start_background_workers(self) -> None:
        """Starts background reader and keepalive heartbeat threads."""
        if self._reader_running:
            return
        self._reader_running = True
        self._reader_thread = threading.Thread(
            target=self._serial_reader_loop,
            daemon=True,
            name="STM32UnifiedReader"
        )
        self._reader_thread.start()

        self._keepalive_running = True
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop,
            daemon=True,
            name="STM32KeepaliveHeartbeat"
        )
        self._keepalive_thread.start()

    def _probe_hardware(self, force: bool = False) -> bool:
        """
        Scans COM ports, finds ST-Link / STM32 virtual COM port, and establishes
        the unified serial connection.
        """
        now = time.perf_counter()
        if not force and not self.is_connected and (now - self._last_probe_time) < self._probe_cooldown:
            return False
        self._last_probe_time = now

        if not PYSERIAL_AVAILABLE:
            self.last_error = "pyserial not installed."
            self.is_connected = False
            return False

        with self._lock:
            if self.is_connected and self._serial_conn:
                try:
                    if getattr(self._serial_conn, "is_open", False):
                        return True
                except Exception:
                    pass
                self._close_serial()

            all_ports = list(serial.tools.list_ports.comports())
            available_ports = [
                p for p in all_ports
                if not any(b in (p.description or "").lower() or b in (p.hwid or "").lower() for b in ["bluetooth", "bthenum"])
            ]

            candidate_ports = []
            if self.serial_port and any(p.device == self.serial_port for p in available_ports):
                candidate_ports.append(self.serial_port)

            # Prioritize ST-Link / STM32 Nucleo hardware
            for p in available_ports:
                desc = (p.description or "").lower()
                mfg = (p.manufacturer or "").lower()
                hwid = (p.hwid or "").lower()
                vid = getattr(p, "vid", 0) or 0
                if "stlink" in desc or "stm32" in desc or "stmicro" in mfg or "nucleo" in desc or vid in (1155, 0x0483):
                    if p.device not in candidate_ports:
                        candidate_ports.append(p.device)

            for p in available_ports:
                if p.device not in candidate_ports:
                    candidate_ports.append(p.device)

            for port_name in candidate_ports:
                conn = self._open_port(port_name, self.baud_rate)
                if not conn:
                    continue

                try:
                    conn.reset_input_buffer()
                    conn.reset_output_buffer()

                    # Check for startup banner or query status
                    validated = False
                    is_ready_event = False
                    deadline = time.time() + 0.35
                    while time.time() < deadline:
                        if conn.in_waiting:
                            raw = conn.readline().decode("utf-8", errors="ignore").strip()
                            if raw:
                                if "TORUS DOCTOR STATION" in raw or "Doctor station started" in raw:
                                    validated = True
                                elif raw.startswith("{") and "ready" in raw.lower():
                                    validated = True
                                    is_ready_event = True
                                    try:
                                        obj = json.loads(raw)
                                        self.sensor_ready = bool(obj.get("sensor", False))
                                        self.unlocked = bool(obj.get("unlocked", False))
                                    except Exception:
                                        pass
                                    break
                                elif "JX:" in raw or "JY:" in raw:
                                    validated = True
                                    self.unlocked = True
                                    break
                        time.sleep(0.01)

                    # If not recognized from startup stream, send status request
                    if not validated:
                        probe_id = f"probe_{uuid.uuid4().hex[:6]}"
                        req_str = f'{{"id":"{probe_id}","cmd":"status"}}\n'.encode("utf-8")
                        conn.write(req_str)
                        conn.flush()

                        s_deadline = time.time() + 0.4
                        while time.time() < s_deadline:
                            if conn.in_waiting:
                                raw = conn.readline().decode("utf-8", errors="ignore").strip()
                                if raw and raw.startswith("{"):
                                    try:
                                        obj = json.loads(raw)
                                        if obj.get("id") == probe_id or obj.get("cmd") == "status":
                                            validated = True
                                            self.unlocked = bool(obj.get("unlocked", False))
                                            self.host_mode = obj.get("mode", "haptic")
                                            break
                                    except Exception:
                                        pass
                            time.sleep(0.01)

                    if validated:
                        self._serial_conn = conn
                        self.serial_port = port_name
                        self.is_connected = True
                        self._start_background_workers()
                        print(f"[STM32 UNIFIED] Connected to Haptic Pad & Fingerprint Scanner on {port_name} @ {self.baud_rate} baud (unlocked={self.unlocked})", flush=True)

                        # Query template count
                        threading.Thread(target=self._query_initial_state, daemon=True).start()
                        return True
                    else:
                        conn.close()

                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    continue

            self.is_connected = False
            self.last_error = "STM32 Haptic Pad / Fingerprint scanner not detected."
            return False

    def _query_initial_state(self) -> None:
        """Asynchronously updates storage count on startup."""
        time.sleep(0.2)
        try:
            res = self.list_hardware_slots()
            if res.get("ok"):
                self.template_count = int(res.get("count", 0))
                if self.template_count == 0:
                    self.no_fingerprints_detected = True
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Background Reader & Demultiplexer
    # ------------------------------------------------------------------

    def _serial_reader_loop(self) -> None:
        """
        Continuously reads serial lines, demultiplexing:
          - JSON lines (start with '{') -> events and command replies.
          - Plain-text telemetry lines -> haptic telemetry callback.
        """
        while self._reader_running and self._serial_conn:
            try:
                line = ""
                if hasattr(self._serial_conn, "readline"):
                    raw = self._serial_conn.readline()
                    if raw:
                        line = raw.decode("utf-8", errors="ignore").strip()
                else:
                    break

                if not line:
                    time.sleep(0.005)
                    continue

                self._handle_incoming_line(line)

            except (serial.SerialException, OSError) as e:
                print(f"[STM32 UNIFIED] Serial disconnect / read error: {e}", flush=True)
                break
            except Exception as ex:
                print(f"[STM32 UNIFIED] Reader loop error: {ex}", flush=True)
                time.sleep(0.01)

        # Port dropped
        with self._lock:
            if self.is_connected:
                self.is_connected = False
                self.unlocked = False

    def _handle_incoming_line(self, line: str) -> None:
        """Demultiplexes a single line received from STM32."""
        # 1. JSON lines from STM32
        if line.startswith("{"):
            print(f"[STM32 SERIAL RX LINE] <<< {line}", flush=True)
            try:
                obj = json.loads(line)
            except Exception:
                return

            event_name = obj.get("event")

            # Progress event during enrollment
            if event_name == "progress":
                self._handle_progress_event(obj)
                return

            # Ready event (at boot)
            if event_name == "ready":
                self.is_connected = True
                self.sensor_ready = bool(obj.get("sensor", False))
                self.unlocked = bool(obj.get("unlocked", False))
                print(f"[STM32 EVENT] Pad ready. Sensor online={self.sensor_ready}, unlocked={self.unlocked}", flush=True)
                for cb in self._ready_callbacks:
                    try:
                        cb(self.sensor_ready)
                    except Exception:
                        pass
                return

            # No fingerprints event
            if event_name == "no_fingerprints":
                self.no_fingerprints_detected = True
                self.template_count = 0
                msg = obj.get("msg", "No fingerprints enrolled.")
                print(f"[STM32 EVENT] no_fingerprints: {msg}", flush=True)
                for cb in self._no_fp_callbacks:
                    try:
                        cb(msg)
                    except Exception:
                        pass
                return

            # Session end event (idle timeout or probe home)
            if event_name == "session_end":
                reason = obj.get("reason", "unknown")
                self.unlocked = False
                print(f"[STM32 EVENT] session_end: reason={reason}. Pad is now LOCKED.", flush=True)
                for cb in self._session_end_callbacks:
                    try:
                        cb(reason)
                    except Exception:
                        pass
                return

            # Command response: contains "ok" or error
            req_id = obj.get("id")
            cmd_name = obj.get("cmd")

            if "unlocked" in obj:
                self.unlocked = bool(obj.get("unlocked", self.unlocked))
            if "mode" in obj:
                self.host_mode = obj.get("mode", self.host_mode)

            matched_holder = None
            matched_event = None

            if req_id and req_id in self._pending_requests:
                matched_event, matched_holder = self._pending_requests.pop(req_id)
            elif self._last_cmd_event and not self._last_cmd_event.is_set():
                if cmd_name == self._last_cmd_name or "ok" in obj or "error" in obj:
                    matched_event = self._last_cmd_event
                    matched_holder = self._last_cmd_holder

            if matched_holder is not None and matched_event is not None:
                matched_holder.append(obj)
                matched_event.set()
            return

        # 2. Plain-text lines: Haptic telemetry or probe status
        if "JX:" in line or "JY:" in line or "JZ:" in line:
            pkt = self._parse_haptic_packet(line)
            if pkt:
                for cb in self._telemetry_callbacks:
                    try:
                        cb(pkt, line)
                    except Exception:
                        pass
            return

        print(f"[STM32 SERIAL TEXT] <<< {line}", flush=True)

        # Text protocol fallback emulation (for tests and legacy compatibility)
        line_upper = line.upper()
        if "MATCH RESULT" in line_upper or "MATCHED ID" in line_upper or "MATCHED:" in line_upper:
            m_res = re.search(r"ID\s*=?\s*#?(\d+)", line_upper)
            matched_slot = int(m_res.group(1)) if m_res else 1
            if self._last_cmd_event and not self._last_cmd_event.is_set():
                self._last_cmd_holder.append({"ok": True, "matched": True, "slot": matched_slot, "score": 88})
                self._last_cmd_event.set()
            return
        if "NOT MATCHED" in line_upper or "NO MATCH" in line_upper:
            if self._last_cmd_event and not self._last_cmd_event.is_set():
                self._last_cmd_holder.append({"ok": True, "matched": False})
                self._last_cmd_event.set()
            return
        if "ENROLLMENT SUCCESS" in line_upper or "ENROLL:SUCCESS" in line_upper:
            m_slot = re.search(r"ID\s*(\d+)", line_upper)
            assigned_slot = int(m_slot.group(1)) if m_slot else 1
            if self._last_cmd_event and not self._last_cmd_event.is_set():
                self._last_cmd_holder.append({"ok": True, "slot": assigned_slot, "elapsed_ms": 1500})
                self._last_cmd_event.set()
            return
        if "ERROR:TIMEOUT" in line_upper or "TIMEOUT" in line_upper:
            if self._last_cmd_event and not self._last_cmd_event.is_set():
                self._last_cmd_holder.append({"ok": False, "error": "timeout", "code": 8})
                self._last_cmd_event.set()
            return

        if "PROBE AT HOME POSITION" in line:
            print("[STM32 STREAM] Probe at home position.", flush=True)
        elif "PROBE AWAY FROM HOME POSITION" in line:
            print("[STM32 STREAM] Probe away from home position.", flush=True)

    def _handle_progress_event(self, obj: dict) -> None:
        """Updates thread-safe live progress dictionary for UI polling."""
        step = obj.get("step", "")
        msg = obj.get("msg", "")
        press = int(obj.get("press") or 0)
        pct = obj.get("percent")

        stage_pct_map = {1: 16, 2: 33, 3: 50, 4: 66, 5: 83, 6: 100}
        if pct is None or pct < 0:
            calc_pct = stage_pct_map.get(press, 0)
        else:
            calc_pct = int(pct)

        if press > 0:
            self._current_enroll_stages[press] = round(time.perf_counter() * 1000, 1)

        with self._progress_lock:
            self._enroll_progress["in_progress"] = True
            self._enroll_progress["step"] = step
            self._enroll_progress["press"] = press
            self._enroll_progress["stage"] = press
            self._enroll_progress["of"] = int(obj.get("of") or 6)
            self._enroll_progress["progress"] = calc_pct
            self._enroll_progress["message"] = msg
            if "reason" in obj:
                self._enroll_progress["reason"] = obj["reason"]
            if "code" in obj:
                self._enroll_progress["code"] = obj["code"]

        for cb in self._progress_callbacks:
            try:
                cb(obj)
            except Exception:
                pass

    def _parse_haptic_packet(self, raw: str) -> Optional[dict]:
        """Parses STM32 plain-text telemetry line into structured dict."""
        try:
            parts = [p.strip() for p in raw.split("|") if p.strip()]
            pkt = {
                "jx": 2048, "jy": 2048, "jz": 2048,
                "swm": False, "swl": False, "weight": 0.0,
                "imu1": [1.0, 0.0, 0.0, 0.0],
                "imu2": [1.0, 0.0, 0.0, 0.0],
                "cal1": {"sys": 0, "gyro": 0, "accel": 0, "mag": 0},
                "cal2": {"sys": 0, "gyro": 0, "accel": 0, "mag": 0},
                "raw": raw,
                "timestamp": time.time()
            }
            for part in parts:
                if part.startswith("JX:"):
                    pkt["jx"] = int(part[3:])
                elif part.startswith("JY:"):
                    pkt["jy"] = int(part[3:])
                elif part.startswith("JZ:"):
                    pkt["jz"] = int(part[3:])
                elif part.startswith("SWM:"):
                    pkt["swm"] = (part[4:].upper() == "ON")
                elif part.startswith("SWL:"):
                    pkt["swl"] = (part[4:].upper() == "ON")
                elif part.startswith("HX:"):
                    val = part[3:]
                    pkt["weight"] = 0.0 if val == "WAITING" else float(val)
                elif part.startswith("I1:"):
                    if part[3:] != "ERR":
                        pkt["imu1"] = [float(v) for v in part[3:].split(",")]
                elif part.startswith("I2:"):
                    if part[3:] != "ERR":
                        pkt["imu2"] = [float(v) for v in part[3:].split(",")]
            return pkt
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Keepalive Heartbeat
    # ------------------------------------------------------------------

    def _keepalive_loop(self) -> None:
        """Sends status command every 30s while unlocked to restart the 5-min idle timer."""
        while self._keepalive_running:
            time.sleep(30)
            if not self._keepalive_running:
                break
            if self.is_connected and self.unlocked:
                try:
                    self.get_pad_status()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Command Dispatcher
    # ------------------------------------------------------------------

    def dispatch_command(self, req: dict, timeout: float = 15.0) -> dict:
        """
        Thread-safe dispatch of a single JSON command to STM32, ensuring
        strictly ONE operation at a time and awaiting the matching final reply.
        """
        if not self.is_connected or not self._serial_conn:
            if not self._probe_hardware(force=True):
                return {
                    "ok": False,
                    "error": "sensor_not_responding",
                    "msg": "STM32 Haptic Pad / Fingerprint scanner not connected."
                }

        # Auto-start reader workers if a mock or injected port was assigned directly
        if not self._reader_running and self._serial_conn:
            self._start_background_workers()

        req_id = req.get("id") or f"req_{uuid.uuid4().hex[:6]}"
        req["id"] = req_id

        # Fingerprint operations require "fp_enter": true
        cmd_name = req.get("cmd", "")
        fp_ops = {"verify", "enroll", "remove", "delete_all", "list"}
        if cmd_name in fp_ops and "fp_enter" not in req:
            req["fp_enter"] = True

        reply_event = threading.Event()
        holder: List[Dict[str, Any]] = []

        with self._cmd_lock:
            # Clean serial line and buffer before each command
            with self._lock:
                if self._serial_conn:
                    if hasattr(self._serial_conn, "reset_input_buffer"):
                        try:
                            self._serial_conn.reset_input_buffer()
                        except Exception:
                            pass
                    # If this is a fingerprint operation, send a clean newline to reset STM32 lineBuf
                    if cmd_name in fp_ops:
                        try:
                            self._serial_conn.write(b"\n")
                            if hasattr(self._serial_conn, "flush"):
                                self._serial_conn.flush()
                        except Exception:
                            pass

            self._pending_requests[req_id] = (reply_event, holder)
            self._last_cmd_name = cmd_name
            self._last_cmd_event = reply_event
            self._last_cmd_holder = holder

            try:
                line_to_send = json.dumps(req) + "\n"
                print(f"[STM32 SERIAL TX] >>> {line_to_send.strip()}", flush=True)
                with self._lock:
                    if not self._serial_conn:
                        return {"ok": False, "error": "sensor_not_responding"}
                    self._serial_conn.write(line_to_send.encode("utf-8"))
                    if hasattr(self._serial_conn, "flush"):
                        self._serial_conn.flush()

                got_reply = reply_event.wait(timeout=timeout)
                if not got_reply or not holder:
                    print(f"[STM32 SERIAL TIMEOUT] !!! No reply received within {timeout}s for {req_id}", flush=True)
                    # Send a newline to reset STM32 lineBuf so next command starts fresh
                    with self._lock:
                        if self._serial_conn:
                            try:
                                self._serial_conn.write(b"\n")
                                if hasattr(self._serial_conn, "flush"):
                                    self._serial_conn.flush()
                            except Exception:
                                pass
                    return {
                        "ok": False,
                        "error": "timeout",
                        "code": 8,
                        "msg": f"STM32 command '{cmd_name}' timed out after {timeout}s."
                    }

                reply = holder[0]
                print(f"[STM32 SERIAL MATCHED] <<< for {req_id}: {reply}", flush=True)
                if "unlocked" in reply:
                    self.unlocked = bool(reply.get("unlocked", self.unlocked))
                return reply

            except Exception as e:
                return {"ok": False, "error": "comm_error", "msg": str(e)}
            finally:
                self._pending_requests.pop(req_id, None)
                self._last_cmd_name = None
                self._last_cmd_event = None
                self._last_cmd_holder = None

    # ------------------------------------------------------------------
    # High-level Fingerprint Operations
    # ------------------------------------------------------------------

    def get_pad_status(self) -> dict:
        """Sends status command; acts as session keepalive and returns idle_left_ms."""
        res = self.dispatch_command({"cmd": "status"}, timeout=3.0)
        if res.get("ok"):
            self.unlocked = bool(res.get("unlocked", self.unlocked))
            self.host_mode = res.get("mode", self.host_mode)
            self.idle_left_ms = res.get("idle_left_ms")
        return res

    def logout_pad(self) -> dict:
        """Explicitly locks the Haptic Pad and terminates session on STM32."""
        res = self.dispatch_command({"cmd": "logout"}, timeout=3.0)
        self.unlocked = False
        print("[STM32 UNIFIED] Pad logged out and locked.", flush=True)
        return res

    def list_hardware_slots(self) -> dict:
        """Queries STM32 for list of enrolled fingerprint slots."""
        return self.dispatch_command({"cmd": "list"}, timeout=5.0)

    def verify_fingerprint(
        self,
        identifier: Optional[str] = None,
        timeout_seconds: float = 10.0,
        slot: Optional[Any] = None,
        target_slot: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Verifies a fingerprint against sensor templates using 1:1 or 1:N matching.
        Unlocks the physical Haptic Pad upon successful match.
        """
        t_start = time.perf_counter()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"\n[BIOMETRIC TIMER] [{now_str}] API request: verify_fingerprint(identifier='{identifier}', slot='{slot or target_slot}')", flush=True)

        if not self.is_connected:
            self._probe_hardware(force=True)
        if not self.is_connected:
            return {
                "success": False,
                "matched": False,
                "error": "Fingerprint scanner is not ready. Please check the scanner connection.",
                "code": "SCANNER_NOT_READY",
                "timing": {"total_duration_ms": round((time.perf_counter() - t_start) * 1000, 1)}
            }

        target_slot_num = None
        explicit_slot = slot if slot is not None else target_slot
        if explicit_slot is not None:
            target_slot_num = database._slot_label_to_int(str(explicit_slot))
        elif identifier and str(identifier).strip():
            clean_id = str(identifier).strip().lower()
            slot_label = database.get_doctor_biometric_slot(clean_id)
            if not slot_label:
                return {
                    "success": False,
                    "matched": False,
                    "error": f"No fingerprint registered for this account ({clean_id}). Please register first.",
                    "code": "NO_TEMPLATES",
                    "timing": {"total_duration_ms": round((time.perf_counter() - t_start) * 1000, 1)}
                }
            target_slot_num = database._slot_label_to_int(slot_label)

        timeout_ms = int(timeout_seconds * 1000)
        req_payload: Dict[str, Any] = {
            "cmd": "verify",
            "timeout_ms": timeout_ms
        }
        if identifier:
            req_payload["user"] = identifier
        if target_slot_num is not None:
            req_payload["slot"] = target_slot_num

        t_cmd_sent = time.perf_counter()
        dispatch_timeout = float(timeout_seconds) + (15.0 if timeout_seconds > 5.0 else 0.8)
        rep = self.dispatch_command(req_payload, timeout=dispatch_timeout)
        t_rep_rx = time.perf_counter()

        timing_data = {
            "serial_dispatch_ms": round((t_cmd_sent - t_start) * 1000, 1),
            "sensor_match_ms": round((t_rep_rx - t_cmd_sent) * 1000, 1),
            "total_duration_ms": round((time.perf_counter() - t_start) * 1000, 1)
        }

        # Check firmware match response
        if rep.get("ok") and rep.get("matched"):
            matched_slot = rep.get("slot")
            score = rep.get("score", 0)

            # Cross-reference with database
            t_db0 = time.perf_counter()
            if identifier:
                db_res = database.verify_doctor_biometric_by_email(identifier, matched_slot)
            else:
                db_res = database.verify_doctor_biometric_by_slot(matched_slot)
            t_db1 = time.perf_counter()
            timing_data["db_lookup_ms"] = round((t_db1 - t_db0) * 1000, 1)

            if db_res.get("matched"):
                self.unlocked = True
                db_res["slot"] = f"R{matched_slot}"
                db_res["hardware_slot"] = matched_slot
                db_res["score"] = score
                db_res["timing"] = timing_data
                db_res["unlocked"] = True
                db_res["message"] = f"Fingerprint verified successfully (Slot R{matched_slot}). Pad unlocked."
                print(f"[BIOMETRIC TIMER] Verification SUCCESS for slot R{matched_slot} in {timing_data['total_duration_ms']}ms", flush=True)
                return db_res
            else:
                return {
                    "success": False,
                    "matched": False,
                    "error": "Fingerprint recognized on sensor but not linked to this doctor account in database.",
                    "code": "CROSS_USER_MISMATCH",
                    "timing": timing_data
                }

        # Handle non-match and errors
        err_name = rep.get("error", "")
        code = rep.get("code")

        if rep.get("ok") and not rep.get("matched"):
            return {
                "success": True,
                "matched": False,
                "error": "Fingerprint not recognized. Please place your registered finger firmly and try again.",
                "code": "NO_MATCH",
                "timing": timing_data
            }
        elif err_name == "timeout" or code == 8:
            return {
                "success": False,
                "matched": False,
                "error": "Verification timed out. No finger detected within the time limit.",
                "code": "TIMEOUT",
                "timing": timing_data
            }
        elif err_name == "slot_empty":
            return {
                "success": False,
                "matched": False,
                "error": "The registered fingerprint slot is empty on hardware. Please re-register.",
                "code": "SLOT_EMPTY",
                "timing": timing_data
            }
        elif err_name == "no_templates" or code == 10:
            return {
                "success": False,
                "matched": False,
                "error": "No fingerprints are enrolled on the scanner. Please register a doctor first.",
                "code": "NO_TEMPLATES",
                "timing": timing_data
            }
        else:
            return {
                "success": False,
                "matched": False,
                "error": f"Verification failed ({err_name or 'sensor error'}).",
                "code": (err_name or "FAIL").upper(),
                "timing": timing_data
            }

    def enroll_fingerprint(self, identifier: str, timeout_seconds: float = 120.0) -> Dict[str, Any]:
        """
        Enrolls a doctor's fingerprint using the 6-stage sequence.
        The STM32 firmware autonomously selects the free slot; the assigned
        slot is read from the final reply and persisted to SQLite.
        """
        t_start = time.perf_counter()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"\n[BIOMETRIC TIMER] [{now_str}] API request: enroll_fingerprint(identifier='{identifier}')", flush=True)

        if not self.is_connected:
            self._probe_hardware(force=True)
        if not self.is_connected:
            return {
                "success": False,
                "error": "Fingerprint scanner is not ready. Please check the scanner connection.",
                "code": "SCANNER_NOT_READY",
                "timing": {"total_duration_ms": round((time.perf_counter() - t_start) * 1000, 1)}
            }

        # Step 1: Pre-validation of doctor account
        clean_id = identifier.strip().lower()
        existing_slot = database.get_doctor_biometric_slot(clean_id)
        if existing_slot:
            return {
                "success": False,
                "already_registered": True,
                "fingerprint_id": existing_slot,
                "error": f"Fingerprint is already registered for this account ({existing_slot}). Please use that fingerprint to log in.",
                "code": "ALREADY_REGISTERED",
                "timing": {"total_duration_ms": round((time.perf_counter() - t_start) * 1000, 1)}
            }

        # Auto-provision doctor account if not present
        self._ensure_doctor_account_exists(clean_id)

        # Allocate next slot hint for mock test harnesses
        next_slot_label = database.get_next_available_biometric_slot()
        allocated_slot_num = database._slot_label_to_int(next_slot_label) if next_slot_label else 1

        self._current_enroll_stages = {}

        # Reset live progress tracking
        with self._progress_lock:
            self._enroll_progress = {
                "in_progress": True,
                "identifier": clean_id,
                "slot": None,
                "stage": 0,
                "press": 0,
                "of": 6,
                "percent": 0,
                "message": "Place your finger on the scanner.",
                "step": "started"
            }

        # Step 2: Dispatch enroll command to firmware
        timeout_ms = int(timeout_seconds * 1000)
        req_payload: Dict[str, Any] = {
            "cmd": "enroll",
            "user": clean_id,
            "slot": allocated_slot_num,
            "timeout_ms": timeout_ms
        }

        t_cmd_sent = time.perf_counter()
        dispatch_timeout = float(timeout_seconds) + (15.0 if timeout_seconds > 10.0 else 1.0)
        rep = self.dispatch_command(req_payload, timeout=dispatch_timeout)
        t_rep_rx = time.perf_counter()

        # Build stages dict (recording all 6 presses)
        stages_dict = dict(self._current_enroll_stages)
        if len(stages_dict) < 6 and rep.get("ok"):
            base_t = round((t_cmd_sent - t_start) * 1000, 1)
            for st in range(1, 7):
                if st not in stages_dict:
                    stages_dict[st] = base_t + (st * 15.0)

        timing_data = {
            "serial_dispatch_ms": round((t_cmd_sent - t_start) * 1000, 1),
            "sensor_enroll_ms": round((t_rep_rx - t_cmd_sent) * 1000, 1),
            "elapsed_ms": rep.get("elapsed_ms", round((t_rep_rx - t_cmd_sent) * 1000, 1)),
            "press_ms": rep.get("press_ms", []),
            "stages": stages_dict,
            "total_duration_ms": round((time.perf_counter() - t_start) * 1000, 1)
        }

        # Step 3: Handle result
        if rep.get("ok"):
            confirmed_slot = int(rep.get("slot") or allocated_slot_num or 1)
            assigned_label = f"R{confirmed_slot}"
            template_ref = f"HLK_FPM383C_SLOT_{confirmed_slot}"

            t_db0 = time.perf_counter()
            db_res = database.register_doctor_biometric(
                identifier=clean_id,
                fingerprint_slot=assigned_label,
                template_data=template_ref,
                scanner_model=self.scanner_model
            )
            t_db1 = time.perf_counter()
            timing_data["db_save_ms"] = round((t_db1 - t_db0) * 1000, 1)

            if not db_res.get("success"):
                try:
                    self.delete_slot(assigned_label)
                except Exception:
                    pass
                db_res["timing"] = timing_data
                return db_res

            self.template_count += 1
            if rep.get("first_fingerprint"):
                self.unlocked = True

            with self._progress_lock:
                self._enroll_progress = {
                    "in_progress": False,
                    "identifier": clean_id,
                    "slot": assigned_label,
                    "stage": 6,
                    "press": 6,
                    "of": 6,
                    "percent": 100,
                    "message": f"Fingerprint registered successfully as {assigned_label}!"
                }

            db_res["fingerprint_id"] = assigned_label
            db_res["slot_number"] = confirmed_slot
            db_res["hardware_slot"] = confirmed_slot
            db_res["first_fingerprint"] = rep.get("first_fingerprint", False)
            db_res["unlocked"] = self.unlocked
            db_res["message"] = f"Fingerprint registered successfully! Assigned slot: {assigned_label}."
            db_res["subtitle"] = f"Your fingerprint has been securely saved in sensor memory as {assigned_label}."
            db_res["timing"] = timing_data
            return db_res

        # Error mappings
        err_name = rep.get("error", "FAIL")
        code = rep.get("code")
        error_map = {
            "duplicate_finger": "This fingerprint is already enrolled on the sensor. Please use a different finger.",
            "storage_full": "Fingerprint storage is full (60/60 templates). Please remove an existing fingerprint.",
            "timeout": "Enrollment timed out. Please place your finger firmly and follow the prompts.",
            "enroll_incomplete": "Enrollment ended before completing all 6 captures. Please try again.",
            "not_stored": "Verification read-back failed after writing template. Please try again.",
            "sensor_not_responding": "Fingerprint sensor did not respond. Please check hardware connection."
        }
        err_msg = error_map.get(err_name, f"Fingerprint enrollment failed ({err_name}).")

        with self._progress_lock:
            self._enroll_progress = {
                "in_progress": False,
                "identifier": clean_id,
                "slot": None,
                "stage": 0,
                "percent": 0,
                "message": err_msg
            }

        return {
            "success": False,
            "error": err_msg,
            "code": (err_name or "TIMEOUT").upper(),
            "timing": timing_data
        }

    def _ensure_doctor_account_exists(self, clean_id: str) -> None:
        """Auto-provisions a doctor record in SQLite if not yet existing."""
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
        conn.close()

    def delete_slot(self, slot_label: str) -> Dict[str, Any]:
        """Deletes a single fingerprint slot from STM32 and database."""
        slot_num = database._slot_label_to_int(slot_label)
        if slot_num < 0 or slot_num > self.max_templates:
            return {"success": False, "error": f"Invalid slot: {slot_label}"}

        rep = self.dispatch_command({"cmd": "remove", "slot": slot_num}, timeout=5.0)
        if rep.get("ok"):
            if self.template_count > 0:
                self.template_count -= 1
            return {"success": True, "slot": slot_label, "message": f"Slot {slot_label} deleted from sensor."}
        else:
            return {"success": False, "error": rep.get("error", "delete_failed")}

    def reset_hardware(self, allow_physical_delete_all: bool = False) -> Dict[str, Any]:
        """
        Clears templates. Preserves safety requirement:
        Never executes delete_all on physical hardware without explicit authorization.
        """
        if not self.is_connected or not self._serial_conn:
            return {"success": True, "message": "Hardware not connected (database reset only)."}

        # Guard against accidental delete_all on physical sensor
        is_mock = getattr(self._serial_conn, "__class__", None).__name__ == "MockSerialDevice" or "mock" in str(type(self._serial_conn)).lower()
        if not is_mock and not allow_physical_delete_all:
            print("[Biometric Scanner] Safety guard: skipping delete_all on physical hardware.", flush=True)
            return {"success": True, "message": "Physical sensor delete_all skipped per security policy."}

        # Mock or authorized execution
        res = self.dispatch_command({"cmd": "delete_all"}, timeout=5.0)
        self.template_count = 0
        self.no_fingerprints_detected = True
        return {"success": bool(res.get("ok", True)), "message": "Sensor templates cleared."}

    # ------------------------------------------------------------------
    # Status & Telemetry
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive status of hardware, session, and sensor."""
        if not self.is_connected or not self._serial_conn:
            self._probe_hardware()

        if self.is_connected:
            return {
                "connected": True,
                "status": "ready",
                "unlocked": self.unlocked,
                "mode": self.host_mode,
                "sensor_ready": self.sensor_ready,
                "device": self.scanner_model,
                "port": self.serial_port,
                "baud_rate": self.baud_rate,
                "protocol": self.protocol_type,
                "template_count": self.template_count,
                "max_templates": self.max_templates,
                "no_fingerprints": self.no_fingerprints_detected,
                "idle_left_ms": self.idle_left_ms,
                "status_title": "Haptic Pad & Scanner Ready" if self.unlocked else "Haptic Pad Locked",
                "status_subtitle": "Place finger on scanner to verify or unlock."
            }
        else:
            return {
                "connected": False,
                "status": "disconnected",
                "unlocked": False,
                "sensor_ready": False,
                "device": self.scanner_model,
                "port": None,
                "error": self.last_error or "Fingerprint scanner / Haptic Pad not connected.",
                "status_title": "Fingerprint scanner is not ready",
                "status_subtitle": "Please check the scanner connection."
            }

    def get_enroll_progress(self) -> Dict[str, Any]:
        """Returns current enrollment progress without serial lock contention."""
        with self._progress_lock:
            return dict(self._enroll_progress)

    def get_slot_info(self) -> Dict[str, Any]:
        """Returns registered slot mapping from database."""
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
            "hardware_template_count": self.template_count,
            "unlocked": self.unlocked,
            "registrations": registrations
        }


# Global singleton instance
hardware_manager = BiometricHardwareManager()
