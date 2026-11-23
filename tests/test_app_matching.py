"""App launching: confident matches only, honest failure, and only real apps become shortcuts."""

import pytest

from daemon.os_interface.linux import LinuxOS
from daemon.tools.app_scanner import AppEntry, AppScanner


def scanner_with(*apps):
    s = AppScanner.__new__(AppScanner)
    s._system = LinuxOS()
    s.apps = {}
    for name, desktop_id, exec_cmd, keywords in apps:
        e = AppEntry(f"/x/{desktop_id}.desktop", name, exec_cmd, keywords, desktop_id)
        s.apps.setdefault(name.lower(), e)
        s.apps[desktop_id.lower()] = e
    return s


APPS = scanner_with(
    ("Firmware", "org.gnome.Firmware", "gnome-firmware", []),
    ("Startup Configuration", "kcm_autostart", "systemsettings kcm_autostart", []),
    ("Peaks of Yore", "steam_app_123", "steam steam://rungameid/123", []),
    ("Camera", "org.gnome.Snapshot", "snapshot", ["camera", "webcam", "photo"]),
    ("Visual Studio Code", "code", "/usr/bin/code --new-window", ["vscode"]),
    ("Discord", "com.discordapp.Discord", "discord", []),
    ("DOOM: The Dark Ages", "steam_app_456", "steam steam://rungameid/456", []),
)


@pytest.mark.parametrize("query,expected", [
    ("figma", None),
    ("up Figma?", None),
    ("Figma, the design website", None),
    ("us on movie mode", None),
    ("my camera", "Camera"),
    ("org.gnome.Snapshot", "Camera"),
    ("VS Code", "Visual Studio Code"),
    ("discrod", "Discord"),
    ("doom dark ages", "DOOM: The Dark Ages"),
])
def test_find_app(query, expected):
    app = APPS.find_app(query)
    assert (app.name if app else None) == expected


@pytest.mark.parametrize("query,expected", [
    ("can you open up Figma?", None),
    ("No. Hey Claude, can you open up Figma?", None),
    ("start us on movie mode.", None),
    ("start a 10 second timer", None),
    ("can you pull up my camera?", "Camera"),
    ("open discord please", "Discord"),
])
def test_open_shortcut(query, expected):
    m = APPS.match_app_launch_intent(query)
    assert (m[1] if m else None) == expected


def test_launcher_reports_missing_app(monkeypatch):
    import daemon.tools.app_scanner as mod
    from daemon.tools.execution_engine import ExecutionEngine
    monkeypatch.setattr(mod, "get_app_scanner", lambda: APPS)
    monkeypatch.setattr(APPS, "scan_installed_apps", lambda: None, raising=False)
    res = ExecutionEngine.__new__(ExecutionEngine)
    import threading
    res._local = threading.local()
    out = res.execute_custom_tool("app_launcher", {"app_name": "figma", "_raw_user_query": "open figma"})
    assert out["success"] is False
    assert "couldn't find an app called figma" in out["spoken_confirmation"].lower()


def test_turn_outcome_beats_stderr():
    from main import classify_turn
    ok = classify_turn({"spoken_response": "Installed it.", "execution_stderr": "Cloning into '/tmp/x'...", "outcome": "ok"})
    assert ok["status"] == "ok"
    old = classify_turn({"spoken_response": "x", "execution_stderr": "boom"})
    assert old["status"] == "failed"


def test_learner_skips_failed_and_missing_apps(monkeypatch):
    import daemon.agent.fast_path_agent as fpa
    monkeypatch.setattr(fpa, "_app_exists", lambda name: name == "discord")

    class Mgr:
        learned_rules = []
        def __init__(self): self.added = []
        def prune_unlaunchable_app_rules(self): return []
        def add_learned_rule(self, **k): self.added.append(k); return k
        def save_learned_rules(self): pass

    mgr = Mgr()
    agent = fpa.FastPathCreatorAgent(fast_path_manager=mgr)
    turns = (
        [{"user_query": "open up figma please", "tool_executed": "app_launcher", "tool_args": {"app_name": "figma"}, "outcome": "ok"}] * 4
        + [{"user_query": "install that skill now", "tool_executed": "execute_terminal_command", "tool_args": {"command": "x"}, "outcome": "ok"}] * 4
        + [{"user_query": "pause the spotify music", "tool_executed": "media_play_pause", "tool_args": {}, "outcome": "failed"}] * 4
        + [{"user_query": "open discord app", "tool_executed": "app_launcher", "tool_args": {"app_name": "discord"}, "outcome": "ok"}] * 4
    )
    agent.update_fast_paths(turns)
    assert [r["tool"] for r in mgr.added] == ["app_launcher"]
    assert mgr.added[0]["args"]["app_name"] == "discord"
