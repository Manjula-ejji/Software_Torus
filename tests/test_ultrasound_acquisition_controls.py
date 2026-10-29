import unittest
import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.ultrasound import app, execute_direct_runtime_command, handle_control_command, get_status


class TestUltrasoundAcquisitionControls(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_all_direct_runtime_commands(self):
        """Test that every control command is accepted and processed without NameError or unhandled exception."""
        test_commands = [
            ("start", True),
            ("start", False),
            ("stop", True),
            ("freeze", True),
            ("resume", True),
            ("voltage", 45.0),
            ("voltage", "30"),
            ("gain", 40.0),
            ("gain", "70"),
            ("display", True),
            ("display", False),
            ("log_gain", 55.0),
            ("dynamic_range", 65.0),
            ("tgc_toggle", True),
            ("tgc_toggle", False),
            ("tgc_slider_1", 50),
            ("tgc_slider_2", 12),
            ("tgc_slider_3", 3),
            ("tgc_slider_4", 77),
            ("tgc_slider_5", 90),
            ("tgc_slider_6", 30),
            ("save_setup", True),
            ("advanced", True),
            ("capture", True),
            ("record", True),
            ("record", False),
            ("rotate_image", 90),
            ("reset_position", True),
        ]

        for cmd, val in test_commands:
            with self.subTest(command=cmd, value=val):
                res = execute_direct_runtime_command(cmd, val)
                self.assertTrue(res, f"execute_direct_runtime_command failed for {cmd}={val}")

    def test_remote_input_api_endpoints(self):
        """Test that POST /api/remote-input successfully responds with 200 and success for every control."""
        test_payloads = [
            {"control": "start", "value": True},
            {"control": "stop", "value": True},
            {"control": "freeze", "value": True},
            {"control": "resume", "value": True},
            {"control": "voltage", "value": 42},
            {"control": "gain", "value": 55},
            {"control": "display", "value": True},
            {"control": "tgc_toggle", "value": True},
            {"control": "tgc_slider_1", "value": 60},
            {"control": "tgc_slider_6", "value": 40},
            {"control": "save_setup", "value": True},
            {"control": "advanced", "value": True},
            {"control": "capture", "value": True},
            {"control": "record", "value": True},
            {"control": "rotate_image", "value": 90},
            {"control": "reset_position", "value": True},
        ]

        for payload in test_payloads:
            with self.subTest(payload=payload):
                response = self.app.post(
                    "/api/remote-input",
                    data=json.dumps(payload),
                    content_type="application/json"
                )
                self.assertEqual(response.status_code, 200, f"Failed for {payload}: {response.data}")
                data = json.loads(response.data)
                self.assertEqual(data.get("status"), "success")
                self.assertTrue(data.get("executed"))

    def test_status_api(self):
        """Test that GET /api/status returns valid state with all required acquisition attributes."""
        response = self.app.get("/api/status")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn("status", data)
        self.assertIn("is_frozen", data)
        self.assertIn("voltage", data)
        self.assertIn("gain", data)
        self.assertIn("display", data)
        self.assertIn("tgc_enabled", data)
        self.assertIn("tgc_sliders", data)
        self.assertEqual(len(data["tgc_sliders"]), 6)


    def test_voltage_and_gain_immediate_reflection_without_start_stop(self):
        """
        Verify that Voltage and Analog Gain changes (e.g. 28 V, 56 dB) are applied
        immediately and reflected in /api/remote-input and /api/status without requiring Start or Stop clicks.
        """
        # Test Voltage change to 28 V
        v_resp = self.app.post(
            "/api/remote-input",
            data=json.dumps({"control": "voltage", "value": 28}),
            content_type="application/json"
        )
        self.assertEqual(v_resp.status_code, 200)
        v_data = json.loads(v_resp.data)
        self.assertEqual(v_data.get("status"), "success")
        self.assertEqual(v_data.get("voltage"), 28.0)

        # Check status immediately confirms 28 V
        s_resp = self.app.get("/api/status")
        self.assertEqual(s_resp.status_code, 200)
        s_data = json.loads(s_resp.data)
        self.assertEqual(s_data.get("voltage"), 28.0)

        # Test Analog Gain change to 56 dB
        g_resp = self.app.post(
            "/api/remote-input",
            data=json.dumps({"control": "gain", "value": 56}),
            content_type="application/json"
        )
        self.assertEqual(g_resp.status_code, 200)
        g_data = json.loads(g_resp.data)
        self.assertEqual(g_data.get("status"), "success")
        self.assertEqual(g_data.get("gain"), 56.0)

        # Check status immediately confirms 56 dB
        s_resp2 = self.app.get("/api/status")
        self.assertEqual(s_resp2.status_code, 200)
        s_data2 = json.loads(s_resp2.data)
        self.assertEqual(s_data2.get("gain"), 56.0)
        self.assertEqual(s_data2.get("voltage"), 28.0)

    def test_multiple_voltage_and_gain_values_with_clamping(self):
        """Test multiple arbitrary values and bounds clamping for Voltage and Analog Gain."""
        voltage_test_cases = [
            (15, 15.0),
            (28, 28.0),
            (45.5, 45.5),
            (60, 50.0),    # Clamped to max 50 V
            (-5, 0.0),     # Clamped to min 0 V
        ]
        for input_val, expected_val in voltage_test_cases:
            res = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "voltage", "value": input_val}),
                content_type="application/json"
            )
            self.assertEqual(res.status_code, 200)
            data = json.loads(res.data)
            self.assertEqual(data.get("voltage"), expected_val)

        gain_test_cases = [
            (20, 20.0),
            (56, 56.0),
            (75.5, 75.5),
            (95, 80.0),    # Clamped to max 80 dB
            (-10, 0.0),    # Clamped to min 0 dB
        ]
        for input_val, expected_val in gain_test_cases:
            res = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "gain", "value": input_val}),
                content_type="application/json"
            )
            self.assertEqual(res.status_code, 200)
            data = json.loads(res.data)
            self.assertEqual(data.get("gain"), expected_val)


if __name__ == "__main__":
    unittest.main()
