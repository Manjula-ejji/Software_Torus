import unittest
import os
import re

class TestTorusStationsDashboardFeature(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
        with open(os.path.join(frontend_dir, "index.html"), "r", encoding="utf-8") as f:
            cls.index_html = f.read()
        with open(os.path.join(frontend_dir, "app.js"), "r", encoding="utf-8") as f:
            cls.app_js = f.read()
        with open(os.path.join(frontend_dir, "css", "styles.css"), "r", encoding="utf-8") as f:
            cls.styles_css = f.read()

    def test_01_summary_cards_exist(self):
        self.assertIn('id="patRepTotalCount"', self.index_html)
        self.assertIn('id="patRepFinalizedCount"', self.index_html)
        self.assertIn('id="patRepStandbyCount"', self.index_html)
        self.assertIn('id="patRepOfflineCount"', self.index_html)
        self.assertIn('id="patRepTotalPatientsCount"', self.index_html)
        self.assertIn('id="patRepActiveConsultCount"', self.index_html)

    def test_02_advanced_filters_and_search_elements(self):
        # Station dashboard toolbar
        self.assertIn('id="patRepSearchInput"', self.index_html)
        self.assertIn('id="patRepLocationInput"', self.index_html)
        self.assertIn('id="patRepScanTypeFilter"', self.index_html)
        self.assertIn('id="patRepStationScanFilter"', self.index_html)
        self.assertIn('id="tstaStationSort"', self.index_html)
        self.assertIn('id="patRepRefreshBtn"', self.index_html)

        # Station patient list toolbar
        self.assertIn('id="tstaPatientSearchInput"', self.index_html)
        self.assertIn('id="tstaPatientScanFilter"', self.index_html)
        self.assertIn('id="tstaPatientStatusFilter"', self.index_html)
        self.assertIn('id="tstaPatientDoctorFilter"', self.index_html)
        self.assertIn('id="tstaPatientRefreshBtn"', self.index_html)

    def test_03_stations_and_data_integrity(self):
        # Verify existing 10 stations
        for st_id in ["TORUS-A12", "TORUS-B08", "TORUS-C15", "TORUS-D22", "TORUS-E18",
                      "TORUS-F09", "TORUS-G04", "TORUS-H17", "TORUS-K03", "TORUS-Z99"]:
            self.assertIn(f'id: "{st_id}"', self.app_js)
            self.assertIn(f'"{st_id}": [', self.app_js)

    def test_04_consultation_timeline_events(self):
        # Verify 4 key events in the lifecycle timeline
        self.assertIn('Consultation Started', self.app_js)
        self.assertIn('Scan Completed', self.app_js)
        self.assertIn('Report Generated', self.app_js)
        self.assertIn('Report Sent', self.app_js)
        self.assertIn('tsta-timeline-stepper', self.app_js)

    def test_05_views_and_navigation(self):
        self.assertIn('id="tstaDashboardView"', self.index_html)
        self.assertIn('id="tstaPatientsView"', self.index_html)
        self.assertIn('id="tstaPatientHistoryView"', self.index_html)
        self.assertIn('id="tstaBreadcrumb"', self.index_html)
        self.assertIn('navigateTorusStationView', self.app_js)
        self.assertIn('renderTorusStationsGrid', self.app_js)
        self.assertIn('renderStationPatients', self.app_js)
        self.assertIn('renderPatientDetailedHistory', self.app_js)

if __name__ == "__main__":
    unittest.main()
