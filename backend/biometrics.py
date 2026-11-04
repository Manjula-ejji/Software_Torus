"""
TORUS Healthcare - Biometric Scanner & Serial Integration Engine
HLK-FPM383C Optical/Capacitive Fingerprint Sensor on STM32F446RE

Architecture & Hardware Specifications:
  - Microcontroller: STM32F446RE (Nucleo-64)
  - Fingerprint Module: HLK-FPM383C
  - Sensor UART: STM32 USART1 (PA9-TX, PA10-RX) @ 57600 baud, 8-N-1
  - Host Serial: STM32 USART2 (PA2-TX, PA3-RX) via ST-Link VCP @ 115200 baud, 8-N-1
  - TOUCHOUT: PC0 input (Active LOW: LOW = finger detected, HIGH = idle)
  - Sensor Capacity: 60 fingerprint templates (IDs 0..59)
  - TORUS Slots: R1..R59 mapped 1:1 to hardware IDs 1..59

Protocol Commands (USART2 @ 115200 baud):
  Host -> STM32       | Expected STM32 Responses
  ─────────────────────────────────────────────────────────────────────────────
  STATUS / COUNT      | "Stored fingerprints: <N>/60\r\n"
  HELP / ?            | "FPM383C COMMANDS (IDs 0-59; capacity 60)\r\n..."
  ENROLL <id>         | "Starting enrollment for ID <id>.\r\n"
                      | "Enrollment status: progress <P>%, capture stage <C>.\r\n"
                      | "ENROLLMENT SUCCESS: fingerprint saved as ID <id>.\r\n"
                      | "DUPLICATE FINGERPRINT: sensor rejected this enrollment.\r\n"
                      | "ID <id> is already enrolled.\r\n"
                      | "Enrollment timed out.\r\n"
  ADD                 | "ADD selected free fingerprint ID <id>.\r\n"
  MATCH               | "Touch the sensor and hold your finger still...\r\n"
                      | "Finger detected. Scanning...\r\n"
                      | "Match result=1, ID=<id>, score=<score>\r\n"
                      | "MATCHED: fingerprint ID <id> (score <score>).\r\n"
                      | "NOT MATCHED.\r\n"
  MATCH <id>          | "MATCHED: fingerprint matches ID <id> (score <score>).\r\n"
                      | "NOT MATCHED to ID <id>. Sensor recognized ID <other> instead.\r\n"
                      | "NOT MATCHED.\r\n"
                      | "NOT MATCHED: no fingerprint is stored at ID <id>.\r\n"
  DELETE <id>         | "DELETED fingerprint ID <id>.\r\n"
                      | "No fingerprint is stored at ID <id>.\r\n"
"""

from __future__ import annotations

