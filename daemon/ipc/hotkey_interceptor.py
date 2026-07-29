"""
Linux Native Kernel Input Event Hotkey Interceptor (Sub-Task 4.3)
Intercepts hold-to-talk key combinations system-wide across ALL Linux desktop applications
(Wayland, X11, GNOME, KDE, Bazzite) regardless of which window is focused.

Features:
1. Reads /dev/input/event* kernel keyboard devices directly in pure Python (zero C/gcc dependency)
2. Held-Key Set accumulation buffer (no simultaneous instant press required)
3. Release buffer timer (200ms) to prevent premature audio cutoff on release
4. Dynamic keybind reconfiguration over IPC from GUI Settings menu
"""

import os
import glob
import time
import struct
import select
import threading
import fcntl
from typing import Dict, Any, Set, Optional, Callable, List

# Linux Kernel Input Event Constants
EV_KEY = 1
EVIOCGRAB = 0x40044590  # Linux Kernel ioctl to exclusively grab/ungrab input event device

# Keycode mapping for Linux kernel event codes -> key names
KEY_MAP = {
    29: "ctrl",    97: "ctrl",      # Left & Right Ctrl
    56: "alt",     100: "alt",      # Left & Right Alt
    42: "shift",   54: "shift",     # Left & Right Shift
    125: "super",  126: "super",    # Left & Right Super (Meta)
    57: "space",                    # Spacebar
    28: "enter",   1: "escape",
    30: "a", 48: "b", 46: "c", 32: "d", 18: "e", 33: "f", 34: "g", 35: "h", 23: "i",
    36: "j", 37: "k", 38: "l", 50: "m", 49: "n", 24: "o", 25: "p", 16: "q", 19: "r",
    31: "s", 20: "t", 22: "u", 47: "v", 17: "w", 45: "x", 21: "y", 44: "z"
}


def find_keyboard_devices() -> List[str]:
    """
    Scans /dev/input/ for active keyboard event devices.
    """
    devices = []
    # Check /dev/input/by-id/ first
    by_id_kbds = glob.glob("/dev/input/by-id/*kbd*") + glob.glob("/dev/input/by-id/*keyboard*")
    for d in by_id_kbds:
        try:
            real_path = os.path.realpath(d)
            if real_path not in devices:
                devices.append(real_path)
        except Exception:
            pass

    # Fallback scan all event devices
    for event_path in sorted(glob.glob("/dev/input/event*")):
        if event_path not in devices:
            try:
                # Test opening for reading
                with open(event_path, "rb") as f:
                    devices.append(event_path)
            except (PermissionError, OSError):
                pass

    return devices


