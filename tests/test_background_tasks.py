"""Background tasks: quick reply, then the work continues and is announced; routing keeps object phrases."""

import re
import threading
import time

import pytest

import daemon.agent.orchestrator as orch_mod
from daemon.agent.orchestrator import AgentOrchestrator
from daemon.agent.tasks import TaskBoard
from daemon.tools.execution_engine import ExecutionEngine


class FakeRegistry:
    _tools = {}


class FakeFastPaths:
    def match(self, *_a, **_k):
        return None


class FakeLogger:
    def __init__(self):
        self.turns = []
        self.pending = {}

    def pop_next_turn_meta(self):
        meta, self.pending = self.pending, {}
        return meta

    def log_turn(self, session_id, user_query, tool_executed=None, tool_args=None, execution_stdout="",
                 execution_stderr="", spoken_response="", meta=None):
        self.turns.append({"user_query": user_query, "tool_executed": tool_executed,
                           "spoken_response": spoken_response, **(meta or {})})


class ScriptedProvider:
    """Returns the scripted replies in order and records the history it was given each time."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.histories = []

    def process_voice_query(self, user_query, history, system_prompt):
        self.histories.append(list(history))
        return self.replies.pop(0)

    def get_provider_info(self):
        return {"name": "scripted", "model_name": "scripted"}


def make_orchestrator(provider, board=True, events=None):
    o = AgentOrchestrator(registry=FakeRegistry(), engine=ExecutionEngine(FakeRegistry()), logger=FakeLogger(),
                          llm_provider=provider, fast_path_manager=FakeFastPaths())
    o.build_system_prompt = lambda *a, **k: "system"
    if board:
        o.task_board = TaskBoard(listener=(lambda e, t: events.append((e, t))) if events is not None else None)
    return o


def wait_for(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_quick_request_answers_in_foreground():
    p = ScriptedProvider([{"tool": "none", "args": {}, "status": "complete", "spoken_summary": "Hi there."}])
    o = make_orchestrator(p)
    res = o.process_voice_query("hello", speak_output=False)
    assert res["final_spoken_summary"] == "Hi there."
    assert o.task_board.snapshot() == []  # foreground requests don't show as tasks


def test_command_moves_to_background_and_reports_outcome():
    events = []
    p = ScriptedProvider([
        {"tool": "Bash", "args": {"command": "sleep 2.5; echo installed"}, "status": "complete",
         "spoken_summary": "Installing it now."},
        {"tool": "none", "args": {}, "status": "complete", "spoken_summary": "Installed it."},
    ])
    o = make_orchestrator(p, events=events)
    started = time.time()
    res = o.process_voice_query("install the thing", speak_output=False)
    assert time.time() - started < 2.2, "the quick reply shouldn't wait for the command"
    assert res["tool"] == "background_task"
    assert res["final_spoken_summary"].startswith("Installing it now.")
    assert wait_for(lambda: any(e == "task_finished" for e, _ in events))
    finished = [t for e, t in events if e == "task_finished"][0]
    assert finished["status"] == "done" and finished["result"] == "Installed it."
    assert finished["steps"][0]["state"] == "done"
    # The model saw the command's output before writing its closing line.
    assert any("installed" in m["content"] for m in p.histories[1] if m["role"] == "user")
    assert o.logger.turns[-1]["background_task"]["status"] == "done"


def test_observation_reaches_the_model():
    p = ScriptedProvider([
        {"tool": "Bash", "args": {"command": "echo needle"}, "status": "continue", "spoken_summary": "Checking."},
        {"tool": "none", "args": {}, "status": "complete", "spoken_summary": "Found it."},
    ])
    o = make_orchestrator(p, board=False)
    res = o.process_voice_query("find the needle", speak_output=False)
    assert res["final_spoken_summary"] == "Found it."
    assert any("needle" in m["content"] and m["content"].startswith("[Observation") for m in p.histories[1])


def test_cancel_stops_a_running_command():
    events = []
    p = ScriptedProvider([{"tool": "Bash", "args": {"command": "sleep 30"}, "status": "complete",
                           "spoken_summary": "Working on it."}])
    o = make_orchestrator(p, events=events)
    o.process_voice_query("do the long thing", speak_output=False)
    assert wait_for(lambda: o.task_board.running(background_only=True))
    started = time.time()
    res = o.process_voice_query("cancel that", speak_output=False)
    assert res["tool"] == "cancel_task"
    assert wait_for(lambda: any(e == "task_finished" for e, _ in events), timeout=8)
    assert time.time() - started < 8
    assert [t for e, t in events if e == "task_finished"][0]["status"] == "cancelled"


def test_turn_meta_belongs_to_its_own_request():
    p = ScriptedProvider([{"tool": "none", "args": {}, "status": "complete", "spoken_summary": "Ok."}])
    o = make_orchestrator(p)
    o.logger.pending = {"heard_alternatives": [{"text": "hello", "probability": 1.0}]}
    o.process_voice_query("hello", speak_output=False)
    assert o.logger.pending == {}
    assert o.logger.turns[-1]["heard_alternatives"][0]["text"] == "hello"


@pytest.mark.parametrize("query,expected", [
    ("Could you install the Socratic skill onto my computer for Claude Code?",
     "Could you install the Socratic skill onto my computer for Claude Code?"),
    ("pause spotify, Claude?", "pause spotify"),
    ("play my liked songs playlist Claude?", "play my liked songs playlist"),
    ("Hey Claude, install the skill.", "install the skill."),
])
def test_route_address_stripping(query, expected):
    o = make_orchestrator(ScriptedProvider([]), board=False)
    name = r"(?:claude|clawed|clod)(?:\s+code)?"
    leading = re.compile(r"^\s*(?:(?:hey|hi|ok(?:ay)?|yo)[\s,]+)?(?:ask[\s,]+)?" + name + r"\b[\s,:.!?-]*(?:to\s+)?", re.I)
    trailing = re.compile(r"(?:(?:,\s*|\s+hey\s+)" + name + r"\s*[.?!]*|\s+" + name + r"\s*\?)\s*$", re.I)
    m = leading.search(query) or trailing.search(query)
    assert m
    assert o._strip_address(query, m) == expected


def test_quick_command_finishes_in_foreground():
    p = ScriptedProvider([{"tool": "Bash", "args": {"command": "true"}, "status": "complete",
                           "spoken_summary": "Opening Figma in your browser."}])
    o = make_orchestrator(p)
    res = o.process_voice_query("open figma's website", speak_output=False)
    assert res.get("tool") != "background_task"
    assert res["final_spoken_summary"] == "Opening Figma in your browser."


def test_failed_action_goes_back_to_the_model():
    p = ScriptedProvider([
        {"tool": "Bash", "args": {"command": "exit 3"}, "status": "complete", "spoken_summary": "Doing it."},
        {"tool": "none", "args": {}, "status": "complete", "spoken_summary": "That failed with exit code 3."},
    ])
    o = make_orchestrator(p, board=False)
    res = o.process_voice_query("do it", speak_output=False)
    assert res["final_spoken_summary"] == "That failed with exit code 3."
    assert any("exit code 3" in m["content"] for m in p.histories[1])
    assert o.logger.turns[-1]["outcome"] == "ok"  # the final answer explained it; nothing left failing
