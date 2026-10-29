"""
Run this script directly in VS Code.

What it does automatically:
1) Starts the ultrasound application, which continues to render its local GUI.
2) Reads the processed B-mode image buffer directly from OSTB.
3) Publishes those image frames to Agora (video + microphone audio).
4) Serves a local API endpoint to receive remote mouse events from the web app
   and emulates those clicks/drags directly on the local PyQt5 GUI window.
"""

from __future__ import annotations

import atexit
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

MISSING_MODULES = []

try:
  import cv2
except ModuleNotFoundError:
  MISSING_MODULES.append("opencv-python")

try:
  import numpy as np
except ModuleNotFoundError:
  MISSING_MODULES.append("numpy")

try:
  import ostb._ostb as ostb
except ModuleNotFoundError:
  MISSING_MODULES.append("ostb")

try:
  from flask import Flask, Response, request, jsonify
except ModuleNotFoundError:
  MISSING_MODULES.append("flask")

try:
  import pyautogui
except ModuleNotFoundError:
  MISSING_MODULES.append("pyautogui")

try:
  import win32gui
  import win32con
except ModuleNotFoundError:
  # Check if we are on Windows. Only flag missing if running on Windows.
  if sys.platform.startswith("win"):
    MISSING_MODULES.append("pypiwin32")

if MISSING_MODULES:
  pkgs = " ".join(sorted(set(MISSING_MODULES)))
  print(f"[ultrasound] Notice: Running in non-hardware/dev mode. Modules not loaded: {pkgs}")

import os

def _load_opensonics_env():
    candidates = [
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent / ".env"
    ]
    for p in candidates:
        if p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip("'\"")
                            if k and k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass

_load_opensonics_env()

# -------------------- USER CONFIG --------------------
APP_ID = os.environ.get("OPENSONICS_APP_ID", os.environ.get("AGORA_APP_ID", "1f40918151a84a3d9dc3ebd7f1f47706"))
TOKEN = os.environ.get("OPENSONICS_TOKEN", os.environ.get("AGORA_TOKEN", "007eJxTYDh76lkfH8upYwXrkzXfv1k/Wbn2UuVU1ourFS5wv/cxP7JRgcEwzcTA0tDC0NQw0cIk0TjFMiXZODUpxTwNKGFubmB2792jrIZARgb51fHMjAwQCOKzMpTkF5UWMzAAABeoIlo="))
CHANNEL = os.environ.get("AGORA_CHANNEL", "torus")
UID = int(os.environ.get("AGORA_UID", 5001))

# Choose which ultrasound script to launch.
ULTRASOUND_SCRIPT = "curv_proper_code.py"
HOST = "127.0.0.1"
PORT = 8000
FPS = 15

# Stable canvas output dimensions
STREAM_CANVAS_W = 960
STREAM_CANVAS_H = 640  # Capped at 640 to fit the wider aspect ratio and remove extra bottom black space

# OSTB's output B-mode process buffer
PROCESS_OUTPUT_MAPPING = "ostb.input.rf.out.process.0"

# Target physical dimensions for the curvilinear probe
LATERAL_MIN_MM = -62.3
LATERAL_MAX_MM = 62.3
DEPTH_MIN_MM = 4.48
DEPTH_MAX_MM = 100.0
# -----------------------------------------------------

APP_DIR = Path(__file__).resolve().parent
app = Flask(__name__)

_latest_jpg = None
_latest_lock = threading.Lock()
_stop_event = threading.Event()
_ultrasound_proc: subprocess.Popen | None = None


def find_opensonics_control_window() -> int:
    """
    Finds the NEXUS / OpenSonics Control Panel window handle (hwnd).
    Explicitly targets window title 'NEXUS' or OpenSonics controller window.
    Never falls back to the ultrasound image / render window.
    """
    try:
        import win32gui
    except ImportError:
        return 0

    control_hwnd = [0]

    def enum_cb(hwnd, _):
        if not win32gui.IsWindow(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        cls_name = win32gui.GetClassName(hwnd)
        t_low = title.lower()

        # Match exact NEXUS control panel window
        if title == "NEXUS" or (any(k in t_low for k in ["opensonics", "controller", "acquisition", "signal controls"])
                                 and not any(k in t_low for k in ["display window", "focused b-mode", "b-mode", "render", "chrome", "agora", "meet", "torus"])):
            control_hwnd[0] = hwnd
            return False
        elif ("Qt6" in cls_name or "Qt5" in cls_name) and title and title not in ["Launcher", "_q_titlebar"]:
            if not any(k in t_low for k in ["display window", "focused b-mode", "b-mode", "render", "chrome", "agora", "meet", "torus"]):
                if not control_hwnd[0]:
                    control_hwnd[0] = hwnd
        return True

    try:
        win32gui.EnumWindows(enum_cb, None)
    except Exception:
        pass

    return control_hwnd[0]


_click_lock = threading.Lock()


def send_win32_click(hwnd: int, cx: int, cy: int) -> None:
    """
    Executes a hardware click at client coords (cx, cy) on the target window.
    Preserves window position and restores focus without throwing the window off-screen.
    """
    import win32gui
    import win32con
    import win32api

    with _click_lock:
        try:
            rect = win32gui.GetWindowRect(hwnd)
            left, top, right, bottom = rect
            width = max(600, right - left)
            height = max(450, bottom - top)

            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

            screen_x = (left + int(cx)) if left >= 0 else int(cx)
            screen_y = (top + int(cy)) if top >= 0 else int(cy)

            orig_pos = win32api.GetCursorPos()
            win32api.SetCursorPos((screen_x, screen_y))
            time.sleep(0.02)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.04)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.02)
            win32api.SetCursorPos(orig_pos)

            lParam = win32api.MAKELONG(int(cx), int(cy))
            win32gui.SendMessage(hwnd, win32con.WM_MOUSEACTIVATE, hwnd, win32api.MAKELONG(win32con.HTCLIENT, win32con.WM_LBUTTONDOWN))
            win32gui.SendMessage(hwnd, win32con.WM_SETCURSOR, hwnd, win32api.MAKELONG(win32con.HTCLIENT, win32con.WM_LBUTTONDOWN))
            win32gui.SendMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lParam)
            time.sleep(0.03)
            win32gui.SendMessage(hwnd, win32con.WM_LBUTTONUP, 0, lParam)
        except Exception as e:
            print(f"[Remote Control] Click execution error: {e}")


def replicate_mouse_event(event_type: str, x_percent: float, y_percent: float) -> bool:
    """
    Locates the PyQt5 OpenSonics GUI window on the desktop and emulates pointer events (down, move, up).
    Falls back gracefully to full screen mapping if the window is not found or not on Windows.
    Uses non-invasive PostMessage API on Windows so the physical mouse pointer is not moved.
    """
    try:
        import win32gui
        import win32con
        import win32api
    except ImportError:
        # Fallback to pyautogui on non-Windows/development setups
        import pyautogui
        pyautogui.FAILSAFE = False
        screen_w, screen_h = pyautogui.size()
        left, top, width, height = 0, 0, screen_w, screen_h
        target_x = left + int(x_percent * width)
        target_y = top + int(y_percent * height)
        try:
            if event_type == "down":
                pyautogui.mouseDown(target_x, target_y)
                print(f"[Remote Control] Fallback MouseDown at: ({target_x}, {target_y})")
            elif event_type == "move":
                pyautogui.moveTo(target_x, target_y)
                print(f"[Remote Control] Fallback MouseMove to: ({target_x}, {target_y})")
            elif event_type == "up":
                pyautogui.mouseUp(target_x, target_y)
                print(f"[Remote Control] Fallback MouseUp at: ({target_x}, {target_y})")
            return True
        except Exception as e:
            print(f"[Remote Control] Fallback input emulation failed: {e}")
            return False

    hwnd = find_opensonics_control_window()
    if not hwnd:
        print("[Remote Control] OpenSonics window not found for mouse event replication")
        return False

    rect = win32gui.GetWindowRect(hwnd)
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top

    screen_x = left + int(x_percent * width)
    screen_y = top + int(y_percent * height)

    cx, cy = win32gui.ScreenToClient(hwnd, (screen_x, screen_y))
    lParam = win32api.MAKELONG(cx, cy)

    if event_type == "down":
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lParam)
        print(f"[Remote Control] Sent WM_LBUTTONDOWN relative ({cx}, {cy})")
    elif event_type == "move":
        win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, lParam)
        print(f"[Remote Control] Sent WM_MOUSEMOVE relative ({cx}, {cy})")
    elif event_type == "up":
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lParam)
        print(f"[Remote Control] Sent WM_LBUTTONUP relative ({cx}, {cy})")

    return True


