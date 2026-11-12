import json
import os
import sys
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestTorusSelectedDeviceHeader(unittest.TestCase):
    def setUp(self):
        self.client = srv.app.test_client()
        self.client.post("/api/haptic-pad/session/unbind", data=json.dumps({}), content_type="application/json")

    def tearDown(self):
        self.client.post("/api/haptic-pad/session/unbind", data=json.dumps({}), content_type="application/json")

    def test_unbound_device_info_returns_none_never_os_hostname(self):
        with patch("socket.gethostname", return_value="Manjula"):
            resp = self.client.get("/api/device-info")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertFalse(data["connected"])
            self.assertIsNone(data["device_id"])
            self.assertIsNone(data["device_name"])
            self.assertNotEqual(data["device_id"], "Manjula")

            health = json.loads(self.client.get("/api/health").data)
            self.assertNotIn("Manjula", json.dumps(health))

    def test_bound_session_returns_exact_torus_device_id(self):
        for dev_id in ("TORUS-B08", "TORUS-E18", "TORUS-A12"):
            with self.subTest(device=dev_id):
                bind_resp = self.client.post(
                    "/api/haptic-pad/session/bind",
                    data=json.dumps({
                        "session_id": f"S-{dev_id}",
                        "doctor_id": "3001",
                        "doctor_name": "Dr. Manjula Test",
                        "patient_id": "P-100",
                        "patient_name": "John Doe",
                        "device_id": dev_id,
                    }),
                    content_type="application/json",
                )
                self.assertEqual(bind_resp.status_code, 200)
                info = json.loads(self.client.get("/api/device-info").data)
                self.assertTrue(info["connected"])
                self.assertEqual(info["device_id"], dev_id)
                self.assertEqual(info["device_name"], dev_id)

    def test_frontend_header_defaults_to_dash_and_tracks_selected_device(self):
        with open(os.path.join(ROOT_DIR, "frontend", "index.html"), "r", encoding="utf-8") as f:
            index_html = f.read()
        with open(os.path.join(ROOT_DIR, "frontend", "app.js"), "r", encoding="utf-8") as f:
            app_js = f.read()

        self.assertIn('<span id="header-device-text">--</span>', index_html)
        self.assertNotIn('<span id="header-device-text">TORUS-A12</span>', index_html)
        self.assertNotIn('<span id="header-device-text">TORUS-E18</span>', index_html)
        self.assertNotIn('<span id="header-device-text">Loading...</span>', index_html)

        self.assertIn("isValidTorusDeviceId", app_js)
        self.assertIn("persistConnectedTorusDeviceId", app_js)
        self.assertIn("resolveConnectedTorusDeviceId", app_js)
        self.assertIn("renderHeaderDeviceBadge", app_js)
        self.assertNotIn("fetchTorusDeviceInfo", app_js)
        self.assertNotIn("get_system_device_info", open(os.path.join(BACKEND_DIR, "server.py"), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
