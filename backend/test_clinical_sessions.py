"""
Automated Test Suite for TORUS Clinical Sessions Creation, Validation, and Multi-Role Join Flow
"""
import sys
import unittest
from pathlib import Path

# Add backend directory to sys.path
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

import database
import server

class TestClinicalSessionsSuite(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = server.app.test_client()

    def test_01_create_session_by_doctor(self):
        """Doctor creates a real clinical session with server-generated unique code."""
        res = self.client.post("/api/sessions/create", json={
            "doctor_uid": "3001",
            "doctor_name": "Admin Doctor",
            "doctor_email": "admin@gmail.com",
            "channel_name": "torus"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        session_code = data.get("session_code")
        self.assertTrue(session_code.startswith("TORUS-"))
        self.assertEqual(len(session_code), 12)  # TORUS- + 6 chars = 12 chars
        self.assertEqual(data.get("channel"), "torus")

        # Verify in DB
        session_db = database.get_clinical_session(session_code)
        self.assertIsNotNone(session_db)
        self.assertEqual(session_db["status"], "active")
        self.assertEqual(session_db["doctor_name"], "Admin Doctor")

    def test_02_join_empty_code_rejected(self):
        """Joining with empty code is rejected with descriptive error."""
        res = self.client.post("/api/sessions/join", json={
            "session_code": "",
            "participant_name": "Viewer 1",
            "role": "viewer"
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data.get("success"))
        self.assertIn("Please enter the session code", data.get("error"))

    def test_03_join_invalid_code_rejected(self):
        """Joining with non-existent session code is rejected."""
        res = self.client.post("/api/sessions/join", json={
            "session_code": "TORUS-NONEXISTENT99",
            "participant_name": "Viewer 1",
            "role": "viewer"
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data.get("success"))
        self.assertEqual(data.get("error"), "Invalid session code.")

    def test_04_patient_and_viewer_join_same_doctor_session(self):
        """Doctor creates session, then Patient and Viewer join the exact same session."""
        # 1. Doctor creates session
        create_res = self.client.post("/api/sessions/create", json={
            "doctor_uid": "3001",
            "doctor_name": "Admin Doctor",
            "doctor_email": "admin@gmail.com"
        })
        self.assertEqual(create_res.status_code, 200)
        doc_data = create_res.get_json()
        session_code = doc_data.get("session_code")

        # 2. Patient joins with that session code
        pat_res = self.client.post("/api/sessions/join", json={
            "session_code": session_code,
            "participant_name": "Patient User",
            "role": "patient",
            "participant_uid": "4001"
        })
        self.assertEqual(pat_res.status_code, 200)
        pat_data = pat_res.get_json()
        self.assertTrue(pat_data.get("success"))
        self.assertEqual(pat_data.get("session_code"), session_code)
        self.assertEqual(pat_data.get("participant")["role"], "patient")

        # 3. Viewer joins with that session code
        view_res = self.client.post("/api/sessions/join", json={
            "session_code": session_code,
            "participant_name": "Consultant Viewer",
            "role": "viewer",
            "participant_uid": "6001"
        })
        self.assertEqual(view_res.status_code, 200)
        view_data = view_res.get_json()
        self.assertTrue(view_data.get("success"))
        self.assertEqual(view_data.get("session_code"), session_code)
        self.assertEqual(view_data.get("participant")["role"], "viewer")

        # 4. Verify in DB that participants are linked to same session
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM session_participants WHERE session_code = ?", (session_code,))
        participants = cursor.fetchall()
        conn.close()

        # Doctor + Patient + Viewer = 3 participants in same session
        self.assertEqual(len(participants), 3)
        roles = [p["role"] for p in participants]
        self.assertIn("doctor", roles)
        self.assertIn("patient", roles)
        self.assertIn("viewer", roles)

    def test_05_closed_session_rejected(self):
        """Closed session cannot be joined."""
        # Create session
        create_res = self.client.post("/api/sessions/create", json={
            "doctor_uid": "3001",
            "doctor_name": "Admin Doctor"
        })
        session_code = create_res.get_json().get("session_code")

        # Close session
        close_res = self.client.post("/api/sessions/close", json={
            "session_code": session_code
        })
        self.assertEqual(close_res.status_code, 200)

        # Attempt to join
        join_res = self.client.post("/api/sessions/join", json={
            "session_code": session_code,
            "participant_name": "Late Viewer",
            "role": "viewer"
        })
        self.assertEqual(join_res.status_code, 400)
        self.assertEqual(join_res.get_json().get("error"), "Session is no longer active.")

    def test_06_no_hardcoded_session_accepted_unless_created(self):
        """Hardcoded legacy value like TORUS-2026-001 is rejected if not created."""
        res = self.client.post("/api/sessions/join", json={
            "session_code": "TORUS-2026-001",
            "participant_name": "Viewer",
            "role": "viewer"
        })
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("error"), "Invalid session code.")

if __name__ == "__main__":
    unittest.main(verbosity=2)
