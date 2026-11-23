"""The OS interface: the right implementation per OS, and macOS commands built correctly (all stubbed)."""

import os
import subprocess
import threading

import numpy as np
import pytest

from daemon.os_interface import OSInterface, POWER_ACTIONS, os_for_platform, play_samples
from daemon.os_interface.linux import LinuxOS
from daemon.os_interface.macos import MacOS
from daemon.tools.execution_engine import ExecutionEngine


class FakeShell:
    """Records commands; answers osascript reads from a fake Mac's state."""

    def __init__(self, volume="50", muted="false", running=""):
        self.calls, self.volume, self.muted, self.running = [], volume, muted, running

    def run(self, cmd, **_k):
        self.calls.append(cmd)
        script = " ".join(cmd[1:]) if cmd and cmd[0] == "osascript" else ""
        out = ""
        if "get volume settings" in script:
            out = f"output volume:{self.volume}, input volume:34, alert volume:100, output muted:{self.muted}\n"
        elif "is running" in script:
            out = self.running
        return subprocess.CompletedProcess(cmd, 0, out, "")


@pytest.fixture
def shell(monkeypatch):
    fake = FakeShell()
    monkeypatch.setattr(subprocess, "run", fake.run)
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **_k: fake.calls.append(cmd))
    return fake


def scripts(shell):
    return [" ".join(c[1:]) for c in shell.calls if c[0] == "osascript"]


@pytest.fixture
def mac_engine(shell):
    eng = ExecutionEngine.__new__(ExecutionEngine)
    eng._local = threading.local()
    eng._system = MacOS()
    eng.dry_run = True
    return eng


# ---- Choosing the implementation -------------------------------------------------------------

@pytest.mark.parametrize("platform,cls", [("linux", LinuxOS), ("darwin", MacOS)])
def test_each_os_gets_its_own_implementation(platform, cls):
    assert type(os_for_platform(platform)) is cls


def test_an_unsupported_os_fails_honestly_instead_of_running_linux_commands():
    win = os_for_platform("win32")
    assert win.name == "Windows"
    res = win.set_volume(40)
    assert not res.ok and "Windows" in res.error
    assert win.power_command("shutdown") is None and win.media_players() == []


@pytest.mark.parametrize("cls", [LinuxOS, MacOS])
def test_supported_oses_implement_every_action(cls):
    public = [n for n, v in vars(OSInterface).items() if callable(v) and not n.startswith("_") and n != "unsupported"]
    missing = [n for n in public if getattr(cls, n) is getattr(OSInterface, n)
               and n not in ("temp_audio_dir", "no_media_players_message", "overlay_insets", "unholdable_keys", "prepare_overlay_window",
                             "show_in_dock", "bring_app_forward", "running_apps")]
    assert missing == []
    assert all(cls().power_command(a) for a in POWER_ACTIONS)


# ---- macOS sound -----------------------------------------------------------------------------

def test_mac_reads_volume_and_mute(shell):
    shell.volume, shell.muted = "35", "true"
    state = MacOS().get_volume()
    assert state.level == 35 and state.muted


def test_mac_output_without_a_volume_control(shell):
    shell.volume = "missing value"
    assert MacOS().get_volume().level is None
    res = MacOS().change_volume(5)
    assert not res.ok and "doesn't have a volume" in res.error


def test_mac_volume_up_never_goes_past_100(shell):
    shell.volume = "98"
    assert MacOS().change_volume(5).ok
    assert scripts(shell)[-1] == "-e set volume output volume 100"


def test_mac_toggle_mute_flips_the_current_state(shell):
    shell.muted = "true"
    MacOS().set_mute(None)
    assert scripts(shell)[-1] == "-e set volume output muted false"


@pytest.mark.parametrize("action,script,spoken", [
    ("up", "-e set volume output volume 55", "Volume up, now 50%."),
    ("down", "-e set volume output volume 45", "Volume down, now 50%."),
    ("30%", "-e set volume output volume 30", "Volume set, now 50%."),
    ("mute", "-e set volume output muted true", "Muted."),
])
def test_mac_volume_through_the_engine(mac_engine, shell, action, script, spoken):
    res = mac_engine.execute_custom_tool("volume_control", {"action": action})
    assert script in scripts(shell) and res["spoken_confirmation"] == spoken


def test_speech_plays_with_afplay_and_cleans_up(shell):
    assert play_samples(np.zeros(2400, dtype=np.float32) + 0.1, 24000, os_interface=MacOS())
    cmd = shell.calls[-1]
    assert cmd[0] == "afplay" and cmd[1].endswith(".wav") and not os.path.exists(cmd[1])


