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
            ("freeze", True),
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
            {"control": "freeze", "value": True},
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
        self.assertIn("voltage", data)
        self.assertIn("gain", data)
        self.assertIn("display", data)
        self.assertIn("tgc_enabled", data)
        self.assertIn("tgc_sliders", data)
        self.assertEqual(len(data["tgc_sliders"]), 6)


if __name__ == "__main__":
    unittest.main()
