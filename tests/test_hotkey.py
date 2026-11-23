"""The talk shortcut: held-key logic shared by every OS, and the macOS reader's choices (no real keyboard)."""

import time

from daemon.ipc.hotkey_interceptor import HotkeyInterceptor
from daemon.os_interface import OSResult
from daemon.os_interface.base import OSInterface
from daemon.os_interface.keyboard_macos import MODIFIER_MASKS, MacKeyboard
from daemon.os_interface.linux import LinuxOS
from daemon.os_interface.macos import MacOS


class FakeKeyboard:
    def __init__(self, ok=True):
        self.ok, self.released = ok, 0

    def start(self):
        return OSResult(self.ok, detail="fake", error="" if self.ok else "Needs permission.")

    def stop(self):
        pass

    def shortcut_released(self):
        self.released += 1


class FakeOS(OSInterface):
    name = "FakeOS"
    default_hotkey = "Alt + Space"

    def __init__(self, keyboard=None, unholdable=None):
        self.kb, self._unholdable = keyboard or FakeKeyboard(), unholdable or {}

    def keyboard(self, on_key, targets):
        return self.kb

    def unholdable_keys(self):
        return self._unholdable


def interceptor(system, shortcut=None):
    events = []
    hk = HotkeyInterceptor(shortcut, on_press_callback=lambda: events.append("press"),
                           on_release_callback=lambda: events.append("release"), release_buffer_ms=20, system=system)
    hk.start()
    return hk, events


def test_holding_the_whole_combination_talks_and_letting_go_stops():
    system = FakeOS()
    hk, events = interceptor(system, "Ctrl + Space")
    hk.handle_key_event("ctrl", True)
    assert events == []
    hk.handle_key_event("space", True)
    hk.handle_key_event("space", True)  # key repeat: still one press
    assert events == ["press"]
    hk.handle_key_event("space", False)
    hk.handle_key_event("ctrl", False)
    time.sleep(0.1)
    assert events == ["press", "release"] and system.kb.released == 1


def test_each_os_picks_its_own_default_shortcut():
    assert interceptor(FakeOS())[0].shortcut_str == "Alt + Space"
    assert LinuxOS.default_hotkey == "Super + Space"
    assert MacOS.default_hotkey == "Alt + Space"  # Cmd + Space is Spotlight


def test_a_key_that_cant_be_held_says_so_and_how_to_fix_it():
    hk, _ = interceptor(FakeOS(unholdable={"capslock": "Caps Lock can't be held."}), "CapsLock + Space")
    assert hk.problem == "Caps Lock can't be held. Pick another talk shortcut in Settings, such as Alt + Space."
    hk.update_shortcut("Alt + Space")
    assert hk.problem == ""


def test_missing_permission_is_reported_until_keys_arrive():
    hk, _ = interceptor(FakeOS(keyboard=FakeKeyboard(ok=False)), "Alt + Space")
    assert hk.problem == "Needs permission." and not hk.listening
    hk.handle_key_event("alt", True)  # granted later: keys arriving mean it works
    assert hk.problem == "" and hk.listening


def test_os_without_a_keyboard_reader_says_so():
    hk, _ = interceptor(OSInterface(), "Alt + Space")
    assert "isn't supported" in hk.problem


# ---- macOS: what the event tap swallows -------------------------------------------------------

def mac_keyboard(shortcut, swallowing=True):
    kb = MacKeyboard(lambda *_: None, lambda: set(shortcut))
    kb.swallowing = swallowing
    return kb


def test_mac_swallows_the_shortcut_space_so_it_isnt_typed():
    kb = mac_keyboard({"alt", "space"})
    option = MODIFIER_MASKS["alt"]
    assert kb._swallow("space", True, option) is True
    assert kb._swallow("space", True, option) is True     # key repeat while held
    assert kb._swallow("space", False, 0) is True          # and its release, even after Option is up


def test_mac_leaves_ordinary_typing_alone():
    kb = mac_keyboard({"alt", "space"})
    assert kb._swallow("space", True, 0) is False          # a plain space
    assert kb._swallow("space", False, 0) is False
    assert kb._swallow("a", True, MODIFIER_MASKS["alt"]) is False


def test_mac_listen_only_never_swallows():
    kb = mac_keyboard({"alt", "space"}, swallowing=False)
    assert kb._swallow("space", True, MODIFIER_MASKS["alt"]) is False


def test_mac_rejects_caps_lock():
    assert "capslock" in MacOS().unholdable_keys() and LinuxOS().unholdable_keys() == {}


def test_mac_without_permission_reports_it_even_though_a_tap_could_be_created(monkeypatch):
    # macOS creates a listen-only tap without permission, then delivers it no keys: check the permission.
    kb = mac_keyboard({"super", "shift", "space"})
    asked = []
    monkeypatch.setattr(MacKeyboard, "_permitted", staticmethod(lambda: False))
    monkeypatch.setattr(MacKeyboard, "_ask_for_permission", staticmethod(lambda: asked.append(True)))
    monkeypatch.setattr(MacKeyboard, "_run", lambda *a: (_ for _ in ()).throw(AssertionError("no tap without permission")))
    monkeypatch.setattr("daemon.os_interface.keyboard_macos.responsible_app", lambda: "Ghostty")
    res = kb.start()
    kb.stop()
    assert not res.ok and asked == [True]
    assert "Accessibility and turn on Ghostty" in res.error
