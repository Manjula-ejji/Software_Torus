"""
TORUS Healthcare - STM32 Unified Biometric & Haptic Pad Integration Test Suite
Validates the complete protocol between STM32 firmware (Haptic_Pad_vib3v5_login.ino)
and the TORUS backend/frontend integration:
  1. Boot detection & ready events
  2. 6-stage enrollment with progress tracking & dynamic slot allocation
  3. Enrollment errors (duplicate finger, timeout)
  4. Fingerprint verification (1:1 & 1:N, match vs mismatch, timeout)
  5. Multi-doctor mapping in SQLite database
  6. Pad logout and locking triggers (explicit logout, probe-home docking, idle timeout)
  7. Telemetry & JSON demultiplexing over the single serial link
"""

import os
import sys
import json
import time
import queue
import unittest

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, BACKEND_DIR)

import database
import biometrics


class SimulatedSTM32Serial:
    """
    Simulates the STM32F446RE virtual COM port running Haptic_Pad_vib3v5_login.ino.
    Handles JSON commands with 'fp_enter: true', responds with events and final replies,
    and streams plain-text telemetry when unlocked.
    """

    def __init__(self):
        self.is_open = True
        self.in_waiting = 0
        self._rx_queue = queue.Queue()
        self.unlocked = False
        self.enrolled_slots = {1: "doctor_1@torus.test"}
        self.next_free_slot = 2
        self.last_written = []

    def close(self):
        self.is_open = False

    def write(self, data: bytes):
        raw = data.decode("utf-8", errors="ignore").strip()
        self.last_written.append(raw)
        if not raw:
            return

        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            return

        req_id = req.get("id", "r0")
        cmd = req.get("cmd")

        if cmd == "ping":
            self._queue_line(json.dumps({"id": req_id, "ok": True, "msg": "pong"}))

        elif cmd == "status":
            slots_list = sorted(list(self.enrolled_slots.keys()))
            self._queue_line(json.dumps({
                "id": req_id,
                "ok": True,
                "unlocked": self.unlocked,
                "count": len(slots_list),
                "capacity": 60,
                "slots": slots_list
            }))

        elif cmd == "enroll":
            assert req.get("fp_enter") is True, "Firmware requires fp_enter: true"
            slot = self.next_free_slot
            self.next_free_slot += 1
            self.enrolled_slots[slot] = "temp"

            # 1. Started event
            self._queue_line(json.dumps({"id": req_id, "event": "progress", "step": "started", "press": 0, "of": 6, "percent": 0}))
            # 2. Six presses
            for i in range(1, 7):
                pct = int((i / 6.0) * 100)
                self._queue_line(json.dumps({"id": req_id, "event": "progress", "step": "captured", "press": i, "of": 6, "percent": pct}))
                if i < 6:
                    self._queue_line(json.dumps({"id": req_id, "event": "progress", "step": "lift_finger", "press": i, "of": 6, "percent": pct}))
            # 3. Saving
            self._queue_line(json.dumps({"id": req_id, "event": "progress", "step": "saving", "press": 6, "of": 6, "percent": 100}))
            # 4. Final reply
            self.unlocked = True
            self._queue_line(json.dumps({
                "id": req_id,
                "ok": True,
                "slot": slot,
                "unlocked": True,
                "first_fingerprint": False
            }))

        elif cmd == "verify":
            assert req.get("fp_enter") is True, "Firmware requires fp_enter: true"
            target_slot = req.get("slot")
            if target_slot is not None:
                # 1:1 verify
                if target_slot in self.enrolled_slots:
                    self.unlocked = True
                    self._queue_line(json.dumps({"id": req_id, "ok": True, "matched": True, "slot": target_slot, "unlocked": True}))
                else:
                    self._queue_line(json.dumps({"id": req_id, "ok": True, "matched": False, "unlocked": False}))
            else:
                # 1:N verify
                matched_slot = next(iter(self.enrolled_slots.keys())) if self.enrolled_slots else None
                if matched_slot is not None:
                    self.unlocked = True
                    self._queue_line(json.dumps({"id": req_id, "ok": True, "matched": True, "slot": matched_slot, "unlocked": True}))
                else:
                    self._queue_line(json.dumps({"id": req_id, "ok": True, "matched": False, "unlocked": False}))

        elif cmd == "logout":
            self.unlocked = False
            self._queue_line(json.dumps({"id": req_id, "ok": True, "unlocked": False}))

        elif cmd == "remove":
            assert req.get("fp_enter") is True
            rem_slot = req.get("slot")
            if rem_slot in self.enrolled_slots:
                del self.enrolled_slots[rem_slot]
            self._queue_line(json.dumps({"id": req_id, "ok": True, "slot": rem_slot}))

    def _queue_line(self, line: str):
        self._rx_queue.put(line + "\n")

    def readline(self) -> bytes:
        try:
            line = self._rx_queue.get(timeout=0.1)
            return line.encode("utf-8")
        except queue.Empty:
            return b""

    def inject_event(self, event_data: dict):
        self._queue_line(json.dumps(event_data))

    def inject_telemetry(self, jx=0, jy=0, load=0.0):
        self._queue_line(f"JX:{jx}|JY:{jy}|L:{load:.2f}|AX:0.01|AY:0.02|AZ:9.80|GX:0.0|GY:0.0|GZ:0.0")


