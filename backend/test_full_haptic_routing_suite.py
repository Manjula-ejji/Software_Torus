"""
Comprehensive End-to-End Verification Test for TORUS Haptic Pad Session-Based Patient Routing.

Tests:
- Test A: Patient A receives real STM32 telemetry during consultation with Doctor.
- Test B: Unauthorized Patients (Patient B, Patient C) receive NOTHING (BLOCKED & null telemetry).
- Test C: Switch consultation from Patient A to Patient B -> Patient B receives telemetry, Patient A is immediately BLOCKED.
- Test D: End consultation -> All routing unbound, zero patients receive telemetry.
"""

import unittest
import requests
import time

BASE_URL = "http://127.0.0.1:3000"

class TestHapticSessionRoutingSuite(unittest.TestCase):
    def setUp(self):
        # Reset routing state to clean UNBOUND before each test
        requests.post(f"{BASE_URL}/api/haptic-pad/session/unbind", json={})

    def tearDown(self):
        # Always clean up routing state after each test
        requests.post(f"{BASE_URL}/api/haptic-pad/session/unbind", json={})

    def test_01_hardware_presence(self):
        """Verify real physical STM32 Haptic Pad on USB COM port"""
        res = requests.get(f"{BASE_URL}/api/haptic-pad/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        print(f"\n[HARDWARE] Status={data.get('status')}, Device={data.get('device')}, Port={data.get('port')}, PacketsRx={data.get('packets_rx')}")
        self.assertTrue(data.get("connected"), "Physical Haptic Pad must be connected")
        self.assertIsNotNone(data.get("telemetry"), "Physical Haptic Pad must provide real telemetry")

    def test_02_test_a_patient_a_receives_telemetry(self):
        """
        Test A — Patient A:
        Doctor + Haptic Pad -> Patient A consultation -> Patient A joins -> Telemetry delivered to Patient A
        """
        # Doctor starts/joins consultation with Patient A
        bind_res = requests.post(f"{BASE_URL}/api/haptic-pad/session/bind", json={
            "session_id": "S-001",
            "session_code": "TORUS-CLI-P12345",
            "doctor_id": "3001",
            "doctor_name": "Dr. Admin Doctor",
            "patient_id": "P-12345",
            "patient_name": "Patient A",
            "device_id": "TORUS-A12"
        })
        self.assertEqual(bind_res.status_code, 200)
        bind_data = bind_res.json()
        self.assertTrue(bind_data.get("success"))
        self.assertEqual(bind_data["routing"]["status"], "ACTIVE")
        self.assertEqual(bind_data["routing"]["patient_id"], "P-12345")

        # Patient A queries telemetry -> Authorized with live STM32 signals
        res_a = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-001&patient_id=P-12345")
        self.assertEqual(res_a.status_code, 200)
        data_a = res_a.json()
        self.assertTrue(data_a.get("authorized"))
        self.assertEqual(data_a.get("routing_status"), "ROUTED_ACTIVE_SESSION")
        self.assertEqual(data_a.get("patient_id"), "P-12345")
        self.assertIsNotNone(data_a.get("telemetry"))
        print(f"\n[TEST A PASS] Patient A successfully receiving real Haptic Pad telemetry: {data_a.get('telemetry')}")

    def test_03_test_b_unauthorized_patients_blocked(self):
        """
        Test B — Unauthorized Patient:
        Doctor is consulting Patient A.
        Patient B and Patient C are logged in.
        Patient B and C query telemetry -> MUST receive NOTHING (BLOCKED & null telemetry).
        """
        # Doctor in consultation with Patient A
        requests.post(f"{BASE_URL}/api/haptic-pad/session/bind", json={
            "session_id": "S-001",
            "doctor_id": "3001",
            "patient_id": "P-12345",
            "patient_name": "Patient A"
        })

        # Patient B tries to get telemetry
        res_b = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-002&patient_id=P-8821")
        self.assertEqual(res_b.status_code, 200)
        data_b = res_b.json()
        self.assertFalse(data_b.get("authorized"))
        self.assertEqual(data_b.get("routing_status"), "BLOCKED_UNAUTHORIZED_PATIENT")
        self.assertIsNone(data_b.get("telemetry"))
        print(f"\n[TEST B PASS] Patient B correctly blocked: {data_b.get('routing_status')}, Telemetry={data_b.get('telemetry')}")

        # Patient C tries to get telemetry
        res_c = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-003&patient_id=P-9104")
        self.assertEqual(res_c.status_code, 200)
        data_c = res_c.json()
        self.assertFalse(data_c.get("authorized"))
        self.assertEqual(data_c.get("routing_status"), "BLOCKED_UNAUTHORIZED_PATIENT")
        self.assertIsNone(data_c.get("telemetry"))
        print(f"[TEST B PASS] Patient C correctly blocked: {data_c.get('routing_status')}, Telemetry={data_c.get('telemetry')}")

    def test_04_test_c_switching_patients(self):
        """
        Test C — Switch:
        Patient A consultation ends -> Doctor starts Patient B consultation -> Patient B joins -> Haptic Pad -> Patient B ONLY.
        Patient A immediately stops receiving new signals.
        """
        # 1. Doctor starts Patient A consultation
        requests.post(f"{BASE_URL}/api/haptic-pad/session/bind", json={
            "session_id": "S-001",
            "patient_id": "P-12345",
            "patient_name": "Patient A"
        })

        # 2. Patient A consultation ends -> Doctor starts Patient B consultation
        switch_res = requests.post(f"{BASE_URL}/api/haptic-pad/session/bind", json={
            "session_id": "S-002",
            "patient_id": "P-8821",
            "patient_name": "Patient B",
            "device_id": "TORUS-C15"
        })
        self.assertEqual(switch_res.status_code, 200)
        self.assertTrue(switch_res.json().get("success"))

        # 3. Patient B queries -> ROUTED & Authorized
        res_b = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-002&patient_id=P-8821")
        self.assertEqual(res_b.status_code, 200)
        data_b = res_b.json()
        self.assertTrue(data_b.get("authorized"))
        self.assertEqual(data_b.get("routing_status"), "ROUTED_ACTIVE_SESSION")
        self.assertEqual(data_b.get("patient_id"), "P-8821")
        self.assertIsNotNone(data_b.get("telemetry"))
        print(f"\n[TEST C PASS] Switched to Patient B: Telemetry Received={data_b.get('telemetry')}")

        # 4. Patient A queries -> IMMEDIATELY BLOCKED
        res_a = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-001&patient_id=P-12345")
        self.assertEqual(res_a.status_code, 200)
        data_a = res_a.json()
        self.assertFalse(data_a.get("authorized"))
        self.assertEqual(data_a.get("routing_status"), "BLOCKED_UNAUTHORIZED_PATIENT")
        self.assertIsNone(data_a.get("telemetry"))
        print(f"[TEST C PASS] Patient A immediately blocked after switch: {data_a.get('routing_status')}")

    def test_05_test_d_end_session_unbound(self):
        """
        Test D — End Session:
        Consultation ends -> Haptic routing is unbound -> No patient receives Haptic Pad signals.
        """
        # Bind session
        requests.post(f"{BASE_URL}/api/haptic-pad/session/bind", json={
            "session_id": "S-002",
            "patient_id": "P-8821",
            "patient_name": "Patient B"
        })

        # End consultation (unbind)
        unbind_res = requests.post(f"{BASE_URL}/api/haptic-pad/session/unbind", json={"session_id": "S-002"})
        self.assertEqual(unbind_res.status_code, 200)
        self.assertTrue(unbind_res.json().get("success"))

        # Verify active session state is UNBOUND
        active_res = requests.get(f"{BASE_URL}/api/haptic-pad/session/active")
        self.assertEqual(active_res.status_code, 200)
        self.assertFalse(active_res.json().get("active"))

        # Patient B queries -> Blocked with NO_ACTIVE_CONSULTATION
        res_b = requests.get(f"{BASE_URL}/api/haptic-pad/patient/telemetry?session_id=S-002&patient_id=P-8821")
        self.assertEqual(res_b.status_code, 200)
        data_b = res_b.json()
        self.assertFalse(data_b.get("authorized"))
        self.assertEqual(data_b.get("routing_status"), "NO_ACTIVE_CONSULTATION")
        self.assertIsNone(data_b.get("telemetry"))
        print(f"\n[TEST D PASS] Session ended: Routing unbound. Telemetry blocked for all patients: {data_b.get('routing_status')}")

if __name__ == "__main__":
    unittest.main()