def test_speech_falls_back_to_sounddevice_without_a_player(monkeypatch):
    import sys
    import types
    played = []
    monkeypatch.setitem(sys.modules, "sounddevice",
                        types.SimpleNamespace(play=lambda s, r, **k: played.append(r), wait=lambda: None))
    assert play_samples(np.ones(10, dtype=np.float32), 16000, os_interface=OSInterface())
    assert played == [16000]


# ---- macOS media and desktop -----------------------------------------------------------------

def test_mac_media_controls_running_spotify(mac_engine, shell):
    shell.running = "Spotify\n"
    res = mac_engine.execute_custom_tool("media_play_pause", {"action": "pause"})
    assert '-e tell application "Spotify" to pause' in scripts(shell)
    assert res["success"] and res["spoken_confirmation"] == "Paused media playback."


def test_mac_media_with_no_player_says_what_it_can_control(mac_engine, shell):
    res = mac_engine.execute_custom_tool("media_play_pause", {"action": "pause"})
    assert res["success"] is False and "Spotify and Music" in res["spoken_confirmation"]


def test_mac_next_track(mac_engine, shell):
    shell.running = "Music\n"
    res = mac_engine.execute_custom_tool("media_play_pause", {"action": "next"})
    assert '-e tell application "Music" to next track' in scripts(shell)
    assert res["spoken_confirmation"] == "Skipped to the next track."


def test_mac_notification_text_cannot_break_the_script(shell):
    MacOS().notify('Done: "x"', "it's ok\" & do shell script \"rm\"")
    cmd = shell.calls[-1]
    assert cmd[-2:] == ['Done: "x"', "it's ok\" & do shell script \"rm\""]
    assert not any("rm" in part for part in cmd[:-2])


def test_mac_terminal_falls_back_to_terminal_app(shell, monkeypatch):
    monkeypatch.setattr("daemon.os_interface.macos.Path.exists", lambda self: False)
    assert MacOS().open_terminal().ok
    assert shell.calls[-1] == ["open", "-a", "Terminal"]


@pytest.mark.parametrize("tool,args,expected", [
    ("system_power_control", {"action": "suspend"}, "pmset sleepnow"),
    ("lock_screen", {}, "pmset displaysleepnow"),
])
def test_mac_power_commands(mac_engine, tool, args, expected):
    res = mac_engine.execute_custom_tool(tool, args)
    assert expected in res["cmd"]


def test_linux_power_commands_are_unchanged():
    assert LinuxOS().power_command("shutdown") == "systemctl poweroff || loginctl poweroff || shutdown -h now"


# ---- macOS apps --------------------------------------------------------------------------------

def make_bundle(root, name, plist: bytes, script: str = ""):
    contents = root / f"{name}.app" / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Info.plist").write_bytes(plist)
    if script:
        (contents / "MacOS" / "run.sh").write_text(script)


def plist(**keys) -> bytes:
    import plistlib
    return plistlib.dumps(keys)


@pytest.fixture
def mac_apps(tmp_path, monkeypatch):
    system_apps, user_apps = tmp_path / "System", tmp_path / "User"
    make_bundle(tmp_path, "Visual Studio Code", plist(CFBundleIdentifier="com.microsoft.VSCode",
                                                      CFBundleExecutable="Electron", CFBundleName="Code"))
    make_bundle(system_apps, "Messages", plist(CFBundleIdentifier="com.apple.MobileSMS", CFBundleExecutable="Messages"))
    make_bundle(system_apps, "URL Handler", plist(CFBundleIdentifier="x.handler", LSBackgroundOnly=True))
    # A Safari web app with a system app's name, and a Steam shortcut (indented, NUL-padded plist).
    make_bundle(user_apps, "Messages", plist(CFBundleIdentifier="com.apple.Safari.WebApp.1"))
    make_bundle(user_apps, "Haste", b"\n\t" + plist(CFBundleExecutable="run.sh") + b"\0\0",
                script="#!/bin/bash\nopen steam://run/1796470\n")
    monkeypatch.setattr("daemon.os_interface.macos.APP_DIRS", [str(tmp_path), str(system_apps), str(user_apps)])
    from daemon.tools.app_scanner import AppScanner
    return AppScanner(system=MacOS())


def test_mac_finds_app_bundles_and_skips_background_helpers(mac_apps):
    names = sorted(a["name"] for a in mac_apps.get_installed_apps_manifest())
    assert names == ["Haste", "Messages", "Messages", "Visual Studio Code"]
    assert mac_apps.find_app("vs code").name == "Visual Studio Code"
    assert mac_apps.find_app("code").name == "Visual Studio Code"  # its CFBundleName


def test_mac_real_app_beats_a_web_app_with_the_same_name(mac_apps):
    assert mac_apps.find_app("messages").app_id == "com.apple.MobileSMS"


