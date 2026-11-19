import unittest
import json
import os
import re
from backend.server import app, SPA_CLIENT_ROUTES

class TestTorusRefreshNavigation(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_all_spa_client_routes_serve_index_html(self):
        """Verify all declared SPA client routes return 200 OK and serve index.html."""
        for route in SPA_CLIENT_ROUTES:
            with self.subTest(route=route):
                res = self.client.get(route)
                self.assertEqual(res.status_code, 200, f"Route {route} failed to return 200")
                html = res.data.decode("utf-8")
                self.assertIn("TORUS", html)
                self.assertIn("role-selection-screen", html)

    def test_trailing_slashes_and_subpaths(self):
        """Verify routes with trailing slashes also serve index.html."""
        routes = [
            "/doctor-dashboard/",
            "/patient-dashboard/",
            "/viewer-dashboard/",
            "/ultrasound-acquisition/",
            "/generate-report/",
            "/settings/",
            "/user-profile/"
        ]
        for route in routes:
            with self.subTest(route=route):
                res = self.client.get(route, follow_redirects=True)
                self.assertEqual(res.status_code, 200)
                html = res.data.decode("utf-8")
                self.assertIn("TORUS", html)

    def test_api_404_isolation(self):
        """Verify non-existent API routes return 404 JSON and are NOT caught by SPA fallback."""
        res = self.client.get("/api/unknown_endpoint_xyz")
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertIsNotNone(data)
        self.assertEqual(data.get("error"), "Endpoint not found")

    def test_frontend_route_definitions(self):
        """Verify index.html and app.js contain the required route mapping and handlers."""
        app_js_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            app_js = f.read()

        self.assertIn("const TORUS_PATH_MAP =", app_js)
        self.assertIn("function resolveTorusCurrentRoute()", app_js)
        self.assertIn("function getTorusRouteForState(", app_js)
        self.assertIn("function syncTorusBrowserRoute(", app_js)
        self.assertIn("function restoreAuthenticatedUserFromStorage(", app_js)
        self.assertIn("sessionStorage.setItem(\"torus_current_screen\", targetId)", app_js)

        # Check required key routes in app.js TORUS_PATH_MAP
        for key in [
            "/doctor-dashboard",
            "/patient-dashboard",
            "/viewer-dashboard",
            "/video-consultation",
            "/ultrasound-acquisition",
            "/generate-report",
            "/settings",
            "/user-profile",
            "/doctor-login",
            "/patient-login",
            "/viewer-login"
        ]:
            self.assertIn(f'"{key}"', app_js)

    def test_index_html_preboot_and_path_map(self):
        """Verify index.html contains TORUS_PATH_MAP and early route resolution."""
        index_html_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
        with open(index_html_path, "r", encoding="utf-8") as f:
            index_html = f.read()

        self.assertIn("window.TORUS_PATH_MAP =", index_html)
        self.assertIn("window.resolveTorusCurrentRoute =", index_html)
        self.assertIn("window.showTorusScreen =", index_html)
        self.assertIn("window.selectTorusRole =", index_html)
        # Ensure fragile document.write anti-flash is replaced with head pre-paint style element
        self.assertNotIn("document.write('<style id=\"torus-anti-flash\">", index_html)
        self.assertIn("torus-route-prepaint", index_html)

    def test_app_js_role_and_anti_flash_protection(self):
        """Verify app.js includes strict role resolution, pre-paint cleanup, and forced initial display."""
        app_js_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            app_js = f.read()

        self.assertIn("torus-route-prepaint", app_js)
        self.assertIn("getResolvedActiveRole", app_js)
        self.assertIn("options.force", app_js)
        self.assertIn("updateLocalFeedTitle", app_js)
        # Ensure logout purges cross-role storage
        self.assertIn("keysToPurge", app_js)

if __name__ == "__main__":
    unittest.main()
