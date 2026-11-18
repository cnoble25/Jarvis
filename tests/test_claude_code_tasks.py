"""Claude Code tasks: steps stream into the Jarvis task, permission requests use Jarvis's rules."""

import sys
import time
from pathlib import Path

import pytest

import daemon.agent.claude_code_agent as cca
from tests.test_background_tasks import ScriptedProvider, make_orchestrator, wait_for

FAKE = str(Path(__file__).parent / "fixtures" / "fake_claude.py")


@pytest.fixture(autouse=True)
def fake_claude(monkeypatch):
    monkeypatch.setattr(cca, "find_claude", lambda: FAKE)


def hand_off(task_text):
    return ScriptedProvider([{"tool": "claude_code_task", "args": {"task": task_text}, "status": "complete",
                              "spoken_summary": "Handing that to Claude Code."}])


def run(o, query="do it"):
    o.registry._tools = {"claude_code_task": None}
    return o.process_voice_query(query, speak_output=False)


def finished(events):
    done = [t for e, t in events if e == "task_finished"]
    return done[0] if done else None


def last_task(o):
    """Quick tasks finish in the foreground and send no task_finished event: read the task itself."""
    t = o.task_board._tasks[-1]
    return t.to_dict() if t.finished else None


def test_safe_command_runs_without_asking():
    events = []
    o = make_orchestrator(hand_off("RUN: ls ~"), events=events)
    res = run(o)
    assert wait_for(lambda: last_task(o), timeout=15)
    t = last_task(o)
    assert t["result"] == "I did the thing." and t["approval"] is None
    assert [s["label"] for s in t["steps"]] == ["Handing it to Claude Code", "Doing the thing"]
    assert t["steps"][1]["detail"] == "ls ~" and t["steps"][1]["state"] == "done"


def test_risky_command_waits_for_ok(tmp_path):
    events = []
    o = make_orchestrator(hand_off(f"RUN: touch {tmp_path}/x"), events=events)
    res = run(o)
    assert wait_for(lambda: o.task_board.awaiting_approval(), timeout=15)
    task = o.task_board.awaiting_approval()[0]
    assert task.approval["detail"] == f"touch {tmp_path}/x"
    o.process_voice_query("go ahead", speak_output=False)
    assert wait_for(lambda: finished(events), timeout=15)
    assert finished(events)["result"] == "I did the thing."


def test_refused_command_is_denied():
    events = []
    o = make_orchestrator(hand_off("RUN: rm -r ~/Downloads/old"), events=events)
    run(o)
    assert wait_for(lambda: o.task_board.awaiting_approval(), timeout=15)
    o.process_voice_query("no", speak_output=False)
    assert wait_for(lambda: finished(events), timeout=15)
    assert "said no" in finished(events)["result"]


def test_destructive_command_is_refused_without_asking():
    events = []
    o = make_orchestrator(hand_off("RUN: rm -rf ~/"), events=events)
    run(o)
    assert wait_for(lambda: last_task(o), timeout=15)
    t = last_task(o)
    assert t["approval"] is None and "wipe data" in t["result"]


def test_cancel_stops_the_session():
    events = []
    o = make_orchestrator(hand_off("SLOW RUN: ls"), events=events)
    run(o)
    assert wait_for(lambda: o.task_board.running(background_only=True), timeout=10)
    started = time.time()
    o.process_voice_query("cancel that", speak_output=False)
    assert wait_for(lambda: finished(events), timeout=15)
    assert finished(events)["status"] == "cancelled" and time.time() - started < 10


def test_spoken_names_match_loosely(tmp_path, monkeypatch):
    import threading
    from daemon.tools.execution_engine import ExecutionEngine
    for name in ("jarvis-cc-demo", "JarvisCCDemo", "jarvis_cc_demo_v2", "unrelated"):
        (tmp_path / name).mkdir()
    eng = ExecutionEngine.__new__(ExecutionEngine)
    eng._local = threading.local()
    monkeypatch.setattr(ExecutionEngine, "SEARCH_ROOTS", [(str(tmp_path), 2)])
    res = eng._search_files("Jarvis CC demo")
    found = {line.split("/")[-1] for line in res["stdout"].splitlines()[1:]}
    assert found == {"jarvis-cc-demo", "JarvisCCDemo", "jarvis_cc_demo_v2"}
    assert eng._search_files("nothing like this")["spoken_confirmation"].startswith("I couldn't find anything")


def test_place_hints_only_for_file_requests(tmp_path, monkeypatch):
    xbel = tmp_path / "recent.xbel"
    folder = tmp_path / "notes"
    folder.mkdir()
    xbel.write_text(f'<bookmark href="file://{folder}/a.txt" added="x" modified="2026-11-17T10:00:00Z" visited="x">'
                    '<bookmark href="https://example.com/x" added="x" modified="2026-11-17T11:00:00Z" visited="x">')
    monkeypatch.setattr(cca, "RECENT_XBEL", xbel)
    assert cca.with_place_hints("pause the music") == "pause the music"
    hinted = cca.with_place_hints("summarize my notes folder")
    assert str(folder) in hinted and "example.com" not in hinted


def test_followups_continue_the_claude_session():
    o = make_orchestrator(hand_off("RUN: ls ~"), events=[])
    run(o)
    assert wait_for(lambda: last_task(o), timeout=15)
    assert o.claude_followup_active()
    # A plain follow-up (no "Claude") goes back to the same session.
    o.process_voice_query("RUN: ls /tmp", speak_output=False)
    assert wait_for(lambda: last_task(o) and "resumed sess-1" in last_task(o)["result"], timeout=15)
    # "Jarvis, ..." ends the window and goes to the normal model.
    o.llm_provider = ScriptedProvider([{"tool": "none", "args": {}, "status": "complete", "spoken_summary": "Sure."}])
    res = o.process_voice_query("Jarvis, what time is it", speak_output=False)
    assert res["final_spoken_summary"] == "Sure." and not o.claude_followup_active()
