import json
import unittest
from unittest.mock import patch, MagicMock
import backend.ultrasound as us


class TestVoltageGainDelayElimination(unittest.TestCase):
    def setUp(self):
        us.app.config["TESTING"] = True
        self.app = us.app.test_client()

    def test_immediate_voltage_and_gain_without_automatic_start_stop(self):
        """
        Verify that changing Voltage (e.g. 26 V, 35 V, 39 V, 28 V) and Analog Gain (e.g. 49 dB, 40 dB, 56 dB)
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
            # Test 1: Change Voltage to 26 V (from clinical screenshot)
            # -------------------------------------------------------------
            res1 = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "voltage", "value": 26}),
                content_type="application/json"
            )
            self.assertEqual(res1.status_code, 200)
            res1_data = json.loads(res1.data)
            self.assertTrue(res1_data["executed"])
            self.assertEqual(res1_data["voltage"], 26.0)

            # Hardware reconfigured immediately
            self.assertEqual(mock_rt.configure_count, 1)
            # Automatic Start and Stop MUST NOT be called!
            self.assertEqual(mock_rt.stop_count, 0)
            self.assertEqual(mock_rt.start_count, 0)
            # Live acquisition stream MUST remain continuously active
            self.assertTrue(us._is_acquiring)
            self.assertFalse(us._is_frozen)
            self.assertFalse(us._is_user_stopped)

            # Status query must confirm RUNNING and 26 V
            st1 = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st1["status"], "RUNNING")
            self.assertEqual(st1["voltage"], 26.0)

            # -------------------------------------------------------------
            # Test 2: Change Analog Gain to 49 dB (from clinical screenshot)
            # -------------------------------------------------------------
            res2 = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "gain", "value": 49}),
                content_type="application/json"
            )
            self.assertEqual(res2.status_code, 200)
            res2_data = json.loads(res2.data)
            self.assertTrue(res2_data["executed"])
            self.assertEqual(res2_data["gain"], 49.0)

            self.assertEqual(mock_rt.configure_count, 2)
            self.assertEqual(mock_rt.stop_count, 0)  # Still 0!
            self.assertEqual(mock_rt.start_count, 0) # Still 0!
            self.assertTrue(us._is_acquiring)

            st2 = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st2["status"], "RUNNING")
            self.assertEqual(st2["gain"], 49.0)

            # -------------------------------------------------------------
            # Test 3: Change Voltage to 35 V
            # -------------------------------------------------------------
            res3 = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "voltage", "value": 35}),
                content_type="application/json"
            )
            self.assertEqual(res3.status_code, 200)
            self.assertEqual(mock_rt.configure_count, 3)
            self.assertEqual(mock_rt.stop_count, 0)  # Still 0!
            self.assertEqual(mock_rt.start_count, 0) # Still 0!
            self.assertTrue(us._is_acquiring)

            st3 = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st3["status"], "RUNNING")
            self.assertEqual(st3["voltage"], 35.0)

            # -------------------------------------------------------------
            # Test 4: Change Voltage to 28 V
            # -------------------------------------------------------------
            res4 = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "voltage", "value": 28}),
                content_type="application/json"
            )
            self.assertEqual(res4.status_code, 200)
            self.assertEqual(mock_rt.configure_count, 4)
            self.assertEqual(mock_rt.stop_count, 0)  # Still 0!
            self.assertEqual(mock_rt.start_count, 0) # Still 0!
            self.assertTrue(us._is_acquiring)

            st4 = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st4["status"], "RUNNING")
            self.assertEqual(st4["voltage"], 28.0)

            # -------------------------------------------------------------
            # Test 5: Change Analog Gain to 56 dB
            # -------------------------------------------------------------
            res5 = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "gain", "value": 56}),
                content_type="application/json"
            )
            self.assertEqual(res5.status_code, 200)
            self.assertEqual(mock_rt.configure_count, 5)
            self.assertEqual(mock_rt.stop_count, 0)  # Still 0!
            self.assertEqual(mock_rt.start_count, 0) # Still 0!
            self.assertTrue(us._is_acquiring)

            st5 = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st5["status"], "RUNNING")
            self.assertEqual(st5["gain"], 56.0)

            # -------------------------------------------------------------
            # Test 6: Verify manual Start, Stop, Freeze
            # work as expected when clicked intentionally by the user
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

    def test_live_configure_exception_does_not_trigger_stop_start_cycle(self):
        """
        Verify that if the underlying physical TPAC hardware driver raises an exception
        when configure() is called while acquiring (e.g. DMA active), the system NEVER
        falls back to stopping or restarting the runtime. Acquisition continues smoothly.
        """
        class HardwareDriverWithDmaConstraint:
            def __init__(self):
                self.configure_count = 0
                self.stop_count = 0
                self.start_count = 0

            def configure(self, config):
                self.configure_count += 1
                raise RuntimeError("TPAC Driver: Cannot reconfigure sequence while DMA is streaming RF data")

            def stop(self):
                self.stop_count += 1

            def start(self):
                self.start_count += 1

        dma_mock = HardwareDriverWithDmaConstraint()
        orig_rt = us._global_ostb_runtime
        orig_acquiring = us._is_acquiring

        try:
            us._global_ostb_runtime = dma_mock
            us._is_acquiring = True
            us._is_frozen = False
            us._is_user_stopped = False

            # Change voltage while stream is active
            res = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "voltage", "value": 26}),
                content_type="application/json"
            )
            self.assertEqual(res.status_code, 200)

            # STOP and START must NEVER be called despite configure() error!
            self.assertEqual(dma_mock.stop_count, 0)
            self.assertEqual(dma_mock.start_count, 0)

            # Acquisition must remain RUNNING
            self.assertTrue(us._is_acquiring)
            st = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st["status"], "RUNNING")
            self.assertEqual(st["voltage"], 26.0)

        finally:
            us._global_ostb_runtime = orig_rt
            us._is_acquiring = orig_acquiring

    def test_voltage_and_gain_bypass_win32_click_and_window_focus(self):
        """
        Verify that handle_control_command('voltage', ...) and ('gain', ...)
        never invoke send_qt_input_value, send_direct_qt_click, or send_win32_click,
        preventing accidental triggering of default dialog buttons or window focus shifts.
        """
        with patch.object(us, "send_qt_input_value") as mock_input, \
             patch.object(us, "send_direct_qt_click") as mock_qt_click, \
             patch.object(us, "send_win32_click") as mock_win32_click:

            res_v = us.handle_control_command("voltage", 26)
            self.assertTrue(res_v)
            mock_input.assert_not_called()
            mock_qt_click.assert_not_called()
            mock_win32_click.assert_not_called()

            res_g = us.handle_control_command("gain", 49)
            self.assertTrue(res_g)
            mock_input.assert_not_called()
            mock_qt_click.assert_not_called()
            mock_win32_click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