def test_mac_launches_with_open(mac_apps):
    cmd, name = mac_apps.resolve_app_launcher_command("visual studio code")
    assert cmd.startswith("open -a '") and cmd.endswith("Visual Studio Code.app'") and name == "Visual Studio Code"


def test_mac_close_plans(mac_apps):
    assert mac_apps.close_plan("vs code")[1] == {"kind": "mac_app", "by": "id", "target": "com.microsoft.VSCode"}
    assert mac_apps.close_plan("haste")[1] == {"kind": "steam_game", "appid": "1796470"}


@pytest.mark.parametrize("answer,state,spoken", [
    ("closed\n", "closed", "Closed Spotify."),
    ("not_running\n", "not_running", "Spotify isn't running."),
])
def test_mac_quits_apps_like_cmd_q(mac_engine, shell, monkeypatch, answer, state, spoken):
    monkeypatch.setattr(shell, "run", lambda cmd, **k: (shell.calls.append(cmd), subprocess.CompletedProcess(cmd, 0, answer, ""))[1])
    monkeypatch.setattr(subprocess, "run", shell.run)
    res = mac_engine._close_app("Spotify", {"kind": "mac_app", "by": "id", "target": "com.spotify.client"})
    assert shell.calls[-1][-2:] == ["id", "com.spotify.client"]  # the bundle id goes in as an argument
    assert res["success"] and res["spoken_confirmation"] == spoken


def test_mac_steam_games_say_they_cant_be_closed_yet(mac_engine):
    res = mac_engine._close_app("Haste", {"kind": "steam_game", "appid": "1796470"})
    assert res["success"] is False and res["spoken_confirmation"] == "Couldn't close Haste."


# ---- Windows (overlays) ----------------------------------------------------------------------

def test_only_linux_reraises_overlays():
    assert LinuxOS.overlays_need_reraise and not MacOS.overlays_need_reraise
    assert MacOS().qt_environment() == {"QT_MAC_SET_RAISE_PROCESS": "0"}
    # Started at login: Qt mustn't turn Jarvis into a foreground app (it would take focus).
    assert MacOS().qt_environment(background=True)["QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM"] == "1"
    assert LinuxOS().qt_environment() == {"QT_QPA_PLATFORM": "xcb"}


def test_mac_overlays_keep_clear_of_the_menu_bar_and_dock():
    # 1512x982 screen, 33px menu bar, 70px Dock at the bottom.
    assert MacOS().overlay_insets((0, 0, 1512, 982), (0, 33, 1512, 879)) == {"top": 33, "left": 0, "bottom": 70, "right": 0}


def test_mac_overlay_survives_hide_and_shows_on_every_space(monkeypatch):
    # Cmd-H (Hide Jarvis) used to take the pill with it; it must show over any app, on any Space.
    import AppKit
    import objc

    class FakeWindow:
        def __init__(self): self.set = {"style": 14}
        def isKindOfClass_(self, cls): return cls is AppKit.NSPanel
        def styleMask(self): return self.set["style"]
        def setStyleMask_(self, v): self.set["style"] = v
        def setHidesOnDeactivate_(self, v): self.set["hides_on_deactivate"] = v
        def setCanHide_(self, v): self.set["can_hide"] = v
        def setLevel_(self, v): self.set["level"] = v
        def setCollectionBehavior_(self, v): self.set["behavior"] = v

    window = FakeWindow()
    monkeypatch.setattr(objc, "objc_object", lambda c_void_p: type("View", (), {"window": lambda self: window})())
    MacOS().prepare_overlay_window(1234)
    assert window.set["can_hide"] is False and window.set["hides_on_deactivate"] is False
    assert window.set["level"] == AppKit.NSStatusWindowLevel
    assert window.set["behavior"] & AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
    assert window.set["behavior"] & AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
    # Only a non-activating panel may enter another app's full-screen Space.
    assert window.set["style"] & AppKit.NSWindowStyleMaskNonactivatingPanel


def test_mac_runs_in_the_background_without_the_dashboard(monkeypatch):
    # A regular app takes focus the first time it shows any window: in the background, be an accessory.
    import AppKit

    class FakeApp:
        policy = AppKit.NSApplicationActivationPolicyRegular
        def activationPolicy(self): return self.policy
        def setActivationPolicy_(self, p): self.policy = p

    fake = FakeApp()
    monkeypatch.setattr(AppKit, "NSApplication", type("FakeNSApplication", (), {"sharedApplication": staticmethod(lambda: fake)}))
    MacOS().show_in_dock(False)
    assert fake.policy == AppKit.NSApplicationActivationPolicyAccessory
    MacOS().show_in_dock(True)
    assert fake.policy == AppKit.NSApplicationActivationPolicyRegular
