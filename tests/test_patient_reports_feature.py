import unittest
import requests

BASE_URL = "http://127.0.0.1:3000"

class TestPatientDiagnosticReportsFeature(unittest.TestCase):
    def test_01_api_reports_list(self):
        res = requests.get(f"{BASE_URL}/api/reports")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        reports = data.get("reports", [])
        self.assertGreaterEqual(len(reports), 12)
        report_ids = [r["report_id"] for r in reports]
        self.assertIn("REP-2026-001", report_ids)
        self.assertIn("REP-2026-002", report_ids)
        self.assertIn("REP-2026-003", report_ids)
        self.assertIn("REP-2026-012", report_ids)

    def test_02_view_specific_report_patient_a(self):
        res = requests.get(f"{BASE_URL}/api/reports/REP-2026-001")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        rep = data.get("report")
        self.assertEqual(rep.get("report_id"), "REP-2026-001")
        self.assertEqual(rep.get("patient_id"), "P-12345")
        self.assertEqual(rep.get("patient_name"), "Patient A")
        self.assertEqual(rep.get("scan_type"), "Abdominal")
        self.assertEqual(rep.get("session_id"), "S-101")
        self.assertEqual(rep.get("report_status"), "ready")
        self.assertIn("hepatobiliary", rep.get("clinical_summary", "").lower())
        self.assertTrue(len(rep.get("ultrasound_findings", "")) > 20)
        self.assertTrue(len(rep.get("diagnosis_impression", "")) > 10)
        self.assertIn("maxForce", rep.get("telemetry", {}))

    def test_03_view_specific_report_jane_smith(self):
        res = requests.get(f"{BASE_URL}/api/reports/REP-2026-003")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        rep = data.get("report")
        self.assertEqual(rep.get("report_id"), "REP-2026-003")
        self.assertEqual(rep.get("patient_id"), "P-9104")
        self.assertEqual(rep.get("patient_name"), "Jane Smith")
        self.assertEqual(rep.get("scan_type"), "Cardiac")
        self.assertEqual(rep.get("session_id"), "S-103")

    def test_04_view_missing_report_404(self):
        res = requests.get(f"{BASE_URL}/api/reports/REP-9999-999")
        self.assertEqual(res.status_code, 404)
        data = res.json()
        self.assertFalse(data.get("success"))
        self.assertIn("error", data)

    def test_05_download_pdf_report_patient_a(self):
        res = requests.get(f"{BASE_URL}/api/reports/REP-2026-001/download")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("Content-Type"), "application/pdf")
        disp = res.headers.get("Content-Disposition", "")
        self.assertIn("attachment", disp)
        self.assertIn("P-12345-REP-2026-001.pdf", disp)
        self.assertTrue(res.content.startswith(b"%PDF-"))
        self.assertGreater(len(res.content), 2000)

    def test_06_download_pdf_report_robert_brown(self):
        res = requests.get(f"{BASE_URL}/api/reports/REP-2026-004/download")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("Content-Type"), "application/pdf")
        disp = res.headers.get("Content-Disposition", "")
        self.assertIn("P-7543-REP-2026-004.pdf", disp)
        self.assertTrue(res.content.startswith(b"%PDF-"))
        self.assertGreater(len(res.content), 2000)

if __name__ == "__main__":
    unittest.main()
