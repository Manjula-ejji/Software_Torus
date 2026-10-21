import unittest
import os
import re

class TestSearchTorusDevicePopupFilters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
        with open(os.path.join(frontend_dir, "index.html"), "r", encoding="utf-8") as f:
            cls.index_html = f.read()
        with open(os.path.join(frontend_dir, "app.js"), "r", encoding="utf-8") as f:
            cls.app_js = f.read()
        with open(os.path.join(frontend_dir, "css", "styles.css"), "r", encoding="utf-8") as f:
            cls.styles_css = f.read()

    def test_01_scan_type_dropdown_present(self):
        # Scan Type dropdown must replace the first input
        self.assertIn('id="deviceScanTypeFilter"', self.index_html)
        self.assertIn('<select id="deviceScanTypeFilter"', self.index_html)
        self.assertIn('<option value="all">All Scan Types</option>', self.index_html)
        self.assertIn('<option value="Abdominal">Abdominal</option>', self.index_html)
        self.assertIn('<option value="Cardiac">Cardiac</option>', self.index_html)
        self.assertIn('<option value="Pelvic">Pelvic</option>', self.index_html)
        self.assertIn('<option value="Vascular">Vascular</option>', self.index_html)
        self.assertIn('<option value="Thyroid">Thyroid</option>', self.index_html)

    def test_02_device_name_search_input_present(self):
        # Device Name search must replace the second input
        self.assertIn('id="deviceNameSearchInput"', self.index_html)
        self.assertIn('placeholder="Search by device name or ID..."', self.index_html)
        self.assertNotIn('placeholder="Filter by country or city..."', self.index_html)
        self.assertNotIn('placeholder="Search by ID, hospital, city..."', self.index_html)

    def test_03_modal_styles_defined(self):
        # Verify custom select styling and chevron in styles.css
        self.assertIn('.device-filter-select', self.styles_css)
        self.assertIn('.device-filter-chevron', self.styles_css)

    def test_04_device_supported_scans_in_app_js(self):
        # Verify supportedScans mapped to devices matching existing application data
        self.assertIn('supportedScans: ["Pelvic"]', self.app_js)
        self.assertIn('supportedScans: ["Cardiac", "Pelvic"]', self.app_js)
        self.assertIn('supportedScans: ["Abdominal", "Thyroid"]', self.app_js)
        self.assertIn('supportedScans: ["Vascular", "Pelvic"]', self.app_js)
        self.assertIn('supportedScans: ["Abdominal", "Vascular"]', self.app_js)
        self.assertIn('supportedScans: ["Cardiac", "Thyroid"]', self.app_js)
        self.assertIn('supportedScans: ["Abdominal", "Cardiac"]', self.app_js)
        self.assertIn('supportedScans: ["Vascular", "Abdominal"]', self.app_js)
        self.assertIn('supportedScans: ["Abdominal"]', self.app_js)
        self.assertIn('supportedScans: ["Cardiac"]', self.app_js)
        self.assertIn('function getDeviceConfiguredScanTypes(deviceId)', self.app_js)

    def test_05_ensure_device_modal_in_dom_synchronized(self):
        # ensureDeviceModalInDOM must build the updated controls
        self.assertIn('id="deviceScanTypeFilter"', self.app_js)
        self.assertIn('id="deviceNameSearchInput"', self.app_js)

    def test_06_filter_handlers_and_events(self):
        # Check event bindings for both filters
        self.assertIn('deviceScanTypeFilter', self.app_js)
        self.assertIn('deviceNameSearchInput', self.app_js)
        self.assertIn('getFilteredDevices', self.app_js)

if __name__ == "__main__":
    unittest.main()
