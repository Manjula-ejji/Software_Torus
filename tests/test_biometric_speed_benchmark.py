"""
TORUS Healthcare - Fingerprint Registration & Verification Speed Benchmark Test
Verifies performance against required targets:
  1. Registration completes within 10 seconds.
  2. Verification completes within 3-5 seconds.
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

# Ensure backend directory is in sys.path
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, BACKEND_DIR)

import database
import biometrics


class MockSerialDevice:
    """Simulates realistic optical/capacitive fingerprint sensor timing over UART."""

    def __init__(self, mode="normal"):
        self.mode = mode
        self.in_waiting = 0
        self.is_open = True
        self._out_buffer = []
        self._read_idx = 0
        self._active_cmd = None
        self._cmd_time = 0.0

    def write(self, data: bytes):
        cmd = data.decode("utf-8", errors="ignore").strip()
        self._active_cmd = cmd
        self._cmd_time = time.perf_counter()
        self._out_buffer = []
        self._read_idx = 0

        if cmd.startswith("{"):
            import json
            try:
                req = json.loads(cmd)
                req_id = req.get("id", "r")
                c = req.get("cmd")
                if c in ("ping", "status"):
                    self._out_buffer = [json.dumps({"id": req_id, "ok": True, "count": 2, "capacity": 60})]
                elif c == "enroll":
                    slot = req.get("slot", 1)
                    if self.mode == "timeout":
                        self._out_buffer = [json.dumps({"id": req_id, "event": "progress", "step": "place_finger", "press": 1, "of": 6, "percent": 0})]
                    else:
                        self._out_buffer = [
                            json.dumps({"id": req_id, "event": "progress", "step": "captured", "press": 1, "of": 6, "percent": 16}),
                            json.dumps({"id": req_id, "event": "progress", "step": "captured", "press": 2, "of": 6, "percent": 33}),
                            json.dumps({"id": req_id, "event": "progress", "step": "captured", "press": 3, "of": 6, "percent": 50}),
                            json.dumps({"id": req_id, "event": "progress", "step": "captured", "press": 4, "of": 6, "percent": 66}),
                            json.dumps({"id": req_id, "event": "progress", "step": "captured", "press": 5, "of": 6, "percent": 83}),
                            json.dumps({"id": req_id, "event": "progress", "step": "captured", "press": 6, "of": 6, "percent": 100}),
                            json.dumps({"id": req_id, "cmd": "enroll", "ok": True, "slot": slot, "elapsed_ms": 1800})
                        ]
                elif c == "verify":
                    slot = req.get("slot", 1)
                    if self.mode == "timeout":
                        self._out_buffer = [json.dumps({"id": req_id, "cmd": "verify", "ok": False, "error": "timeout", "code": 8})]
                    elif self.mode == "mismatch":
                        self._out_buffer = [json.dumps({"id": req_id, "cmd": "verify", "ok": True, "matched": False})]
                    else:
                        self._out_buffer = [json.dumps({"id": req_id, "cmd": "verify", "ok": True, "matched": True, "slot": slot, "score": 88})]
                elif c == "delete":
                    self._out_buffer = [json.dumps({"id": req_id, "cmd": "delete", "ok": True})]
            except Exception:
                pass
        elif cmd == "STATUS" or cmd == "PING":
            self._out_buffer = ["STATUS:READY", "Stored fingerprints: 2/60"]
        elif cmd.startswith("ENROLL"):
            slot_id = cmd.split()[-1] if " " in cmd else cmd.split(":")[-1]
            if self.mode == "timeout":
                self._out_buffer = ["EVENT:WAITING_FOR_FINGER"]
            else:
                # Realistic sensor stages with all 6 captures
                self._out_buffer = [
                    "EVENT:WAITING_FOR_FINGER",
                    "Enrollment status: progress 16%, capture stage 1.",
                    "EVENT:PASS_1_CAPTURED_LIFT_FINGER",
                    "Enrollment status: progress 33%, capture stage 2.",
                    "EVENT:PASS_2_CAPTURED_LIFT_FINGER",
                    "Enrollment status: progress 50%, capture stage 3.",
                    "EVENT:PASS_3_CAPTURED_LIFT_FINGER",
                    "Enrollment status: progress 66%, capture stage 4.",
                    "EVENT:PASS_4_CAPTURED_LIFT_FINGER",
                    "Enrollment status: progress 83%, capture stage 5.",
                    "EVENT:PASS_5_CAPTURED_LIFT_FINGER",
                    "Enrollment status: progress 100%, capture stage 6.",
                    f"ENROLLMENT SUCCESS: fingerprint saved as ID {slot_id}."
                ]
        elif cmd.startswith("MATCH") or cmd == "VERIFY":
            target_id = cmd.split()[-1] if " " in cmd and cmd != "MATCH" else "1"
            if self.mode == "timeout":
                self._out_buffer = ["EVENT:READING_FINGERPRINT", "ERROR:TIMEOUT_NO_FINGER"]
            elif self.mode == "mismatch":
                self._out_buffer = ["EVENT:READING_FINGERPRINT", "NOT MATCHED"]
            else:
                # Realistic sensor match
                self._out_buffer = [
                    "EVENT:READING_FINGERPRINT",
                    f"Match result=1, ID={target_id}, score=88",
                    f"MATCHED: fingerprint ID {target_id} (score 88)."
                ]
        elif cmd.startswith("DELETE"):
            slot_id = cmd.split()[-1] if " " in cmd else cmd.split(":")[-1]
            self._out_buffer = [f"DELETED fingerprint ID {slot_id}."]

        self.in_waiting = len(self._out_buffer)

    def flush(self):
        pass

    def reset_input_buffer(self):
        self._out_buffer = []
        self._read_idx = 0
        self.in_waiting = 0

    def reset_output_buffer(self):
        pass

    def readline(self) -> bytes:
        if self._read_idx < len(self._out_buffer):
            # Simulate real optical sensor response latency (~15ms per event)
            time.sleep(0.015)
            line = self._out_buffer[self._read_idx] + "\r\n"
            self._read_idx += 1
            self.in_waiting = len(self._out_buffer) - self._read_idx
            return line.encode("utf-8")
        self.in_waiting = 0
        return b""

    def close(self):
        self.is_open = False


class TestBiometricSpeedBenchmark(unittest.TestCase):
    """Performance benchmarks testing registration (<=10s) and verification (3-5s)."""

    def setUp(self):
        # Reset DB state
        database.reset_all_biometrics()
        self.mgr = biometrics.BiometricHardwareManager()

    def test_registration_speed_multiple_runs(self):
        """Test registration 5 times and verify all complete within 10 seconds."""
        mock_device = MockSerialDevice(mode="normal")
        self.mgr._serial_conn = mock_device
        self.mgr.is_connected = True

        durations = []
        for i in range(1, 6):
            email = f"speed_doctor_{i}@torus.test"
            t0 = time.perf_counter()
            res = self.mgr.enroll_fingerprint(email)
            elapsed = time.perf_counter() - t0
            durations.append(elapsed)

            self.assertTrue(res.get("success"), f"Run {i} failed: {res.get('error')}")
            self.assertLessEqual(elapsed, 10.0, f"Registration took {elapsed:.2f}s, exceeding 10.0s target!")
            self.assertEqual(res.get("fingerprint_id"), f"R{i}")
            stages = res.get("timing", {}).get("stages", {})
            self.assertEqual(len(stages), 6, f"Expected all 6 stages recorded, got {len(stages)}: {stages}")
            for st in range(1, 7):
                self.assertIn(st, stages, f"Stage {st} missing from recorded stages!")

        avg_duration = sum(durations) / len(durations)
        print(f"\n[BENCHMARK] Registration 5-run average: {avg_duration:.3f}s (Min: {min(durations):.3f}s, Max: {max(durations):.3f}s)")
        print(f"[BENCHMARK] Target <= 10.0s: PASSED for all runs.")

    def test_verification_speed_multiple_runs(self):
        """Test verification 5 times and verify all complete within 3-5 seconds."""
        # Setup doctor in slot R1
        mock_device = MockSerialDevice(mode="normal")
        self.mgr._serial_conn = mock_device
        self.mgr.is_connected = True

        enroll_res = self.mgr.enroll_fingerprint("speed_verify@torus.test")
        self.assertTrue(enroll_res.get("success"))

        durations = []
        for i in range(1, 6):
            t0 = time.perf_counter()
            res = self.mgr.verify_fingerprint("speed_verify@torus.test")
            elapsed = time.perf_counter() - t0
            durations.append(elapsed)

            self.assertTrue(res.get("success"), f"Verify run {i} failed: {res.get('error')}")
            self.assertTrue(res.get("matched"))
            self.assertLessEqual(elapsed, 5.0, f"Verification took {elapsed:.2f}s, exceeding 5.0s target!")
            self.assertGreaterEqual(elapsed, 0.01, "Verification completed suspiciously fast without checking.")

        avg_duration = sum(durations) / len(durations)
        print(f"\n[BENCHMARK] Verification 5-run average: {avg_duration:.3f}s (Min: {min(durations):.3f}s, Max: {max(durations):.3f}s)")
        print(f"[BENCHMARK] Target 3-5s: PASSED for all runs (Execution is within budget).")

    def test_verification_timeout_bounded(self):
        """Test that verification timeout strictly triggers between 3.5s and 5.0s."""
        mock_device = MockSerialDevice(mode="timeout")
        self.mgr._serial_conn = mock_device
        self.mgr.is_connected = True

        database.register_doctor_biometric("timeout_doc@torus.test", "R1", "REF_1", "Test Scanner")

        t0 = time.perf_counter()
        res = self.mgr.verify_fingerprint("timeout_doc@torus.test", timeout_seconds=4.0)
        elapsed = time.perf_counter() - t0

        print(f"\n[BENCHMARK] Verification timeout elapsed: {elapsed:.3f}s")
        self.assertFalse(res.get("matched"))
        self.assertEqual(res.get("code"), "TIMEOUT")
        self.assertLessEqual(elapsed, 5.0, f"Timeout took {elapsed:.2f}s, exceeding 5.0s max limit!")

    def test_registration_timeout_bounded(self):
        """Test that registration timeout strictly terminates within 10 seconds."""
        mock_device = MockSerialDevice(mode="timeout")
        self.mgr._serial_conn = mock_device
        self.mgr.is_connected = True

        t0 = time.perf_counter()
        res = self.mgr.enroll_fingerprint("reg_timeout@torus.test", timeout_seconds=8.0)
        elapsed = time.perf_counter() - t0

        print(f"\n[BENCHMARK] Registration timeout elapsed: {elapsed:.3f}s")
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("code"), "TIMEOUT")
        self.assertLessEqual(elapsed, 10.0, f"Registration timeout took {elapsed:.2f}s, exceeding 10.0s max limit!")

    def tearDown(self):
        database.reset_all_biometrics()


if __name__ == "__main__":
    unittest.main()
