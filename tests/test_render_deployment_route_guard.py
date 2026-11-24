import unittest
import os
import re

class TestRenderDeploymentRouteGuard(unittest.TestCase):
    def setUp(self):
        self.repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(self.repo_root, "frontend", "index.html"), "r", encoding="utf-8") as f:
            self.index_html = f.read()
        with open(os.path.join(self.repo_root, "frontend", "app.js"), "r", encoding="utf-8") as f:
            self.app_js = f.read()

    def test_unauthenticated_video_consultation_guard(self):
        """Verify unauthenticated direct access to /video-consultation redirects to role selection."""
        self.assertIn("isConsultationPath && !hasAuth", self.index_html)
        self.assertIn("isConsultationPath && !hasAuth", self.app_js)
        self.assertIn('screen = "role-selection-screen"', self.index_html)
        self.assertIn('screen = "role-selection-screen"', self.app_js)

    def test_root_path_prevents_auto_video_consultation(self):
        """Verify root landing path never auto-opens video consultation room from stale stored screen."""
        self.assertIn('storedScreen !== "app-dashboard"', self.index_html)
        self.assertIn('storedScreen !== "app-dashboard"', self.app_js)

    def test_call_backend_api_prioritizes_relative_endpoint_on_https_render(self):
        """Verify callBackendAPI prioritizes relative endpoint on hosted/HTTPS environments to avoid mixed-content blocking."""
        self.assertIn("isHttps", self.app_js)
        self.assertIn("isHosted", self.app_js)
        self.assertIn("endpoint,\n      `${window.location.origin}${endpoint}`", self.app_js)

    def test_fetch_agora_configuration_supports_https(self):
        """Verify fetchAgoraConfiguration avoids insecure http:// endpoints on https."""
        self.assertIn('const isHttps = window.location.protocol === "https:";', self.app_js)
        self.assertIn('"/api/agora/config",\n      `${window.location.origin}/api/agora/config`', self.app_js)

    def test_set_status_does_not_treat_enter_as_error(self):
        """Verify prompt messages containing 'enter' (e.g. Enter channel name) do not turn badge into Video Call Error."""
        # Ensure 'enter' is NOT grouped with 'failed' and 'error'
        self.assertNotIn('msgLower.includes("failed") || msgLower.includes("error") || msgLower.includes("enter")', self.app_js)

if __name__ == "__main__":
    unittest.main()