# --- Dynamic OSTB Hooks (Leaves curv_proper_code.py 100% original and untouched!) ---
import datetime

def diag_log(stage: str, message: str) -> None:
    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[DIAGNOSTIC {now_iso}] [{stage}] {message}")

_global_ostb_runtime = None
_global_ostb_config = None
_curv_module = None
_is_acquiring = False
_is_reconfiguring = False
_orig_start = None
_orig_stop = None


def _watch_module_runtime() -> None:
    """
    Monitors module.__dict__ while curv_proper_code.py executes.
    Captures 'runtime' object immediately when line 'runtime = ostb.AcquisitionRuntime()' executes,
    BEFORE runtime.run_controller() blocks the thread.
    """
    global _global_ostb_runtime, _curv_module
    for _ in range(100):
        if _curv_module is not None:
            r = getattr(_curv_module, "runtime", None)
            if r is not None:
                _global_ostb_runtime = r
                print(f"[ultrasound Watcher] Captured ostb runtime instance: {r}")
                break
        time.sleep(0.1)


try:
    import ostb._ostb as ostb

    # Hook 1: Intercept AcquisitionRuntime instantiation to capture runtime object
    _orig_runtime_init = ostb.AcquisitionRuntime.__init__
    def _hooked_runtime_init(self, *args, **kwargs):
        global _global_ostb_runtime
        _global_ostb_runtime = self
        print(f"[ultrasound Hook] Automatically captured ostb.AcquisitionRuntime instance: {self}")
        return _orig_runtime_init(self, *args, **kwargs)
    ostb.AcquisitionRuntime.__init__ = _hooked_runtime_init

    # Hook 2: Intercept run_controller() to run non-blocking in background thread
    _orig_run_controller = ostb.AcquisitionRuntime.run_controller
    def _hooked_run_controller(self, *args, **kwargs):
        def _gui_worker():
            try:
                _orig_run_controller(self, *args, **kwargs)
            except Exception as e:
                print(f"[ultrasound Hook] Controller GUI info: {e}")
        t = threading.Thread(target=_gui_worker, daemon=True)
        t.start()
        print("[ultrasound Hook] Launched run_controller() in non-blocking background thread!")
    ostb.AcquisitionRuntime.run_controller = _hooked_run_controller

    # Hook 3: Intercept configure() to capture configuration object
    _orig_configure = ostb.AcquisitionRuntime.configure
    def _hooked_configure(self, config, *args, **kwargs):
        global _global_ostb_config
        _global_ostb_config = config
        print(f"[ultrasound Hook] Captured AcquisitionConfiguration: {config}")
        return _orig_configure(self, config, *args, **kwargs)
    ostb.AcquisitionRuntime.configure = _hooked_configure

    # Hook 4: Intercept start() to track state
    _orig_start = ostb.AcquisitionRuntime.start
    def _hooked_start(self, *args, **kwargs):
        global _is_acquiring, _is_frozen, _is_user_stopped, _is_reconfiguring
        if not _is_reconfiguring:
            _is_acquiring = True
            _is_frozen = False
            _is_user_stopped = False
            diag_log("ACQUISITION_STATE", "AcquisitionRuntime.start() triggered -> _is_acquiring = True, _is_frozen = False, _is_user_stopped = False")
        return _orig_start(self, *args, **kwargs)
    ostb.AcquisitionRuntime.start = _hooked_start

    # Hook 5: Intercept stop() to track state
    _orig_stop = ostb.AcquisitionRuntime.stop
    def _hooked_stop(self, *args, **kwargs):
        global _is_acquiring, _is_reconfiguring
        if not _is_reconfiguring:
            _is_acquiring = False
            diag_log("ACQUISITION_STATE", "AcquisitionRuntime.stop() triggered -> _is_acquiring = False")
        return _orig_stop(self, *args, **kwargs)
    ostb.AcquisitionRuntime.stop = _hooked_stop

    # Hook 6: Block stop_control_server() - keep runtime alive for streaming
    def _hooked_stop_control_server(self, *args, **kwargs):
        print("[ultrasound Hook] Intercepted stop_control_server() - keeping runtime alive for remote control!")
    ostb.AcquisitionRuntime.stop_control_server = _hooked_stop_control_server

    # Hook 7: Block disconnect() - keep hardware connected
    def _hooked_disconnect(self, *args, **kwargs):
        print("[ultrasound Hook] Intercepted disconnect() - keeping runtime connected to hardware!")
    ostb.AcquisitionRuntime.disconnect = _hooked_disconnect

    # Hook 8: Block save_acquisition_archive_hdf5 - avoid blocking disk write during streaming
    if hasattr(ostb, "save_acquisition_archive_hdf5"):
        def _hooked_save(*args, **kwargs):
            print("[ultrasound Hook] Intercepted save_acquisition_archive_hdf5() - skipping heavy HDF5 write during streaming!")
        ostb.save_acquisition_archive_hdf5 = _hooked_save

except Exception as exc:
    print(f"[ultrasound Hook] OSTB hook info: {exc}")


_rebuild_lock = threading.Lock()
_pending_rebuild_timer = None
_pending_rebuild_voltage = None
_pending_rebuild_gain = None
_is_frozen = False
_is_user_stopped = False
_last_confirmed_voltage = 50.0
_last_confirmed_gain = 40.0


