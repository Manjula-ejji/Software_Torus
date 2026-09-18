"""
Test Suite for TORUS Physical Haptic Pad Session-Based Routing.
Verifies that real STM32 Haptic Pad telemetry is routed strictly to the Doctor's active consultation session.
"""

import unittest
import requests
import time

BASE_URL = "http://127.0.0.1:3000"

class TestHapticSessionRouting(unittest.TestCase):
    def setUp(self):
        # Ensure clean state before tests
        requests.post(f"{BASE_URL}/api/haptic-pad/session/unbind", json={})

    def tearDown(self):
        # Clean unbind
        requests.post(f"{BASE_URL}/api/haptic-pad/session/unbind", json={})

    def test_01_real_haptic_pad_hardware_status(self):
        """Verify real STM32 Haptic Pad status endpoint"""
        res = requests.get(f"{BASE_URL}/api/haptic-pad/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        print(f"\n[TEST 1] Haptic Pad Hardware Status: Connected={data.get('connected')}, Device={data.get('device')}, Port={data.get('port')}, PacketsRx={data.get('packets_rx')}")
        if data.get("connected"):
            print(f"[TEST 1] Real Telemetry Sample: {data.get('telemetry')}")

    def test_02_blocked_when_no_active_consultation(self):
        """When no doctor consultation is active, all patient requests must receive NO_ACTIVE_CONSULTATION and null telemetry"""
        res_a = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-001&patient_id=P-12345")
        self.assertEqual(res_a.status_code, 200)
        data_a = res_a.json()
        self.assertFalse(data_a.get("authorized"))
        self.assertEqual(data_a.get("routing_status"), "NO_ACTIVE_CONSULTATION")
        self.assertIsNone(data_a.get("telemetry"))
        print(f"\n[TEST 2] Unbound Session Request correctly blocked: {data_a.get('routing_status')}")

    def test_03_patient_a_consultation_routing_and_isolation(self):
        """
        When doctor starts consultation with Patient A (S-001 / P-12345):
        - Patient A receives real telemetry
        - Patient B (P-8821) receives BLOCKED and null telemetry
        - Patient C (P-9104) receives BLOCKED and null telemetry
        """
        # 1. Doctor binds to Patient A session
        bind_res = requests.post(f"{BASE_URL}/api/haptic-pad/session/bind", json={
            "session_id": "S-001",
            "session_code": "TORUS-CLI-P-12345",
            "doctor_id": "3001",
            "doctor_name": "Admin Doctor",
            "patient_id": "P-12345",
            "patient_name": "Patient A",
            "device_id": "TORUS-A12"
        })
        self.assertEqual(bind_res.status_code, 200)
        self.assertTrue(bind_res.json().get("success"))

        # 2. Query Patient A telemetry (Active Session)
        pat_a_res = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-001&patient_id=P-12345")
        self.assertEqual(pat_a_res.status_code, 200)
        data_a = pat_a_res.json()
        self.assertTrue(data_a.get("authorized"))
        self.assertEqual(data_a.get("routing_status"), "ROUTED_ACTIVE_SESSION")
        self.assertEqual(data_a.get("patient_id"), "P-12345")
        self.assertEqual(data_a.get("session_id"), "S-001")
        print(f"\n[TEST 3] Patient A (Authorized) Telemetry Received: {data_a.get('telemetry')}")

        # 3. Query Patient B telemetry (Inactive Session / Unauthorized)
        pat_b_res = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-002&patient_id=P-8821")
        self.assertEqual(pat_b_res.status_code, 200)
        data_b = pat_b_res.json()
        self.assertFalse(data_b.get("authorized"))
        self.assertEqual(data_b.get("routing_status"), "BLOCKED_UNAUTHORIZED_PATIENT")
        self.assertIsNone(data_b.get("telemetry"))
        print(f"[TEST 3] Patient B (Unauthorized) Signal Blocked: {data_b.get('routing_status')}")

        # 4. Query Patient C telemetry (Inactive Session / Unauthorized)
        pat_c_res = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-003&patient_id=P-9104")
        self.assertEqual(pat_c_res.status_code, 200)
        data_c = pat_c_res.json()
        self.assertFalse(data_c.get("authorized"))
        self.assertEqual(data_c.get("routing_status"), "BLOCKED_UNAUTHORIZED_PATIENT")
        self.assertIsNone(data_c.get("telemetry"))
        print(f"[TEST 3] Patient C (Unauthorized) Signal Blocked: {data_c.get('routing_status')}")

    def test_04_dynamic_consultation_switch_patient_a_to_b(self):
        """
        When doctor switches consultation from Patient A to Patient B:
        - Patient B immediately starts receiving real telemetry
        - Patient A immediately becomes blocked and receives null telemetry
        """
        # 1. Doctor is with Patient A
        requests.post(f"{BASE_URL}/api/haptic-pad/session/bind", json={
            "session_id": "S-001",
            "patient_id": "P-12345",
            "patient_name": "Patient A",
            "device_id": "TORUS-A12"
        })

        # 2. Doctor switches to Patient B (S-002 / P-8821 / John Doe)
        switch_res = requests.post(f"{BASE_URL}/api/haptic-pad/session/bind", json={
            "session_id": "S-002",
            "patient_id": "P-8821",
            "patient_name": "John Doe",
            "device_id": "TORUS-A12"
        })
        self.assertEqual(switch_res.status_code, 200)
        self.assertTrue(switch_res.json().get("success"))

        # 3. Patient B now queries -> Authorized!
        pat_b_res = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-002&patient_id=P-8821")
        self.assertEqual(pat_b_res.status_code, 200)
        data_b = pat_b_res.json()
        self.assertTrue(data_b.get("authorized"))
        self.assertEqual(data_b.get("routing_status"), "ROUTED_ACTIVE_SESSION")
        self.assertEqual(data_b.get("patient_id"), "P-8821")
        print(f"\n[TEST 4] After Switch: Patient B Telemetry Received: {data_b.get('telemetry')}")

        # 4. Patient A queries -> Now BLOCKED!
        pat_a_res = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-001&patient_id=P-12345")
        self.assertEqual(pat_a_res.status_code, 200)
        data_a = pat_a_res.json()
        self.assertFalse(data_a.get("authorized"))
        self.assertEqual(data_a.get("routing_status"), "BLOCKED_UNAUTHORIZED_PATIENT")
        self.assertIsNone(data_a.get("telemetry"))
        print(f"[TEST 4] After Switch: Patient A Signal Successfully Blocked: {data_a.get('routing_status')}")

    def test_05_consultation_ended_unbind_stops_all_signals(self):
        """When doctor leaves / ends consultation, unbind stops all signals for all patients"""
        requests.post(f"{BASE_URL}/api/haptic-pad/session/bind", json={
            "session_id": "S-002",
            "patient_id": "P-8821",
            "patient_name": "John Doe"
        })
        # End consultation
        unbind_res = requests.post(f"{BASE_URL}/api/haptic-pad/session/unbind", json={"session_id": "S-002"})
        self.assertEqual(unbind_res.status_code, 200)

        # Check Patient B
        res_b = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-002&patient_id=P-8821")
        data_b = res_b.json()
        self.assertFalse(data_b.get("authorized"))
        self.assertEqual(data_b.get("routing_status"), "NO_ACTIVE_CONSULTATION")
        self.assertIsNone(data_b.get("telemetry"))
        print(f"\n[TEST 5] Consultation End: All signals securely removed: {data_b.get('routing_status')}")

if __name__ == "__main__":
    unittest.main()
