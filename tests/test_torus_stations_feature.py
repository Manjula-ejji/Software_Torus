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

    def test_01_overview_page_removed(self):
        # Stations overview page elements must be completely removed
        self.assertNotIn('id="tstaDashboardView"', self.index_html)
        self.assertNotIn('id="patRepTotalCount"', self.index_html)
        self.assertNotIn('id="patRepFinalizedCount"', self.index_html)
        self.assertNotIn('id="patRepStandbyCount"', self.index_html)
        self.assertNotIn('id="patRepOfflineCount"', self.index_html)
        self.assertNotIn('id="patRepTotalPatientsCount"', self.index_html)
        self.assertNotIn('id="patRepActiveConsultCount"', self.index_html)
        self.assertNotIn('id="patRepSearchInput"', self.index_html)
        self.assertNotIn('id="patRepLocationInput"', self.index_html)
        self.assertNotIn('id="patRepScanTypeFilter"', self.index_html)
        self.assertNotIn('id="patRepStationScanFilter"', self.index_html)
        self.assertNotIn('id="tstaStationSort"', self.index_html)
        self.assertNotIn('id="patRepRefreshBtn"', self.index_html)
        self.assertNotIn('id="tstaStationsGrid"', self.index_html)

    def test_02_individual_station_details_preserved(self):
        # Station patient list toolbar and controls must be preserved
        self.assertIn('id="tstaPatientSearchInput"', self.index_html)
        self.assertIn('id="tstaPatientScanFilter"', self.index_html)
        self.assertIn('id="tstaPatientStatusFilter"', self.index_html)
        self.assertIn('id="tstaPatientDoctorFilter"', self.index_html)
        self.assertIn('id="tstaPatientRefreshBtn"', self.index_html)
        self.assertIn('id="tstaStationBanner"', self.index_html)
        self.assertIn('id="tstaPatientsList"', self.index_html)

    def test_03_stations_and_data_integrity(self):
        # Verify existing 10 stations data
        for st_id in ["TORUS-A12", "TORUS-B08", "TORUS-C15", "TORUS-D22", "TORUS-E18",
                      "TORUS-F09", "TORUS-G04", "TORUS-H17", "TORUS-K03", "TORUS-Z99"]:
            self.assertIn(f'id: "{st_id}"', self.app_js)
            self.assertIn(f'"{st_id}": [', self.app_js)

    def test_04_consultation_timeline_events(self):
        # Verify 4 key events in the lifecycle timeline
        self.assertIn('Consultation Started', self.app_js)
        self.assertIn('Scan Completed', self.app_js)
        self.assertIn('Report Generated', self.app_js)
        self.assertIn('Report Received', self.app_js)
        self.assertIn('tsta-timeline-stepper', self.app_js)

    def test_05_views_and_navigation(self):
        # Verify individual station details view and patient history view are intact, and breadcrumb is removed
        self.assertIn('id="tstaPatientsView"', self.index_html)
        self.assertIn('id="tstaPatientHistoryView"', self.index_html)
        self.assertNotIn('id="tstaBreadcrumb"', self.index_html)
        self.assertIn('navigateTorusStationView', self.app_js)
        self.assertIn('renderStationPatients', self.app_js)
        self.assertIn('renderPatientDetailedHistory', self.app_js)

    def test_06_report_page_sections_and_line_removed(self):
        # Ultrasound Findings & Telemetry and Clinical Impression & Follow-up must be completely removed
        self.assertNotIn('Ultrasound Findings & Telemetry', self.app_js)
        self.assertNotIn('Clinical Impression & Follow-up', self.app_js)

        # Timeline milestones must remain intact
        self.assertIn('Consultation & Telemetry Lifecycle Timeline', self.app_js)
        self.assertIn('Consultation Started', self.app_js)
        self.assertIn('Scan Completed', self.app_js)
        self.assertIn('Report Generated', self.app_js)
        self.assertIn('Report Received', self.app_js)

        # Blue/cyan horizontal connecting line in timeline must be removed/disabled
        self.assertNotIn('background: linear-gradient(90deg, #10b981 0%, #06b6d4 100%);', self.styles_css)
        self.assertIn('.tsta-timeline-step::before', self.styles_css)
        self.assertIn('display: none !important;', self.styles_css)

if __name__ == "__main__":
    unittest.main()
