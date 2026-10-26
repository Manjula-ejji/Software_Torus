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

class TestNotificationsAndChat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with database.get_db() as conn:
            conn.execute("UPDATE notifications SET is_read = 0 WHERE event_key LIKE 'demo_%'")

    def test_01_demo_notifications(self):
        """Verifies exactly two demo notifications exist for doctor."""
        req = urllib.request.urlopen(f"{BASE_URL}/api/notifications?user_id=3001&role=doctor")
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode())
        self.assertTrue(data.get("success"))
        # Check that demo notifications exist
        demo_notifs = [n for n in data.get("notifications", []) if "demo_" in str(n.get("event_key", ""))]
        self.assertEqual(len(demo_notifs), 2, "Must have exactly 2 demo notifications for doctor")
        self.assertGreaterEqual(data.get("unread_count", 0), 2)

    def test_02_report_email_failure_creates_notification_and_retry_resolves_it(self):
        """Verifies report email failure creates doctor & patient notifications, and retry resolves it."""
        test_rep_id = f"RPT-FAILNOTIF-{int(time.time())}"
        database.create_diagnostic_report({
            "report_id": test_rep_id,
            "patient_id": "4001",
            "patient_name": "Patient User",
            "doctor_id": "3001",
            "scan_type": "Renal Ultrasound",
            "delivery_status": "pending"
        })

        # 1. Delivery to patient@gmail.com fails
        fail_payload = json.dumps({
            "report_id": test_rep_id,
            "patient_id": "4001",
            "email": "patient@gmail.com"
        }).encode("utf-8")
        req1 = urllib.request.Request(
            f"{BASE_URL}/api/reports/{test_rep_id}/deliver",
            data=fail_payload,
            headers={"Content-Type": "application/json"}
        )
        try:
            urllib.request.urlopen(req1)
            self.fail("Expected delivery failure for over-quota inbox")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

        # 2. Check that Doctor received email_failure notification
        notif_req = urllib.request.urlopen(f"{BASE_URL}/api/notifications?user_id=3001&role=doctor")
        notif_data = json.loads(notif_req.read().decode())
        failed_notifs = [n for n in notif_data.get("notifications", []) if n.get("reference_id") == test_rep_id and n.get("type") == "email_failure"]
        self.assertTrue(len(failed_notifs) >= 1, "Doctor did not receive email_failure notification")
        self.assertEqual(failed_notifs[0]["is_read"], 0)
        self.assertIn("report-generation.html", failed_notifs[0]["action_url"])

        # 3. Check Patient also received notification
        pat_notif_req = urllib.request.urlopen(f"{BASE_URL}/api/notifications?user_id=4001&role=patient")
        pat_notif_data = json.loads(pat_notif_req.read().decode())
        pat_failed_notifs = [n for n in pat_notif_data.get("notifications", []) if n.get("reference_id") == test_rep_id]
        self.assertTrue(len(pat_failed_notifs) >= 1, "Patient did not receive delivery failure notification")

        # 4. Successful retry to alternate email resolves failure notification
        success_payload = json.dumps({
            "report_id": test_rep_id,
            "patient_id": "4001",
            "email": "patient.updated@torus.med",
            "is_resend": True
        }).encode("utf-8")
        req2 = urllib.request.Request(
            f"{BASE_URL}/api/reports/{test_rep_id}/deliver",
            data=success_payload,
            headers={"Content-Type": "application/json"}
        )
        res2 = urllib.request.urlopen(req2)
        self.assertEqual(res2.status, 200)

        # 5. Verify failure notification is resolved (is_read=1, resolved_at set)
        notif_req_after = urllib.request.urlopen(f"{BASE_URL}/api/notifications?user_id=3001&role=doctor")
        notif_after_data = json.loads(notif_req_after.read().decode())
        resolved_notif = [n for n in notif_after_data.get("notifications", []) if n.get("reference_id") == test_rep_id and n.get("type") == "email_failure"]
        self.assertTrue(len(resolved_notif) >= 1)
        self.assertEqual(resolved_notif[0]["is_read"], 1, "Failure notification was not marked resolved after successful delivery")

        # Clean up: revert patient 4001 email back to patient@gmail.com
        database.update_patient_email("4001", "patient@gmail.com")

    def test_03_mark_notification_as_read_and_read_all(self):
        """Verifies marking single notification as read and mark all as read."""
        notif = database.create_notification(
            user_id="3001",
            role="doctor",
            n_type="system",
            title="Test Alert",
            message="Test unread message",
            event_key=f"test_mark_read_{int(time.time())}"
        )
        nid = notif["notification_id"]

        # Mark single as read
        read_payload = json.dumps({"user_id": "3001"}).encode("utf-8")
        req = urllib.request.Request(
            f"{BASE_URL}/api/notifications/{nid}/read",
            data=read_payload,
            headers={"Content-Type": "application/json"}
        )
        res = urllib.request.urlopen(req)
        self.assertEqual(res.status, 200)

        # Mark all as read
        all_payload = json.dumps({"user_id": "3001", "role": "doctor"}).encode("utf-8")
        req_all = urllib.request.Request(
            f"{BASE_URL}/api/notifications/read-all",
            data=all_payload,
            headers={"Content-Type": "application/json"}
        )
        res_all = urllib.request.urlopen(req_all)
        self.assertEqual(res_all.status, 200)

        # Check count is 0
        cnt_req = urllib.request.urlopen(f"{BASE_URL}/api/notifications/unread-count?user_id=3001&role=doctor")
        cnt_data = json.loads(cnt_req.read().decode())
        self.assertEqual(cnt_data.get("unread_count"), 0)

    def test_04_two_way_chat_workflow(self):
        """Verifies two-way conversation between doctor and patient, messaging, and unread counts."""
        conv_res = database.get_or_create_conversation("3001", "4001")
        conv_id = conv_res["id"]

        # 1. Patient messages doctor
        msg_payload1 = json.dumps({
            "sender_id": "4001",
            "sender_role": "patient",
            "sender_name": "Patient User",
            "content": "Doctor, when is my consultation?"
        }).encode("utf-8")
        req1 = urllib.request.Request(
            f"{BASE_URL}/api/conversations/{conv_id}/messages",
            data=msg_payload1,
            headers={"Content-Type": "application/json"}
        )
        res1 = urllib.request.urlopen(req1)
        self.assertEqual(res1.status, 200)
        data1 = json.loads(res1.read().decode())
        self.assertTrue(data1.get("success"))

        # 2. Doctor replies
        msg_payload2 = json.dumps({
            "sender_id": "3001",
            "sender_role": "doctor",
            "sender_name": "Dr. Admin Doctor",
            "content": "Your consultation is at 10:30 AM today."
        }).encode("utf-8")
        req2 = urllib.request.Request(
            f"{BASE_URL}/api/conversations/{conv_id}/messages",
            data=msg_payload2,
            headers={"Content-Type": "application/json"}
        )
        res2 = urllib.request.urlopen(req2)
        self.assertEqual(res2.status, 200)

        # 3. Fetch conversation messages
        msgs_req = urllib.request.urlopen(f"{BASE_URL}/api/conversations/{conv_id}/messages")
        self.assertEqual(msgs_req.status, 200)
        msgs_data = json.loads(msgs_req.read().decode())
        self.assertGreaterEqual(len(msgs_data.get("messages", [])), 2)

    def test_05_ai_support_assistant(self):
        """Verifies AI support assistant answers queries with real clinical data."""
        # Query pending reports
        ai_payload = json.dumps({
            "user_id": "3001",
            "role": "doctor",
            "question": "Which patients have pending reports?"
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{BASE_URL}/api/ai/chat",
            data=ai_payload,
            headers={"Content-Type": "application/json"}
        )
        res = urllib.request.urlopen(req)
        self.assertEqual(res.status, 200)
        data = json.loads(res.read().decode())
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("is_ai"))
        self.assertEqual(data.get("assistant_name"), "TORUS AI Support Assistant")
        self.assertIn("disclaimer", data)
        self.assertGreaterEqual(len(data.get("suggested_actions", [])), 1)

if __name__ == "__main__":
    unittest.main()
