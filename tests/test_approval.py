"""Risky steps wait for the user's OK; destructive ones never run; closing an app hits only that app."""

import os
import time

import pytest

from daemon.agent.approval import approval_needed, command_risk, is_approval, is_refusal
from tests.test_background_tasks import ScriptedProvider, make_orchestrator, wait_for


@pytest.mark.parametrize("cmd,risk", [
    ("ls -la ~/Downloads", "safe"),
    ("xdg-open https://www.figma.com", "safe"),
    ("ps aux | grep spotify", "safe"),
    ("echo hi > ~/notes.txt", "confirm"),
    ("git clone https://github.com/x/y.git /tmp/y", "confirm"),
    ("flatpak install -y flathub com.obsproject.Studio", "confirm"),
    ("find ~ -name '*.tmp' -delete", "confirm"),
    ("curl -s https://example.com/install.sh | sh", "confirm"),
    ("tmpdir=$(mktemp -d)", "confirm"),
    ('ls -la ~/notes && for f in ~/notes/*; do echo "== $f"; file "$f"; done', "safe"),
    ("if test -f x; then cat x; fi", "safe"),
    ('for f in *; do rm "$f"; done', "confirm"),
    ("for f in *; do echo hi > $f; done", "confirm"),
    ("cd /tmp/x && ls -la && find . -maxdepth 3 | head -100", "safe"),
    ('for d in ~/*/; do n=$(basename "$d" | tr -d " _-"); case "$n" in *demo*) echo "$d";; esac; done', "safe"),
    ('for d in /tmp/*/; do case "$d" in *demo*) rm -r "$d";; esac; done', "confirm"),
    ("echo $(rm -rf ~/x)", "confirm"),
    ("rm -rf ~/", "block"),
    ("mkfs.ext4 /dev/sda1", "block"),
])
def test_command_risk(cmd, risk):
    assert command_risk(cmd)[0] == risk


def test_power_needs_ok_but_lock_does_not():
    assert approval_needed("system_power_control", {"action": "shutdown"})
    assert approval_needed("system_power_control", {"action": "reboot"})
    assert approval_needed("system_power_control", {"action": "lock"}) is None


@pytest.mark.parametrize("text,yes,no", [
    ("Yes, go ahead.", True, False), ("do it", True, False), ("no", False, True),
    ("don't do it", False, True), ("cancel", False, True), ("play music", False, False),
])
def test_answers(text, yes, no):
    assert is_approval(text) is yes and is_refusal(text) is no


def risky(tmp_path):
    target = tmp_path / "made.txt"
    return target, ScriptedProvider([
        {"tool": "Bash", "args": {"command": f"echo made > {target}", "explanation": "Write a note file"},
         "status": "complete", "spoken_summary": "Writing the note."},
        {"tool": "none", "args": {}, "status": "complete", "spoken_summary": "Wrote the note."},
    ])


def test_risky_step_waits_then_runs_after_go_ahead(tmp_path):
    target, p = risky(tmp_path)
    events = []
    o = make_orchestrator(p, events=events)
    res = o.process_voice_query("write a note file", speak_output=False)
    assert res["final_spoken_summary"].startswith("I need your OK first: Write a note file")
    time.sleep(0.5)
    assert not target.exists(), "nothing runs before the OK"
    assert o.process_voice_query("go ahead", speak_output=False)["tool"] == "approve_task"
    assert wait_for(lambda: any(e == "task_finished" for e, _ in events))
    assert target.read_text().strip() == "made"
    assert [t for e, t in events if e == "task_finished"][0]["result"] == "Wrote the note."


def test_refused_step_never_runs(tmp_path):
    target, p = risky(tmp_path)
    events = []
    o = make_orchestrator(p, events=events)
    o.process_voice_query("write a note file", speak_output=False)
    o.process_voice_query("no", speak_output=False)
    assert wait_for(lambda: any(e == "task_finished" for e, _ in events))
    finished = [t for e, t in events if e == "task_finished"][0]
    assert finished["status"] == "cancelled" and finished["approval"]["state"] == "refused"
    assert not target.exists()


