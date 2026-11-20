"""
TORUS Healthcare - Unit & Integration Test Suite for HLK-FPM383C Backend Protocol
Tests communication, 1:1 exact matching, 6-stage enrollment streaming, and multi-user isolation.
"""

import os
import sys
import json
import time
import io
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database
import biometrics


class MockSerialFPM383C:
    """Simulates the NUCLEO-F446RE + HLK-FPM383C running fpm383c_backend.ino"""

    def __init__(self, default_enrolled_slot=1):
        self.is_open = True
        self.in_waiting_bytes = bytearray()
        self.out_bytes = bytearray()
        self.default_enrolled_slot = default_enrolled_slot
        self.simulate_cross_user = False
        self.simulate_no_match = False
        self.simulate_timeout = False

    @property
    def in_waiting(self):
        return len(self.in_waiting_bytes)

    def write(self, data: bytes):
        self.out_bytes.extend(data)
        line = data.decode("utf-8", errors="ignore").strip()
        if not line:
            return

        if line.startswith("{"):
            try:
                req = json.loads(line)
                req_id = req.get("id", "r")
                cmd = req.get("cmd")

                if cmd == "ping" or cmd == "status":
                    rep = {"id": req_id, "cmd": cmd, "ok": True, "sensor": True, "count": 1, "capacity": 60}
                    self._queue_json(rep)

                elif cmd == "verify":
                    if self.simulate_timeout:
                        rep = {"id": req_id, "cmd": "verify", "ok": False, "error": "timeout", "code": 8}
                        self._queue_json(rep)
                    elif self.simulate_no_match:
                        rep = {"id": req_id, "cmd": "verify", "ok": True, "matched": False}
                        self._queue_json(rep)
                    elif self.simulate_cross_user:
                        # User touched slot 2 while slot 1 was wanted
                        rep = {"id": req_id, "cmd": "verify", "ok": True, "matched": False}
                        self._queue_json(rep)
                    else:
                        target_slot = req.get("slot")
                        if target_slot is not None:
                            # 1:1 exact match
                            if target_slot == self.default_enrolled_slot:
                                rep = {"id": req_id, "cmd": "verify", "ok": True, "matched": True, "slot": target_slot, "score": 3950}
                            else:
                                rep = {"id": req_id, "cmd": "verify", "ok": True, "matched": False}
                        else:
                            # 1:N open search
                            rep = {"id": req_id, "cmd": "verify", "ok": True, "matched": True, "slot": self.default_enrolled_slot, "score": 3950}
                        self._queue_json(rep)

                elif cmd == "enroll":
                    user = req.get("user")
                    slot = req.get("slot", 1)
                    # Stream 6 capture progress events
                    steps = [
                        ("started", "Enrollment started", 0, None),
                        ("place_finger", "Place your finger on the sensor", 1, 0),
                        ("captured", "Fingerprint captured", 1, 16),
                        ("lift_finger", "Lift your finger", 1, 16),
                        ("place_finger", "Place the same finger again, slightly moved", 2, 16),
                        ("captured", "Fingerprint captured", 2, 33),
                        ("lift_finger", "Lift your finger", 2, 33),
                        ("place_finger", "Place the same finger again, slightly moved", 3, 33),
                        ("captured", "Fingerprint captured", 3, 50),
                        ("lift_finger", "Lift your finger", 3, 50),
                        ("place_finger", "Place the same finger again, slightly moved", 4, 50),
                        ("captured", "Fingerprint captured", 4, 66),
                        ("lift_finger", "Lift your finger", 4, 66),
                        ("place_finger", "Place the same finger again, slightly moved", 5, 66),
                        ("captured", "Fingerprint captured", 5, 83),
                        ("lift_finger", "Lift your finger", 5, 83),
                        ("place_finger", "Place the same finger again, slightly moved", 6, 83),
                        ("captured", "Fingerprint captured", 6, 100),
                        ("saving", "Saving fingerprint", 6, 100)
                    ]
                    for step, msg, press, pct in steps:
                        ev = {"id": req_id, "event": "progress", "step": step, "msg": msg}
                        if press:
                            ev["press"] = press
                            ev["of"] = 6
                        if pct is not None:
                            ev["percent"] = pct
                        self._queue_json(ev)

                    # Final reply
                    final_rep = {
                        "id": req_id,
                        "cmd": "enroll",
                        "user": user,
                        "ok": True,
                        "slot": slot,
                        "elapsed_ms": 3200
                    }
                    self._queue_json(final_rep)

                elif cmd == "delete":
                    slot = req.get("slot", 1)
                    rep = {"id": req_id, "cmd": "delete", "ok": True, "slot": slot}
                    self._queue_json(rep)

                elif cmd == "empty":
                    rep = {"id": req_id, "cmd": "empty", "ok": True}
                    self._queue_json(rep)

            except Exception:
                pass

    def _queue_json(self, doc: dict):
        line = (json.dumps(doc) + "\n").encode("utf-8")
        self.in_waiting_bytes.extend(line)

    def flush(self):
        pass

    def reset_input_buffer(self):
        self.in_waiting_bytes.clear()

    def reset_output_buffer(self):
        self.out_bytes.clear()

    def readline(self):
        idx = self.in_waiting_bytes.find(b"\n")
        if idx >= 0:
            line = self.in_waiting_bytes[:idx + 1]
            del self.in_waiting_bytes[:idx + 1]
            return bytes(line)
        line = bytes(self.in_waiting_bytes)
        self.in_waiting_bytes.clear()
        return line

    def read(self, n):
        data = self.in_waiting_bytes[:n]
        del self.in_waiting_bytes[:n]
        return bytes(data)

    def close(self):
        self.is_open = False


