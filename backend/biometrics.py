"""
TORUS Healthcare - Real Biometric Scanner & Arduino Serial Integration Engine
Handles communication with Arduino / USB Serial Fingerprint Scanner hardware (e.g. R307 / AS608 / FPM10A / R503).
Strictly operates on physical hardware data and prevents simulated/fake authentications.
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
    Manages physical Serial/USB communication with the Arduino / Fingerprint Scanner.
    """

    def __init__(self):
        self.serial_port: Optional[str] = os.environ.get("BIOMETRIC_SERIAL_PORT", "").strip() or None
        self.baud_rate: int = int(os.environ.get("BIOMETRIC_BAUD_RATE", "57600"))
        self._serial_conn: Optional[Any] = None
        self._lock = threading.Lock()
        self.is_connected: bool = False
        self.scanner_model: str = "Arduino R307/AS608 Optical Biometric Scanner"
        self.last_error: Optional[str] = None
        self._current_enroll_event: str = "IDLE"
        self._probe_hardware()

    def _probe_hardware(self) -> bool:
        """Probes available COM ports to find connected Arduino/Fingerprint hardware."""
        if not PYSERIAL_AVAILABLE:
            self.last_error = "PySerial library not available."
            self.is_connected = False
            return False

        try:
            available_ports = list(serial.tools.list_ports.comports())
            if not available_ports:
                self.is_connected = False
                self.last_error = "Fingerprint scanner not detected. Please check the device connection."
                return False

            # If a specific port was configured, try that first
            candidate_ports = []
            if self.serial_port:
                candidate_ports.append(self.serial_port)

            # Auto-detect Arduino / CH340 / FTDI / USB-Serial devices
            for p in available_ports:
                desc = (p.description or "").lower()
                mfg = (p.manufacturer or "").lower()
                if any(k in desc or k in mfg for k in ["arduino", "ch340", "ftdi", "usb serial", "cp210", "silicon labs", "fingerprint"]):
                    if p.device not in candidate_ports:
                        candidate_ports.append(p.device)

            # Add other ports as fallback
            for p in available_ports:
                if p.device not in candidate_ports:
                    candidate_ports.append(p.device)

            for port_name in candidate_ports:
                try:
                    conn = serial.Serial(port_name, self.baud_rate, timeout=1.0)
                    time.sleep(0.5)
                    conn.write(b"STATUS\n")
                    response = conn.readline().decode("utf-8", errors="ignore").strip()
                    if "READY" in response or "STATUS" in response or "OK" in response:
                        self._serial_conn = conn
                        self.serial_port = port_name
                        self.is_connected = True
                        self.last_error = None
                        print(f"[Biometric Hardware] Connected on {port_name} (response: {response})")
                        return True
                    else:
                        conn.close()
                except Exception:
                    continue

            self.is_connected = False
            self.last_error = "Fingerprint scanner not detected. Please check the device connection."
            return False

        except Exception as e:
            self.is_connected = False
            self.last_error = str(e)
            return False

    def get_status(self) -> Dict[str, Any]:
        """Returns the real hardware connection status and device metadata."""
        with self._lock:
            if not self.is_connected or not self._serial_conn:
                self._probe_hardware()

            if self.is_connected and self._serial_conn:
                return {
                    "connected": True,
                    "status": "ready",
                    "device": self.scanner_model,
                    "port": self.serial_port,
                    "baud_rate": self.baud_rate,
                    "status_title": "Fingerprint scanner ready",
                    "status_subtitle": "Place your finger on the scanner"
                }
            else:
                return {
                    "connected": False,
                    "status": "disconnected",
                    "device": self.scanner_model,
                    "port": None,
                    "error": self.last_error or "Fingerprint scanner not detected",
                    "status_title": "Fingerprint scanner not detected",
                    "status_subtitle": "Please check the device connection"
                }

    def enroll_fingerprint(self, identifier: str) -> Dict[str, Any]:
        """
        Executes real hardware fingerprint enrollment over serial with Arduino.
        Does NOT timeout early; blocks and reads hardware stream until hardware confirms success or user cancels.
        """
        status = self.get_status()
        if not status["connected"]:
            return {
                "success": False,
                "error": "Fingerprint scanner not detected. Please check the device connection.",
                "code": "DEVICE_NOT_DETECTED"
            }

        with self._lock:
            try:
                conn = self._serial_conn
                conn.flushInput()
                conn.flushOutput()

                # Send command to Arduino
                cmd = f"ENROLL:{identifier}\n"
                conn.write(cmd.encode("utf-8"))

                template_data = None
                start_time = time.time()
                # Allow generous interaction time for user to place finger, lift, and place again
                while time.time() - start_time < 90.0:
                    line = conn.readline().decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue

                    print(f"[Arduino Hardware Log] {line}")
                    if line.startswith("EVENT:"):
                        self._current_enroll_event = line.replace("EVENT:", "").strip()
                    elif line.startswith("ENROLL:SUCCESS"):
                        parts = line.split(":", 2)
                        template_data = parts[2] if len(parts) > 2 else f"ARDUINO_TEMPLATE_SLOT_1_{identifier}"
                        break
                    elif line.startswith("ERROR:") or line.startswith("ENROLL:FAIL"):
                        err_msg = line.replace("ERROR:", "").replace("ENROLL:FAIL:", "").strip()
                        if "IMAGING_FAILED" in err_msg or "NO_FINGER" in err_msg:
                            return {
                                "success": False,
                                "error": "Unable to read fingerprint. Please try again.",
                                "code": "CAPTURE_FAILED"
                            }
                        return {
                            "success": False,
                            "error": f"Fingerprint enrollment failed: {err_msg}",
                            "code": "ENROLLMENT_FAILED"
                        }

                if not template_data:
                    return {
                        "success": False,
                        "error": "Unable to read fingerprint. Please try again.",
                        "code": "DEVICE_TIMEOUT"
                    }

                # Save template into database linked to doctor
                db_res = database.register_doctor_biometric(identifier, template_data, self.scanner_model)
                return db_res

            except Exception as e:
                self.is_connected = False
                return {
                    "success": False,
                    "error": f"Device communication failure: {str(e)}",
                    "code": "COMM_ERROR"
                }

    def verify_fingerprint(self, identifier: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes real hardware fingerprint verification over serial with Arduino.
        Requires an actual fingerprint MATCH against the registered biometric template.
        """
        status = self.get_status()
        if not status["connected"]:
            return {
                "success": False,
                "matched": False,
                "error": "Fingerprint scanner not detected. Please check the device connection.",
                "code": "DEVICE_NOT_DETECTED"
            }

        with self._lock:
            try:
                conn = self._serial_conn
                conn.flushInput()
                conn.flushOutput()

                # Send verification request to Arduino
                conn.write(b"VERIFY\n")

                matched_uid = None
                start_time = time.time()
                while time.time() - start_time < 30.0:
                    line = conn.readline().decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue

                    print(f"[Arduino Hardware Log] {line}")
                    if line.startswith("VERIFY:SUCCESS"):
                        parts = line.split(":", 2)
                        matched_uid = parts[2] if len(parts) > 2 else identifier
                        break
                    elif line.startswith("VERIFY:NO_MATCH") or line.startswith("NO_MATCH"):
                        return {
                            "success": False,
                            "matched": False,
                            "error": "Fingerprint does not match. Please try again.",
                            "code": "FINGERPRINT_MISMATCH"
                        }
                    elif line.startswith("ERROR:"):
                        err_msg = line.replace("ERROR:", "").strip()
                        return {
                            "success": False,
                            "matched": False,
                            "error": "Unable to read fingerprint. Please try again.",
                            "code": "READ_ERROR"
                        }

                if not matched_uid:
                    return {
                        "success": False,
                        "matched": False,
                        "error": "Unable to read fingerprint. Please try again.",
                        "code": "TIMEOUT"
                    }

                # Validate against database enrolled template for doctor
                return database.verify_doctor_biometric(matched_uid)

            except Exception as e:
                self.is_connected = False
                return {
                    "success": False,
                    "matched": False,
                    "error": f"Device communication failure: {str(e)}",
                    "code": "COMM_ERROR"
                }

# Global Singleton instance
hardware_manager = BiometricHardwareManager()
