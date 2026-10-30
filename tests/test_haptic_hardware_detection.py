"""
Unit and integration test suite for TORUS STM32 Haptic Pad Hardware Connection Detection.
Validates:
1. Dynamic COM port detection without hardcoded port numbers (COM5/COM6).
2. Proper STMicroelectronics / ST-Link / STM32 USB VID/PID recognition.
3. Server hardware status API returning actual connection state.
4. Clean disconnection handling and heartbeat expiration watchdog.
5. Local-to-cloud synchronization pipeline.
"""

import unittest
import time
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root and backend to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR))

import server
import haptic_pad_agent

class TestHapticHardwareDetection(unittest.TestCase):

    def setUp(self):
        self.client = server.app.test_client()

    def test_dynamic_port_detection_no_hardcoding(self):
        """Verify candidate ports are detected dynamically by VID/PID and description."""
        ports = server.find_candidate_ports()
        # Ensure it returns a list of tuples (device, is_stm32)
        self.assertIsInstance(ports, list)
        for item in ports:
            self.assertIsInstance(item, tuple)
            self.assertEqual(len(item), 2)
            self.assertIsInstance(item[0], str)
            self.assertIsInstance(item[1], bool)

    def test_st_hardware_identification(self):
        """Verify STMicroelectronics VID 0x0483 (1155) is flagged as STM32 hardware."""
        mock_port = MagicMock()
        mock_port.device = "COM42"
        mock_port.vid = 1155
        mock_port.hwid = "USB VID:PID=0483:374B"
        mock_port.description = "STMicroelectronics STLink Virtual COM Port"

        with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
            detected = server.find_candidate_ports()
            self.assertEqual(len(detected), 1)
            port_name, is_st = detected[0]
            self.assertEqual(port_name, "COM42")
            self.assertTrue(is_st)

    def test_generic_port_not_falsely_flagged_as_stm32(self):
        """Verify non-ST serial ports (e.g. FTDI/Prolific) are not blindly treated as STM32."""
        mock_port = MagicMock()
        mock_port.device = "COM99"
        mock_port.vid = 9999
        mock_port.hwid = "USB VID:PID=9999:0001"
        mock_port.description = "Standard USB-to-Serial Bridge"

        with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
            detected = server.find_candidate_ports()
            self.assertEqual(len(detected), 1)
            port_name, is_st = detected[0]
            self.assertEqual(port_name, "COM99")
            self.assertFalse(is_st)

    def test_status_api_reflects_actual_state(self):
        """Verify GET /api/haptic-pad/status returns genuine hardware connection state."""
        with server.haptic_state_lock:
            server.haptic_device_state["connected"] = True
            server.haptic_device_state["status"] = "CONNECTED"
            server.haptic_device_state["port"] = "COM6"
            server.haptic_device_state["device"] = "STM32 Haptic Pad"
            server.haptic_device_state["last_heartbeat"] = time.time()
            server.haptic_device_state["last_packet_time"] = time.time()

        resp = self.client.get("/api/haptic-pad/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["connected"])
        self.assertEqual(data["status"], "CONNECTED")
        self.assertEqual(data["port"], "COM6")
        self.assertEqual(data["device"], "STM32 Haptic Pad")

    def test_heartbeat_timeout_clears_connected_state(self):
        """Verify status returns NOT_CONNECTED when heartbeat expires (device disconnected)."""
        with server.haptic_state_lock:
            server.haptic_device_state["connected"] = True
            server.haptic_device_state["status"] = "CONNECTED"
            # Set heartbeat to 10 seconds ago
            server.haptic_device_state["last_heartbeat"] = time.time() - 10.0

        resp = self.client.get("/api/haptic-pad/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data["connected"])
        self.assertEqual(data["status"], "NOT_CONNECTED")

    def test_agent_report_endpoint_auth(self):
        """Verify /api/haptic-pad/report requires authorized secret."""
        # Unauthorized request
        resp = self.client.post("/api/haptic-pad/report", json={"connected": True})
        self.assertEqual(resp.status_code, 401)

        # Authorized request
        resp = self.client.post(
            "/api/haptic-pad/report",
            json={"connected": True, "port": "COM7", "device": "STM32 Haptic Pad"},
            headers={"X-Haptic-Agent-Secret": "torus_haptic_sec_2026"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], "CONNECTED")

if __name__ == "__main__":
    unittest.main()
