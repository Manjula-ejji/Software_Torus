import unittest
import os
import re

class TestExaminationHistoryRefactor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
        with open(os.path.join(frontend_dir, "index.html"), "r", encoding="utf-8") as f:
            cls.index_html = f.read()
        with open(os.path.join(frontend_dir, "app.js"), "r", encoding="utf-8") as f:
            cls.app_js = f.read()
        with open(os.path.join(frontend_dir, "css", "styles.css"), "r", encoding="utf-8") as f:
            cls.styles_css = f.read()

    def test_01_examination_history_table_columns(self):
        # 8 specific columns in examination history table header
        self.assertIn('EXAMINATION DATE &amp; TIME', self.index_html)
        self.assertIn('EXAMINATION ID', self.index_html)
        self.assertIn('PATIENT NAME / ID', self.index_html)
        self.assertIn('SCAN TYPE', self.index_html)
        self.assertIn('PHYSICIAN / CENTER', self.index_html)
        self.assertIn('DURATION', self.index_html)
        self.assertIn('REPORT STATUS', self.index_html)
        self.assertIn('ACTION', self.index_html)

    def test_02_view_report_action_only_no_download_in_rows(self):
        # View Report button exists in renderPatientHistory rows
        self.assertIn('dhist-btn-view', self.app_js)
        self.assertIn('openPatientReportViewModal', self.app_js)
        # Download button is removed from Examination History rows
        self.assertNotIn('dhist-btn-download" onclick="downloadPatientReport', self.app_js)
        # In CSS, download button is disabled/hidden
        self.assertIn('.dhist-btn-download', self.styles_css)
        self.assertIn('display: none !important;', self.styles_css)

    def test_03_filters_and_search_controls(self):
        # Examination search, scan-type filter, and date-range filter exist
        self.assertIn('id="patHistSearchInput"', self.index_html)
        self.assertIn('id="patHistScanTypeFilter"', self.index_html)
        self.assertIn('id="patHistDateFilter"', self.index_html)
        self.assertIn('id="patHistRefreshBtn"', self.index_html)

    def test_04_unverified_claims_removed_from_footer(self):
        # Unverified medical badges and claims must not be in footer
        self.assertNotIn('Verified Clinical Archive', self.index_html)
        self.assertNotIn('DICOM & Telemetry Compliant', self.index_html)
        self.assertIn('id="patHistRecordsCount"', self.index_html)

    def test_05_diagnostic_reports_distinct_responsibilities(self):
        # Diagnostic reports retains station details and assigned-patient table
        self.assertIn('id="tstaStationBanner"', self.index_html)
        self.assertIn('id="tstaPatientsList"', self.index_html)
        self.assertIn('id="tstaPatientSearchInput"', self.index_html)
        self.assertIn('id="tstaPatientScanFilter"', self.index_html)
        self.assertIn('renderStationPatients', self.app_js)
        self.assertIn('renderPatientDetailedHistory', self.app_js)

    def test_06_authorized_examinations_no_duplicate_data(self):
        # Reuses existing data stores and IDs
        self.assertIn('function getAuthorizedExaminations', self.app_js)
        self.assertIn('window.torusSessions?.completed', self.app_js)
        self.assertIn('calculateTotalDuration', self.app_js)

if __name__ == "__main__":
    unittest.main()
