import json
import unittest
import backend.ultrasound as us


class TestVoltageGainDelayElimination(unittest.TestCase):
    def setUp(self):
        us.app.config["TESTING"] = True
        self.app = us.app.test_client()

    def test_immediate_voltage_and_gain_without_automatic_start_stop(self):
        """
        Verify that changing Voltage (e.g. 39 V, 28 V) and Analog Gain (e.g. 40 dB, 56 dB)
        applies to hardware immediately without triggering automatic Start, Stop, or Freeze.
        """
        class MockHardwareRuntime:
            def __init__(self):
                self.configure_count = 0
                self.stop_count = 0
                self.start_count = 0
                self._started = True
                self.last_config = None

            def stop(self):
                self.stop_count += 1
                self._started = False

            def configure(self, config):
                self.configure_count += 1
                self.last_config = config

            def start(self):
                self.start_count += 1
                self._started = True

        mock_rt = MockHardwareRuntime()
        orig_rt = us._global_ostb_runtime
        orig_config = us._global_ostb_config
        orig_frozen = us._is_frozen
        orig_stopped = us._is_user_stopped
        orig_acquiring = us._is_acquiring

        try:
            us._global_ostb_runtime = mock_rt
            us._global_ostb_config = object()
            us._is_frozen = False
            us._is_user_stopped = False
            us._is_acquiring = True

            # -------------------------------------------------------------
            # Mandatory Acceptance Test 1: Change Voltage to 39 V
            # -------------------------------------------------------------
            res1 = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "voltage", "value": 39}),
                content_type="application/json"
            )
            self.assertEqual(res1.status_code, 200)
            res1_data = json.loads(res1.data)
            self.assertTrue(res1_data["executed"])
            self.assertEqual(res1_data["voltage"], 39.0)

            # Hardware MUST be configured with new voltage
            self.assertEqual(mock_rt.configure_count, 1)
            # Automatic Start and Stop MUST NOT be called!
            self.assertEqual(mock_rt.stop_count, 0)
            self.assertEqual(mock_rt.start_count, 0)
            # Live acquisition stream MUST remain continuously active
            self.assertTrue(us._is_acquiring)
            self.assertFalse(us._is_frozen)
            self.assertFalse(us._is_user_stopped)

            # Status query must confirm RUNNING and 39 V
            st1 = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st1["status"], "RUNNING")
            self.assertEqual(st1["voltage"], 39.0)

            # -------------------------------------------------------------
            # Mandatory Acceptance Test 2: Change Voltage to 28 V
            # -------------------------------------------------------------
            res2 = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "voltage", "value": 28}),
                content_type="application/json"
            )
            self.assertEqual(res2.status_code, 200)
            self.assertEqual(mock_rt.configure_count, 2)
            self.assertEqual(mock_rt.stop_count, 0)  # Still 0!
            self.assertEqual(mock_rt.start_count, 0) # Still 0!
            self.assertTrue(us._is_acquiring)

            st2 = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st2["status"], "RUNNING")
            self.assertEqual(st2["voltage"], 28.0)

            # -------------------------------------------------------------
            # Mandatory Acceptance Test 3: Change Analog Gain to 40 dB
            # -------------------------------------------------------------
            res3 = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "gain", "value": 40}),
                content_type="application/json"
            )
            self.assertEqual(res3.status_code, 200)
            res3_data = json.loads(res3.data)
            self.assertTrue(res3_data["executed"])
            self.assertEqual(res3_data["gain"], 40.0)

            self.assertEqual(mock_rt.configure_count, 3)
            self.assertEqual(mock_rt.stop_count, 0)  # Still 0!
            self.assertEqual(mock_rt.start_count, 0) # Still 0!
            self.assertTrue(us._is_acquiring)

            st3 = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st3["status"], "RUNNING")
            self.assertEqual(st3["gain"], 40.0)

            # -------------------------------------------------------------
            # Mandatory Acceptance Test 4: Change Analog Gain to 56 dB
            # -------------------------------------------------------------
            res4 = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "gain", "value": 56}),
                content_type="application/json"
            )
            self.assertEqual(res4.status_code, 200)
            self.assertEqual(mock_rt.configure_count, 4)
            self.assertEqual(mock_rt.stop_count, 0)  # Still 0!
            self.assertEqual(mock_rt.start_count, 0) # Still 0!
            self.assertTrue(us._is_acquiring)

            st4 = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st4["status"], "RUNNING")
            self.assertEqual(st4["gain"], 56.0)

            # -------------------------------------------------------------
            # Mandatory Acceptance Test 5: Verify manual Start, Stop, Freeze
            # work as expected when clicked intentionally
            # -------------------------------------------------------------
            # Manual Freeze
            self.app.post("/api/remote-input", data=json.dumps({"control": "freeze", "value": True}), content_type="application/json")
            self.assertTrue(us._is_frozen)
            st_frz = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st_frz["status"], "FROZEN")

            # Manual Resume
            self.app.post("/api/remote-input", data=json.dumps({"control": "resume", "value": True}), content_type="application/json")
            self.assertFalse(us._is_frozen)
            self.assertTrue(us._is_acquiring)
            st_res = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st_res["status"], "RUNNING")

            # Manual Stop
            self.app.post("/api/remote-input", data=json.dumps({"control": "stop", "value": True}), content_type="application/json")
            self.assertTrue(us._is_user_stopped)
            self.assertEqual(mock_rt.stop_count, 2) # Manual freeze + manual stop
            st_stp = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st_stp["status"], "STOPPED")

            # Manual Start
            self.app.post("/api/remote-input", data=json.dumps({"control": "start", "value": True}), content_type="application/json")
            self.assertFalse(us._is_user_stopped)
            self.assertTrue(us._is_acquiring)
            st_srt = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st_srt["status"], "RUNNING")

        finally:
            us._global_ostb_runtime = orig_rt
            us._global_ostb_config = orig_config
            us._is_frozen = orig_frozen
            us._is_user_stopped = orig_stopped
            us._is_acquiring = orig_acquiring


if __name__ == "__main__":
    unittest.main()