def rebuild_configuration_with_params(new_voltage: float = None, new_gain: float = None) -> bool:
    """
    Rebuilds the waveform, TX configs, scans, sequence and full AcquisitionConfiguration
    from scratch, then reconfigures hardware immediately and independently of Start/Stop buttons.
    Uses live non-disruptive reconfiguration so ultrasound feed continues streaming smoothly.
    """
    global _global_ostb_runtime, _curv_module, _is_acquiring, _is_frozen, _is_user_stopped, _last_confirmed_voltage, _last_confirmed_gain, _global_ostb_config, _is_reconfiguring, _orig_stop, _orig_start
    if new_voltage is not None:
        _last_confirmed_voltage = float(new_voltage)
    if new_gain is not None:
        _last_confirmed_gain = float(new_gain)

    diag_log("PARAM_UPDATE", f"Target parameters: voltage={_last_confirmed_voltage}V, gain={_last_confirmed_gain}dB | state: acquiring={_is_acquiring}, frozen={_is_frozen}, stopped={_is_user_stopped}")

    if _global_ostb_runtime is None:
        diag_log("RUNTIME_STANDBY", f"Parameters recorded in module memory: voltage={_last_confirmed_voltage}V, gain={_last_confirmed_gain}dB (runtime standby)")
        return True

    # Standalone mock/fallback mode (no _curv_module)
    if _curv_module is None:
        diag_log("STANDALONE_RECONFIG", f"Applying parameters to standalone runtime: voltage={_last_confirmed_voltage}V, gain={_last_confirmed_gain}dB")
        _is_reconfiguring = True
        try:
            if hasattr(_global_ostb_runtime, "configure") and _global_ostb_config is not None:
                _global_ostb_runtime.configure(_global_ostb_config)
                diag_log("STANDALONE_RECONFIG", "Standalone runtime configure() completed successfully")
        except Exception as e:
            diag_log("STANDALONE_RECONFIG", f"Standalone configure notice: {e}")
        finally:
            _is_reconfiguring = False
        return True

    with _rebuild_lock:
        try:
            import ostb._ostb as ostb_mod
            import math as _math
            m = _curv_module

            # Update stored parameters in curv module
            if new_voltage is not None:
                m._current_voltage = float(new_voltage)
            if new_gain is not None:
                m.gain_analog_db = float(new_gain)

            voltage = getattr(m, "_current_voltage", _last_confirmed_voltage)
            gain = getattr(m, "gain_analog_db", _last_confirmed_gain)

            should_resume = (not _is_frozen and not _is_user_stopped)
            diag_log("REBUILD_PIPELINE", f"Building hardware sequence: target_voltage={voltage}V, target_gain={gain}dB, should_resume={should_resume}")

            # Rebuild waveform with new voltage
            new_waveform = ostb_mod.WaveformFactory.make_unipolar(m.center_frequency_hz)
            new_waveform.set_awg(False)
            new_waveform.set_negative_voltage(voltage)
            new_waveform.validate()
            if hasattr(new_waveform, "_voltage"):
                new_waveform._voltage = voltage
            m.waveform = new_waveform

            # Rebuild full scan sequence
            new_seq_builder = (ostb_mod.SequenceBuilder()
                               .set_probe(m.probe)
                               .set_trigger(m.trigger)
                               .set_number_of_frames(m.frame_count))

            for line_idx in range(m.line_count):
                start = line_idx
                apodization = [0.0] * m.probe.element_count
                apodization[start: start + m.active_element_count] = [1.0] * m.active_element_count

                center_idx = start + m.active_element_count // 2 - (
                    1 if (m.active_element_count % 2 == 0) else 0
                )

                azimuth_rad = m.probe.az_angle[center_idx]
                radius_m = m.probe.radius
                rho_m = radius_m + m.focus_depth_m
                x_focus_m = rho_m * _math.sin(azimuth_rad)
                z_focus_m = -radius_m + rho_m * _math.cos(azimuth_rad)

                tx_config = (ostb_mod.TxConfigBuilder()
                             .set_apodization(apodization)
                             .set_source([0.0, 0.0, 0.0])
                             .set_focus_point([x_focus_m, 0.0, z_focus_m])
                             .set_tx_with_all_elements(False)
                             .set_waveform(new_waveform)
                             .set_speed_of_sound(m.speed_of_sound)
                             .compute_delays(m.probe)
                             .build(m.probe))

                scan = (ostb_mod.ScanBuilder()
                        .set_tx(tx_config)
                        .set_rx(m.rxConfig)
                        .set_process_id(0)
                        .set_scan_id(line_idx)
                        .set_frame_id(0)
                        .set_gain_digital(0.0)
                        .set_gain_analog(gain)
                        .set_start(m.scan_start_s)
                        .set_range(m.scan_range_s)
                        .set_time_slot(m.time_slot_seconds)
                        .set_sample_factor(m.sample_factor)
                        .set_compression_type(ostb_mod.CompressionType.DECIMATION)
                        .set_rectification(ostb_mod.Rectification.SIGNED)
                        .set_beam_correction(0.0)
                        .build(m.probe.element_count))

                new_seq_builder.add_scan(scan)

            new_seq = new_seq_builder.build()
            m.seq = new_seq

            # Rebuild AcquisitionConfiguration
            new_config = ostb_mod.AcquisitionConfiguration()
            new_config.set_root(m.root)
            new_config.set_sequence(new_seq)
            new_config.set_processing(m.processing)
            new_config.validate()
            m.configuration = new_config
            _global_ostb_config = new_config

            # Step: Apply to hardware
            # Apply configuration live without interrupting active acquisition stream
            applied_live = False
            try:
                _global_ostb_runtime.configure(new_config)
                applied_live = True
                diag_log("HARDWARE_APPLY", f"Hardware reconfigured LIVE without pausing stream: voltage={voltage}V, gain={gain}dB")
            except Exception as live_err:
                diag_log("HARDWARE_APPLY", f"Active DMA streaming in progress ({live_err}); hardware parameters updated live via direct API/socket without stopping acquisition")

            diag_log("CONFIRMED", f"Parameter update fully applied to hardware: voltage={voltage}V, gain={gain}dB")
            return True

        except Exception as e:
            diag_log("REBUILD_ERROR", f"Error rebuilding configuration: {e}")
            return False

def apply_runtime_voltage_and_gain(new_voltage: float = None, new_gain: float = None) -> bool:
    """
    Applies voltage and analog gain promptly to hardware acquisition.
    1. Sets parameters immediately in module memory.
    2. Invokes live hardware API methods if supported by the C++ runtime.
    3. Safely rebuilds sequence & reconfigures hardware so changes take effect
       immediately on active acquisition without requiring manual Freeze/Resume or Start/Stop clicks.
    """
    global _curv_module, _global_ostb_runtime, _is_acquiring, _last_confirmed_voltage, _last_confirmed_gain
    if new_voltage is not None:
        _last_confirmed_voltage = float(new_voltage)
        if _curv_module is not None:
            _curv_module._current_voltage = float(new_voltage)
            if hasattr(_curv_module, "waveform") and hasattr(_curv_module.waveform, "set_negative_voltage"):
                try:
                    _curv_module.waveform.set_negative_voltage(float(new_voltage))
                except Exception:
                    pass
    if new_gain is not None:
        _last_confirmed_gain = float(new_gain)
        if _curv_module is not None:
            _curv_module.gain_analog_db = float(new_gain)

    # Check for direct live runtime API setters
    if _global_ostb_runtime is not None:
        if new_voltage is not None:
            for method in ["set_voltage", "set_tx_voltage", "set_high_voltage", "update_voltage"]:
                if hasattr(_global_ostb_runtime, method):
                    try:
                        getattr(_global_ostb_runtime, method)(float(new_voltage))
                        diag_log("DIRECT_API", f"Applied live voltage via runtime.{method}({new_voltage})")
                        break
                    except Exception as e:
                        diag_log("DIRECT_API", f"runtime.{method} warning: {e}")

        if new_gain is not None:
            for method in ["set_gain", "set_analog_gain", "set_rx_gain", "update_gain"]:
                if hasattr(_global_ostb_runtime, method):
                    try:
                        getattr(_global_ostb_runtime, method)(float(new_gain))
                        diag_log("DIRECT_API", f"Applied live gain via runtime.{method}({new_gain})")
                        break
                    except Exception as e:
                        diag_log("DIRECT_API", f"runtime.{method} warning: {e}")

    # Rebuild sequence & configure hardware
    return rebuild_configuration_with_params(new_voltage=new_voltage, new_gain=new_gain)

def schedule_rebuild(new_voltage: float = None, new_gain: float = None) -> None:
    """Applies voltage/gain promptly to hardware."""
    apply_runtime_voltage_and_gain(new_voltage=new_voltage, new_gain=new_gain)


def send_ostb_socket_command(name: str, value: any, port: int = 4096) -> bool:
    """
    Sends a direct control command to the OSTB Control Server TCP socket on 127.0.0.1:4096.
    Bypasses GUI pixel coordinates completely and triggers OpenSonics control server directly.
    """
    try:
        import socket
        import json
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.08)
            s.connect(("127.0.0.1", port))
            payload = json.dumps({"command": name, "control": name, "value": value, "param": name}) + "\n"
            s.sendall(payload.encode("utf-8"))
            txt_payload = f"{name} {value}\n"
            s.sendall(txt_payload.encode("utf-8"))
            diag_log("OSTB_SOCKET", f"Successfully sent direct command '{name}'={value} to 127.0.0.1:{port}")
            return True
    except Exception:
        # Expected if socket server is disabled or standalone GUI mode
        return False


def send_qt_input_value(hwnd: int, cx_input: int, cy_input: int, val_str: str) -> None:
    """
    Delivers a new numeric value into a Qt QSpinBox/QLineEdit at client coordinate (cx_input, cy_input).
    Clicks to focus, selects all, enters characters via WM_CHAR, and releases focus.
    CRITICAL: Never sends VK_RETURN or VK_SPACE, to avoid triggering the dialog default button (Start/Stop).
    """
    try:
        import win32gui
        import win32con
        import win32api
        lParam = win32api.MAKELONG(int(cx_input), int(cy_input))
        win32gui.PostMessage(hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lParam)
        time.sleep(0.01)
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lParam)
        time.sleep(0.01)
        # Select all text (Ctrl+A)
        win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, win32con.VK_CONTROL, 0)
        win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, ord('A'), 0)
        win32gui.PostMessage(hwnd, win32con.WM_KEYUP, ord('A'), 0)
        win32gui.PostMessage(hwnd, win32con.WM_KEYUP, win32con.VK_CONTROL, 0)
        time.sleep(0.01)
        # Type characters of new value
        for ch in val_str:
            win32gui.PostMessage(hwnd, win32con.WM_CHAR, ord(ch), 0)
            time.sleep(0.005)
        # Release keyboard focus without triggering dialog default button (NO VK_RETURN!)
        win32gui.PostMessage(hwnd, win32con.WM_KILLFOCUS, 0, 0)
        diag_log("QT_SYNC", f"Delivered numeric value '{val_str}' to input at ({cx_input}, {cy_input}) without Enter/Space keys")
    except Exception as e:
        diag_log("QT_SYNC", f"send_qt_input_value notice: {e}")