class TestFPM383CIntegration(unittest.TestCase):

    def setUp(self):
        # Reset DB biometrics
        database.reset_all_biometrics()
        # Seed test doctors
        with database.get_db() as conn:
            cursor = conn.cursor()
            for email, name, uid in [
                ("dr_smith@torus.med", "Dr. John Smith", "DOC-SMITH"),
                ("dr_jones@torus.med", "Dr. Sarah Jones", "DOC-JONES")
            ]:
                cursor.execute("SELECT id FROM doctors WHERE LOWER(email) = ?", (email,))
                if not cursor.fetchone():
                    database.register_doctor(name, email, "Pass@12345", uid=uid)

    def tearDown(self):
        database.reset_all_biometrics()

    def test_01_hardware_probing_json(self):
        """Validates that BiometricHardwareManager identifies FPM383C JSON firmware."""
        mgr = biometrics.BiometricHardwareManager()
        mock_ser = MockSerialFPM383C()

        with patch.object(mgr, "_open_port", return_value=mock_ser):
            with patch("serial.tools.list_ports.comports") as mock_ports:
                mock_port_obj = MagicMock()
                mock_port_obj.device = "COM9"
                mock_port_obj.description = "STLink VCP"
                mock_port_obj.manufacturer = "STMicroelectronics"
                mock_port_obj.hwid = "USB\\VID_0483&PID_374B"
                mock_ports.return_value = [mock_port_obj]

                res = mgr._probe_hardware(force=True)
                self.assertTrue(res)
                self.assertTrue(mgr.is_connected)
                self.assertEqual(mgr.protocol_type, "fpm383c_json")
                self.assertEqual(mgr.baud_rate, 57600)

    def test_02_registration_stream_and_exact_slot_assignment(self):
        """Validates 6-stage registration streaming and exact slot storage."""
        mgr = biometrics.BiometricHardwareManager()
        mock_ser = MockSerialFPM383C(default_enrolled_slot=1)
        mgr._serial_conn = mock_ser
        mgr.is_connected = True
        mgr.protocol_type = "fpm383c_json"

        enroll_res = mgr.enroll_fingerprint("dr_smith@torus.med")
        self.assertTrue(enroll_res.get("success"), f"Enroll failed: {enroll_res}")
        self.assertEqual(enroll_res.get("fingerprint_id"), "R1")
        self.assertEqual(enroll_res.get("hardware_slot"), 1)

        # Confirm DB mapping
        stored_slot = database.get_doctor_biometric_slot("dr_smith@torus.med")
        self.assertEqual(stored_slot, "R1")

        # Verify duplicate registration is strictly blocked
        dup_res = mgr.enroll_fingerprint("dr_smith@torus.med")
        self.assertFalse(dup_res.get("success"))
        self.assertTrue(dup_res.get("already_registered"))

    def test_03_exact_match_verification_legitimate(self):
        """Validates 1:1 exact matching for legitimate user."""
        mgr = biometrics.BiometricHardwareManager()
        mock_ser = MockSerialFPM383C(default_enrolled_slot=1)
        mgr._serial_conn = mock_ser
        mgr.is_connected = True
        mgr.protocol_type = "fpm383c_json"

        # Register dr_smith to slot 1
        database.register_doctor_biometric("dr_smith@torus.med", "R1", "HLK_FPM383C_SLOT_1")

        # Verification attempt for dr_smith
        v_res = mgr.verify_fingerprint("dr_smith@torus.med")
        self.assertTrue(v_res.get("success"))
        self.assertTrue(v_res.get("matched"))
        self.assertEqual(v_res.get("fingerprint_id"), "R1")
        self.assertEqual(v_res.get("doctor", {}).get("email"), "dr_smith@torus.med")

    def test_04_exact_match_rejection_cross_user(self):
        """Validates that a finger from another doctor is strictly rejected (no access granted)."""
        mgr = biometrics.BiometricHardwareManager()
        mock_ser = MockSerialFPM383C(default_enrolled_slot=2)  # Sensor sees slot 2
        mgr._serial_conn = mock_ser
        mgr.is_connected = True
        mgr.protocol_type = "fpm383c_json"

        # Register dr_smith to R1, dr_jones to R2
        database.register_doctor_biometric("dr_smith@torus.med", "R1", "HLK_FPM383C_SLOT_1")
        database.register_doctor_biometric("dr_jones@torus.med", "R2", "HLK_FPM383C_SLOT_2")

        # Attempt to login as dr_smith while touching dr_jones' finger (slot 2)
        v_cross = mgr.verify_fingerprint("dr_smith@torus.med")
        self.assertFalse(v_cross.get("matched"))
        self.assertIn(v_cross.get("code"), ["SLOT_MISMATCH", "CROSS_USER_MISMATCH", "NO_MATCH"])

    def test_05_multi_user_1_to_n_search(self):
        """Validates 1:N open search identifying the exact doctor owning the scanned finger."""
        mgr = biometrics.BiometricHardwareManager()
        mock_ser = MockSerialFPM383C(default_enrolled_slot=2)  # Sensor sees slot 2
        mgr._serial_conn = mock_ser
        mgr.is_connected = True
        mgr.protocol_type = "fpm383c_json"

        database.register_doctor_biometric("dr_smith@torus.med", "R1", "HLK_FPM383C_SLOT_1")
        database.register_doctor_biometric("dr_jones@torus.med", "R2", "HLK_FPM383C_SLOT_2")

        # Open 1:N search (no email pre-specified)
        v_open = mgr.verify_fingerprint(None)
        self.assertTrue(v_open.get("success"))
        self.assertTrue(v_open.get("matched"))
        self.assertEqual(v_open.get("fingerprint_id"), "R2")
        self.assertEqual(v_open.get("doctor", {}).get("email"), "dr_jones@torus.med")

    def test_06_hardware_slot_deletion(self):
        """Validates deleting a specific slot."""
        mgr = biometrics.BiometricHardwareManager()
        mock_ser = MockSerialFPM383C()
        mgr._serial_conn = mock_ser
        mgr.is_connected = True
        mgr.protocol_type = "fpm383c_json"

        del_res = mgr.delete_slot("R1")
        self.assertTrue(del_res.get("success"))


if __name__ == "__main__":
    unittest.main()
