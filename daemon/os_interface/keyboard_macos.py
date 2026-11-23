"""
macOS keyboard reader for the talk shortcut: a Quartz event tap sees every key press system-wide.

Permission (System Settings > Privacy & Security), granted to the app Jarvis runs from (your
terminal, or Python when it starts at login):
  Accessibility     the tap can also swallow the shortcut's own key, so holding Option + Space
                    doesn't type a space into the app you're in.
  Input Monitoring  enough to see keys (the shortcut's key still reaches the focused app).
Without either, macOS shows its permission prompt and Jarvis keeps checking, so the shortcut
starts working as soon as it's granted, without a restart.
"""

import queue
import threading
from typing import Callable, Optional, Set

from .base import OSResult

# Virtual key codes (Carbon kVK_*) -> shortcut key names (as the dashboard recorder writes them, lowercased).
KEY_MAP = {
    49: "space", 36: "enter", 48: "tab", 53: "escape",
    0: "a", 11: "b", 8: "c", 2: "d", 14: "e", 3: "f", 5: "g", 4: "h", 34: "i", 38: "j", 40: "k", 37: "l",
    46: "m", 45: "n", 31: "o", 35: "p", 12: "q", 15: "r", 1: "s", 17: "t", 32: "u", 9: "v", 13: "w",
    7: "x", 16: "y", 6: "z",
    18: "1", 19: "2", 20: "3", 21: "4", 23: "5", 22: "6", 26: "7", 28: "8", 25: "9", 29: "0",
    122: "f1", 120: "f2", 99: "f3", 118: "f4", 96: "f5", 97: "f6", 98: "f7", 100: "f8", 101: "f9",
    109: "f10", 103: "f11", 111: "f12",
}
# Modifier keys arrive as flag changes. Command is "super", Option is "alt" (what the recorder writes).
MODIFIER_KEYS = {55: "super", 54: "super", 56: "shift", 60: "shift", 59: "ctrl", 62: "ctrl",
                 58: "alt", 61: "alt", 63: "fn"}
MODIFIER_MASKS = {"super": 1 << 20, "shift": 1 << 17, "ctrl": 1 << 18, "alt": 1 << 19, "fn": 1 << 23}
# Caps Lock only reports on/off toggles, never held or released, so it can't be held to talk.
UNHOLDABLE = {"capslock": "Caps Lock can't be held to talk on macOS (it only reports on/off)."}

PERMISSION_HELP = ("macOS hasn't given Jarvis permission to see the keyboard. Open System Settings > Privacy & "
                   "Security > Accessibility and turn on {app}. The shortcut starts working within a few seconds; "
                   "if not, restart Jarvis.")


def responsible_app() -> str:
    """
    The app macOS charges Jarvis's permissions to: the terminal it was started from (Ghostty,
    Terminal), or Python itself when nothing launched it.
    """
    import ctypes
    import os
    import re
    import subprocess
    try:
        lookup = ctypes.CDLL("/usr/lib/libSystem.B.dylib").responsibility_get_pid_responsible_for_pid
        lookup.restype, lookup.argtypes = ctypes.c_int, [ctypes.c_int]
        pid = lookup(os.getpid())
        path = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)], capture_output=True, text=True, timeout=2).stdout
        m = re.search(r"([^/]+)\.app/", path)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "the app Jarvis runs from (your terminal app, or Python)"

TAP_DISABLED = (0xFFFFFFFE, 0xFFFFFFFF)  # kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput
PERMISSION_POLL_SECONDS = 3


def held_modifiers(flags: int) -> Set[str]:
    return {name for name, mask in MODIFIER_MASKS.items() if flags & mask}