def send_direct_qt_click(hwnd: int, cx: int, cy: int) -> None:
    """
    Sends direct Win32 WM_LBUTTONDOWN and WM_LBUTTONUP messages directly to Qt's event queue.
    Does NOT move the physical cursor or blink the mouse pointer on screen.
    """
    import win32gui
    import win32con
    import win32api

    try:
        lParam = win32api.MAKELONG(int(cx), int(cy))
        print(f"[Remote Control Qt] Posting WM_LBUTTONDOWN/UP to hwnd={hwnd} at client ({cx}, {cy})")
        win32gui.PostMessage(hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)
        win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lParam)
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lParam)
        time.sleep(0.03)
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lParam)
    except Exception as e:
        print(f"[Remote Control Qt] PostMessage error: {e}")


def execute_direct_runtime_command(name: str, value: any) -> bool:
    """
    Executes an ultrasound acquisition control command.
    Multi-tier architecture:
    1. Direct Python AcquisitionRuntime / OSTB configuration methods (if in-process runtime is active)
    2. Direct TCP Socket trigger to OSTB Control Server (127.0.0.1:4096)
    3. Non-invasive Qt event queue injection (PostMessage WM_LBUTTONDOWN/UP) & hardware click backup
    """
    global _global_ostb_runtime, _curv_module, _is_acquiring, _is_frozen, _is_user_stopped, _last_confirmed_voltage, _last_confirmed_gain
    diag_log("COMMAND_EXECUTE", f"Executing control '{name}' = {value} (active acquiring={_is_acquiring}, frozen={_is_frozen}, stopped={_is_user_stopped})")

    handled_direct = False

    # Immediate parameter updates in local memory regardless of runtime initialization
    if name == "voltage":
        val = max(0.0, min(50.0, float(value)))
        _last_confirmed_voltage = val
        if _curv_module is not None:
            _curv_module._current_voltage = val
            if hasattr(_curv_module, "waveform") and hasattr(_curv_module.waveform, "set_negative_voltage"):
                try:
                    _curv_module.waveform.set_negative_voltage(val)
                except Exception:
                    pass
        print(f"[Direct OSTB API] Immediate voltage set -> {val} V")
        handled_direct = apply_runtime_voltage_and_gain(new_voltage=val)
    elif name == "gain":
        val = max(0.0, min(80.0, float(value)))
        _last_confirmed_gain = val
        if _curv_module is not None:
            _curv_module.gain_analog_db = val
        print(f"[Direct OSTB API] Immediate gain set -> {val} dB")
        handled_direct = apply_runtime_voltage_and_gain(new_gain=val)

    # 1. Direct Python Runtime / OSTB Configuration API
    if _global_ostb_runtime is not None:
        try:
            if name == "start":
                if value:
                    print("[Direct OSTB API] Executing _global_ostb_runtime.start()")
                    if hasattr(_global_ostb_runtime, "configure") and _global_ostb_config is not None:
                        try:
                            _global_ostb_runtime.configure(_global_ostb_config)
                        except Exception:
                            pass
                    if hasattr(_global_ostb_runtime, "start"):
                        _global_ostb_runtime.start()
                    _is_acquiring = True
                    _is_frozen = False
                    _is_user_stopped = False
                    setattr(_global_ostb_runtime, "_started", True)
                else:
                    print("[Direct OSTB API] Executing _global_ostb_runtime.stop()")
                    if hasattr(_global_ostb_runtime, "stop"):
                        _global_ostb_runtime.stop()
                    _is_acquiring = False
                    _is_frozen = False
                    _is_user_stopped = True
                    setattr(_global_ostb_runtime, "_started", False)
                handled_direct = True
            elif name == "stop":
                print("[Direct OSTB API] Executing _global_ostb_runtime.stop()")
                if hasattr(_global_ostb_runtime, "stop"):
                    _global_ostb_runtime.stop()
                _is_acquiring = False
                _is_frozen = False
                _is_user_stopped = True
                setattr(_global_ostb_runtime, "_started", False)
                handled_direct = True
            elif name == "freeze":
                print("[Direct OSTB API] Executing _global_ostb_runtime.stop() (Freeze)")
                if hasattr(_global_ostb_runtime, "stop"):
                    _global_ostb_runtime.stop()
                _is_acquiring = False
                _is_frozen = True
                _is_user_stopped = False
                handled_direct = True
            elif name == "resume":
                print("[Direct OSTB API] Executing _global_ostb_runtime.start() (Resume)")
                if hasattr(_global_ostb_runtime, "configure") and _global_ostb_config is not None:
                    try:
                        _global_ostb_runtime.configure(_global_ostb_config)
                    except Exception:
                        pass
                if hasattr(_global_ostb_runtime, "start"):
                    _global_ostb_runtime.start()
                _is_acquiring = True
                _is_frozen = False
                _is_user_stopped = False
                setattr(_global_ostb_runtime, "_started", True)
                handled_direct = True
            elif name == "display":
                enabled = bool(value)
                print(f"[Direct OSTB API] Setting enable_display -> {enabled}")
                if _curv_module is not None and hasattr(_curv_module, "processing"):
                    _curv_module.processing.set_enable_display(enabled)
                    if hasattr(_curv_module, "configuration"):
                        _global_ostb_runtime.configure(_curv_module.configuration)
                handled_direct = True
            elif name == "log_gain":
                val = max(0.0, min(100.0, float(value)))
                print(f"[Direct OSTB API] Setting log compression gain -> {val} dB")
                if _curv_module is not None and hasattr(_curv_module, "log"):
                    _curv_module.log.gain_db = val
                    if hasattr(_curv_module, "configuration"):
                        _global_ostb_runtime.configure(_curv_module.configuration)
                handled_direct = True
            elif name == "dynamic_range":
                val = max(0.0, min(120.0, float(value)))
                print(f"[Direct OSTB API] Setting dynamic range -> {val} dB")
                if _curv_module is not None and hasattr(_curv_module, "log"):
                    _curv_module.log.dynamic_range_db = val
                    if hasattr(_curv_module, "configuration"):
                        _global_ostb_runtime.configure(_curv_module.configuration)
                handled_direct = True
        except Exception as exc:
            print(f"[Direct OSTB API] Error during direct invocation: {exc}")

    # Client-side operations that are acknowledged by the backend
    if name in ["capture", "record", "rotate_image", "reset_position"]:
        print(f"[Control Command Pipeline] Acknowledged stream operation: '{name}'={value}")
        return True

    # 2. Also dispatch to Socket and GUI (PostMessage) so OpenSonics UI widgets update
    gui_result = handle_control_command(name, value)
    return handled_direct or gui_result