import os
import re
import time
import datetime
import threading
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
    Manages communication with the physical STM32F446RE + HLK-FPM383C fingerprint sensor.
    Console communication is over USB Serial (ST-Link Virtual COM Port) @ 115200 baud.
    """

    def __init__(self):
        self.serial_port: Optional[str] = (
            os.environ.get("BIOMETRIC_SERIAL_PORT", "").strip() or None
        )
        self.baud_rate: int = int(os.environ.get("BIOMETRIC_BAUD_RATE", "115200"))
        self._serial_conn: Optional[Any] = None
        self._lock = threading.RLock()
        self.is_connected: bool = False
        self.scanner_model: str = "STM32 / HLK-FPM383C Fingerprint Scanner"
        self.protocol_type: str = "stm32_fpm383c"
        self.last_error: Optional[str] = None
        self.template_count: int = 0
        self.max_templates: int = 60

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

    def _drain_trailing_bytes(self, window_seconds: float = 0.03) -> None:
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
                timeout=0.25,
                write_timeout=1.0,
                dsrdtr=False,
                rtscts=False
            )
            time.sleep(0.08)  # Settle time for ST-Link VCP
            return conn
        except Exception:
            return None

    def _probe_hardware(self) -> bool:
        """
        Probes serial ports dynamically and validates the STM32 HLK-FPM383C controller
        via the STATUS / COUNT / HELP command handshake.
        Fast-path: tries configured/last known port first.
        """
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
            if self.serial_port:
                candidate_ports.append(self.serial_port)

            # Prioritize STLink or known COM8 port
            for p in available_ports:
                desc = (p.description or "").lower()
                mfg = (p.manufacturer or "").lower()
                hwid = (p.hwid or "").lower()
                if "stlink" in desc or "stm32" in desc or "stmicro" in mfg or p.device == "COM8":
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

            baud_candidates = [115200, 57600]
            if self.baud_rate not in baud_candidates:
                baud_candidates.insert(0, self.baud_rate)

            for port_name in candidate_ports:
                for baud in baud_candidates:
                    conn = self._open_port(port_name, baud)
                    if not conn:
                        continue
                    try:
                        conn.reset_input_buffer()
                        conn.reset_output_buffer()

                        # Send test probe command
                        conn.write(b"STATUS\r\n")
                        conn.flush()
                        deadline = time.time() + 0.5
                        validated = False
                        detected_model = "STM32 / HLK-FPM383C Fingerprint Scanner"
                        detected_proto = "stm32_fpm383c"
                        count_found = 0

                        while time.time() < deadline:
                            if conn.in_waiting:
                                raw_line = conn.readline()
                                if not raw_line:
                                    continue
                                line = raw_line.decode("utf-8", errors="ignore").strip()
                                if not line:
                                    continue
                                line_upper = line.upper()

                                m = re.search(r"STORED FINGERPRINTS:\s*(\d+)/(\d+)", line_upper)
                                if m:
                                    validated = True
                                    count_found = int(m.group(1))
                                    self.template_count = count_found
                                    self.max_templates = int(m.group(2))
                                    detected_model = "STM32 / HLK-FPM383C Fingerprint Scanner"
                                    detected_proto = "stm32_fpm383c"
                                    break

                                if any(sig in line_upper for sig in ["FPM383C", "HLK-FPM383C", "COMMANDS"]):
                                    validated = True
                                    detected_model = "STM32 / HLK-FPM383C Fingerprint Scanner"
                                    detected_proto = "stm32_fpm383c"
                                    break
                            time.sleep(0.01)

                        # Fallback query if STATUS did not answer immediately: send HELP
                        if not validated:
                            conn.write(b"HELP\r\n")
                            conn.flush()
                            h_deadline = time.time() + 0.4
                            while time.time() < h_deadline:
                                if conn.in_waiting:
                                    raw_line = conn.readline()
                                    if not raw_line:
                                        continue
                                    line = raw_line.decode("utf-8", errors="ignore").strip()
                                    line_upper = line.upper()
                                    if any(sig in line_upper for sig in ["FPM383C", "HLK-FPM383C", "ENROLL", "MATCH"]):
                                        validated = True
                                        detected_model = "STM32 / HLK-FPM383C Fingerprint Scanner"
                                        detected_proto = "stm32_fpm383c"
                                        break
                                time.sleep(0.01)

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
                                f"({detected_model}, Stored: {self.template_count}/{self.max_templates})",
                                flush=True
                            )
                            return True
                        else:
                            conn.close()

                    except Exception as probe_err:
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

    def _read_line(self, timeout: float = 0.3) -> str:
        """Read one line from the microcontroller with a responsive deadline."""
        if not self._serial_conn:
            return ""
        try:
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self._serial_conn.in_waiting:
                    raw = self._serial_conn.readline()
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if line:
                        return line
                time.sleep(0.005)
            # One quick final check
            if self._serial_conn.in_waiting:
                raw = self._serial_conn.readline()
                return raw.decode("utf-8", errors="ignore").strip()
            return ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Returns hardware connection status, re-probing only if disconnected."""
        with self._lock:
            if self.is_connected and self._serial_conn:
                try:
                    if not self._serial_conn.is_open:
                        self.is_connected = False
                        self._serial_conn = None
                except Exception:
                    self.is_connected = False
                    self._serial_conn = None

            if not self.is_connected or not self._serial_conn:
                self._probe_hardware()

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
                    "port": self.serial_port,
                    "error": self.last_error or "Fingerprint scanner not connected.",
                    "status_title": "Fingerprint scanner is not ready",
                    "status_subtitle": "Please check the scanner connection."
                }

    def get_enroll_progress(self) -> Dict[str, Any]:
        """Returns the current enrollment progress for UI polling."""
        with self._lock:
            return dict(self._enroll_progress)

    # ------------------------------------------------------------------
    # Enrollment
    # ------------------------------------------------------------------

    def enroll_fingerprint(self, identifier: str) -> Dict[str, Any]:
        """
        Enrolls a doctor's fingerprint using the HLK-FPM383C auto-enrollment sequence.

        Workflow:
        1. Validates doctor account in database (or auto-provisions doctor record).
        2. Blocks if doctor already has an active enrolled fingerprint.
        3. Allocates the next available hardware slot (R1..R59).
        4. Sends 'ENROLL <id>' to STM32 over USART2.
        5. STM32 commands the HLK-FPM383C module through USART1.
        6. Sensor performs 6 captures with finger lift/place.
        7. Streams stage progress (16%, 33%, 50%, 66%, 83%, 100%) in self._enroll_progress.
        8. On 'ENROLLMENT SUCCESS', verifies template stored, saves DB mapping, returns success.

        Returns:
          dict with success, fingerprint_id (e.g. 'R1'), message, timing, and doctor record.
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

                self._enroll_progress = {
                    "in_progress": True,
                    "identifier": identifier,
                    "slot": slot_label,
                    "stage": 0,
                    "progress": 5,
                    "message": f"Starting enrollment for {slot_label}. Follow the sensor LED prompts."
                }

                # Step 2: Dispatch command to STM32
                cmd = f"ENROLL {slot_num}"
                t_cmd_sent = time.perf_counter()
                self._send_line(cmd)
                print(f"[BIOMETRIC TIMER] Serial command '{cmd}' dispatched at {(t_cmd_sent-t_start)*1000:.1f}ms", flush=True)

                enroll_result = None
                confirmed_slot = None
                max_enroll_seconds = 130  # FPM383C 6-capture timeout is up to 120 seconds
                stage_times = {}

                while time.perf_counter() - t_cmd_sent < max_enroll_seconds:
                    line = self._read_line(timeout=0.35)
                    if not line:
                        continue

                    line_upper = line.upper()

                    # Ignore asynchronous TOUCHOUT pin status lines
                    if "TOUCHOUT" in line_upper:
                        continue

                    print(f"[STM32 ENROLL RX] {line}", flush=True)

                    # Progress parsing: "Enrollment status: progress 33%, capture stage 2."
                    prog_match = re.search(r"PROGRESS\s*(\d+)%.*?STAGE\s*(\d+)", line_upper)
                    if prog_match:
                        pct = int(prog_match.group(1))
                        stage = int(prog_match.group(2))
                        now_t = time.perf_counter()
                        stage_times[stage] = round((now_t - t_cmd_sent), 2)
                        msg = f"Capture stage {stage}/6 recorded ({pct}%). Lift finger and place again..."
                        self._enroll_progress = {
                            "in_progress": True,
                            "identifier": identifier,
                            "slot": slot_label,
                            "stage": stage,
                            "progress": pct,
                            "message": msg
                        }
                        print(f"[BIOMETRIC TIMER] Stage {stage}/6 recorded at {stage_times[stage]}s ({pct}%)", flush=True)
                        continue

                    # Success: "ENROLLMENT SUCCESS: fingerprint saved as ID 1."
                    if "ENROLLMENT SUCCESS" in line_upper:
                        m_id = re.search(r"(?:SAVED AS ID|ID)\s*(\d+)", line_upper)
                        confirmed_slot = int(m_id.group(1)) if m_id else slot_num
                        enroll_result = "SUCCESS"
                        self._enroll_progress = {
                            "in_progress": False,
                            "identifier": identifier,
                            "slot": slot_label,
                            "stage": 6,
                            "progress": 100,
                            "message": f"Fingerprint registered successfully as {slot_label}!"
                        }
                        break

                    # Overwrite protection / occupied slot
                    if "ALREADY ENROLLED" in line_upper:
                        enroll_result = "ALREADY_OCCUPIED"
                        break

                    # Duplicate finger protection
                    if "DUPLICATE FINGERPRINT" in line_upper:
                        enroll_result = "DUPLICATE"
                        break

                    # Storage capacity limit
                    if "FINGERPRINT LIMIT REACHED" in line_upper:
                        enroll_result = "STORAGE_FULL"
                        break

                    # Timeout
                    if "ENROLLMENT TIMED OUT" in line_upper or "TIMEOUT" in line_upper:
                        enroll_result = "TIMEOUT"
                        break

                    # Sensor hardware/software failure
                    if "ENROLLMENT FAILED" in line_upper or "TRANSMIT FAILED" in line_upper:
                        enroll_result = "FAIL"
                        break

                    # Legacy firmware support
                    if "ENROLL_OK" in line_upper or "ENROLLED OK" in line_upper:
                        confirmed_slot = slot_num
                        enroll_result = "SUCCESS"
                        break

                t_enroll_finish = time.perf_counter()

                # Step 3: Handle result and database persistence
                if enroll_result == "SUCCESS" and confirmed_slot is not None:
                    template_ref = f"HLK_FPM383C_SLOT_{confirmed_slot}"
                    assigned_label = f"R{confirmed_slot}"

                    t_db_start = time.perf_counter()
                    # Persist mapping in SQLite database
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
                    "TIMEOUT":          "Enrollment timed out. Please follow the sensor prompts and place your finger firmly.",
                    "FAIL":             "Fingerprint capture failed on hardware. Please reposition your finger and try again."
                }
                err_msg = error_map.get(enroll_result, "Fingerprint enrollment failed. Please try again.")

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
                self._drain_trailing_bytes(0.03)

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
            temp_uid = f"DOC{int(time.time()) % 100000:05d}"
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
    # Verification / Matching
    # ------------------------------------------------------------------

    def verify_fingerprint(self, identifier: Optional[str] = None) -> Dict[str, Any]:
        """
        Verifies a fingerprint against sensor templates using real physical matching.

        Workflow:
        1. Checks physical scanner is connected.
        2. If identifier (email/UID) is provided:
           - Verifies doctor has an active biometric registration.
           - Targets match command 'MATCH <slot_id>' to guarantee identity.
        3. If no identifier provided:
           - Sends 'MATCH' to perform 1:N search across all enrolled templates.
        4. Doctor places registered finger on the sensor.
        5. STM32 reads TOUCHOUT on PC0 and initiates USART1 match transaction with HLK-FPM383C.
        6. Sensor returns match result, matched template ID, and confidence score.
        7. Python confirms matched ID against the authenticated doctor's registered slot.
        8. Returns authenticated doctor record on success; rejects unauthorized attempts.

        Returns:
          dict with success, matched (bool), fingerprint_id, doctor dict, timing, and message.
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
            try:
                conn = self._serial_conn
                self._drain_serial_buffer()

                target_slot_num: Optional[int] = None
                registered_slot_label: Optional[str] = None

                # If identifier provided, verify account registration first
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

                # Send appropriate match command
                if target_slot_num is not None:
                    cmd = f"MATCH {target_slot_num}"
                    print(f"[BIOMETRIC VERIFY] Targeted verification command: '{cmd}' for slot {registered_slot_label}", flush=True)
                else:
                    cmd = "MATCH"
                    print("[BIOMETRIC VERIFY] 1:N open search command: 'MATCH'", flush=True)

                t_cmd_sent = time.perf_counter()
                self._send_line(cmd)
                print(f"[BIOMETRIC TIMER] Serial command '{cmd}' dispatched at {(t_cmd_sent-t_start)*1000:.1f}ms", flush=True)

                verify_result = None
                matched_id = None
                match_score = 0
                max_verify_seconds = 9.0  # Firmware waits up to 8s for finger match
                t_first_rx = None
                t_match_done = None

                while time.perf_counter() - t_cmd_sent < max_verify_seconds:
                    line = self._read_line(timeout=0.15)
                    if not line:
                        continue

                    if t_first_rx is None:
                        t_first_rx = time.perf_counter()
                        print(f"[BIOMETRIC TIMER] First sensor response at {(t_first_rx-t_cmd_sent)*1000:.1f}ms: '{line}'", flush=True)

                    line_upper = line.upper()

                    # Timeout waiting for finger touch or match response: catch before checking TOUCHOUT
                    if "NO FINGER DETECTED" in line_upper or "NO MATCH RESPONSE" in line_upper:
                        t_match_done = time.perf_counter()
                        verify_result = "TIMEOUT"
                        print(f"[STM32 MATCH RX] Timeout response: {line}", flush=True)
                        break

                    # Ignore asynchronous TOUCHOUT pin status lines only
                    if line_upper.startswith("TOUCHOUT PC0 CHANGED") or line_upper.startswith("TOUCHOUT:"):
                        continue

                    if "TOUCH THE SENSOR" in line_upper or "HOLD YOUR FINGER" in line_upper:
                        print(f"[BIOMETRIC TIMER] Sensor waiting for finger at {(time.perf_counter()-t_cmd_sent)*1000:.1f}ms", flush=True)
                        continue

                    if "FINGER DETECTED" in line_upper:
                        print(f"[BIOMETRIC TIMER] Sensor scanning finger at {(time.perf_counter()-t_cmd_sent)*1000:.1f}ms", flush=True)
                        continue

                    print(f"[STM32 MATCH RX] {line}", flush=True)

                    # Direct match result line from firmware: "Match result=1, ID=1, score=85"
                    m_res = re.search(r"MATCH RESULT\s*=\s*(\d+)\s*,\s*ID\s*=\s*(\d+)\s*,\s*SCORE\s*=\s*(\d+)", line_upper)
                    if m_res:
                        t_match_done = time.perf_counter()
                        res_code = int(m_res.group(1))
                        res_id = int(m_res.group(2))
                        res_score = int(m_res.group(3))
                        print(f"[BIOMETRIC TIMER] Match result evaluated at {(t_match_done-t_cmd_sent)*1000:.1f}ms: code={res_code}, id={res_id}, score={res_score}", flush=True)
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

                    # Match success line: "MATCHED: fingerprint ID 1 (score 85)." or "MATCHED: fingerprint matches ID 1..."
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

                    # Cross-user mismatch: "NOT MATCHED to ID 1. Sensor recognized ID 2 instead."
                    if "NOT MATCHED TO ID" in line_upper or "RECOGNIZED ID" in line_upper:
                        t_match_done = time.perf_counter()
                        verify_result = "WRONG_DOCTOR"
                        break

                    # Unrecognized / no match
                    if "NOT MATCHED" in line_upper:
                        t_match_done = time.perf_counter()
                        verify_result = "NO_MATCH"
                        break

                    # No templates enrolled in sensor (firmware: "No fingerprints are enrolled" or "No figerprints are enrolled")
                    if any(sig in line_upper for sig in [
                        "NO FINGERPRINTS ARE ENROLLED",
                        "NO FIGERPRINTS ARE ENROLLED",
                        "ARE ENROLLED. USE ENROLL",
                        "NO FINGERPRINTS",
                        "NO FIGERPRINTS"
                    ]):
                        t_match_done = time.perf_counter()
                        verify_result = "NO_TEMPLATES"
                        break

                    # Timeout waiting for finger touch: "No finger detected within 10 seconds..."
                    if "NO FINGER DETECTED" in line_upper or "NO MATCH RESPONSE" in line_upper:
                        t_match_done = time.perf_counter()
                        verify_result = "TIMEOUT"
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
                    print(f"[BIOMETRIC TIMER] [TOTAL DURATION] Verification completed in {t_total:.3f}s (Target met: {t_total <= 5.0})", flush=True)

                    if db_res.get("matched"):
                        db_res["message"] = f"Fingerprint verified successfully ({logical_slot})."
                    else:
                        db_res["message"] = "Fingerprint not recognized for this account."

                    db_res["timing"] = {
                        "serial_dispatch_ms": round((t_cmd_sent - t_start) * 1000, 1),
                        "sensor_match_ms": round(((t_match_done or t_eval) - t_cmd_sent) * 1000, 1),
                        "db_lookup_ms": round((t_db_end - t_db_start) * 1000, 1),
                        "total_duration_ms": round(t_total * 1000, 1),
                        "target_met": t_total <= 5.0
                    }
                    return db_res

                # Handle failure results with accurate timing
                t_total = time.perf_counter() - t_start
                timing_data = {
                    "serial_dispatch_ms": round((t_cmd_sent - t_start) * 1000, 1),
                    "total_duration_ms": round(t_total * 1000, 1),
                    "target_met": t_total <= 5.0
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
                self._drain_trailing_bytes(0.03)

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
                cmd = f"DELETE {slot_num}"
                self._send_line(cmd)

                deadline = time.time() + 3.0
                while time.time() < deadline:
                    line = self._read_line(timeout=0.3)
                    if not line:
                        continue
                    line_upper = line.upper()
                    if "DELETED FINGERPRINT" in line_upper or "NO FINGERPRINT IS STORED" in line_upper:
                        if self.template_count > 0:
                            self.template_count -= 1
                        self._drain_trailing_bytes(0.03)
                        return {
                            "success": True,
                            "slot": slot_label,
                            "message": f"Slot {slot_label} removed from sensor."
                        }
                    if "DELETE FAILED" in line_upper:
                        return {
                            "success": False,
                            "error": f"Sensor could not delete slot {slot_label}.",
                            "code": "DELETE_FAILED"
                        }

                return {"success": False, "error": "Delete command timed out.", "code": "TIMEOUT"}

            except Exception as e:
                self._close_serial()
                return {"success": False, "error": str(e), "code": "SCANNER_COMM_ERROR"}
            finally:
                self._drain_trailing_bytes(0.03)

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
                print("[Biometric Scanner] Resetting hardware: deleting active slots...", flush=True)
                for s in range(0, 60):
                    self._send_line(f"DELETE {s}")
                    time.sleep(0.02)

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