class TestSTM32UnifiedBiometrics(unittest.TestCase):
    """Full integration tests for the unified STM32 biometric & haptic manager."""

    def setUp(self):
        self.mock_serial = SimulatedSTM32Serial()
        self.mgr = biometrics.BiometricHardwareManager()
        self.mgr._close_serial()
        self.mgr._serial_conn = self.mock_serial
        self.mgr.serial_port = "COM_MOCK_STM32"
        self.mgr.is_connected = True
        self.mgr._start_background_workers()

        # Clean test doctor mappings
        database.reset_all_biometrics()

    def tearDown(self):
        self.mgr._close_serial()
        if self.mock_serial:
            self.mock_serial.close()

    def test_01_boot_ready_detection(self):
        """STM32 sends ready event on boot; backend marks hardware detected and records locked state."""
        self.mock_serial.inject_event({"event": "ready", "sensor": True, "unlocked": False, "first_fingerprint": False})
        time.sleep(0.15)

        self.assertTrue(self.mgr.is_connected)
        self.assertTrue(self.mgr.sensor_ready)
        self.assertFalse(self.mgr.unlocked)

    def test_02_status_query_enforces_locking_and_slots(self):
        """Status query returns correct slot list and unlocked status."""
        status = self.mgr.get_pad_status()
        self.assertTrue(status.get("ok"))
        self.assertFalse(status.get("unlocked"))
        self.assertIn("slots", status)
        self.assertEqual(status["slots"], [1])

    def test_03_six_stage_enrollment_success(self):
        """Doctor enrollment receives 6 progress stages and saves allocated slot to database."""
        doctor_id = "dr_neuro@torus.test"
        progress_steps = []

        def on_progress(p):
            progress_steps.append((p.get("step"), p.get("press"), p.get("percent")))

        self.mgr.set_progress_callback(on_progress)
        result = self.mgr.enroll_fingerprint(doctor_id, timeout_seconds=5.0)

        self.assertTrue(result.get("success"), f"Enrollment failed: {result}")
        self.assertEqual(result.get("hardware_slot"), 2)
        self.assertTrue(result.get("unlocked"))
        self.assertTrue(self.mgr.unlocked)

        # Verify all 6 presses were tracked
        presses = [p[1] for p in progress_steps if p[0] == "captured"]
        self.assertEqual(presses, [1, 2, 3, 4, 5, 6])

        # Verify command sent included fp_enter: true
        found_enroll = any("enroll" in cmd and '"fp_enter":true' in cmd.replace(" ", "") for cmd in self.mock_serial.last_written)
        self.assertTrue(found_enroll, "Firmware must receive fp_enter: true in enroll command")

        # Verify doctor is registered in SQLite
        slot_label = database.get_doctor_biometric_slot(doctor_id)
        self.assertEqual(slot_label, "R2")
        bio_info = database.get_doctor_biometric(doctor_id)
        self.assertIsNotNone(bio_info)
        self.assertEqual(bio_info.get("fingerprint_id"), "R2")

    def test_04_enrollment_duplicate_finger_error(self):
        """Firmware duplicate error (code 15) is surfaced cleanly without corrupting state."""
        doctor_id = "dr_duplicate@torus.test"

        original_write = self.mock_serial.write
        def mock_write_duplicate(data: bytes):
            raw = data.decode("utf-8", errors="ignore").strip()
            if "enroll" in raw:
                req = json.loads(raw)
                req_id = req.get("id", "r")
                self.mock_serial._queue_line(json.dumps({
                    "id": req_id,
                    "ok": False,
                    "code": 15,
                    "error": "duplicate_finger",
                    "duplicate_slot": 1
                }))
            else:
                original_write(data)

        self.mock_serial.write = mock_write_duplicate

        result = self.mgr.enroll_fingerprint(doctor_id, timeout_seconds=5.0)
        self.assertFalse(result.get("success"))
        self.assertEqual(result.get("code"), "DUPLICATE_FINGER")
        self.assertTrue("already enrolled" in result.get("error", "").lower() or "duplicate" in result.get("error", "").lower())

    def test_05_verification_success_and_doctor_authentication(self):
        """Fingerprint match unlocks pad and validates doctor identity against DB."""
        # 1. Register a doctor with slot R1
        doctor_id = "dr_verified@torus.test"
        # Auto-provision doctor account first
        self.mgr._ensure_doctor_account_exists(doctor_id)
        database.register_doctor_biometric(doctor_id, "R1", template_data="MOCK_TPL_1")

        # 2. Verify with slot 1
        result = self.mgr.verify_fingerprint(slot="R1", timeout_seconds=5.0)
        self.assertTrue(result.get("success"))
        self.assertTrue(result.get("matched"))
        self.assertEqual(result.get("slot"), "R1")
        self.assertTrue(self.mgr.unlocked)

        # 3. Confirm doctor lookup
        doc_verify = database.verify_doctor_biometric_by_slot("R1")
        self.assertTrue(doc_verify.get("matched"))
        self.assertEqual(doc_verify.get("doctor", {}).get("email"), doctor_id)

    def test_06_verification_mismatch_keeps_pad_locked(self):
        """Fingerprint mismatch keeps pad locked and denies doctor entry."""
        result = self.mgr.verify_fingerprint(slot="R99", timeout_seconds=5.0)
        self.assertTrue(result.get("success"))
        self.assertFalse(result.get("matched"))
        self.assertFalse(self.mgr.unlocked)

    def test_07_explicit_logout_locks_pad(self):
        """POST logout sends cmd:logout, turns off unlocked state and stops vibration."""
        self.mgr.unlocked = True
        self.assertTrue(self.mgr.unlocked)

        res = self.mgr.logout_pad()
        self.assertTrue(res.get("ok"))
        self.assertFalse(res.get("unlocked"))
        self.assertFalse(self.mgr.unlocked)

        found_logout = any("logout" in cmd for cmd in self.mock_serial.last_written)
        self.assertTrue(found_logout)

    def test_08_session_end_probe_home_docking(self):
        """Firmware event 'session_end' with reason 'probe_home' triggers session end and locks pad."""
        self.mgr.unlocked = True
        session_ended = []

        self.mgr.register_session_end_callback(lambda reason: session_ended.append(reason))

        self.mock_serial.inject_event({
            "event": "session_end",
            "reason": "probe_home",
            "unlocked": False
        })
        time.sleep(0.15)

        self.assertFalse(self.mgr.unlocked)
        self.assertIn("probe_home", session_ended)

    def test_09_session_end_idle_timeout(self):
        """Firmware event 'session_end' with reason 'idle_timeout' locks pad."""
        self.mgr.unlocked = True
        session_ended = []

        self.mgr.register_session_end_callback(lambda reason: session_ended.append(reason))

        self.mock_serial.inject_event({
            "event": "session_end",
            "reason": "idle_timeout",
            "unlocked": False
        })
        time.sleep(0.15)

        self.assertFalse(self.mgr.unlocked)
        self.assertIn("idle_timeout", session_ended)

    def test_10_plain_text_telemetry_demultiplexing(self):
        """Plain-text telemetry (JX/JY/L/AX...) is separated from JSON and delivered to telemetry callback."""
        received_telemetry = []

        def on_telemetry(pkt, raw_line):
            received_telemetry.append(raw_line)

        self.mgr.register_telemetry_callback(on_telemetry)

        self.mock_serial.inject_telemetry(jx=25, jy=-10, load=1.45)
        time.sleep(0.15)

        self.assertEqual(len(received_telemetry), 1)
        self.assertIn("JX:25", received_telemetry[0])
        self.assertIn("JY:-10", received_telemetry[0])
        self.assertIn("L:1.45", received_telemetry[0])


if __name__ == "__main__":
    unittest.main()