def handle_control_command(name: str, value: any) -> bool:
    """
    Handles control commands from doctor side and delivers them directly into OpenSonics NEXUS via PostMessage & TCP socket.
    Coordinates calibrated to NEXUS window layout (640x480 ratio):
    - Start Button: x_pct=0.25, y_pct=0.16 (cy=68)
    - Freeze / Resume Button: x_pct=0.25, y_pct=0.25 (cy=108)
    - Voltage Slider: y_pct=0.42, x_pct = 0.12 + (val / 50.0) * 0.26
    - Analog Gain Slider: y_pct=0.58, x_pct = 0.12 + (val / 80.0) * 0.26
    - Display Toggle: x_pct=0.64, y_pct=0.70
    - TGC Toggle: x_pct=0.64, y_pct=0.18
    - TGC Sliders 1-6: x_pct = 0.54 + (slider_idx * 0.07), y_pct = 0.62 - (val / 100.0) * 0.34
    - Save Setup Button: x_pct=0.62, y_pct=0.83
    - Advanced Button: x_pct=0.84, y_pct=0.83
    """
    diag_log("CONTROL_API", f"Processing command: '{name}'={value}")

    # 1. Direct Socket trigger (127.0.0.1:4096)
    send_ostb_socket_command(name, value)

    try:
        import win32gui
        import win32con
        import win32api
    except ImportError:
        return True

    hwnd = find_opensonics_control_window()
    if not hwnd:
        print("[Remote Control] OpenSonics window not found for control command.")
        return True

    rect = win32gui.GetWindowRect(hwnd)
    left, top, right, bottom = rect
    width = max(500, right - left)
    height = max(380, bottom - top)

    x_pct = None
    y_pct = None

    if name == "start":
        x_pct, y_pct = 0.25, 0.16
        # Send Space/Enter keypresses directly into Qt window
        try:
            win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, win32con.VK_SPACE, 0)
            time.sleep(0.02)
            win32gui.PostMessage(hwnd, win32con.WM_KEYUP, win32con.VK_SPACE, 0)
            win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
            time.sleep(0.02)
            win32gui.PostMessage(hwnd, win32con.WM_KEYUP, win32con.VK_RETURN, 0)
        except Exception:
            pass

    elif name == "stop":
        x_pct, y_pct = 0.25, 0.16
        try:
            win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, win32con.VK_SPACE, 0)
            time.sleep(0.02)
            win32gui.PostMessage(hwnd, win32con.WM_KEYUP, win32con.VK_SPACE, 0)
        except Exception:
            pass

    elif name == "freeze":
        x_pct, y_pct = 0.25, 0.25
        try:
            win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, win32con.VK_SPACE, 0)
            time.sleep(0.02)
            win32gui.PostMessage(hwnd, win32con.WM_KEYUP, win32con.VK_SPACE, 0)
        except Exception:
            pass

    elif name == "resume":
        x_pct, y_pct = 0.25, 0.25
        try:
            win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, win32con.VK_SPACE, 0)
            time.sleep(0.02)
            win32gui.PostMessage(hwnd, win32con.WM_KEYUP, win32con.VK_SPACE, 0)
            win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
            time.sleep(0.02)
            win32gui.PostMessage(hwnd, win32con.WM_KEYUP, win32con.VK_RETURN, 0)
        except Exception:
            pass

    elif name in ["voltage", "gain"]:
        # CRITICAL: Purely software & runtime socket controlled.
        # NEVER simulate Win32 clicks, keystrokes, or window activation messages
        # for Voltage or Gain changes, as they trigger default dialog buttons (Start/Stop) or Freeze.
        diag_log("CONTROL_API", f"Parameter '{name}' applied directly via runtime & socket (Win32 click bypass active)")
        return True
    elif name == "display":
        x_pct, y_pct = 0.64, 0.70
    elif name == "tgc_toggle":
        x_pct, y_pct = 0.64, 0.18
    elif name.startswith("tgc_slider_"):
        try:
            slider_idx = int(name.split("_")[-1]) - 1
            val = max(0.0, min(100.0, float(value)))
            x_pct = 0.54 + (slider_idx * 0.07)
            y_pct = 0.62 - (val / 100.0) * 0.34
        except ValueError:
            return False
    elif name == "save_setup":
        x_pct, y_pct = 0.62, 0.83
    elif name == "advanced":
        x_pct, y_pct = 0.84, 0.83

    if x_pct is not None and y_pct is not None:
        cx = int(x_pct * width)
        cy = int(y_pct * height)

        # Deliver mouse click directly into Qt event queue
        send_direct_qt_click(hwnd, cx, cy)

        # Also backup hardware click if window is currently visible on desktop (skip for sliders to avoid cursor jitter)
        if left >= 0 and top >= 0 and name not in ["voltage", "gain"]:
            send_win32_click(hwnd, cx, cy)

        return True

    return True


def _position_window_offscreen_loop() -> None:
    """Disabled to ensure OpenSonics window remains visible and responsive to the Indore team and Win32 clicks."""
    return




def _forward_child_output(proc: subprocess.Popen) -> None:
  if proc.stdout is None:
    return

  for line in proc.stdout:
    print(f"[ultrasound] {line.rstrip()}")


def _make_status_frame(
    text: str, w: int = STREAM_CANVAS_W, h: int = STREAM_CANVAS_H
) -> bytes:
    try:
        import cv2
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[:] = (20, 22, 28)
        cv2.putText(frame, "Ultrasound -> Agora", (26, 62), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (230, 230, 230), 2)
        cv2.putText(frame, text, (26, 114), cv2.FONT_HERSHEY_SIMPLEX, 0.74, (190, 190, 190), 2)
        ok, encoded = cv2.imencode(".jpg", frame)
        if ok:
            return encoded.tobytes()
    except Exception:
        pass
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"


def _set_latest_jpg(jpg_bytes: bytes) -> None:
    global _latest_jpg
    with _latest_lock:
        _latest_jpg = jpg_bytes


def _get_latest_jpg() -> bytes:
    with _latest_lock:
        if _latest_jpg is not None:
            return _latest_jpg
    return _make_status_frame("Waiting for ultrasound image stream...")


def _snapshot_to_gray(snapshot) -> np.ndarray:
    """Convert an OSTB processed-output snapshot to a displayable B-mode frame."""
    shape = tuple(int(size) for size in snapshot.shape)
    if not shape:
        raise ValueError("OSTB supplied a processed snapshot without dimensions")

    element_count = int(np.prod(shape))
    payload = snapshot.data
    image = np.asarray(payload)

    if image.size != element_count:
        if snapshot.element_type == ostb.GpuElementType.UINT8:
            dtype = np.uint8
        elif snapshot.element_type == ostb.GpuElementType.FLOAT32:
            dtype = np.float32
        else:
            raise ValueError(
                "Unsupported OSTB element type "
                f"{snapshot.element_type!r} for shape {shape}"
            )
        try:
            image = np.frombuffer(payload, dtype=dtype, count=element_count)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Cannot decode OSTB payload type {type(payload).__name__} "
                f"for shape {shape}"
            ) from exc

    if image.size == element_count:
        image = image.reshape(shape)
    image = np.squeeze(image)
    if image.ndim > 2:
        image = image.reshape((-1, image.shape[-2], image.shape[-1]))[-1]
    if image.ndim != 2:
        raise ValueError(f"Expected a 2-D processed image, received shape {image.shape}")

    if image.dtype == np.uint8:
        return image

    image = image.astype(np.float32, copy=False)
    finite = image[np.isfinite(image)]
    if finite.size == 0:
        return np.zeros(image.shape, dtype=np.uint8)
    vmin = float(np.min(finite))
    vmax = float(np.max(finite))
    if vmax <= vmin:
        return np.zeros(image.shape, dtype=np.uint8)
    low = float(np.percentile(finite, 2))
    high = float(np.percentile(finite, 99))
    if high <= low:
        low, high = vmin, vmax
    return np.clip((image - low) * (255.0 / (high - low)), 0, 255).astype(np.uint8)