class MacKeyboard:
    def __init__(self, on_key: Callable[[str, bool], None], targets: Callable[[], Set[str]]):
        """
        on_key(name, is_press) runs on a worker thread (the tap callback must return within
        about a second or macOS disables it). targets() is the shortcut's key set.
        """
        self.on_key = on_key
        self.targets = targets
        self.swallowing = False  # True with Accessibility: the shortcut's key doesn't reach other apps
        self._events: "queue.Queue[Optional[tuple]]" = queue.Queue()
        self._swallowed: Set[str] = set()  # keys whose press was swallowed: swallow their release too
        self._down: Set[str] = set()       # non-modifier keys currently down
        self._loop = None
        self._tap = None
        self._stop = threading.Event()

    # ---- Lifecycle ----------------------------------------------------------------------------

    def start(self) -> OSResult:
        threading.Thread(target=self._dispatch, daemon=True, name="JarvisKeyDispatch").start()
        try:
            import Quartz  # noqa: F401
        except ImportError:
            return OSResult(False, error="The pyobjc-framework-Quartz package is missing. Run: pip install -r requirements.txt")
        # Check the permission itself: without it macOS still lets a listen-only tap be created, then
        # silently delivers it no key events, so "the tap exists" doesn't mean the shortcut works.
        if self._permitted():
            started, result = threading.Event(), {}
            threading.Thread(target=self._run, args=(started, result), daemon=True, name="JarvisKeyTap").start()
            started.wait(5)
            if result.get("ok"):
                mode = "and swallows the shortcut key" if self.swallowing else "(Input Monitoring only: the shortcut key also reaches the focused app)"
                return OSResult(True, detail=f"Quartz event tap listening {mode}")
        self._ask_for_permission()
        threading.Thread(target=self._wait_for_permission, daemon=True, name="JarvisKeyPermission").start()
        return OSResult(False, error=PERMISSION_HELP.format(app=responsible_app()))

    def stop(self):
        self._stop.set()
        self._events.put(None)
        if self._loop is not None:
            import Quartz
            Quartz.CFRunLoopStop(self._loop)

    def shortcut_released(self):
        self._swallowed.clear()

    # ---- Permission -----------------------------------------------------------------------------

    @staticmethod
    def _permitted() -> bool:
        """Accessibility (see and swallow keys) or Input Monitoring (see keys) is granted."""
        try:
            import ApplicationServices as AS
            if AS.AXIsProcessTrusted():
                return True
        except Exception:
            pass
        try:
            import Quartz
            return bool(Quartz.CGPreflightListenEventAccess())
        except Exception:
            return False

    @staticmethod
    def _ask_for_permission():
        """Show macOS's own prompts (each appears once; after that the user goes to System Settings)."""
        try:
            import ApplicationServices as AS
            AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True})
        except Exception:
            pass
        try:
            import Quartz
            Quartz.CGRequestListenEventAccess()
        except Exception:
            pass

    def _wait_for_permission(self):
        while not self._stop.wait(PERMISSION_POLL_SECONDS):
            if not self._permitted():
                continue
            started, result = threading.Event(), {}
            threading.Thread(target=self._run, args=(started, result), daemon=True, name="JarvisKeyTap").start()
            started.wait(5)
            if result.get("ok"):
                print("[HotkeyInterceptor] macOS permission granted: the talk shortcut is listening now.", flush=True)
                return

    # ---- The event tap --------------------------------------------------------------------------

    def _run(self, started: threading.Event, result: dict):
        import Quartz
        mask = (Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown) | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
                | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged))
        tap = None
        for option, swallows in ((Quartz.kCGEventTapOptionDefault, True), (Quartz.kCGEventTapOptionListenOnly, False)):
            tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap, option, mask,
                                          self._callback, None)
            if tap is not None:
                self.swallowing = swallows
                break
        if tap is None:
            result["ok"] = False
            started.set()
            return
        self._tap = tap
        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        self._loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(self._loop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)
        result["ok"] = True
        started.set()
        Quartz.CFRunLoopRun()

    def _callback(self, proxy, event_type, event, refcon):
        import Quartz
        if event_type in TAP_DISABLED:  # macOS turned the tap off (slow callback, secure input): back on
            if self._tap is not None:
                Quartz.CGEventTapEnable(self._tap, True)
            return event
        try:
            keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
            flags = Quartz.CGEventGetFlags(event)
            if event_type == Quartz.kCGEventFlagsChanged:
                name = MODIFIER_KEYS.get(keycode)
                if name:
                    self._events.put((name, bool(flags & MODIFIER_MASKS[name])))
                return event  # modifiers always pass through, so the OS never sees one stuck
            name = KEY_MAP.get(keycode)
            if name is None:
                return event
            is_press = event_type == Quartz.kCGEventKeyDown
            self._events.put((name, is_press))
            return None if self._swallow(name, is_press, flags) else event
        except Exception:
            return event

    def _swallow(self, name: str, is_press: bool, flags: int) -> bool:
        """Decided here, on the tap thread, from the event's own modifier flags: no waiting on the worker."""
        if is_press:
            self._down.add(name)
            targets = self.targets()
            if name in targets and targets <= (held_modifiers(flags) | self._down):
                self._swallowed.add(name)
        else:
            self._down.discard(name)
        if not self.swallowing:
            return False
        if is_press:
            return name in self._swallowed
        if name in self._swallowed:
            self._swallowed.discard(name)
            return True
        return False

    def _dispatch(self):
        while True:
            item = self._events.get()
            if item is None:
                return
            try:
                self.on_key(*item)
            except Exception as err:
                print(f"[HotkeyInterceptor] Key handling error: {err}", flush=True)
