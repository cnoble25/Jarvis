"""Built-in commands do what they say and report failures honestly (all execution stubbed)."""

import subprocess
import threading

import pytest

from daemon.tools.execution_engine import ExecutionEngine, timer_sentence


@pytest.fixture
def engine(monkeypatch):
    calls = []

    def fake_run(cmd, **_k):
        calls.append(cmd)
        out = "Volume: 0.45\n" if cmd[:2] == ["wpctl", "get-volume"] else ""
        return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **_k: calls.append(cmd))
    eng = ExecutionEngine.__new__(ExecutionEngine)
    eng._local = threading.local()
    eng.calls = calls
    return eng


@pytest.mark.parametrize("action,expected_cmd,spoken", [
    ("up", ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "5%+"], "Volume up, now 45%."),
    ("down", ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"], "Volume down, now 45%."),
    ("mute", ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"], "Muted."),
    ("toggle", ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"], "Toggled mute."),
    ("50%", ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "50%"], "Volume set, now 45%."),
    ("5%+", ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "5%+"], "Volume up, now 45%."),
])
def test_volume(engine, action, expected_cmd, spoken):
    res = engine._volume({"action": action})
    assert engine.calls[0] == expected_cmd
    assert res["spoken_confirmation"] == spoken


def test_volume_down_never_raises_or_mutes(engine):
    engine._volume({"action": "down"})
    assert not any("5%+" in c or "set-mute" in c for c in engine.calls if isinstance(c, list))


@pytest.mark.parametrize("secs,label,text", [
    (600, "Timer", "Set a 10 minute timer."),
    (300, "Pizza", "Set a Pizza timer for 5 minutes."),
    (5400, None, "Set a timer for 1 hour 30 minutes."),
])
def test_timer_sentence(secs, label, text):
    assert timer_sentence(secs, label) == text


def test_media_with_no_player_says_so(engine):
    res = engine.execute_custom_tool("media_play_pause", {"action": "pause"})
    assert res["success"] is False and res["spoken_confirmation"] == "Nothing is playing right now."


def test_terminal_opens_an_installed_one(engine, monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/konsole" if name == "konsole" else None)
    res = engine.execute_custom_tool("open_terminal", {})
    assert engine.calls[-1] == ["konsole"] and res["success"]


def test_calendar_without_khal_says_so(engine, monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None)
    res = engine.execute_custom_tool("calendar_create_event", {"title": "x", "start_time": "y"})
    assert res["success"] is False and "khal" in res["spoken_confirmation"]
