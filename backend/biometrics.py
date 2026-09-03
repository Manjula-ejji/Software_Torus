"""
TORUS Healthcare - Biometric Scanner & Serial Integration Engine
Handles communication with physical optical/capacitive fingerprint scanner hardware (STM32 / ST-Link R307, Arduino, etc.).
Uses doctor-friendly, non-technical messaging for all status and error conditions.
"""

from __future__ import annotations

import os
import sys
import time
import json
import threading
from typing import Optional, Dict, Any, Tuple
from pathlib import Path

try:
    import serial
    import serial.tools.list_ports
    PYSERIAL_AVAILABLE = True
except ImportError:
    PYSERIAL_AVAILABLE = False

import database

class BiometricHardwareManager:
    """
    Manages communication with the biometric fingerprint scanner.
    Matches STM32 R307 firmware protocol (main.c) with clean terminal serial settings.
    """

    def __init__(self):
        self.serial_port: Optional[str] = os.environ.get("BIOMETRIC_SERIAL_PORT", "COM5").strip() or "COM5"
        self.baud_rate: int = int(os.environ.get("BIOMETRIC_BAUD_RATE", "115200"))
        self._serial_conn: Optional[Any] = None
        self._lock = threading.Lock()
        self.is_connected: bool = False
        self.scanner_model: str = "STM32 R307 Optical Biometric Scanner"
        self.protocol_type: str = "stm32"
        self.last_error: Optional[str] = None
        self._current_enroll_event: str = "IDLE"
        self._probe_hardware()

    def _open_port(self, port_name: str, baud: int) -> Optional[Any]:
        """Opens serial port with clean terminal settings (DTR/RTS disabled to prevent STM32 resets)."""
        try:
            conn = serial.Serial(
                port_name,
                baud,
                timeout=1.0,
                write_timeout=1.0,
                dsrdtr=False,
                rtscts=False
            )
            conn.dtr = False
            conn.rts = False
            time.sleep(0.3)
            return conn
        except Exception:
            return None

    def _probe_hardware(self) -> bool:
        """Probes available serial ports to find and initialize the connected fingerprint scanner."""
        if not PYSERIAL_AVAILABLE:
            self.last_error = "Biometric driver module unavailable."
            self.is_connected = False
            return False

        try:
            available_ports = list(serial.tools.list_ports.comports())
            if not available_ports:
                self.is_connected = False
                self.last_error = "Fingerprint scanner is not ready. Please check the scanner connection."
                return False

            candidate_ports = []
            if self.serial_port:
                candidate_ports.append(self.serial_port)

            priority_keywords = [
                "stlink", "stmicroelectronics", "stm", "arduino", "ch340",
                "ftdi", "usb serial", "cp210", "silicon labs", "fingerprint",
                "virtual com port", "usb-serial", "cdc"
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
                        self._serial_conn = conn
                        self.serial_port = port_name
                        self.baud_rate = baud
                        self.protocol_type = "stm32" if baud == 115200 else "arduino"
                        self.scanner_model = "STM32 R307 Optical Biometric Scanner"
                        self.is_connected = True
                        self.last_error = None
                        print(f"[Biometric Scanner] Connected on {port_name} @ {baud} baud", flush=True)
                        return True
                    except Exception:
                        try:
                            conn.close()
                        except Exception:
                            pass
                        continue

            self.is_connected = False
            self.last_error = "Fingerprint scanner is not ready. Please check the scanner connection."
            return False

        except Exception as e:
            self.is_connected = False
            self.last_error = f"Fingerprint scanner is unavailable: {e}"
            return False

    def get_status(self) -> Dict[str, Any]:
        """Returns the hardware connection status without disrupting active serial communication."""
        with self._lock:
            # Check if current connection is still alive
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
                    "status_subtitle": "Place your finger on the scanner to register your fingerprint."
                }
            else:
                return {
                    "connected": False,
                    "status": "disconnected",
                    "device": self.scanner_model,
                    "port": None,
                    "error": "Fingerprint scanner is not ready. Please check the scanner connection.",
                    "status_title": "Fingerprint scanner is not ready",
                    "status_subtitle": "Please check the scanner connection."
                }

    def enroll_fingerprint(self, identifier: str) -> Dict[str, Any]:
        """
        Executes real hardware fingerprint enrollment according to main.c protocol.
        Sends 'ENROLL\\r\\n' and waits for 2-scan execution (Place finger 1 -> Lift -> Place finger 2).
        """
        status = self.get_status()
        if not status["connected"]:
            return {
                "success": False,
                "error": "Fingerprint scanner is not ready. Please check the scanner connection.",
                "code": "SCANNER_NOT_READY"
            }

        with self._lock:
            try:
                conn = self._serial_conn
                conn.reset_input_buffer()
                conn.reset_output_buffer()

                template_data = None
                start_time = time.time()

                print(f"[Biometric Scanner] Sending ENROLL command for: {identifier}", flush=True)
                conn.write(b"ENROLL\r\n")
                conn.flush()

                enroll_status = None
                # Total sequence takes up to ~35 seconds for 2 scans
                while time.time() - start_time < 40.0:
                    line = conn.readline().decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    
                    print(f"[STM32 Prompt] {line}", flush=True)
                    line_upper = line.upper()

                    if "PLACE FINGER FOR SCAN 1" in line_upper:
                        self._current_enroll_event = "WAITING_FOR_FINGER_1"
                    elif "LIFT FINGER" in line_upper:
                        self._current_enroll_event = "LIFT_FINGER"
                    elif "PLACE SAME FINGER FOR SCAN 2" in line_upper:
                        self._current_enroll_event = "WAITING_FOR_FINGER_2"
                    elif "ENROLLED OK" in line_upper or "ENROLL_OK" in line_upper or "SUCCESS" in line_upper:
                        enroll_status = "OK"
                        template_data = f"STM32_R307_PAGE0_{identifier}_{int(time.time())}"
                        break
                    elif "ENROLL_TIMEOUT" in line_upper:
                        enroll_status = "TIMEOUT"
                        break
                    elif "ENROLL_FAIL" in line_upper:
                        enroll_status = "FAIL"
                        break

                if enroll_status == "OK" and template_data:
                    db_res = database.register_doctor_biometric(identifier, template_data, self.scanner_model)
                    if db_res.get("success"):
                        db_res["message"] = "Fingerprint registered successfully."
                        db_res["subtitle"] = "Your fingerprint has been securely linked to your account."
                    return db_res
                elif enroll_status == "TIMEOUT":
                    return {
                        "success": False,
                        "error": "Fingerprint registration timed out. Please place your finger promptly when prompted and try again.",
                        "code": "SCANNER_TIMEOUT"
                    }
                elif enroll_status == "FAIL":
                    return {
                        "success": False,
                        "error": "Fingerprint registration failed. Both scans must match. Please try again.",
                        "code": "ENROLLMENT_FAILED"
                    }
                else:
                    return {
                        "success": False,
                        "error": "Fingerprint registration timed out. Please keep your finger steady on the scanner and try again.",
                        "code": "SCANNER_TIMEOUT"
                    }

            except Exception as e:
                self.is_connected = False
                return {
                    "success": False,
                    "error": f"Fingerprint scanner communication error: {e}",
                    "code": "SCANNER_COMM_ERROR"
                }

    def verify_fingerprint(self, identifier: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes real hardware fingerprint verification according to main.c protocol.
        Sends 'VERIFY\\r\\n' and checks for UNLOCKED vs LOCKED.
        """
        status = self.get_status()
        if not status["connected"]:
            return {
                "success": False,
                "matched": False,
                "error": "Fingerprint scanner is not ready. Please check the scanner connection.",
                "code": "SCANNER_NOT_READY"
            }

        with self._lock:
            try:
                conn = self._serial_conn
                conn.reset_input_buffer()
                conn.reset_output_buffer()

                matched_uid = identifier
                start_time = time.time()

                print(f"[Biometric Scanner] Sending VERIFY command...", flush=True)
                conn.write(b"VERIFY\r\n")
                conn.flush()

                verify_result = None
                while time.time() - start_time < 15.0:
                    line = conn.readline().decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    
                    print(f"[STM32 Verify] {line}", flush=True)
                    line_upper = line.upper()

                    if "UNLOCKED" in line_upper:
                        verify_result = "UNLOCKED"
                        break
                    elif "LOCKED" in line_upper:
                        verify_result = "LOCKED"
                        break
                    elif "VERIFY_TIMEOUT" in line_upper:
                        verify_result = "TIMEOUT"
                        break
                    elif "VERIFY_ERROR" in line_upper:
                        verify_result = "ERROR"
                        break

                if verify_result == "UNLOCKED":
                    return database.verify_doctor_biometric(identifier)
                elif verify_result == "LOCKED":
                    return {
                        "success": False,
                        "matched": False,
                        "error": "Fingerprint does not match registered biometric data. Access denied.",
                        "code": "NO_MATCH"
                    }
                elif verify_result == "TIMEOUT":
                    return {
                        "success": False,
                        "matched": False,
                        "error": "Verification timed out. Please place your registered finger on the scanner.",
                        "code": "TIMEOUT"
                    }
                else:
                    return {
                        "success": False,
                        "matched": False,
                        "error": "Fingerprint does not match or reading error. Please place your finger flat and try again.",
                        "code": "READ_ERROR"
                    }

            except Exception as e:
                self.is_connected = False
                return {
                    "success": False,
                    "matched": False,
                    "error": "Fingerprint scanner is unavailable. Please check the scanner connection.",
                    "code": "SCANNER_COMM_ERROR"
                }

# Global Singleton instance
hardware_manager = BiometricHardwareManager()
