"""
Linux keyboard reader for the talk shortcut: reads /dev/input/event* kernel keyboard devices
directly (pure Python, works the same on X11, Wayland, GNOME and KDE).
"""

import glob
import os
import select
import struct
import subprocess
import threading
from typing import Callable, List

from .base import OSResult

EV_KEY = 1

# Kernel key codes -> shortcut key names (as the dashboard's shortcut recorder writes them, lowercased).
KEY_MAP = {
    29: "ctrl", 97: "ctrl",        # Left & Right Ctrl
    56: "alt", 100: "alt",         # Left & Right Alt
    42: "shift", 54: "shift",      # Left & Right Shift
    125: "super", 126: "super",    # Left & Right Super (Meta)
    57: "space", 58: "capslock", 15: "tab",
    28: "enter", 1: "escape",
    30: "a", 48: "b", 46: "c", 32: "d", 18: "e", 33: "f", 34: "g", 35: "h", 23: "i",
    36: "j", 37: "k", 38: "l", 50: "m", 49: "n", 24: "o", 25: "p", 16: "q", 19: "r",
    31: "s", 20: "t", 22: "u", 47: "v", 17: "w", 45: "x", 21: "y", 44: "z",
    2: "1", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6", 8: "7", 9: "8", 10: "9", 11: "0",
    59: "f1", 60: "f2", 61: "f3", 62: "f4", 63: "f5", 64: "f6", 65: "f7", 66: "f8", 67: "f9", 68: "f10",
    87: "f11", 88: "f12",
}


def find_keyboard_devices() -> List[str]:
    """Physical keyboards under /dev/input/by-id (falls back to every event device there)."""
    devices = []
    by_id_kbds = glob.glob("/dev/input/by-id/*kbd*") + glob.glob("/dev/input/by-id/*keyboard*")
    for path in by_id_kbds:
        try:
            real_path = os.path.realpath(path)
            if real_path not in devices:
                devices.append(real_path)
        except Exception:
            pass
    if not devices:
        for event_path in sorted(glob.glob("/dev/input/by-id/*event*")):
            try:
                real_path = os.path.realpath(event_path)
                if real_path not in devices:
                    devices.append(real_path)
            except Exception:
                pass
    return devices


class LinuxKeyboard:
    """Calls on_key(name, is_press) for every known key. Can't swallow keys (the return value is ignored)."""

    def __init__(self, on_key: Callable[[str, bool], bool]):
        self.on_key = on_key
        self._stop = threading.Event()

    def start(self) -> OSResult:
        self._unbind_system_conflicts()
        devices = find_keyboard_devices()
        self._stop.clear()
        for dev_path in devices:
            threading.Thread(target=self._read, args=(dev_path,), daemon=True,
                             name=f"JarvisKbdReader-{os.path.basename(dev_path)}").start()
        if not devices:
            return OSResult(False, error="No keyboards found under /dev/input. Add your user to the input group.")
        return OSResult(True, detail=f"kernel listener on {len(devices)} input devices")

    def stop(self):
        self._stop.set()

    def shortcut_released(self):
        """Release any stuck OS modifier keys (Ctrl/Alt/Shift/Super) after the shortcut."""
        try:
            subprocess.run(["xdotool", "keyup", "Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R",
                            "Super_L", "Super_R"], capture_output=True, timeout=1)
        except Exception:
            pass

    @staticmethod
    def _unbind_system_conflicts():
        """IBus and GNOME bind Super+Space to switching input source: unbind so only Jarvis reacts."""
        for args in (["org.freedesktop.ibus.general.hotkey", "trigger", "@as []"],
                     ["org.gnome.desktop.wm.keybindings", "switch-input-source", "@as []"]):
            try:
                subprocess.run(["gsettings", "set", *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except Exception:
                pass

    def _read(self, dev_path: str):
        """struct input_event { struct timeval time; __u16 type; __u16 code; __s32 value; } (24 bytes, 64-bit)."""
        try:
            fd = open(dev_path, "rb", buffering=0)
        except Exception:
            return
        fmt = "QQHHi"
        size = struct.calcsize(fmt)
        with fd:
            while not self._stop.is_set():
                try:
                    r, _, _ = select.select([fd], [], [], 0.5)
                    if not r:
                        continue
                    data = fd.read(size)
                    if not data or len(data) < size:
                        continue
                    _, _, ev_type, ev_code, ev_value = struct.unpack(fmt, data)
                    if ev_type == EV_KEY and ev_code in KEY_MAP:
                        self.on_key(KEY_MAP[ev_code], ev_value in (1, 2))  # 1 press, 2 repeat, 0 release
                except Exception:
                    break