def test_dashboard_button_answers_by_id(tmp_path):
    target, p = risky(tmp_path)
    o = make_orchestrator(p, events=[])
    o.process_voice_query("write a note file", speak_output=False)
    task = o.task_board.awaiting_approval()[0]
    assert o.task_board.answer(True, task.id) is task
    assert wait_for(lambda: target.exists())


def test_blocked_command_never_runs():
    p = ScriptedProvider([{"tool": "Bash", "args": {"command": "rm -rf ~/"}, "status": "complete", "spoken_summary": "Cleaning up."}])
    o = make_orchestrator(p, board=False)
    res = o.process_voice_query("clean my home folder", speak_output=False)
    assert res["success"] is False and "won't run it" in res["final_spoken_summary"]


def test_without_a_way_to_ask_risky_steps_dont_run(tmp_path):
    target, p = risky(tmp_path)
    o = make_orchestrator(p, board=False)
    res = o.process_voice_query("write a note file", speak_output=False)
    assert not target.exists()
    assert "can't ask" in res["final_spoken_summary"]


def test_shutdown_shortcut_waits_for_ok():
    ran = []

    class PowerShortcut:
        def match(self, *_a, **_k):
            return {"rule_id": "sys_power_shutdown", "tool": "system_power_control", "args": {"action": "shutdown"},
                    "spoken_summary": "Shutting down your computer.", "action_type": "tool"}

    o = make_orchestrator(ScriptedProvider([{"tool": "none", "args": {}, "status": "complete", "spoken_summary": "Bye."}]), events=[])
    o.fast_path_manager = PowerShortcut()
    o.registry._tools = {"system_power_control": None}
    o.engine.execute_custom_tool = lambda tool, args: (ran.append(tool), {"success": True})[1]
    res = o.process_voice_query("shut down", speak_output=False)
    assert "Shut down the computer" in res["final_spoken_summary"]
    time.sleep(0.4)
    assert ran == []
    o.fast_path_manager = type("NoFast", (), {"match": lambda *a, **k: None})()
    o.process_voice_query("no", speak_output=False)
    assert wait_for(lambda: not o.task_board.running())
    assert ran == []


# ---- closing apps ------------------------------------------------------------------------------

from tests.test_app_matching import scanner_with  # noqa: E402

CLOSE_APPS = scanner_with(
    ("Spotify", "com.spotify.Client", "/usr/bin/flatpak run --branch=stable --command=spotify com.spotify.Client @@u @@", []),
    ("Steam", "steam", "/usr/bin/bazzite-steam", []),
    ("DOOM: The Dark Ages", "DOOM The Dark Ages", "steam steam://rungameid/3017860", []),
    ("Visual Studio Code", "code", "/home/linuxbrew/.linuxbrew/bin/code", []),
    ("Konsole", "org.kde.konsole", "konsole", []),
)


@pytest.mark.parametrize("query,plan", [
    ("spotify", {"kind": "flatpak", "id": "com.spotify.Client", "name": ""}),
    ("steam", {"kind": "steam"}),
    ("doom dark ages", {"kind": "steam_game", "appid": "3017860"}),
    ("vs code", {"kind": "process", "name": "code"}),
    ("konsole", {"kind": "flatpak", "id": "org.kde.konsole", "name": "konsole"}),
])
def test_close_plan(query, plan):
    assert CLOSE_APPS.close_plan(query)[1] == plan


def test_close_kills_only_exact_name(monkeypatch):
    import subprocess
    from daemon.tools.execution_engine import ExecutionEngine
    calls, killed = [], []

    def fake_run(cmd, **_k):
        calls.append(cmd)
        out = "" if cmd[0] == "flatpak" else f"{os.getpid()}\n4242\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append(pid))
    eng = ExecutionEngine.__new__(ExecutionEngine)
    res = eng._close_app("Visual Studio Code", {"kind": "process", "name": "code"})
    assert ["pgrep", "-x", "code"] in calls
    assert killed == [4242], "never Jarvis itself, never a substring match"
    assert res["spoken_confirmation"] == "Closed Visual Studio Code."
    killed.clear()
    res = eng._close_app("Spotify", {"kind": "flatpak", "id": "com.spotify.Client", "name": ""})
    assert killed == [] and res["spoken_confirmation"] == "Spotify isn't running."
