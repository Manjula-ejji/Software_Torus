"""
TORUS Healthcare - Biometric Scanner & Serial Integration Engine
Handles communication with physical optical fingerprint scanner hardware
(STM32 / Arduino + R307 / AS608 / FPM10A optical fingerprint scanner).

Multi-User Slot Architecture:
  - R307 supports up to 162 template slots (hardware IDs 1-162, 0-indexed pages 0-161).
  - TORUS uses slots 1-20 (logical labels R1-R20).
  - Each doctor/user is assigned one unique slot permanently.
  - Registration: ENROLL:<slot_id>  (e.g. ENROLL:3 for R3)
  - Verification: VERIFY  → hardware returns matched slot ID via 1:N search
  - Slot assignment is persisted in SQLite; survives server restarts.

STM32 Firmware Protocol (USART2 @ 115200 baud):
  Host → MCU     | MCU → Host
  ─────────────────────────────────────────────────────────────────
  [Boot / Ping]   | "Boot OK\r\n", "Waiting for ENROLL/VERIFY commands\r\n"
  ENROLL:<n>\r\n  | "Place finger for scan 1\r\n"
                  | "Lift finger\r\n"
                  | "Place same finger for scan 2\r\n"
                  | "Enrolled OK\r\n"
                  | "ENROLL_OK\r\n" | "ENROLL_TIMEOUT\r\n" | "ENROLL_FAIL\r\n" | "ERR:BAD_SLOT\r\n"
  VERIFY\r\n      | "Place finger to verify\r\n"
                  | "Haptic Pad Unlocked\r\n" + "UNLOCKED:<n>\r\n" (on match)
                  | "Haptic Pad Locked\r\n" + "LOCKED\r\n" (no match)
                  | "VERIFY_TIMEOUT\r\n" | "VERIFY_ERROR\r\n"
"""

from __future__ import annotations

