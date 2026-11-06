import json
import unittest
from unittest.mock import patch, MagicMock
import backend.ultrasound as us


class TestLiveUpdatesOnlyDuringActiveAcquisition(unittest.TestCase):
    """
    Test suite for:
    ADDITIONAL CRITICAL REQUIREMENT - LIVE UPDATES ONLY DURING ACTIVE ACQUISITION
    Verifies that Voltage and Analog Gain controls work specifically and continuously
    while acquisition is actively RUNNING, without interruption, while preserving
    standby configuration separately when STOPPED without claiming live updates.
    """

    def setUp(self):
        us.app.config["TESTING"] = True
        self.app = us.app.test_client()

    def test_standby_configuration_when_stopped_does_not_claim_live_update(self):
        """
        When acquisition is STOPPED, do not claim that a live hardware update has occurred.
        Preserve the appropriate standby configuration separately.
        """
        orig_rt = us._global_ostb_runtime
        orig_acquiring = us._is_acquiring
        orig_stopped = us._is_user_stopped
        orig_frozen = us._is_frozen

        try:
            us._is_acquiring = False
            us._is_user_stopped = True
            us._is_frozen = False
            us._global_ostb_runtime = None

            # Verify initially STOPPED
            self.assertFalse(us.is_acquisition_running())
            st_init = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st_init["status"], "STOPPED")
            self.assertFalse(st_init["live_hardware_update"])

            # Change voltage while STOPPED
            res_v = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "voltage", "value": 31}),
                content_type="application/json"
            )
            self.assertEqual(res_v.status_code, 200)
            data_v = json.loads(res_v.data)

            # Strict rule: DO NOT claim live hardware update occurred when stopped!
            self.assertFalse(data_v["live_hardware_update"])
            self.assertFalse(data_v["verified"])
            self.assertEqual(data_v["mode"], "standby")
            self.assertEqual(data_v["standby_voltage"], 31.0)
            self.assertEqual(us._standby_voltage, 31.0)

            # Change gain while STOPPED
            res_g = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "gain", "value": 45}),
                content_type="application/json"
            )
            self.assertEqual(res_g.status_code, 200)
            data_g = json.loads(res_g.data)

            self.assertFalse(data_g["live_hardware_update"])
            self.assertFalse(data_g["verified"])
            self.assertEqual(data_g["mode"], "standby")
            self.assertEqual(data_g["standby_gain"], 45.0)
            self.assertEqual(us._standby_gain, 45.0)

            # Check status endpoint confirms standby preservation
            st = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st["status"], "STOPPED")
            self.assertFalse(st["live_hardware_update"])
            self.assertEqual(st["standby_voltage"], 31.0)
            self.assertEqual(st["standby_gain"], 45.0)

        finally:
            us._global_ostb_runtime = orig_rt
            us._is_acquiring = orig_acquiring
            us._is_user_stopped = orig_stopped
            us._is_frozen = orig_frozen

    def test_workflow_start_then_continuous_live_updates_without_interruption(self):
        """
        Expected workflow:
        1. Doctor clicks Start.
        2. Indore machine starts ultrasound acquisition (status: RUNNING).
        3. Once RUNNING, doctor changes Voltage to 31 -> applies immediately to hardware, acquisition remains RUNNING.
        4. Doctor changes Analog Gain to 45 dB -> applies immediately to hardware, acquisition remains RUNNING.
        5. Doctor can continuously adjust Voltage and Gain throughout running session without restarting or DMA interruption.
        """
        class MockIndoreHardwareRuntime:
            def __init__(self):
                self.configure_count = 0
                self.stop_count = 0
                self.start_count = 0
                self.configured_configs = []
                self._started = False

            def configure(self, cfg):
                self.configure_count += 1
                self.configured_configs.append(cfg)

            def start(self):
                self.start_count += 1
                self._started = True

            def stop(self):
                self.stop_count += 1
                self._started = False

        mock_hw = MockIndoreHardwareRuntime()
        orig_rt = us._global_ostb_runtime
        orig_cfg = us._global_ostb_config
        orig_acquiring = us._is_acquiring
        orig_stopped = us._is_user_stopped
        orig_frozen = us._is_frozen

        try:
            us._global_ostb_runtime = mock_hw
            us._global_ostb_config = object()
            us._is_acquiring = False
            us._is_user_stopped = True
            us._is_frozen = False

            # Set standby configuration before starting
            us._standby_voltage = 30.0
            us._standby_gain = 40.0

            # Step 1: Doctor clicks Start from Doctor Portal
            res_start = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "start", "value": True}),
                content_type="application/json"
            )
            self.assertEqual(res_start.status_code, 200)

            # Step 2: Indore machine starts actual ultrasound acquisition
            self.assertTrue(us.is_acquisition_running())
            self.assertEqual(mock_hw.start_count, 1)
            self.assertEqual(mock_hw.stop_count, 0)
            st_run = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st_run["status"], "RUNNING")
            self.assertTrue(st_run["live_hardware_update"])

            # Step 3: Once RUNNING, Doctor changes Voltage to 31
            res_v31 = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "voltage", "value": 31}),
                content_type="application/json"
            )
            self.assertEqual(res_v31.status_code, 200)
            data_v31 = json.loads(res_v31.data)

            # Hardware update verified live
            self.assertTrue(data_v31["live_hardware_update"])
            self.assertTrue(data_v31["verified"])
            self.assertEqual(data_v31["mode"], "live")
            self.assertEqual(data_v31["voltage"], 31.0)

            # Hardware reconfigured immediately without stopping or restarting
            self.assertEqual(mock_hw.configure_count, 2)  # 1 start + 1 voltage update
            self.assertEqual(mock_hw.stop_count, 0)       # MUST NOT STOP
            self.assertEqual(mock_hw.start_count, 1)      # MUST NOT RESTART

            # Acquisition status remains RUNNING
            self.assertTrue(us.is_acquisition_running())
            st_after_v = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st_after_v["status"], "RUNNING")
            self.assertEqual(st_after_v["voltage"], 31.0)

            # Step 4: Doctor changes Analog Gain to 45 dB
            res_g45 = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "gain", "value": 45}),
                content_type="application/json"
            )
            self.assertEqual(res_g45.status_code, 200)
            data_g45 = json.loads(res_g45.data)

            self.assertTrue(data_g45["live_hardware_update"])
            self.assertTrue(data_g45["verified"])
            self.assertEqual(data_g45["mode"], "live")
            self.assertEqual(data_g45["gain"], 45.0)

            self.assertEqual(mock_hw.configure_count, 3)  # 1 start + 1 volt + 1 gain
            self.assertEqual(mock_hw.stop_count, 0)       # Still 0!
            self.assertEqual(mock_hw.start_count, 1)      # Still 1!
            self.assertTrue(us.is_acquisition_running())

            st_after_g = json.loads(self.app.get("/api/status").data)
            self.assertEqual(st_after_g["status"], "RUNNING")
            self.assertEqual(st_after_g["gain"], 45.0)

            # Step 5: Continuous live adjustments throughout the running session
            continuous_updates = [
                ("voltage", 35, 35.0),
                ("gain", 52, 52.0),
                ("voltage", 40, 40.0),
                ("gain", 60, 60.0),
                ("voltage", 25, 25.0),
                ("gain", 38, 38.0),
            ]

            expected_config_count = 3
            for ctrl, val, expected in continuous_updates:
                res = self.app.post(
                    "/api/remote-input",
                    data=json.dumps({"control": ctrl, "value": val}),
                    content_type="application/json"
                )
                self.assertEqual(res.status_code, 200)
                d = json.loads(res.data)
                self.assertTrue(d["live_hardware_update"])
                self.assertTrue(d["verified"])
                self.assertEqual(d["mode"], "live")
                self.assertEqual(d[ctrl], expected)

                expected_config_count += 1
                self.assertEqual(mock_hw.configure_count, expected_config_count)
                # Acquisition MUST remain continuous without ANY stop or restart!
                self.assertEqual(mock_hw.stop_count, 0)
                self.assertEqual(mock_hw.start_count, 1)
                self.assertTrue(us.is_acquisition_running())

            # Verify final confirmed state
            final_status = json.loads(self.app.get("/api/status").data)
            self.assertEqual(final_status["status"], "RUNNING")
            self.assertEqual(final_status["voltage"], 25.0)
            self.assertEqual(final_status["gain"], 38.0)

        finally:
            us._global_ostb_runtime = orig_rt
            us._global_ostb_config = orig_cfg
            us._is_acquiring = orig_acquiring
            us._is_user_stopped = orig_stopped
            us._is_frozen = orig_frozen

    def test_dma_exception_does_not_interrupt_streaming(self):
        """
        Verify that if physical driver raises DMA constraint during live streaming,
        acquisition is not interrupted (never stop/started).
        """
        class MockDmaStreamingRuntime:
            def __init__(self):
                self.configure_count = 0
                self.stop_count = 0
                self.start_count = 0

            def configure(self, cfg):
                self.configure_count += 1
                raise RuntimeError("DMA RF frame grabber currently streaming")

            def stop(self):
                self.stop_count += 1

            def start(self):
                self.start_count += 1

        dma_rt = MockDmaStreamingRuntime()
        orig_rt = us._global_ostb_runtime
        orig_acquiring = us._is_acquiring

        try:
            us._global_ostb_runtime = dma_rt
            us._is_acquiring = True
            us._is_user_stopped = False
            us._is_frozen = False

            res = self.app.post(
                "/api/remote-input",
                data=json.dumps({"control": "voltage", "value": 31}),
                content_type="application/json"
            )
            self.assertEqual(res.status_code, 200)
            self.assertEqual(dma_rt.stop_count, 0)
            self.assertEqual(dma_rt.start_count, 0)
            self.assertTrue(us.is_acquisition_running())

        finally:
            us._global_ostb_runtime = orig_rt
            us._is_acquiring = orig_acquiring


if __name__ == "__main__":
    unittest.main()

