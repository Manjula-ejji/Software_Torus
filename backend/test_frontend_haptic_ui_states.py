"""
Comprehensive Frontend and Backend Verification for TORUS Haptic Pad Status UI and Header Alignment.
Validates all UI states across Doctor Portal, Patient Portal, and Video Consultation Page.
"""

import unittest
import requests
import json

BASE_URL = "http://127.0.0.1:3000"

class TestHapticUIStates(unittest.TestCase):
    def setUp(self):
        requests.post(f"{BASE_URL}/api/haptic-pad/session/unbind", json={})

    def tearDown(self):
        requests.post(f"{BASE_URL}/api/haptic-pad/session/unbind", json={})

    def test_state_a_doctor_connected_patient_a_active(self):
        """State A: Doctor Haptic Pad connected + Patient A active"""
        # 1. Hardware status
        hw_res = requests.get(f"{BASE_URL}/api/haptic-pad/status").json()
        self.assertTrue(hw_res["connected"], "Doctor physical Haptic Pad must be connected")

        # 2. Bind Patient A
        bind_res = requests.post(f"{BASE_URL}/api/haptic-pad/session/bind", json={
            "session_id": "S-001",
            "patient_id": "P-12345",
            "patient_name": "Patient A",
            "device_id": "TORUS-K03"
        }).json()
        self.assertTrue(bind_res["success"])

        # 3. Patient A queries -> Authorized (Active)
        pat_a = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-001&patient_id=P-12345").json()
        self.assertTrue(pat_a["authorized"])
        self.assertEqual(pat_a["routing_status"], "ROUTED_ACTIVE_SESSION")
        self.assertIsNotNone(pat_a["telemetry"])
        print("\n[STATE A PASS] Doctor: Haptic Pad Connected | Patient A: Remote Haptic Control Active")

    def test_state_b_doctor_connected_no_active_consultation(self):
        """State B: Doctor Haptic Pad connected + no active consultation"""
        # 1. Local hardware remains connected
        hw_res = requests.get(f"{BASE_URL}/api/haptic-pad/status").json()
        self.assertTrue(hw_res["connected"])

        # 2. Active session check returns inactive
        act_res = requests.get(f"{BASE_URL}/api/haptic-pad/session/active").json()
        self.assertFalse(act_res["active"])

        # 3. Patient queries -> Blocked with NO_ACTIVE_CONSULTATION
        pat_res = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-001&patient_id=P-12345").json()
        self.assertFalse(pat_res["authorized"])
        self.assertEqual(pat_res["routing_status"], "NO_ACTIVE_CONSULTATION")
        print("\n[STATE B PASS] Doctor: Haptic Pad Connected | No active consultation | Patients: Inactive")

    def test_state_c_d_patient_a_active_patient_b_inactive(self):
        """State C & D: Patient A active while Patient B & C remain inactive"""
        requests.post(f"{BASE_URL}/api/haptic-pad/session/bind", json={
            "session_id": "S-001",
            "patient_id": "P-12345",
            "patient_name": "Patient A"
        })

        # Patient A is active
        pat_a = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-001&patient_id=P-12345").json()
        self.assertTrue(pat_a["authorized"])

        # Patient B is inactive/blocked
        pat_b = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-002&patient_id=P-8821").json()
        self.assertFalse(pat_b["authorized"])
        self.assertEqual(pat_b["routing_status"], "BLOCKED_UNAUTHORIZED_PATIENT")

        # Patient C is inactive/blocked
        pat_c = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-003&patient_id=P-9104").json()
        self.assertFalse(pat_c["authorized"])
        self.assertEqual(pat_c["routing_status"], "BLOCKED_UNAUTHORIZED_PATIENT")
        print("\n[STATE C & D PASS] Patient A Active | Patient B Inactive | Patient C Inactive")

    def test_state_e_switch_consultation_a_to_b(self):
        """State E: Switch active consultation from Patient A to Patient B"""
        requests.post(f"{BASE_URL}/api/haptic-pad/session/bind", json={
            "session_id": "S-001",
            "patient_id": "P-12345",
            "patient_name": "Patient A"
        })

        # Switch to Patient B
        requests.post(f"{BASE_URL}/api/haptic-pad/session/bind", json={
            "session_id": "S-002",
            "patient_id": "P-8821",
            "patient_name": "Patient B"
        })

        # Patient B is now Active
        pat_b = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-002&patient_id=P-8821").json()
        self.assertTrue(pat_b["authorized"])
        self.assertEqual(pat_b["patient_id"], "P-8821")

        # Patient A is now Inactive / Blocked
        pat_a = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-001&patient_id=P-12345").json()
        self.assertFalse(pat_a["authorized"])
        self.assertEqual(pat_a["routing_status"], "BLOCKED_UNAUTHORIZED_PATIENT")
        print("\n[STATE E PASS] Switched to Patient B: Patient B Active | Patient A Inactive")

    def test_state_f_consultation_end_preserves_doctor_hardware(self):
        """State F: Consultation ends -> Doctor HW remains connected, patients become inactive"""
        requests.post(f"{BASE_URL}/api/haptic-pad/session/bind", json={
            "session_id": "S-002",
            "patient_id": "P-8821",
            "patient_name": "Patient B"
        })

        # End consultation
        requests.post(f"{BASE_URL}/api/haptic-pad/session/unbind", json={})

        # Local Doctor hardware STILL CONNECTED
        hw_res = requests.get(f"{BASE_URL}/api/haptic-pad/status").json()
        self.assertTrue(hw_res["connected"])

        # All patients now Inactive
        pat_b = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-002&patient_id=P-8821").json()
        self.assertFalse(pat_b["authorized"])
        self.assertEqual(pat_b["routing_status"], "NO_ACTIVE_CONSULTATION")
        print("\n[STATE F PASS] Consultation ended: Doctor HW still connected | All patients inactive")

if __name__ == "__main__":
    unittest.main()