class HotkeyInterceptor:
    def __init__(
        self,
        shortcut_str: str = "Ctrl + Shift + Space",
        on_press_callback: Optional[Callable[[], None]] = None,
        on_release_callback: Optional[Callable[[], None]] = None,
        release_buffer_ms: int = 200
    ):
        """
        Initialize Global Hotkey Interceptor.
        
        :param shortcut_str: Key combination string (e.g. "Ctrl + Space", "Alt + Space").
        :param on_press_callback: Function called when shortcut keys are held.
        :param on_release_callback: Function called when shortcut keys are released after buffer.
        :param release_buffer_ms: Buffer delay in milliseconds upon key release before stopping recording.
        """
        self.shortcut_str = shortcut_str
        self.on_press_callback = on_press_callback
        self.on_release_callback = on_release_callback
        self.release_buffer_ms = release_buffer_ms

        self.target_keys: Set[str] = set()
        self.active_keys: Set[str] = set()

        self._is_recording_active = False
        self._is_grabbed = False
        self._release_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_threads: List[threading.Thread] = []
        self._device_fds: Dict[str, Any] = {}

        self.use_grab = False  # Set True only if exclusive device grab is explicitly desired
        self._parse_shortcut(shortcut_str)

    def _parse_shortcut(self, shortcut_str: str):
        """
        Parses shortcut string into target key set (e.g. "Ctrl + Space" -> {'ctrl', 'space'}).
        """
        with self._lock:
            self.shortcut_str = shortcut_str
            parts = [p.strip().lower() for p in shortcut_str.split("+")]
            self.target_keys = set(parts)
            print(f"[HotkeyInterceptor] Updated target keybinding: {self.shortcut_str} (Target keys: {self.target_keys})", flush=True)

    def update_shortcut(self, new_shortcut_str: str):
        """
        Dynamically updates the target shortcut combination from GUI IPC settings.
        """
        self._parse_shortcut(new_shortcut_str)

    def _unbind_system_conflicts(self):
        """
        Unbinds system-level shortcut conflicts (such as Linux IBus)
        so pressing Ctrl+Space triggers ONLY Jarvis without popups.
        """
        try:
            import subprocess
            subprocess.run(
                ["gsettings", "set", "org.freedesktop.ibus.general.hotkey", "trigger", "['<Super>space']"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2
            )
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.wm.keybindings", "activate-window-menu", "['<Alt>space']"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2
            )
        except Exception:
            pass

    def start(self):
        """
        Starts Linux Kernel event device readers in background threads.
        """
        self._unbind_system_conflicts()
        kbd_devices = find_keyboard_devices()
        print(f"[HotkeyInterceptor] Active system-wide kernel listener across {len(kbd_devices)} input devices for '{self.shortcut_str}'", flush=True)

        self._stop_event.clear()
        for dev_path in kbd_devices:
            t = threading.Thread(target=self._device_reader, args=(dev_path,), daemon=True, name=f"JarvisKbdReader-{os.path.basename(dev_path)}")
            t.start()
            self._worker_threads.append(t)

    def _grab_devices(self):
        """
        Grabs active keyboard devices exclusively at the kernel level using EVIOCGRAB if enabled.
        """
        if not self.use_grab or self._is_grabbed:
            return
        self._is_grabbed = True
        for path, fd in list(self._device_fds.items()):
            try:
                fcntl.ioctl(fd.fileno(), EVIOCGRAB, 1)
            except Exception:
                pass

    def _ungrab_devices(self):
        """
        Releases exclusive kernel grab on active keyboard devices and emits synthetic
        modifier keyup signals so Control/Alt/Shift are never left stuck in the OS.
        """
        if self._is_grabbed:
            self._is_grabbed = False
            for path, fd in list(self._device_fds.items()):
                try:
                    fcntl.ioctl(fd.fileno(), EVIOCGRAB, 0)
                except Exception:
                    pass

        # Release any stuck OS modifier keys (Ctrl/Alt/Shift/Super) via xdotool
        try:
            import subprocess
            subprocess.run(
                ["xdotool", "keyup", "Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R", "Super_L", "Super_R"],
                capture_output=True,
                timeout=1
            )
        except Exception:
            pass

    def _device_reader(self, dev_path: str):
        """
        Reads 24-byte kernel struct input_event from /dev/input/event*
        Format: struct input_event { struct timeval time; __u16 type; __u16 code; __s32 value; }
        """
        try:
            fd = open(dev_path, "rb", buffering=0)
            with self._lock:
                self._device_fds[dev_path] = fd
        except Exception:
            return

        # 64-bit Linux kernel struct format: QQHHi (24 bytes)
        struct_format = "QQHHi"
        struct_size = struct.calcsize(struct_format)

        while not self._stop_event.is_set():
            try:
                r, _, _ = select.select([fd], [], [], 0.5)
                if not r:
                    continue

                event_bytes = fd.read(struct_size)
                if not event_bytes or len(event_bytes) < struct_size:
                    continue

                _, _, ev_type, ev_code, ev_value = struct.unpack(struct_format, event_bytes)

                if ev_type == EV_KEY:
                    key_name = KEY_MAP.get(ev_code)
                    if key_name:
                        # ev_value: 1 = press, 2 = repeat, 0 = release
                        is_press = (ev_value in (1, 2))
                        self.handle_key_event(key_name, is_press)

            except Exception:
                break

        try:
            with self._lock:
                self._device_fds.pop(dev_path, None)
            fd.close()
        except Exception:
            pass

    def handle_key_event(self, key_name: str, is_press: bool):
        """
        Processes key press / release event with held-key accumulation and release buffer timer.
        """
        key_lower = key_name.lower()

        with self._lock:
            if is_press:
                # Cancel pending release buffer timer if user is still pressing/holding keys
                if self._release_timer and self._release_timer.is_alive():
                    self._release_timer.cancel()
                    self._release_timer = None

                self.active_keys.add(key_lower)

                # Check if target shortcut keys are held
                if self.target_keys.issubset(self.active_keys):
                    if not self._is_recording_active:
                        self._is_recording_active = True
                        self._grab_devices()  # Instantly grab devices to block space leakage
                        print(f"\n[HotkeyInterceptor] 🔴 System-Wide Global Hold-to-Talk TRIGGERED ({self.shortcut_str})!", flush=True)
                        if self.on_press_callback:
                            self.on_press_callback()

            else:  # Key release
                if key_lower in self.active_keys:
                    self.active_keys.remove(key_lower)

                # Trigger release buffer timer when target key is released
                if self._is_recording_active:
                    if self._release_timer is None or not self._release_timer.is_alive():
                        buffer_sec = self.release_buffer_ms / 1000.0
                        self._release_timer = threading.Timer(buffer_sec, self._finalize_release)
                        self._release_timer.start()

    def _finalize_release(self):
        """
        Invoked after release_buffer_ms passes with no new key presses.
        """
        with self._lock:
            if self._is_recording_active:
                self._is_recording_active = False
                self._ungrab_devices()  # Release kernel grab after hotkey release
                self.active_keys.clear()
                print(f"[HotkeyInterceptor] ⏹️ System-Wide Global Hold-to-Talk RELEASED (Buffer {self.release_buffer_ms}ms passed)!", flush=True)
                if self.on_release_callback:
                    self.on_release_callback()
                self._release_timer = None

    def stop(self):
        """
        Stops global hotkey listener threads.
        """
        self._stop_event.set()
        with self._lock:
            self._ungrab_devices()
            if self._release_timer and self._release_timer.is_alive():
                self._release_timer.cancel()
        print("[HotkeyInterceptor] Stopped cleanly.", flush=True)


if __name__ == "__main__":
    def on_press():
        print(">>> [GLOBAL HOTKEY DEMO] RECORDING STARTED! <<<")

    def on_release():
        print(">>> [GLOBAL HOTKEY DEMO] RECORDING FINISHED! <<<")

    interceptor = HotkeyInterceptor(
        shortcut_str="Ctrl + Space",
        on_press_callback=on_press,
        on_release_callback=on_release,
        release_buffer_ms=200
    )
    interceptor.start()

    print("\nPress & hold Ctrl + Space in ANY application (Chrome, VS Code, Terminal, etc.)... Press Ctrl+C to exit.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        interceptor.stop()
