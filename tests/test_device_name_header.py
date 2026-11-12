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


class TestDeviceNameHeader(unittest.TestCase):
    def setUp(self):
        self.client = srv.app.test_client()

    def test_live_system_device_info_returns_actual_hostname(self):
        resp = self.client.get("/api/device-info")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["device_name"])
        self.assertNotIn(data["device_name"], ("--", "TORUS-A12", "Unknown", "Unavailable"))
        self.assertEqual(data["device_name"], data["hostname"])
        self.assertEqual(data["host_role"], "backend")
        self.assertTrue(data["is_local_access"])

    def test_dynamic_device_names_multiple_machines(self):
        for simulated_name in ("TORUS-E18", "TORUS-E19", "LAB-IMAGING-04"):
            with self.subTest(device=simulated_name):
                with patch("socket.gethostname", return_value=simulated_name), \
                     patch("socket.getfqdn", return_value=simulated_name):
                    resp = self.client.get("/api/device-info")
                    self.assertEqual(resp.status_code, 200)
                    data = json.loads(resp.data)
                    self.assertEqual(data["device_name"], simulated_name)
                    self.assertEqual(data["hostname"], simulated_name)
                    self.assertEqual(data["source"], "socket.gethostname")

    def test_mdns_local_suffix_normalized_and_fallback_sources(self):
        with patch("socket.gethostname", return_value="TORUS-E19.local"), \
             patch("socket.getfqdn", return_value="TORUS-E19.local"):
            resp = self.client.get("/api/device-info")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(json.loads(resp.data)["device_name"], "TORUS-E19")

        # Fallback from generic socket.gethostname to platform.node
        with patch("socket.gethostname", return_value="localhost"), \
             patch("platform.node", return_value="TORUS-E18"), \
             patch("socket.getfqdn", return_value="TORUS-E18"):
            resp = self.client.get("/api/device-info")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertEqual(data["device_name"], "TORUS-E18")
            self.assertEqual(data["source"], "platform.node")

        # Fallback to environment COMPUTERNAME
        with patch("socket.gethostname", side_effect=OSError("no host")), \
             patch("platform.node", return_value=""), \
             patch.dict(os.environ, {"COMPUTERNAME": "TORUS-ENV-22"}, clear=False):
            resp = self.client.get("/api/device-info")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertEqual(data["device_name"], "TORUS-ENV-22")
            self.assertEqual(data["source"], "env.COMPUTERNAME")

    def test_all_hostname_sources_unavailable_returns_503(self):
        with patch("socket.gethostname", return_value=""), \
             patch("platform.node", return_value=""), \
             patch.dict(os.environ, {"COMPUTERNAME": "", "HOSTNAME": ""}, clear=False):
            resp = self.client.get("/api/device-info")
            self.assertEqual(resp.status_code, 503)
            data = json.loads(resp.data)
            self.assertEqual(data["status"], "error")
            self.assertIsNone(data["device_name"])

    def test_remote_client_vs_local_access_distinction(self):
        with patch("socket.gethostname", return_value="TORUS-E18"), \
             patch("socket.gethostbyname_ex", return_value=("TORUS-E18", [], ["10.0.0.18"])):
            local_resp = self.client.get("/api/device-info", environ_base={"REMOTE_ADDR": "127.0.0.1"})
            self.assertTrue(json.loads(local_resp.data)["is_local_access"])

            remote_resp = self.client.get("/api/device-info", environ_base={"REMOTE_ADDR": "192.168.1.99"})
            remote_data = json.loads(remote_resp.data)
            self.assertEqual(remote_data["device_name"], "TORUS-E18")
            self.assertFalse(remote_data["is_local_access"])
            self.assertEqual(remote_data["client_ip"], "192.168.1.99")
            self.assertEqual(remote_data["host_role"], "backend")

            proxied_resp = self.client.get(
                "/api/device-info",
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
                headers={"X-Forwarded-For": "203.0.113.10"},
            )
            self.assertFalse(json.loads(proxied_resp.data)["is_local_access"])

    def test_health_endpoint_includes_dynamic_device_name(self):
        with patch("socket.gethostname", return_value="TORUS-E19"):
            resp = self.client.get("/api/health")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertEqual(data["device_name"], "TORUS-E19")
            self.assertEqual(data["hostname"], "TORUS-E19")

    def test_frontend_has_no_static_header_placeholder_or_user_agent_detection(self):
        with open(os.path.join(ROOT_DIR, "frontend", "index.html"), "r", encoding="utf-8") as f:
            index_html = f.read()
        with open(os.path.join(ROOT_DIR, "frontend", "app.js"), "r", encoding="utf-8") as f:
            app_js = f.read()

        self.assertIn('<span id="header-device-text">Loading...</span>', index_html)
        self.assertNotIn('<span id="header-device-text">TORUS-A12</span>', index_html)
        self.assertNotIn('<span id="header-device-text">--</span>', index_html)
        self.assertNotIn('<span id="header-device-text">TORUS-A12</span>', app_js)
        self.assertNotIn('deviceId: "--"', app_js)
        self.assertIn("/api/device-info", app_js)
        self.assertIn("fetchTorusDeviceInfo", app_js)
        self.assertIn("Unavailable", app_js)
        self.assertNotIn("navigator.userAgent", app_js)


if __name__ == "__main__":
    unittest.main()