import os
import time
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
    Manages communication with the STM32 / Arduino + R307 optical fingerprint scanner.
    Protocol: USB Serial at 115200 baud (STM32) or 57600 baud (Arduino).
    Supports up to 20 concurrent enrolled users (R1-R20).
    """

    def __init__(self):
        self.serial_port: Optional[str] = (
            os.environ.get("BIOMETRIC_SERIAL_PORT", "COM5").strip() or "COM5"
        )
        self.baud_rate: int = int(os.environ.get("BIOMETRIC_BAUD_RATE", "115200"))
        self._serial_conn: Optional[Any] = None
        self._lock = threading.Lock()
        self.is_connected: bool = False
        self.scanner_model: str = "STM32 / R307 Optical Biometric Scanner"
        self.protocol_type: str = "stm32_r307"
        self.last_error: Optional[str] = None
        self._probe_hardware()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _open_port(self, port_name: str, baud: int) -> Optional[Any]:
        """Opens serial port with clean terminal settings."""
        try:
            conn = serial.Serial(
                port_name, baud,
                timeout=2.0,
                write_timeout=2.0,
                dsrdtr=False,
                rtscts=False
            )
            conn.dtr = False
            conn.rts = False
            time.sleep(0.5)  # Allow Arduino to boot/reset
            return conn
        except Exception:
            return None

    def _probe_hardware(self) -> bool:
        """Probes serial ports and validates the fingerprint scanner with STATUS command."""
        if not PYSERIAL_AVAILABLE:
            self.last_error = "pyserial not installed. Cannot communicate with biometric scanner."
            self.is_connected = False
            return False

        try:
            available_ports = list(serial.tools.list_ports.comports())
            if not available_ports:
                self.is_connected = False
                self.last_error = "Fingerprint scanner not connected. No serial ports found."
                return False

            # Priority: configured port first, then keyword-match ports, then all others
            candidate_ports = []
            if self.serial_port:
                candidate_ports.append(self.serial_port)

            priority_keywords = [
                "arduino", "ch340", "ftdi", "cp210", "silicon labs",
                "usb serial", "usb-serial", "cdc", "fingerprint",
                "stlink", "stmicroelectronics", "virtual com port"
            ]
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

            # Prioritize STM32 baud (115200) then Arduino (57600)
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
                        # Send test probe command with CRLF
                        conn.write(b"STATUS\r\n")
                        conn.flush()
                        deadline = time.time() + 2.5
                        validated = False
                        detected_model = "STM32 / R307 Optical Biometric Scanner"
                        detected_proto = "stm32_r307"

                        while time.time() < deadline:
                            line = conn.readline().decode("utf-8", errors="ignore").strip()
                            if not line:
                                continue
                            line_upper = line.upper()
                            # STM32 signatures
                            if any(sig in line_upper for sig in ["BOOT OK", "WAITING FOR ENROLL", "ERR:UNKNOWN_CMD"]):
                                validated = True
                                detected_model = "STM32 / R307 Optical Biometric Scanner"
                                detected_proto = "stm32_r307"
                                break
                            # Arduino signatures
                            if "STATUS:READY" in line_upper:
                                validated = True
                                detected_model = "Arduino R307 Optical Biometric Scanner"
                                detected_proto = "arduino"
                                break
                            if "ERROR:" in line_upper:
                                break

                        if validated:
                            self._serial_conn = conn
                            self.serial_port = port_name
                            self.baud_rate = baud
                            self.scanner_model = detected_model
                            self.protocol_type = detected_proto
                            self.is_connected = True
                            self.last_error = None
                            print(
                                f"[Biometric Scanner] Connected: {port_name} @ {baud} baud ({detected_model})",
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
                        continue

            self.is_connected = False
            self.last_error = "Fingerprint scanner not found. Please check the USB connection."
            return False

        except Exception as e:
            self.is_connected = False
            self.last_error = f"Fingerprint scanner unavailable: {e}"
            return False

    def _send_line(self, command: str) -> None:
        """Send a single command line with CR/LF to the microcontroller."""
        self._serial_conn.write((command + "\r\n").encode("utf-8"))
        self._serial_conn.flush()

    def _read_line(self, timeout: float = 2.0) -> str:
        """Read one line from the microcontroller with a deadline."""
        self._serial_conn.timeout = timeout
        line = self._serial_conn.readline()
        return line.decode("utf-8", errors="ignore").strip()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Returns hardware connection status, re-probing if disconnected."""
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
                    "status_title": "Fingerprint scanner ready",
                    "status_subtitle": "Place your finger on the scanner to register."
                }
            return {
                "connected": False,
                "status": "disconnected",
                "device": self.scanner_model,
                "port": None,
                "error": self.last_error or "Fingerprint scanner not connected.",
                "status_title": "Fingerprint scanner is not ready",
                "status_subtitle": "Please check the USB connection."
            }

    # ------------------------------------------------------------------
    # Enrollment
    # ------------------------------------------------------------------

    def enroll_fingerprint(self, identifier: str) -> Dict[str, Any]:
        """
        Enrolls a doctor's fingerprint into the next available hardware slot (R1-R20).

        Flow:
        1. Check hardware connected.
        2. Validate doctor exists in DB.
        3. Block if doctor already enrolled.
        4. Find next available slot (from DB, not memory).
        5. Block if all 20 slots occupied.
        6. Send ENROLL:<slot_num> to Arduino.
        7. Parse 2-scan enrollment events (EVENT:WAITING_FOR_FINGER, etc.).
        8. On ENROLL:SUCCESS:<slot>, save DB mapping.
        9. Return success with assigned fingerprint_id (R<n>).

        Returns dict with:
          success: bool
          fingerprint_id: "R1" ... "R20"  (on success)
          error: str  (on failure)
        """
        hw = self.get_status()
        if not hw["connected"]:
            return {
                "success": False,
                "error": "Fingerprint scanner is not ready. Please check the USB connection.",
                "code": "SCANNER_NOT_READY"
            }

        with self._lock:
            try:
                conn = self._serial_conn
                conn.reset_input_buffer()
                conn.reset_output_buffer()

                # --- Step 1: Validate doctor ---
                doctor_check = self._validate_doctor_for_enrollment(identifier)
                if not doctor_check["ok"]:
                    return {
                        "success": False,
                        "error": doctor_check["error"],
                        "already_registered": doctor_check.get("already_registered", False),
                        "fingerprint_id": doctor_check.get("fingerprint_id"),
                        "code": doctor_check.get("code", "VALIDATION_ERROR")
                    }

                slot_label = doctor_check["slot_label"]   # e.g. "R3"
                slot_num   = doctor_check["slot_num"]     # e.g. 3

                # --- Step 2: Send enrollment command with specific slot ---
                cmd = f"ENROLL:{slot_num}"
                print(f"[Biometric Scanner] Sending: {cmd} (for {identifier})", flush=True)
                self._send_line(cmd)

                # --- Step 3: Monitor 2-scan enrollment protocol ---
                enroll_result = None
                confirmed_slot = None
                start_time = time.time()
                max_enroll_seconds = 60  # 2 scans + processing, generous timeout

                while time.time() - start_time < max_enroll_seconds:
                    line = self._read_line(timeout=2.0)
                    if not line:
                        continue

                    print(f"[Scanner Enroll] {line}", flush=True)
                    line_upper = line.upper()

                    # Progress indicators (STM32 & Arduino)
                    if "PLACE FINGER FOR SCAN 1" in line_upper or "EVENT:WAITING_FOR_FINGER" in line_upper:
                        print("[STM32] Phase 1: Place finger for scan 1", flush=True)
                    elif "LIFT FINGER" in line_upper or "EVENT:PASS_1_CAPTURED_LIFT_FINGER" in line_upper:
                        print("[STM32] Phase 2: Scan 1 captured — Lift finger", flush=True)
                    elif "PLACE SAME FINGER FOR SCAN 2" in line_upper or "EVENT:WAITING_FOR_SECOND_TOUCH" in line_upper:
                        print("[STM32] Phase 3: Place same finger for scan 2", flush=True)

                    # Success responses
                    elif "ENROLL_OK" in line_upper or "ENROLLED OK" in line_upper:
                        confirmed_slot = slot_num
                        enroll_result = "SUCCESS"
                        break
                    elif line_upper.startswith("ENROLL:SUCCESS:"):
                        parts = line.split(":")
                        if len(parts) >= 3:
                            try:
                                confirmed_slot = int(parts[2].strip())
                            except ValueError:
                                confirmed_slot = slot_num
                        else:
                            confirmed_slot = slot_num
                        enroll_result = "SUCCESS"
                        break

                    # Failure / Error responses
                    elif "ENROLL_TIMEOUT" in line_upper:
                        enroll_result = "TIMEOUT"
                        break
                    elif "ENROLL_FAIL" in line_upper:
                        enroll_result = "FAIL"
                        break
                    elif "ERR:BAD_SLOT" in line_upper or "ERROR:INVALID_SLOT" in line_upper:
                        enroll_result = "INVALID_SLOT"
                        break
                    elif "ERROR:FINGERPRINT_MISMATCH" in line_upper:
                        enroll_result = "MISMATCH"
                        break
                    elif "ERROR:IMAGING_FAILED" in line_upper:
                        enroll_result = "IMAGING_ERROR"
                        break
                    elif "ERROR:CONVERT_PASS_1_FAILED" in line_upper:
                        enroll_result = "CONVERT_1_ERROR"
                        break
                    elif "ERROR:CONVERT_PASS_2_FAILED" in line_upper:
                        enroll_result = "CONVERT_2_ERROR"
                        break
                    elif "ERROR:STORAGE_FAILED" in line_upper:
                        enroll_result = "STORAGE_ERROR"
                        break

                # --- Step 4: Handle result ---
                if enroll_result == "SUCCESS" and confirmed_slot is not None:
                    # Verify hardware stored in the slot we requested
                    if confirmed_slot != slot_num:
                        return {
                            "success": False,
                            "error": f"Hardware stored fingerprint in unexpected slot {confirmed_slot} instead of {slot_num}. Please retry.",
                            "code": "SLOT_MISMATCH"
                        }

                    # Build a template reference string (not the raw biometric data,
                    # which stays in the R307 hardware flash)
                    template_ref = f"R307_SLOT_{slot_num}_{identifier}_{int(time.time())}"

                    # Save DB mapping: email → slot label
                    db_res = database.register_doctor_biometric(
                        identifier=identifier,
                        fingerprint_slot=slot_label,
                        template_data=template_ref,
                        scanner_model=self.scanner_model
                    )

                    if db_res.get("success"):
                        db_res["fingerprint_id"] = slot_label
                        db_res["slot_number"] = slot_num
                        db_res["message"] = f"Fingerprint registered successfully. Assigned slot: {slot_label}."
                        db_res["subtitle"] = f"Your fingerprint has been securely stored in hardware slot {slot_label}."
                    return db_res

                # Error mapping
                error_map = {
                    "TIMEOUT":        "Fingerprint enrollment timed out. Please place your finger promptly and try again.",
                    "FAIL":           "Fingerprint enrollment failed on the scanner. Please ensure your finger is clean and flat.",
                    "MISMATCH":       "Both fingerprint scans did not match. Please try again keeping the same finger position.",
                    "IMAGING_ERROR":  "Fingerprint image capture failed. Please clean the scanner and try again.",
                    "CONVERT_1_ERROR":"Fingerprint scan 1 processing failed. Please try again.",
                    "CONVERT_2_ERROR":"Fingerprint scan 2 processing failed. Please try again.",
                    "STORAGE_ERROR":  "Fingerprint template storage failed. The hardware slot may be faulty.",
                    "INVALID_SLOT":   f"Hardware rejected slot {slot_num}. Slot must be between 1 and 20.",
                }
                error_msg = error_map.get(
                    enroll_result,
                    "Fingerprint enrollment timed out. Please place your finger firmly and try again."
                )
                return {
                    "success": False,
                    "error": error_msg,
                    "code": enroll_result or "TIMEOUT"
                }

            except Exception as e:
                self.is_connected = False
                self._serial_conn = None
                return {
                    "success": False,
                    "error": f"Fingerprint scanner communication error: {e}",
                    "code": "SCANNER_COMM_ERROR"
                }

    def _validate_doctor_for_enrollment(self, identifier: str) -> Dict[str, Any]:
        """
        Pre-enrollment validation:
        1. Checks the doctor exists in the DB.
        2. Blocks if already enrolled (returns existing slot).
        3. Finds next available slot from DB state.
        4. Blocks if all 20 slots are occupied.
        """
        import database as _db

        # Check if already enrolled
        existing_slot = _db.get_doctor_biometric_slot(identifier)
        if existing_slot:
            return {
                "ok": False,
                "already_registered": True,
                "fingerprint_id": existing_slot,
                "error": f"Fingerprint is already registered for this account (slot {existing_slot}). Please use that fingerprint to log in.",
                "code": "ALREADY_REGISTERED"
            }

        # Find next free slot
        next_slot_label = _db.get_next_available_biometric_slot()
        if next_slot_label is None:
            return {
                "ok": False,
                "error": f"All {_db.MAX_BIOMETRIC_SLOTS} fingerprint slots are occupied. Please remove an existing registration before adding a new one.",
                "code": "ALL_SLOTS_FULL"
            }

        slot_num = _db._slot_label_to_int(next_slot_label)
        return {
            "ok": True,
            "slot_label": next_slot_label,
            "slot_num": slot_num
        }

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify_fingerprint(self, identifier: Optional[str] = None) -> Dict[str, Any]:
        """
        Verifies a fingerprint against registered templates using 1:N hardware search.

        Flow:
        1. Check hardware connected.
        2. Send VERIFY to Arduino → hardware searches ALL enrolled templates.
        3. Arduino returns VERIFY:SUCCESS:<fingerID>:<confidence> with matched slot.
        4a. If identifier provided (email/uid from login form):
              - Look up which slot that doctor owns.
              - Compare hardware-matched slot to doctor's registered slot.
              - Only authenticate if they match (blocks User A fingerprint for User B email).
        4b. If no identifier:
              - Look up doctor by matched slot in DB.
              - Authenticate whoever owns that slot.
        5. Return doctor info + fingerprint_id on success.

        Args:
            identifier: Optional doctor email or UID from login form.

        Returns dict with:
          success: bool
          matched: bool
          fingerprint_id: "R<n>" on success
          doctor: {id, uid, name, email, role}
        """
        hw = self.get_status()
        if not hw["connected"]:
            return {
                "success": False,
                "matched": False,
                "error": "Fingerprint scanner is not ready. Please check the USB connection.",
                "code": "SCANNER_NOT_READY"
            }

        with self._lock:
            try:
                conn = self._serial_conn
                conn.reset_input_buffer()
                conn.reset_output_buffer()

                print("[Biometric Scanner] Sending VERIFY command...", flush=True)
                self._send_line("VERIFY")

                verify_result = None
                matched_slot_id = None
                confidence = None
                start_time = time.time()
                max_verify_seconds = 20

                while time.time() - start_time < max_verify_seconds:
                    line = self._read_line(timeout=2.0)
                    if not line:
                        continue

                    print(f"[Scanner Verify] {line}", flush=True)
                    line_upper = line.upper()

                    # Progress indicators
                    if "PLACE FINGER TO VERIFY" in line_upper or "EVENT:READING_FINGERPRINT" in line_upper:
                        verify_result = "READING"

                    # STM32 Match: UNLOCKED:<slot_1_based>
                    elif line_upper.startswith("UNLOCKED:"):
                        parts = line.split(":")
                        try:
                            matched_slot_id = int(parts[1].strip())
                        except (ValueError, IndexError):
                            matched_slot_id = None
                        verify_result = "SUCCESS"
                        break

                    # Arduino Match: VERIFY:SUCCESS:<fingerID>:<confidence>
                    elif line_upper.startswith("VERIFY:SUCCESS:"):
                        parts = line.split(":")
                        try:
                            matched_slot_id = int(parts[2].strip())
                            confidence = int(parts[3].strip()) if len(parts) > 3 else 0
                        except (ValueError, IndexError):
                            matched_slot_id = None
                        verify_result = "SUCCESS"
                        break

                    # Mismatch / Locked
                    elif "LOCKED" in line_upper or "VERIFY:NO_MATCH" in line_upper:
                        verify_result = "NO_MATCH"
                        break

                    # Timeout
                    elif "VERIFY_TIMEOUT" in line_upper or "TIMEOUT_NO_FINGER" in line_upper:
                        verify_result = "TIMEOUT"
                        break

                    # Sensor error
                    elif "VERIFY_ERROR" in line_upper or line_upper.startswith("ERROR:"):
                        verify_result = "ERROR"
                        break

                # --- Handle result ---
                if verify_result == "SUCCESS" and matched_slot_id is not None:
                    print(
                        f"[Biometric Scanner] Hardware matched slot {matched_slot_id}",
                        flush=True
                    )
                    # Route to correct verification logic
                    if identifier and identifier.strip():
                        # Email-specific verification: confirm the matched slot belongs to THIS doctor
                        db_res = database.verify_doctor_biometric_by_email(
                            identifier=identifier,
                            matched_slot_id=matched_slot_id
                        )
                    else:
                        # Open verification: look up who owns the matched slot
                        db_res = database.verify_doctor_biometric_by_slot(
                            matched_slot_id=matched_slot_id
                        )

                    if db_res.get("matched"):
                        db_res["haptic_status"] = "UNLOCKED"
                        db_res["message"] = f"Haptic Pad Unlocked: Fingerprint verified successfully ({db_res.get('fingerprint_id', '')})."
                    else:
                        db_res["haptic_status"] = "LOCKED"
                        db_res["message"] = "Haptic Pad Locked: Fingerprint does not match the registered profile for this account."
                    return db_res

                elif verify_result == "NO_MATCH":
                    return {
                        "success": False,
                        "matched": False,
                        "haptic_status": "LOCKED",
                        "error": "Haptic Pad Locked: Fingerprint does not match any registered biometric profile.",
                        "code": "NO_MATCH"
                    }
                elif verify_result == "TIMEOUT":
                    return {
                        "success": False,
                        "matched": False,
                        "haptic_status": "LOCKED",
                        "error": "Verification timed out. Please place your registered finger firmly on the scanner.",
                        "code": "TIMEOUT"
                    }
                else:
                    return {
                        "success": False,
                        "matched": False,
                        "haptic_status": "LOCKED",
                        "error": "Fingerprint read error. Please place your finger flat on the scanner and try again.",
                        "code": "READ_ERROR"
                    }

            except Exception as e:
                self.is_connected = False
                self._serial_conn = None
                return {
                    "success": False,
                    "matched": False,
                    "error": f"Fingerprint scanner communication error: {e}",
                    "code": "SCANNER_COMM_ERROR"
                }

    # ------------------------------------------------------------------
    # Slot management helpers
    # ------------------------------------------------------------------

    def delete_slot(self, slot_label: str) -> Dict[str, Any]:
        """
        Deletes a fingerprint template from the hardware slot.
        Used when removing a registration to free the slot for a new user.
        """
        hw = self.get_status()
        if not hw["connected"]:
            return {
                "success": False,
                "error": "Fingerprint scanner not connected.",
                "code": "SCANNER_NOT_READY"
            }

        slot_num = database._slot_label_to_int(slot_label)
        if slot_num < 1:
            return {"success": False, "error": f"Invalid slot label: {slot_label}"}

        with self._lock:
            try:
                conn = self._serial_conn
                conn.reset_input_buffer()
                conn.reset_output_buffer()
                self._send_line(f"DELETE:{slot_num}")

                deadline = time.time() + 5.0
                while time.time() < deadline:
                    line = self._read_line(timeout=2.0)
                    if not line:
                        continue
                    if f"DELETE:SUCCESS:{slot_num}" in line:
                        return {"success": True, "slot": slot_label, "message": f"Slot {slot_label} deleted from hardware."}
                    if "ERROR:DELETE_FAILED" in line.upper():
                        return {"success": False, "error": f"Hardware could not delete slot {slot_label}.", "code": "DELETE_FAILED"}

                return {"success": False, "error": "Delete command timed out.", "code": "TIMEOUT"}

            except Exception as e:
                self.is_connected = False
                self._serial_conn = None
                return {"success": False, "error": str(e), "code": "SCANNER_COMM_ERROR"}

    def get_slot_info(self) -> Dict[str, Any]:
        """Returns current slot allocation summary from the database."""
        next_slot = database.get_next_available_biometric_slot()
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.fingerprint_slot, d.email, d.name, b.enrolled_at
            FROM doctor_biometrics b
            JOIN doctors d ON b.doctor_id = d.id
            WHERE b.is_active = 1 AND b.fingerprint_slot IS NOT NULL
            ORDER BY b.fingerprint_slot
        """)
        rows = cursor.fetchall()
        conn.close()

        registrations = [
            {
                "slot": row["fingerprint_slot"],
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
            "registrations": registrations
        }


# Global singleton
hardware_manager = BiometricHardwareManager()
