import unittest
import json
import urllib.request
import urllib.error
import sys
import os
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
import database

BASE_URL = "http://127.0.0.1:5000"

class TestSignatureStorageQuotaFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()

    def test_frontend_markup_has_quota_safe_signature_storage(self):
        """Verifies report-generation.html & js use TorusSignatureStore (IndexedDB) and safe storage."""
        html_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "report-generation.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        # IndexedDB store exists
        self.assertIn("TorusSignatureStore", html)
        self.assertIn("TorusSignatureDB", html)
        # Safe storage helper exists
        self.assertIn("safeLocalStorageSet", html)
        self.assertIn("cleanupRedundantSignatureStorage", html)
        # Backend sync exists
        self.assertIn("syncReportSignatureFromBackend", html)
        # Verify executeDigitalSignature does not store raw signPayload with signatureData in localStorage
        self.assertNotIn("localStorage.setItem('torus_signature_' + reportId, JSON.stringify(signPayload))", html)

        js_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "report-generation.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()

        self.assertIn("TorusSignatureStore", js)
        self.assertIn("safeLocalStorageSet", js)
        self.assertIn("cleanupRedundantSignatureStorage", js)
        self.assertNotIn("localStorage.setItem('torus_signature_' + reportId, JSON.stringify(signPayload))", js)

    def test_backend_signature_endpoint_and_idempotency(self):
        """Tests /api/reports/sign and /api/reports/<report_id>/signature endpoints with retry idempotency."""
        test_rep_id = f"RPT-SIGTEST-{int(time.time())}"

        # 1. Sign a report
        sign_payload = {
            "reportId": test_rep_id,
            "sessionId": "TORUS",
            "doctorName": "Dr. Admin Doctor",
            "doctorLicense": "TORUS-REG-3001",
            "signatureData": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "signatureHash": f"TORUS-SIG-{test_rep_id}",
            "signedAt": "2026-10-22T10:00:00Z",
            "findings": "Test findings for signature quota fix.",
            "recommendations": "Routine follow up.",
            "patientName": "Patient User",
            "scanType": "Abdominal Ultrasound",
            "status": "signed"
        }

        req = urllib.request.Request(
            f"{BASE_URL}/api/reports/sign",
            data=json.dumps(sign_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            res_data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(res_data.get("success"))

        # 2. Check /api/reports/<report_id>/signature endpoint
        with urllib.request.urlopen(f"{BASE_URL}/api/reports/{test_rep_id}/signature") as sig_resp:
            self.assertEqual(sig_resp.status, 200)
            sig_data = json.loads(sig_resp.read().decode("utf-8"))
            self.assertTrue(sig_data.get("success"))
            self.assertTrue(sig_data.get("is_signed"))
            self.assertEqual(sig_data.get("status"), "signed")
            self.assertEqual(sig_data.get("doctorName"), "Dr. Admin Doctor")
            self.assertEqual(sig_data.get("doctorLicense"), "TORUS-REG-3001")
            self.assertEqual(sig_data.get("signatureHash"), f"TORUS-SIG-{test_rep_id}")
            self.assertTrue(sig_data.get("signatureData").startswith("data:image/png;base64,"))

        # 3. Test retry signing for the same report ID (must be idempotent - no duplicate report)
        req_retry = urllib.request.Request(
            f"{BASE_URL}/api/reports/sign",
            data=json.dumps(sign_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_retry) as retry_resp:
            self.assertEqual(retry_resp.status, 200)
            retry_data = json.loads(retry_resp.read().decode("utf-8"))
            self.assertTrue(retry_data.get("success"))

        # Verify only 1 record exists in diagnostic_reports for this report ID
        reports = [r for r in database.get_diagnostic_reports() if r.get("report_id") == test_rep_id]
        self.assertEqual(len(reports), 1, "Duplicate report record created on re-signing!")

if __name__ == "__main__":
    unittest.main()
