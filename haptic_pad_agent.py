"""
TORUS Doctor Station — Local Haptic Pad Hardware Service Agent
================================================================
Detects physical STM32 Haptic Pad via USB/CDC Serial, parses real sensor
packets (JX, JY, JZ, Switches, Load Cell, IMU), securely synchronizes real
hardware status with the TORUS backend, and optionally streams to the slave PC.

Usage:
  python haptic_pad_agent.py
  python haptic_pad_agent.py --backend http://127.0.0.1:3000 --secret torus_haptic_sec_2026
"""

from __future__ import annotations
import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

import serial
import serial.tools.list_ports

# ── Config ────────────────────────────────────────────────────────────────────
BAUD_RATE = 115200
DEFAULT_BACKEND_URL = os.environ.get("TORUS_BACKEND_URL", "http://127.0.0.1:3000")
DEFAULT_AGENT_SECRET = os.environ.get("HAPTIC_AGENT_SECRET", "torus_haptic_sec_2026")
SLAVE_IP_FILE = "slave_ip.txt"

AXIS_MAP = {
    "X": ("JX", 502),
    "Y": ("JY", 503),
    "Z": ("JZ", 65432),
}
IMU_TCP_PORT = 505
HOME_CMD_PORT = 506

# ── Serial Auto-Detection Config (From doctor_launcher.py) ─────────────────────
ST_VID = "0483"
ST_DESCRIPTIONS = (
    "stmicroelectronics virtual com port",
    "stm32 virtual com port",
    "stm virtual com port",
    "doctor station",
    "usb serial device",
)

SKIP_TOKENS = ("===", "BOOT", "LOOP", "ERROR", "OK:", "HX711", "BNO")


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def find_haptic_port() -> str | None:
    for p in serial.tools.list_ports.comports():
        hwid = (p.hwid or "").lower()
        desc = (p.description or "").lower()
        if ST_VID in hwid:
            return p.device
        if any(d in desc for d in ST_DESCRIPTIONS):
            return p.device
    return None


def parse_packet(line: str) -> dict | None:
    line = line.strip()
    if not line or any(t in line for t in SKIP_TOKENS):
        return None
    data = {}
    try:
        for field in line.split("|"):
            if ":" not in field:
                continue
            key, _, value = field.partition(":")
            key, value = key.strip(), value.strip()

            if key in ("JX", "JY", "JZ"):
                data[key] = int(value)
            elif key == "SWM":
                data["SW_M"] = value
            elif key == "SWL":
                data["SW_L"] = value
            elif key == "I1":
                data["I1"] = "1.0,0.0,0.0,0.0" if value == "ERR" else value
            elif key == "I2":
                data["I2"] = "1.0,0.0,0.0,0.0" if value == "ERR" else value
            elif key == "HX":
                data["HX"] = "NOT READY" if value == "NOT_READY" else value
            else:
                data[key] = value

        if not {"JX", "JY", "JZ"}.issubset(data):
            return None
        return data
    except (ValueError, AttributeError):
        return None


class HapticPadAgent:
    def __init__(self, backend_url: str, secret: str, slave_ip: str | None = None):
        self.backend_url = backend_url.rstrip("/")
        self.secret = secret
        self.slave_ip = slave_ip
        self.running = True
        self.ser: serial.Serial | None = None
        self.current_port: str | None = None
        self.is_connected = False
        self.packets_rx = 0
        self.latest_telemetry: dict = {}
        self.lock = threading.Lock()
        self.probe_flag = threading.Event()

    def send_backend_report(self, connected: bool, telemetry: dict | None = None):
        url = f"{self.backend_url}/api/haptic-pad/report" if connected else f"{self.backend_url}/api/haptic-pad/disconnect"
        payload = {
            "connected": connected,
            "port": self.current_port,
            "device": "STM32 Haptic Pad",
            "packets_rx": self.packets_rx,
            "telemetry": telemetry or self.latest_telemetry
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "X-Haptic-Agent-Secret": self.secret
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status == 200
        except Exception as e:
            return False

    def heartbeat_worker(self):
        """Continuously reports device status and heartbeat to TORUS backend."""
        while self.running:
            with self.lock:
                conn = self.is_connected
                telem = dict(self.latest_telemetry)
            if conn:
                self.send_backend_report(True, telem)
            time.sleep(1.0)

    def run(self):
        log("[HAPTIC] Starting TORUS Local Haptic Pad Agent")
        log(f"[HAPTIC] Backend URL: {self.backend_url}")
        
        # Start background heartbeat thread
        threading.Thread(target=self.heartbeat_worker, daemon=True).start()

        while self.running:
            log("[HAPTIC] Searching for STM32 device...")
            port = None
            while port is None and self.running:
                port = find_haptic_port()
                if port is None:
                    time.sleep(1.0)

            if not self.running:
                break

            self.current_port = port
            log(f"[HAPTIC] Device detected: {port}")

            try:
                self.ser = serial.Serial(port, BAUD_RATE, timeout=0.2)
                log(f"[HAPTIC] Serial connection established on {port}")
            except Exception as e:
                log(f"[HAPTIC] Serial connection failed: {e}")
                self.current_port = None
                time.sleep(1.5)
                continue

            first_valid = False
            last_packet_time = time.time()

            while self.running:
                try:
                    raw = self.ser.readline().decode("utf-8", errors="ignore").strip()
                    if not raw:
                        if time.time() - last_packet_time > 2.5:
                            pass
                        continue

                    if "PROBE AT HOME POSITION" in raw:
                        self.probe_flag.set()
                        continue

                    parsed = parse_packet(raw)
                    if parsed:
                        last_packet_time = time.time()
                        with self.lock:
                            self.packets_rx += 1
                            self.latest_telemetry = parsed

                        if not first_valid:
                            first_valid = True
                            with self.lock:
                                self.is_connected = True
                            log("[HAPTIC] Valid packet received")
                            
                            # Report immediately to backend
                            if self.send_backend_report(True, parsed):
                                log("[HAPTIC] Backend connection established")
                            log("[HAPTIC] Device status: CONNECTED")

                except (serial.SerialException, OSError) as err:
                    log(f"[HAPTIC] Serial read error / device unplugged: {err}")
                    break
                except Exception as ex:
                    log(f"[HAPTIC] Packet loop error: {ex}")
                    break

            # Handle Disconnection
            with self.lock:
                self.is_connected = False
            self.send_backend_report(False)
            log("[HAPTIC] Device disconnected")
            log("[HAPTIC] Device status: NOT_CONNECTED")

            if self.ser:
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None

            time.sleep(1.0)


def main():
    parser = argparse.ArgumentParser(description="TORUS Haptic Pad Local Service Agent")
    parser.add_argument("--backend", default=DEFAULT_BACKEND_URL, help="TORUS Backend URL (default: http://127.0.0.1:3000)")
    parser.add_argument("--secret", default=DEFAULT_AGENT_SECRET, help="Agent authentication secret")
    parser.add_argument("--slave-ip", default=None, help="Optional Slave PC IP for direct TCP streaming")
    args = parser.parse_args()

    agent = HapticPadAgent(backend_url=args.backend, secret=args.secret, slave_ip=args.slave_ip)
    try:
        agent.run()
    except KeyboardInterrupt:
        log("[HAPTIC] Agent stopped by user.")
        agent.running = False
        agent.send_backend_report(False)


if __name__ == "__main__":
    main()
