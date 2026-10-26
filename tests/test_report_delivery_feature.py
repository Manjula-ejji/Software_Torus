import unittest
import json
import urllib.request
import urllib.error
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
import database

BASE_URL = "http://127.0.0.1:5000"

class TestReportDeliveryFeature(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()

    def test_popup_markup_contains_required_buttons_and_status(self):
        """Verifies that the Report Generated modal contains Send to Patient, Resend to Patient, and delivery status."""
        html_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "report-generation.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Modal elements
        self.assertIn('id="successDialogModal"', html)
        self.assertIn('Report Generated', html)
        self.assertIn('Your report has been generated successfully.', html)
        self.assertIn('The report is now available to the patient.', html)

        # Buttons
        self.assertIn('id="popupSendPatientBtn"', html)
        self.assertIn('>Send<', html)
        self.assertIn('id="popupResendPatientBtn"', html)
        self.assertIn('>Resend<', html)
        self.assertIn('popupDeliveryButtonsRow', html)

        # Delivery status elements
        self.assertIn('id="popupDeliveryBadge"', html)
        self.assertIn('Delivery Status:', html)
        self.assertIn('id="popupDeliveryReportId"', html)
        self.assertIn('id="popupDeliveryPatientName"', html)
        self.assertIn('id="popupDeliveryPatientId"', html)
        self.assertIn('id="popupDeliveryFeedback"', html)

        # Logic functions
        self.assertIn('updatePopupDeliveryUI', html)
        self.assertIn('executeSendToPatient', html)

    def test_backend_delivery_workflow(self):
        """Verifies real delivery, resend without duplicates, and security verification."""
        import time
        test_rep_id = f"RPT-TEST-DELIVERY-{int(time.time())}"
        # Create test report assigned to patient 4001
        res_create = database.create_diagnostic_report({
            "report_id": test_rep_id,
            "patient_id": "4001",
            "patient_name": "Patient User",
            "doctor_name": "Dr. Admin Doctor",
            "scan_type": "Abdominal Ultrasound",
            "findings": "Test acoustic speckle pattern verified.",
            "recommendations": "Routine follow up.",
            "delivery_status": "pending"
        })
        self.assertTrue(res_create.get("success"), f"Failed to create test report: {res_create}")

        # Check initial delivery status
        status_req = urllib.request.urlopen(f"{BASE_URL}/api/reports/{test_rep_id}/delivery-status")
        self.assertEqual(status_req.status, 200)
        status_data = json.loads(status_req.read().decode())
        self.assertEqual(status_data.get("delivery_status"), "pending")

        # 1. Send to Patient via API
        deliver_payload = json.dumps({
            "report_id": test_rep_id,
            "patient_id": "4001",
            "is_resend": False
        }).encode("utf-8")
        req1 = urllib.request.Request(
            f"{BASE_URL}/api/reports/{test_rep_id}/deliver",
            data=deliver_payload,
            headers={"Content-Type": "application/json"}
        )
        res1 = urllib.request.urlopen(req1)
        self.assertEqual(res1.status, 200)
        data1 = json.loads(res1.read().decode())
        self.assertTrue(data1.get("success"))
        self.assertEqual(data1.get("delivery_status"), "sent")
        self.assertEqual(data1.get("patient_id"), "4001")
        self.assertEqual(data1.get("attempt_number"), 1)
        self.assertFalse(data1.get("is_resend"))

        # Verify no duplicate reports created
        reports = [r for r in database.get_diagnostic_reports() if r.get("report_id") == test_rep_id]
        self.assertEqual(len(reports), 1, "Duplicate report created on delivery!")

        # 2. Resend to Patient via API
        resend_payload = json.dumps({
            "report_id": test_rep_id,
            "patient_id": "4001",
            "is_resend": True
        }).encode("utf-8")
        req2 = urllib.request.Request(
            f"{BASE_URL}/api/reports/{test_rep_id}/deliver",
            data=resend_payload,
            headers={"Content-Type": "application/json"}
        )
        res2 = urllib.request.urlopen(req2)
        self.assertEqual(res2.status, 200)
        data2 = json.loads(res2.read().decode())
        self.assertTrue(data2.get("success"))
        self.assertEqual(data2.get("delivery_status"), "sent")
        self.assertEqual(data2.get("attempt_number"), 2)
        self.assertTrue(data2.get("is_resend"))

        # Verify duplicate send safeguard (is_resend=False when already sent returns already_delivered without re-dispatch)
        req_dup = urllib.request.Request(
            f"{BASE_URL}/api/reports/{test_rep_id}/deliver",
            data=deliver_payload,
            headers={"Content-Type": "application/json"}
        )
        res_dup = urllib.request.urlopen(req_dup)
        self.assertEqual(res_dup.status, 200)
        data_dup = json.loads(res_dup.read().decode())
        self.assertTrue(data_dup.get("success"))
        self.assertTrue(data_dup.get("already_delivered"))
        self.assertEqual(data_dup.get("delivery_status"), "sent")

        # Verify STILL no duplicate reports
        reports_after_resend = [r for r in database.get_diagnostic_reports() if r.get("report_id") == test_rep_id]
        self.assertEqual(len(reports_after_resend), 1, "Duplicate report created on resend!")

        # 3. Security error: attempt delivery to wrong/mismatched patient ID
        mismatch_payload = json.dumps({
            "report_id": test_rep_id,
            "patient_id": "P-99999-WRONG",
            "is_resend": False
        }).encode("utf-8")
        req3 = urllib.request.Request(
            f"{BASE_URL}/api/reports/{test_rep_id}/deliver",
            data=mismatch_payload,
            headers={"Content-Type": "application/json"}
        )
        try:
            urllib.request.urlopen(req3)
            self.fail("Expected HTTP 400 for mismatched patient delivery")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
            err_data = json.loads(e.read().decode())
            self.assertFalse(err_data.get("success"))
            self.assertEqual(err_data.get("delivery_status"), "failed")
            self.assertIn("Security error", err_data.get("error"))

        # 4. Check delivery audit history
        hist_req = urllib.request.urlopen(f"{BASE_URL}/api/reports/{test_rep_id}/delivery-history")
        self.assertEqual(hist_req.status, 200)
        hist_data = json.loads(hist_req.read().decode())
        self.assertTrue(hist_data.get("success"))
        self.assertGreaterEqual(hist_data.get("total"), 3)

    def test_overquota_inbox_failure_stops_automatic_resends(self):
        """Verifies that an over-quota inbox (patient@gmail.com) fails cleanly with status 'failed', exact message, and no auto-retry."""
        import time
        prod_rep_id = f"RPT-20261022-{int(time.time()) % 10000:04d}"
        res_create = database.create_diagnostic_report({
            "report_id": prod_rep_id,
            "patient_id": "4001",
            "patient_name": "Patient User",
            "doctor_name": "Dr. Admin Doctor",
            "scan_type": "Renal Ultrasound",
            "delivery_status": "pending"
        })
        self.assertTrue(res_create.get("success"))

        deliver_payload = json.dumps({
            "report_id": prod_rep_id,
            "patient_id": "4001",
            "is_resend": False
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{BASE_URL}/api/reports/{prod_rep_id}/deliver",
            data=deliver_payload,
            headers={"Content-Type": "application/json"}
        )
        expected_msg = "Email delivery failed because the patient's inbox is full. Please free up mailbox space or update the patient's email address before retrying."
        try:
            urllib.request.urlopen(req)
            self.fail("Expected delivery failure for over-quota inbox patient@gmail.com")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
            err_data = json.loads(e.read().decode())
            self.assertFalse(err_data.get("success"))
            self.assertEqual(err_data.get("delivery_status"), "failed")
            self.assertEqual(err_data.get("error"), expected_msg)

        # Verify delivery status recorded in database as failed
        rep = database.get_diagnostic_report_by_id(prod_rep_id)
        self.assertEqual(rep.get("delivery_status"), "failed")
        self.assertEqual(rep.get("last_delivery_error", ""), expected_msg)

    def test_patient_email_update_and_manual_retry(self):
        """Verifies patient email update workflow and successful manual retry after updating address."""
        import time
        prod_rep_id = f"RPT-20261022-{int(time.time() * 10) % 10000:04d}"
        res_create = database.create_diagnostic_report({
            "report_id": prod_rep_id,
            "patient_id": "4001",
            "patient_name": "Patient User",
            "doctor_name": "Dr. Admin Doctor",
            "scan_type": "Thyroid Ultrasound",
            "findings": "Normal bilateral thyroid lobes.",
            "recommendations": "No further workup required.",
            "delivery_status": "pending"
        })
        self.assertTrue(res_create.get("success"))

        # 1. First attempt fails due to over-quota inbox
        deliver_payload = json.dumps({
            "report_id": prod_rep_id,
            "patient_id": "4001",
            "is_resend": False
        }).encode("utf-8")
        req1 = urllib.request.Request(
            f"{BASE_URL}/api/reports/{prod_rep_id}/deliver",
            data=deliver_payload,
            headers={"Content-Type": "application/json"}
        )
        try:
            urllib.request.urlopen(req1)
            self.fail("Expected delivery failure for initial attempt")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
            err1 = json.loads(e.read().decode())
            self.assertEqual(err1.get("delivery_status"), "failed")

        # 2. Update patient email to valid alternate address via API
        new_email = f"patient.updated.{int(time.time())}@torus.med"
        update_payload = json.dumps({
            "email": new_email,
            "patient_id": "4001"
        }).encode("utf-8")
        req_update = urllib.request.Request(
            f"{BASE_URL}/api/patients/4001/update-email",
            data=update_payload,
            headers={"Content-Type": "application/json"}
        )
        res_update = urllib.request.urlopen(req_update)
        self.assertEqual(res_update.status, 200)
        update_data = json.loads(res_update.read().decode())
        self.assertTrue(update_data.get("success"))
        self.assertEqual(update_data.get("email"), new_email)

        # 3. Manual retry succeeds with the updated email (preserving report ID and data)
        # Note: in test mock/sandbox mode, new_email delivers cleanly
        os.environ["TORUS_TEST_MODE"] = "1"
        try:
            req_retry = urllib.request.Request(
                f"{BASE_URL}/api/reports/{prod_rep_id}/deliver",
                data=deliver_payload,
                headers={"Content-Type": "application/json"}
            )
            res_retry = urllib.request.urlopen(req_retry)
            self.assertEqual(res_retry.status, 200)
            retry_data = json.loads(res_retry.read().decode())
            self.assertTrue(retry_data.get("success"))
            self.assertEqual(retry_data.get("delivery_status"), "sent")
            self.assertEqual(retry_data.get("report_id"), prod_rep_id)
            self.assertEqual(retry_data.get("patient_id"), "4001")
        finally:
            os.environ.pop("TORUS_TEST_MODE", None)

        # 4. Confirm report integrity: Report ID, findings, recommendations unchanged
        final_rep = database.get_diagnostic_report_by_id(prod_rep_id)
        self.assertEqual(final_rep.get("report_id"), prod_rep_id)
        self.assertEqual(final_rep.get("delivery_status"), "sent")
        self.assertEqual(final_rep.get("findings"), "Normal bilateral thyroid lobes.")
        self.assertEqual(final_rep.get("recommendations"), "No further workup required.")

        # Revert patient 4001 email back to patient@gmail.com for other tests
        database.update_patient_email("4001", "patient@gmail.com")

if __name__ == "__main__":
    unittest.main()