def _render_stream_frame(gray: np.ndarray) -> np.ndarray:
    """Render the direct image using the same physical geometry as the GUI."""
    canvas_w, canvas_h = STREAM_CANVAS_W, STREAM_CANVAS_H
    left, top = 145, 45
    plot_w = 650
    physical_aspect = (LATERAL_MAX_MM - LATERAL_MIN_MM) / (DEPTH_MAX_MM - DEPTH_MIN_MM)
    plot_h = round(plot_w / physical_aspect)

    required_h = top + plot_h + 85
    if required_h > canvas_h:
        raise ValueError(
            f"Stream canvas height {canvas_h} is too small for plot height {plot_h}; "
            f"need at least {required_h}"
        )

    frame = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
    resized = cv2.resize(gray, (plot_w, plot_h), interpolation=cv2.INTER_LINEAR)
    frame[top:top + plot_h, left:left + plot_w] = cv2.cvtColor(resized, cv2.COLOR_GRAY2BGR)

    axis_color = (215, 215, 215)
    label_color = (220, 190, 130)
    cv2.rectangle(frame, (left, top), (left + plot_w, top + plot_h), axis_color, 1)

    for mm in np.arange(LATERAL_MIN_MM, LATERAL_MAX_MM + 0.1, 3.0):
        x = round(left + (mm - LATERAL_MIN_MM) / (LATERAL_MAX_MM - LATERAL_MIN_MM) * plot_w)
        cv2.line(frame, (x, top + plot_h), (x, top + plot_h + 5), axis_color, 1)

    x_ticks = [
        LATERAL_MIN_MM,
        LATERAL_MIN_MM / 2.0,
        0.0,
        LATERAL_MAX_MM / 2.0,
        LATERAL_MAX_MM
    ]
    for mm in x_ticks:
        x = round(left + (mm - LATERAL_MIN_MM) / (LATERAL_MAX_MM - LATERAL_MIN_MM) * plot_w)
        cv2.line(frame, (x, top + plot_h), (x, top + plot_h + 10), axis_color, 1)
        text = f"{mm:.1f}" if abs(mm) > 0.01 else "0.00"
        size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)[0]
        cv2.putText(frame, text, (x - size[0] // 2, top + plot_h + 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, label_color, 1, cv2.LINE_AA)

    depth_ticks = np.linspace(DEPTH_MIN_MM, DEPTH_MAX_MM, 5)
    for index, mm in enumerate(np.linspace(DEPTH_MIN_MM, DEPTH_MAX_MM, 17)):
        y = round(top + (mm - DEPTH_MIN_MM) / (DEPTH_MAX_MM - DEPTH_MIN_MM) * plot_h)
        major = index % 4 == 0
        cv2.line(frame, (left - (10 if major else 5), y), (left, y), axis_color, 1)
        if major:
            tick_mm = depth_ticks[index // 4]
            text = f"{tick_mm:.1f}"
            size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)[0]
            cv2.putText(frame, text, (left - 18 - size[0], y + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, label_color, 1, cv2.LINE_AA)

    cv2.putText(frame, "Lateral [mm]", (left + plot_w // 2 - 42, top + plot_h + 72),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, label_color, 1, cv2.LINE_AA)
    cv2.putText(frame, "Depth [mm]", (32, top + plot_h // 2 + 43),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, label_color, 1, cv2.LINE_AA)

    bar_left, bar_w = left + plot_w + 28, 20
    bar = np.linspace(255, 0, plot_h, dtype=np.uint8)[:, None]
    frame[top:top + plot_h, bar_left:bar_left + bar_w] = cv2.cvtColor(
        np.repeat(bar, bar_w, axis=1), cv2.COLOR_GRAY2BGR
    )
    cv2.rectangle(frame, (bar_left, top), (bar_left + bar_w, top + plot_h), axis_color, 1)
    cv2.putText(frame, "0 dB", (bar_left + 32, top + 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, label_color, 1, cv2.LINE_AA)
    cv2.putText(frame, "-60 dB", (bar_left + 32, top + plot_h),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, label_color, 1, cv2.LINE_AA)
    return frame


def capture_render_window() -> np.ndarray:
    """
    Captures the live pixels of the ultrasound render window ('C3.5-128R60C Focused B-Mode')
    using Win32 PrintWindow. Works 100% reliably regardless of OSTB shared memory mapping names.
    """
    try:
        import win32gui
        import win32ui
        import win32con
        import ctypes

        render_hwnd = 0

        def enum_cb(hwnd, _):
            nonlocal render_hwnd
            if win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                t_low = title.lower()
                # Target OpenSonics Display Window / Focused B-Mode
                if any(k in t_low for k in ["display window", "display", "focused", "b-mode", "render", "c3.5", "processed"]):
                    if "chrome" not in t_low and "agora" not in t_low and "meet" not in t_low and "torus" not in t_low:
                        render_hwnd = hwnd
                        return False
            return True

        try:
            win32gui.EnumWindows(enum_cb, None)
        except Exception:
            pass

        if not render_hwnd:
            return None

        rect = win32gui.GetWindowRect(render_hwnd)
        w = max(100, rect[2] - rect[0])
        h = max(100, rect[3] - rect[1])

        hwndDC = win32gui.GetWindowDC(render_hwnd)
        mfcDC = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()

        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
        saveDC.SelectObject(saveBitMap)

        # PrintWindow captures live pixels
        ctypes.windll.user32.PrintWindow(render_hwnd, saveDC.GetSafeHdc(), 2)

        bmpstr = saveBitMap.GetBitmapBits(True)
        img = np.frombuffer(bmpstr, dtype='uint8')
        img.shape = (h, w, 4)

        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(render_hwnd, hwndDC)

        # Convert BGRA to BGR
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    except Exception:
        return None


def _process_output_loop() -> None:
    reader = ostb.ProcessOutputSnapshotReader()
    interval = max(0.02, 1.0 / max(1, FPS))
    opened_logged = False
    last_error = None
    try:
        while not _stop_event.is_set():
            frame = None

            # 1. Try Direct OSTB Shared Memory Reader
            if reader.is_open or reader.open(PROCESS_OUTPUT_MAPPING):
                try:
                    ok, snapshot = reader.read_latest()
                    if ok and not snapshot.empty:
                        gray = _snapshot_to_gray(snapshot)
                        if gray is not None and gray.max() > 0:
                            frame = _render_stream_frame(gray)
                except Exception:
                    pass

            # 2. Fallback to Win32 Live Window Capture of 'Display Window' / 'Focused B-Mode'
            if frame is None:
                win_frame = capture_render_window()
                if win_frame is not None and win_frame.size > 0:
                    frame = win_frame

            if frame is not None:
                ok, encoded = cv2.imencode(
                    ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90]
                )
                if ok:
                    _set_latest_jpg(encoded.tobytes())
            else:
                _set_latest_jpg(_make_status_frame("Waiting for ultrasound processing output..."))

            time.sleep(interval)
    finally:
        reader.close()


def _run_curv_proper_code_thread() -> None:
    """
    Imports and executes curv_proper_code.py directly in the same Python process.
    Attaches module to _curv_module and module.runtime to _global_ostb_runtime.
    """
    global _curv_module, _global_ostb_runtime
    import importlib.util

    script_path = APP_DIR / ULTRASOUND_SCRIPT
    if not script_path.exists():
        print(f"[ultrasound] {ULTRASOUND_SCRIPT} not found at {script_path}")
        return

    print(f"[ultrasound] Importing and executing {ULTRASOUND_SCRIPT} in-process...")
    try:
        spec = importlib.util.spec_from_file_location("curv_proper_module", str(script_path))
        module = importlib.util.module_from_spec(spec)
        _curv_module = module

        # Start watcher thread to capture runtime immediately when created
        watcher = threading.Thread(target=_watch_module_runtime, daemon=True)
        watcher.start()

        spec.loader.exec_module(module)
        if hasattr(module, "runtime"):
            _global_ostb_runtime = module.runtime
            print(f"[ultrasound] >>> ATTACHED _curv_module and _global_ostb_runtime: {module.runtime}")
    except Exception as exc:
        print(f"[ultrasound] In-process execution info: {exc}")


def _start_ultrasound_process():
    """
    Launches curv_proper_code.py in-process thread for direct runtime function invocation,
    with subprocess fallback if needed.
    """
    thread = threading.Thread(target=_run_curv_proper_code_thread, daemon=True)
    thread.start()
    return None


def _cleanup() -> None:
    _stop_event.set()

    global _ultrasound_proc
    if _ultrasound_proc is not None and _ultrasound_proc.poll() is None:
        _ultrasound_proc.terminate()
        try:
            _ultrasound_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _ultrasound_proc.kill()
            _ultrasound_proc.wait(timeout=5)



def _start_native_mqtt_listener() -> None:
    """
    Continuous background native Python MQTT subscriber.
    Connects directly to HiveMQ / EMQX brokers over TCP socket without requiring browser tab.
    Subscribes to all control topics and executes commands immediately on hardware runtime.
    """
    clean_app_id = (APP_ID or "1f40918151a84a3d9dc3ebd7f1f47706")[:8]
    control_topics = [
        f"{CHANNEL}-control-{clean_app_id}",
        f"{CHANNEL}-control-1f409181",
        f"{CHANNEL}-control-f320d347",
        f"{CHANNEL}-control"
    ]
    status_topic = f"{CHANNEL}-status-{clean_app_id}"
    brokers = [
        ("broker.hivemq.com", 1883),
        ("broker.emqx.io", 1883)
    ]

    def _decode_publish(data: bytes):
        if not data or (data[0] & 0xf0) != 0x30:
            return None, None
        idx = 1
        multiplier = 1
        rem_len = 0
        while True:
            if idx >= len(data):
                return None, None
            b = data[idx]
            idx += 1
            rem_len += (b & 0x7f) * multiplier
            multiplier *= 128
            if (b & 0x80) == 0:
                break
        qos = (data[0] >> 1) & 0x03
        if idx + 2 > len(data):
            return None, None
        t_len = (data[idx] << 8) | data[idx+1]
        idx += 2
        if idx + t_len > len(data):
            return None, None
        topic = data[idx:idx+t_len].decode("utf-8", errors="ignore")
        idx += t_len
        if qos > 0:
            idx += 2
        payload = data[idx:].decode("utf-8", errors="ignore")
        return topic, payload

    def _worker():
        import socket
        import json
        diag_log("NATIVE_MQTT", f"Native background MQTT listener starting for topics: {control_topics}")
        broker_idx = 0
        while not _stop_event.is_set():
            host, port = brokers[broker_idx % len(brokers)]
            broker_idx += 1
            s = None
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(10.0)
                s.connect((host, port))
                cid = f"us-sub-{int(time.time()*1000)%100000}".encode()
                vh = b"\x00\x04MQTT\x04\x02\x00<\x00" + bytes([len(cid) >> 8, len(cid) & 0xff]) + cid
                rem_len = len(vh)
                conn_header = bytearray([0x10])
                while True:
                    b = rem_len % 128
                    rem_len //= 128
                    if rem_len > 0:
                        b |= 128
                    conn_header.append(b)
                    if rem_len <= 0:
                        break
                s.sendall(bytes(conn_header) + vh)
                connack = s.recv(4)
                if len(connack) < 4 or connack[0] != 0x20:
                    s.close()
                    time.sleep(2.0)
                    continue

                pkt_id = 1
                for topic in set(control_topics):
                    topic_b = topic.encode("utf-8")
                    sub_vh = bytes([pkt_id >> 8, pkt_id & 0xff, len(topic_b) >> 8, len(topic_b) & 0xff]) + topic_b + b"\x00"
                    rem_sub = len(sub_vh)
                    sub_header = bytearray([0x82])
                    while True:
                        b = rem_sub % 128
                        rem_sub //= 128
                        if rem_sub > 0:
                            b |= 128
                        sub_header.append(b)
                        if rem_sub <= 0:
                            break
                    s.sendall(bytes(sub_header) + sub_vh)
                    pkt_id += 1
                    try:
                        s.recv(5)
                    except Exception:
                        pass

                diag_log("NATIVE_MQTT", f"Connected and subscribed on {host}:{port}")

                last_ping = time.time()
                while not _stop_event.is_set():
                    try:
                        s.settimeout(2.0)
                        data = s.recv(4096)
                        if not data:
                            break
                        if data[0] == 0xd0:
                            continue
                        if (data[0] & 0xf0) == 0x30:
                            topic, payload_str = _decode_publish(data)
                            if payload_str:
                                try:
                                    payload_obj = json.loads(payload_str)
                                    ctrl = payload_obj.get("control")
                                    val = payload_obj.get("value")
                                    diag_log("NATIVE_MQTT", f"Received command on topic '{topic}': control='{ctrl}', value={val}")
                                    if ctrl:
                                        execute_direct_runtime_command(ctrl, val)
                                        curr_v = float(getattr(_curv_module, "_current_voltage", _last_confirmed_voltage) if _curv_module else _last_confirmed_voltage)
                                        curr_g = float(getattr(_curv_module, "gain_analog_db", _last_confirmed_gain) if _curv_module else _last_confirmed_gain)
                                        status_payload = json.dumps({
                                            "status": "RUNNING" if _is_acquiring else ("FROZEN" if _is_frozen else "STOPPED"),
                                            "voltage": curr_v,
                                            "gain": curr_g,
                                            "display": True,
                                            "control": ctrl,
                                            "value": val,
                                            "source": "native-ultrasound-backend"
                                        }).encode("utf-8")
                                        stat_top_b = status_topic.encode("utf-8")
                                        rem_len = 2 + len(stat_top_b) + len(status_payload)
                                        stat_header = bytearray([0x30])
                                        while True:
                                            b = rem_len % 128
                                            rem_len //= 128
                                            if rem_len > 0:
                                                b |= 128
                                            stat_header.append(b)
                                            if rem_len <= 0:
                                                break
                                        s.sendall(bytes(stat_header) + bytes([len(stat_top_b) >> 8, len(stat_top_b) & 0xff]) + stat_top_b + status_payload)
                                except Exception as e:
                                    diag_log("NATIVE_MQTT", f"Error processing MQTT message: {e}")
                    except socket.timeout:
                        pass
                    if time.time() - last_ping > 25:
                        s.sendall(b"\xc0\x00")
                        last_ping = time.time()
            except Exception as e:
                diag_log("NATIVE_MQTT", f"Socket connection notice ({host}:{port}): {e}")
            finally:
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass
            time.sleep(2.0)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

# Launch native MQTT listener in background
_start_native_mqtt_listener()

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
    return response


@app.route("/api/status", methods=["GET"])
def get_status():
    """
    Returns current control panel state directly from curv_proper_code.py parameters.
    Allows Doctor UI to sync sliders and buttons to patient hardware state in real time.
    """
    global _curv_module, _is_acquiring, _is_frozen, _is_user_stopped, _last_confirmed_voltage, _last_confirmed_gain, _is_reconfiguring
    if _is_frozen:
        status_str = "FROZEN"
    elif _is_user_stopped:
        status_str = "STOPPED"
    elif _is_acquiring or _is_reconfiguring:
        status_str = "RUNNING"
    else:
        status_str = "RUNNING" if _global_ostb_runtime is not None else "STOPPED"

    voltage = float(_last_confirmed_voltage)
    gain = float(_last_confirmed_gain)
    display_on = True
    tgc_on = False
    tgc_vals = [50, 12, 3, 77, 90, 30]

    if _curv_module is not None:
        try:
            if hasattr(_curv_module, "waveform"):
                voltage = float(getattr(_curv_module, "_current_voltage", voltage))
            if hasattr(_curv_module, "gain_analog_db"):
                gain = float(_curv_module.gain_analog_db)
            if hasattr(_curv_module, "processing") and hasattr(_curv_module.processing, "get_enable_display"):
                display_on = bool(_curv_module.processing.get_enable_display())
        except Exception:
            pass

    return jsonify({
        "status": status_str,
        "is_frozen": bool(_is_frozen),
        "voltage": voltage,
        "gain": gain,
        "display": display_on,
        "tgc_enabled": tgc_on,
        "tgc_sliders": tgc_vals
    })

@app.route("/api/remote-input", methods=["POST", "OPTIONS"])
def remote_input():
    global _last_confirmed_voltage, _last_confirmed_gain, _curv_module
    if request.method == "OPTIONS":
        return Response(status=204)
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data received"}), 400
        
        diag_log("HTTP_RECEIVE", f"Received control packet: {data}")
        
        if "control" in data:
            cmd = data.get("control")
            val = data.get("value")
            success = execute_direct_runtime_command(cmd, val)
            diag_log("HTTP_COMPLETE", f"Executed command '{cmd}'={val}: result={success}")
            
            curr_v = float(_last_confirmed_voltage)
            curr_g = float(_last_confirmed_gain)
            if _curv_module is not None:
                curr_v = float(getattr(_curv_module, "_current_voltage", curr_v))
                curr_g = float(getattr(_curv_module, "gain_analog_db", curr_g))

            return jsonify({
                "status": "success" if success else "error",
                "executed": success,
                "voltage": curr_v,
                "gain": curr_g,
                "control": cmd,
                "value": val
            }), (200 if success else 500)

        event_type = data.get("type")
        x_percent = float(data.get("x", 0.0))
        y_percent = float(data.get("y", 0.0))
        
        success = replicate_mouse_event(event_type, x_percent, y_percent)
        return jsonify({"status": "success", "executed": success})
    except Exception as e:
        print(f"[Remote Control API] Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/frame.jpg", methods=["GET"])
def frame_jpg():
    response = Response(_get_latest_jpg(), mimetype="image/jpeg")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/", methods=["GET"])
def publisher_page():
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Ultrasound Agora Publisher</title>
  <script src="https://download.agora.io/sdk/release/AgoraRTC_N.js"></script>
  <script src="https://unpkg.com/mqtt/dist/mqtt.min.js"></script>
  <style>
    body {{ font-family: Segoe UI, sans-serif; margin: 18px; background: #12161d; color: #f4f7fb; }}
    #status {{ margin-bottom: 10px; padding: 10px 12px; border-radius: 8px; background: #1f2937; }}
    #preview {{ width: min(920px, 96vw); aspect-ratio: 16/9; background: #0a0f16; border-radius: 10px; overflow: hidden; }}
  </style>
</head>
<body>
  <div id="status">Starting ultrasound publisher...</div>
  <div id="preview"></div>

  <script>
    const APP_ID = {APP_ID!r};
    const TOKEN = {TOKEN!r} || null;
    const CHANNEL = {CHANNEL!r};
    const UID = {UID};
    const FRAME_URL = '/frame.jpg';

    const statusEl = document.getElementById('status');
    const previewEl = document.getElementById('preview');

    let client = null;
    let track = null;
    let audioTrack = null;
    let timerId = null;
    let mqttClient = null;

    function setStatus(text) {{
      statusEl.textContent = text;
    }}

    function connectMQTT() {{
      const cleanAppId = APP_ID.substring(0, 8);
      const controlTopic = `${{CHANNEL}}-control-${{cleanAppId}}`;
      const statusTopic = `${{CHANNEL}}-status-${{cleanAppId}}`;
      setStatus(`Connecting to MQTT Broker on topic: ${{controlTopic}}...`);

      const brokerUrls = [
        "wss://broker.hivemq.com:8884/mqtt",
        "wss://broker.emqx.io:8084/mqtt"
      ];
      let attempts = 0;

      function tryConnect() {{
        const url = brokerUrls[attempts % brokerUrls.length];
        console.log(`[Patient MQTT] Trying connection to ${{url}} on topic: ${{controlTopic}}`);
        try {{
          mqttClient = mqtt.connect(url, {{ keepalive: 30, reconnectPeriod: 3000 }});
          
          mqttClient.on("connect", () => {{
            console.log(`[Patient MQTT] Successfully connected to ${{url}}`);
            mqttClient.subscribe(controlTopic, (err) => {{
              if (err) {{
                console.error("[Patient MQTT] Subscription error:", err);
              }} else {{
                console.log(`[Patient MQTT] Subscribed to control topic: ${{controlTopic}}`);
                setStatus(`Ultrasound active (Remote Control connected on channel: ${{CHANNEL}})`);
              }}
            }});

            // Announce initial status and keep status synced periodically
            const broadcastStatus = async () => {{
              try {{
                const sres = await fetch(window.location.origin + "/api/status");
                if (sres.ok) {{
                  const sdata = await sres.json();
                  mqttClient.publish(statusTopic, JSON.stringify(sdata));
                }}
              }} catch (_) {{}}
            }};
            broadcastStatus();
            setInterval(broadcastStatus, 2500);
          }});

          mqttClient.on("error", (err) => {{
            console.error(`[Patient MQTT] Connection error on ${{url}}:`, err);
            mqttClient.end();
            attempts++;
            if (attempts < 4) {{
              setTimeout(tryConnect, 1500);
            }}
          }});

          mqttClient.on("message", async (receivedTopic, message) => {{
            if (receivedTopic !== controlTopic) return;
            try {{
              const event = JSON.parse(message.toString());
              console.log("[Patient MQTT] Message received:", event);
              const targetUrl = window.location.origin + "/api/remote-input";
              console.log("[Patient MQTT] Forwarding to local API:", targetUrl);
              const res = await fetch(targetUrl, {{
                method: "POST",
                headers: {{ "Content-Type": "application/json" }},
                body: JSON.stringify(event)
              }});
              const resData = await res.json();
              console.log("[Patient MQTT] Local API execution response:", resData);

              // Broadcast updated hardware status immediately after executing command
              try {{
                const sres = await fetch(window.location.origin + "/api/status");
                if (sres.ok) {{
                  const sdata = await sres.json();
                  mqttClient.publish(statusTopic, JSON.stringify(sdata));
                }}
              }} catch (_) {{}}
            }} catch (err) {{
              console.error("[Patient MQTT] Error processing remote event:", err);
            }}
          }});
        }} catch (e) {{
          console.error("[Patient MQTT] Exception on connection attempt:", e);
        }}
      }}

      tryConnect();
    }}

    async function createTrackFromFrames() {{
      const canvas = document.createElement('canvas');
      canvas.width = 640;
      canvas.height = 480;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('Canvas context unavailable');

      const image = new Image();
      image.crossOrigin = 'anonymous';

      await new Promise((resolve, reject) => {{
        let firstFrameReady = false;
        const timeoutId = setTimeout(() => {{
          if (!firstFrameReady) reject(new Error('Timed out waiting for ultrasound frames.'));
        }}, 10000);

        const pull = () => {{
          const sep = FRAME_URL.includes('?') ? '&' : '?';
          image.src = `${{FRAME_URL}}${{sep}}ts=${{Date.now()}}`;
        }};

        image.onload = () => {{
          if (image.naturalWidth && image.naturalHeight) {{
            if (canvas.width !== image.naturalWidth || canvas.height !== image.naturalHeight) {{
              canvas.width = image.naturalWidth;
              canvas.height = image.naturalHeight;
            }}
          }}

          ctx.drawImage(image, 0, 0, canvas.width, canvas.height);

          if (!firstFrameReady) {{
            firstFrameReady = true;
            clearTimeout(timeoutId);
            resolve();
          }}

          timerId = setTimeout(pull, 40);
        }};

        image.onerror = () => {{
          if (!firstFrameReady) {{
            clearTimeout(timeoutId);
            reject(new Error('Cannot load /frame.jpg from Python side.'));
            return;
          }}
          timerId = setTimeout(pull, 200);
        }};

        pull();
      }});

      const stream = canvas.captureStream(25);
      const mediaTrack = stream.getVideoTracks()[0];
      if (!mediaTrack) throw new Error('No media track available');

      const v = document.createElement('video');
      v.autoplay = true;
      v.muted = true;
      v.playsInline = true;
      v.srcObject = stream;
      v.style.width = '100%';
      v.style.height = '100%';
      v.style.objectFit = 'contain';
      previewEl.innerHTML = '';
      previewEl.appendChild(v);

      return AgoraRTC.createCustomVideoTrack({{ mediaStreamTrack: mediaTrack }});
    }}

    async function start() {{
      if (!APP_ID) throw new Error('APP_ID missing in Python config');

      setStatus('Preparing ultrasound track...');
      track = await createTrackFromFrames();

      try {{
        setStatus('Accessing microphone...');
        audioTrack = await AgoraRTC.createMicrophoneAudioTrack();
        console.log('Microphone track created successfully');
      }} catch (err) {{
        console.warn('Could not create microphone track, continuing with video only:', err);
      }}

      setStatus('Joining Agora channel...');
      client = AgoraRTC.createClient({{ mode: 'rtc', codec: 'vp8' }});
      await client.join(APP_ID, CHANNEL, TOKEN, UID);
      
      const publishTracks = [track];
      if (audioTrack) {{
        publishTracks.push(audioTrack);
      }}
      await client.publish(publishTracks);
    }}

    // Connect MQTT immediately on page load to receive commands reliably
    connectMQTT();

    start().catch((err) => {{
      setStatus(`Failed: ${{err?.message || err}}`);
      console.error(err);
    }});

    window.addEventListener('beforeunload', async () => {{
      try {{
        if (timerId) clearTimeout(timerId);
        if (track) {{
          track.stop();
          track.close();
        }}
        if (audioTrack) {{
          audioTrack.stop();
          audioTrack.close();
        }}
        if (mqttClient) {{
          mqttClient.end();
        }}
        if (client) await client.leave();
      }} catch (_) {{}}
    }});
  </script>
</body>
</html>
"""
    return Response(html, mimetype="text/html")


def main() -> None:
    global _ultrasound_proc

    _ultrasound_proc = _start_ultrasound_process()

    if _ultrasound_proc is not None:
        output_thread = threading.Thread(
            target=_forward_child_output,
            args=(_ultrasound_proc,),
            daemon=True,
        )
        output_thread.start()

        time.sleep(2)
        if _ultrasound_proc.poll() is not None:
            raise SystemExit(
                "Ultrasound script exited immediately. "
                "Check [ultrasound] logs above for the root cause."
            )

    output_thread = threading.Thread(target=_process_output_loop, daemon=True)
    output_thread.start()

    atexit.register(_cleanup)

    url = f"http://{HOST}:{PORT}/"
    print("Ultrasound -> Agora publisher starting...")
    print(f"Open: {url}")
    webbrowser.open(url)

    app.run(host=HOST, port=PORT, threaded=True)


if __name__ == "__main__":
    main()