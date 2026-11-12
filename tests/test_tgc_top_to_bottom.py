import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import backend.ultrasound as us
import backend.server as srv


class TestTgcTopToBottom(unittest.TestCase):
    def setUp(self):
        self.us_client = us.app.test_client()
        srv.app.testing = True
        self.srv_client = srv.app.test_client()
        self.orig_tgc_enabled = us._tgc_enabled
        self.orig_tgc_sliders = list(us._tgc_sliders)
        self.orig_srv_state = dict(srv._cached_ultrasound_state)
        self.orig_srv_sliders = list(srv._cached_ultrasound_state.get("tgc_sliders", []))
        self.orig_rt = us._global_ostb_runtime
        self.orig_acquiring = us._is_acquiring
        self.orig_frozen = us._is_frozen
        self.orig_stopped = us._is_user_stopped
        us._tgc_enabled = False
        us._tgc_sliders = [50, 12, 3, 77, 90, 30]
        srv._cached_ultrasound_state["tgc_enabled"] = False
        srv._cached_ultrasound_state["tgc_sliders"] = [50, 12, 3, 77, 90, 30]

    def tearDown(self):
        us._tgc_enabled = self.orig_tgc_enabled
        us._tgc_sliders = self.orig_tgc_sliders
        srv._cached_ultrasound_state.clear()
        srv._cached_ultrasound_state.update(self.orig_srv_state)
        srv._cached_ultrasound_state["tgc_sliders"] = self.orig_srv_sliders
        us._global_ostb_runtime = self.orig_rt
        us._is_acquiring = self.orig_acquiring
        us._is_frozen = self.orig_frozen
        us._is_user_stopped = self.orig_stopped

    def test_frontend_top_to_bottom_css_and_fill_rules(self):
        css_text = (ROOT / "frontend" / "css" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".tgc-range-slider", css_text)
        tgc_block = css_text.split(".tgc-range-slider {", 1)[1].split("}", 1)[0]
        self.assertIn("writing-mode: vertical-lr;", tgc_block)
        self.assertIn("direction: ltr;", tgc_block)
        self.assertNotIn("direction: rtl;", tgc_block)
        self.assertNotIn("rotate(180deg)", tgc_block)

        app_js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        self.assertIn("linear-gradient(to bottom, #2563eb ${percent}%, #e2e8f0 ${percent}%)", app_js)
        self.assertNotIn("linear-gradient(to top, #2563eb ${percent}%", app_js)

        html_text = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        for i in range(1, 7):
            self.assertIn(f'id="tgcSlider{i}"', html_text)
        self.assertNotIn("linear-gradient(to top, #2563eb", html_text)

    def test_all_six_tgc_sliders_independent_and_array_order_preserved(self):
        class MockTgcRuntime:
            def __init__(self):
                self.tgc_enabled_calls = []
                self.tgc_curve_calls = []

            def set_tgc_enabled(self, enabled):
                self.tgc_enabled_calls.append(enabled)

            def set_tgc(self, values):
                self.tgc_curve_calls.append(list(values))

        mock_rt = MockTgcRuntime()
        us._global_ostb_runtime = mock_rt
        us._is_acquiring = True
        us._is_frozen = False
        us._is_user_stopped = False

        # Enable TGC
        res_toggle = self.us_client.post(
            "/api/remote-input",
            data=json.dumps({"control": "tgc_toggle", "value": True}),
            content_type="application/json",
        )
        self.assertEqual(res_toggle.status_code, 200)
        self.assertEqual(mock_rt.tgc_enabled_calls, [True])

        # Test minimum (0), intermediate (42..85), maximum (100), and clamping
        target_zones = [0, 22, 48, 64, 88, 100]
        for idx, val in enumerate(target_zones, start=1):
            res = self.us_client.post(
                "/api/remote-input",
                data=json.dumps({"control": f"tgc_slider_{idx}", "value": val}),
                content_type="application/json",
            )
            self.assertEqual(res.status_code, 200)
            payload = json.loads(res.data)
            self.assertEqual(payload["tgc_sliders"][idx - 1], val)

        # Array order 1..6 (shallow->deep) must remain exact without reversal
        st = json.loads(self.us_client.get("/api/status").data)
        self.assertTrue(st["tgc_enabled"])
        self.assertEqual(st["tgc_sliders"], target_zones)
        self.assertEqual(mock_rt.tgc_curve_calls[-1], target_zones)

        # Bounds clamping & invalid slider rejection
        res_clamp_high = self.us_client.post(
            "/api/remote-input",
            data=json.dumps({"control": "tgc_slider_1", "value": 150}),
            content_type="application/json",
        )
        self.assertEqual(res_clamp_high.status_code, 200)
        self.assertEqual(json.loads(res_clamp_high.data)["tgc_sliders"][0], 100)

        res_clamp_low = self.us_client.post(
            "/api/remote-input",
            data=json.dumps({"control": "tgc_slider_6", "value": -25}),
            content_type="application/json",
        )
        self.assertEqual(res_clamp_low.status_code, 200)
        self.assertEqual(json.loads(res_clamp_low.data)["tgc_sliders"][5], 0)

        res_bad = self.us_client.post(
            "/api/remote-input",
            data=json.dumps({"control": "tgc_slider_7", "value": 50}),
            content_type="application/json",
        )
        self.assertEqual(res_bad.status_code, 500)

    def test_qt_top_to_bottom_y_coordinate_mapping(self):
        with patch.object(us, "find_opensonics_control_window", return_value=99999), \
             patch.object(us, "send_direct_qt_click") as mock_qt_click, \
             patch.object(us, "send_win32_click"):
            for slider_idx in range(1, 7):
                mock_qt_click.reset_mock()
                self.assertTrue(us.handle_control_command(f"tgc_slider_{slider_idx}", 0))
                x0, y0 = mock_qt_click.call_args[0][1], mock_qt_click.call_args[0][2]

                mock_qt_click.reset_mock()
                self.assertTrue(us.handle_control_command(f"tgc_slider_{slider_idx}", 50))
                x50, y50 = mock_qt_click.call_args[0][1], mock_qt_click.call_args[0][2]

                mock_qt_click.reset_mock()
                self.assertTrue(us.handle_control_command(f"tgc_slider_{slider_idx}", 100))
                x100, y100 = mock_qt_click.call_args[0][1], mock_qt_click.call_args[0][2]

                # Top-to-bottom: moving downward (0 -> 50 -> 100) increases Y coordinate
                self.assertEqual(x0, x50)
                self.assertEqual(x50, x100)
                self.assertLess(y0, y50)
                self.assertLess(y50, y100)

    def test_server_cache_tracks_tgc_without_affecting_voltage_or_gain(self):
        srv._cached_ultrasound_state["voltage"] = 37.0
        srv._cached_ultrasound_state["gain"] = 62.0

        with patch.object(srv, "_dispatch_mqtt_control", return_value=True):
            old_url = srv.ULTRASOUND_SERVICE_URL
            srv.ULTRASOUND_SERVICE_URL = "http://127.0.0.1:59999"
            try:
                r_on = self.srv_client.post(
                    "/api/remote-input",
                    data=json.dumps({"control": "tgc_toggle", "value": True}),
                    content_type="application/json",
                )
                self.assertEqual(r_on.status_code, 200)
                self.assertTrue(json.loads(r_on.data)["tgc_enabled"])

                for idx, val in enumerate([10, 20, 30, 40, 50, 60], start=1):
                    r = self.srv_client.post(
                        "/api/remote-input",
                        data=json.dumps({"control": f"tgc_slider_{idx}", "value": val}),
                        content_type="application/json",
                    )
                    self.assertEqual(r.status_code, 200)
            finally:
                srv.ULTRASOUND_SERVICE_URL = old_url

        st = json.loads(self.srv_client.get("/api/status").data)
        self.assertTrue(st["tgc_enabled"])
        self.assertEqual(st["tgc_sliders"], [10, 20, 30, 40, 50, 60])
        self.assertEqual(st["voltage"], 37.0)
        self.assertEqual(st["gain"], 62.0)

    def test_server_ignores_out_of_order_tgc_command_seq(self):
        srv._last_control_seq_by_sender.clear()
        with patch.object(srv, "_dispatch_mqtt_control", return_value=True):
            old_url = srv.ULTRASOUND_SERVICE_URL
            srv.ULTRASOUND_SERVICE_URL = "http://127.0.0.1:59999"
            try:
                # Newer final drag value arrives first
                r1 = self.srv_client.post(
                    "/api/remote-input",
                    data=json.dumps({
                        "control": "tgc_slider_6",
                        "value": 95,
                        "commandSeq": 20,
                        "senderId": "doc-client-1",
                    }),
                    content_type="application/json",
                )
                self.assertEqual(r1.status_code, 200)
                # Older intermediate drag value arrives late out of order
                r2 = self.srv_client.post(
                    "/api/remote-input",
                    data=json.dumps({
                        "control": "tgc_slider_6",
                        "value": 17,
                        "commandSeq": 18,
                        "senderId": "doc-client-1",
                    }),
                    content_type="application/json",
                )
                self.assertEqual(r2.status_code, 200)
                self.assertEqual(json.loads(r2.data)["status"], "ignored_stale")
            finally:
                srv.ULTRASOUND_SERVICE_URL = old_url

        st = json.loads(self.srv_client.get("/api/status").data)
        self.assertEqual(st["tgc_sliders"][5], 95)


if __name__ == "__main__":
    unittest.main()
