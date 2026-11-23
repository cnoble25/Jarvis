"""
The talk shortcut: hold a key combination anywhere on the computer to talk to Jarvis.

What "held" means is the same on every OS and lives here:
1. Held-key accumulation (the keys don't have to go down at the same instant)
2. A release buffer (200ms) so letting go of one key a little early doesn't cut the recording off
3. Changing the shortcut live from the dashboard

Reading the keyboard is the OS interface's job (daemon/os_interface): kernel input devices on
Linux, a Quartz event tap on macOS.
"""

import threading
import time
from typing import Callable, Optional, Set

from daemon.os_interface import OSInterface, get_os


class HotkeyInterceptor:
    def __init__(
        self,
        shortcut_str: Optional[str] = None,
        on_press_callback: Optional[Callable[[], None]] = None,
        on_release_callback: Optional[Callable[[], None]] = None,
        release_buffer_ms: int = 200,
        system: Optional[OSInterface] = None,
    ):
        """
        :param shortcut_str: Key combination (e.g. "Ctrl + Space"); defaults to the OS's default.
        :param on_press_callback: Called when the whole combination is held.
        :param on_release_callback: Called once it's let go (after the release buffer).
        :param release_buffer_ms: How long after a key goes up before the shortcut counts as released.
        """
        self.system = system or get_os()
        self.on_press_callback = on_press_callback
        self.on_release_callback = on_release_callback
        self.release_buffer_ms = release_buffer_ms

        self.target_keys: Set[str] = set()
        self.active_keys: Set[str] = set()
        self.listening = False
        self._shortcut_problem = ""  # the chosen keys can't work on this OS
        self._keyboard_problem = ""  # the keyboard reader isn't running (permission, no devices)

        self._is_recording_active = False
        self._release_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._keyboard = None
        self._parse_shortcut(shortcut_str or self.system.default_hotkey)

    def _parse_shortcut(self, shortcut_str: str):
        """"Ctrl + Space" -> {'ctrl', 'space'}."""
        with self._lock:
            self.shortcut_str = shortcut_str
            self.target_keys = {p.strip().lower() for p in shortcut_str.split("+") if p.strip()}
            print(f"[HotkeyInterceptor] Updated target keybinding: {self.shortcut_str} (Target keys: {self.target_keys})", flush=True)
        self._check_holdable()

    @property
    def problem(self) -> str:
        """Why the shortcut can't work right now, in words the user can act on ("" when it can)."""
        return self._shortcut_problem or self._keyboard_problem

    def _check_holdable(self):
        reasons = [why for key, why in self.system.unholdable_keys().items() if key in self.target_keys]
        self._shortcut_problem = (f"{reasons[0]} Pick another talk shortcut in Settings, such as "
                                  f"{self.system.default_hotkey}.") if reasons else ""
        if self._shortcut_problem:
            print(f"[HotkeyInterceptor] {self._shortcut_problem}", flush=True)

    def update_shortcut(self, new_shortcut_str: str):
        """Dynamically updates the target shortcut combination from GUI IPC settings."""
        self._parse_shortcut(new_shortcut_str)

    def _targets(self) -> Set[str]:
        return self.target_keys

    def start(self):
        """Starts this OS's system-wide keyboard reader."""
        self._keyboard = self.system.keyboard(self.handle_key_event, self._targets)
        if self._keyboard is None:
            self._keyboard_problem = f"The talk shortcut isn't supported on {self.system.name} yet."
        else:
            res = self._keyboard.start()
            self.listening = res.ok
            self._keyboard_problem = "" if res.ok else res.error
            if res.ok:
                print(f"[HotkeyInterceptor] Listening for '{self.shortcut_str}' system-wide ({res.detail})", flush=True)
        if self._keyboard_problem:
            print(f"[HotkeyInterceptor] {self._keyboard_problem}", flush=True)

    def handle_key_event(self, key_name: str, is_press: bool):
        """Processes key press / release event with held-key accumulation and release buffer timer."""
        key_lower = key_name.lower()
        if not self.listening:  # a permission granted after startup: keys arriving means it works now
            self.listening, self._keyboard_problem = True, ""

        with self._lock:
            if is_press:
                # Cancel pending release buffer timer if user is still pressing/holding keys
                if self._release_timer and self._release_timer.is_alive():
                    self._release_timer.cancel()
                    self._release_timer = None

                self.active_keys.add(key_lower)

                if self.target_keys and self.target_keys.issubset(self.active_keys):
                    if not self._is_recording_active:
                        self._is_recording_active = True
                        print(f"\n[HotkeyInterceptor] 🔴 System-Wide Global Hold-to-Talk TRIGGERED ({self.shortcut_str})!", flush=True)
                        if self.on_press_callback:
                            self.on_press_callback()

            else:  # Key release
                self.active_keys.discard(key_lower)

                # Trigger release buffer timer when target key is released
                if self._is_recording_active:
                    if self._release_timer is None or not self._release_timer.is_alive():
                        self._release_timer = threading.Timer(self.release_buffer_ms / 1000.0, self._finalize_release)
                        self._release_timer.start()

    def _finalize_release(self):
        """Invoked after release_buffer_ms passes with no new key presses."""
        with self._lock:
            if self._is_recording_active:
                self._is_recording_active = False
                if self._keyboard is not None:
                    self._keyboard.shortcut_released()
                self.active_keys.clear()
                print(f"[HotkeyInterceptor] ⏹️ System-Wide Global Hold-to-Talk RELEASED (Buffer {self.release_buffer_ms}ms passed)!", flush=True)
                if self.on_release_callback:
                    self.on_release_callback()
                self._release_timer = None

    def stop(self):
        """Stops the keyboard reader."""
        if self._keyboard is not None:
            self._keyboard.stop()
        with self._lock:
            if self._release_timer and self._release_timer.is_alive():
                self._release_timer.cancel()
        print("[HotkeyInterceptor] Stopped cleanly.", flush=True)


if __name__ == "__main__":
    interceptor = HotkeyInterceptor(
        on_press_callback=lambda: print(">>> RECORDING STARTED <<<"),
        on_release_callback=lambda: print(">>> RECORDING FINISHED <<<"),
    )
    interceptor.start()
    print(f"\nHold {interceptor.shortcut_str} in any app... Ctrl+C to exit.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        interceptor.stop()
