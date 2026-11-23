"""Skills Jarvis writes for itself: saved unapproved, run only once approved, re-reviewed when changed."""

import threading

import pytest

import daemon.tools.skills as skills_mod
from daemon.tools.registry import ToolRegistry
from daemon.tools.execution_engine import ExecutionEngine
from daemon.tools.skills import SkillError, SkillStore

GREET = """
import json, sys
args = json.load(sys.stdin)
print("working...")
print(f"Hello, {args.get('name', 'you')}.")
"""


def spec(**over):
    base = {"id": "greet_person", "name": "Greet someone", "description": "Says hello to a person by name.",
            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
            "language": "python", "code": GREET, "risk_level": "SAFE", "example_requests": ["say hi to Sam"]}
    return {**base, **over}


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_mod, "SKILLS_DIR", tmp_path / "skills")  # what approval.py reads
    return ToolRegistry(config_dir=str(tmp_path / "tools"))


def test_new_skill_waits_for_approval(registry):
    skill = registry.skills.save(spec())
    assert skill["status"] == "pending"
    registry.reload_tools()
    assert registry.get_tool("greet_person") is None
    res = registry.skills.run("greet_person", {"name": "Sam"})
    assert res["success"] is False and "approval" in res["spoken_confirmation"]


def test_approved_skill_is_a_tool_and_speaks_its_last_line(registry):
    registry.skills.save(spec())
    registry.skills.approve("greet_person")
    registry.reload_tools()
    tool = registry.get_tool("greet_person")
    assert tool is not None and tool.category == "skill" and registry.is_skill("greet_person")
    res = ExecutionEngine(registry).execute_custom_tool("greet_person", {"name": "Sam", "_raw_user_query": "say hi"})
    assert res["success"] and res["spoken_confirmation"] == "Hello, Sam."


def test_changing_the_code_needs_approval_again(registry):
    registry.skills.save(spec())
    registry.skills.approve("greet_person")
    code = registry.skills.root / "greet_person" / "run.py"
    code.write_text(GREET + "\nimport os\n")
    assert registry.skills.get("greet_person")["status"] == "changed"
    registry.reload_tools()
    assert registry.get_tool("greet_person") is None
    assert registry.skills.run("greet_person", {"name": "Sam"})["success"] is False
    # Claude Code re-saving it also resets approval.
    registry.skills.approve("greet_person")
    assert registry.skills.save(spec(description="Says hi."))["status"] == "pending"


@pytest.mark.parametrize("bad, message", [
    ({"id": "Bad Id"}, "snake_case"),
    ({"id": "app_launcher"}, "already a Jarvis command"),
    ({"language": "ruby"}, "language"),
    ({"risk_level": "LOW"}, "risk_level"),
    ({"code": "  "}, "empty"),
    ({"parameters": {"type": "array"}}, "JSON Schema object"),
])
def test_save_rejects_bad_skills(registry, bad, message):
    with pytest.raises(SkillError, match=message):
        registry.skills.save(spec(**bad), taken=["app_launcher"])


def test_failure_timeout_and_bash(tmp_path):
    store = SkillStore(tmp_path)
    store.save(spec(id="always_fails", code="import sys\nsys.exit('disk is full')\n"))
    store.save(spec(id="too_slow", code="import time\ntime.sleep(30)\n"))
    store.save(spec(id="bash_echo", language="bash", code='read -r args\necho "got $args"\n'))
    for skill_id in ("always_fails", "too_slow", "bash_echo"):
        store.approve(skill_id)
    failed = store.run("always_fails", {})
    assert failed["success"] is False and "disk is full" in failed["spoken_confirmation"]
    slow = store.run("too_slow", {}, timeout=1)
    assert slow["success"] is False and "took too long" in slow["spoken_confirmation"]
    cancel = threading.Event()
    cancel.set()
    assert store.run("too_slow", {}, cancel=cancel)["cancelled"]
    assert store.run("bash_echo", {"x": 1})["spoken_confirmation"] == 'got {"x": 1}'


def test_high_risk_skills_ask_before_every_run(registry):
    from daemon.agent.approval import approval_needed
    registry.skills.save(spec(id="empty_trash", risk_level="HIGH", name="Empty the trash"))
    registry.skills.approve("empty_trash")
    needs = approval_needed("empty_trash", {"_raw_user_query": "empty the trash"})
    assert needs["risk"] == "confirm" and "Empty the trash" in needs["label"]
    registry.skills.save(spec(id="list_trash", risk_level="SAFE"))
    assert approval_needed("list_trash", {}) is None


def test_claude_code_save_skill_tool(registry):
    from daemon.agent.orchestrator import AgentOrchestrator
    from tests.test_background_tasks import FakeLogger, ScriptedProvider
    o = AgentOrchestrator(registry=registry, engine=ExecutionEngine(registry), logger=FakeLogger(),
                          llm_provider=ScriptedProvider([]))
    seen = []
    o.skill_listener = seen.append
    ok = o._save_skill(spec(), "learn to greet people\n\nEarlier in the conversation: ...")
    assert not ok["is_error"] and "approves it" in ok["text"]
    assert seen[0]["id"] == "greet_person" and seen[0]["source_request"] == "learn to greet people"
    clash = o._save_skill(spec(id="app_launcher"), "x")
    assert clash["is_error"] and "already a Jarvis command" in clash["text"]


def test_approved_skills_can_become_learned_shortcuts(registry):
    from daemon.agent import pattern_miner as pm
    registry.skills.save(spec())
    registry.skills.approve("greet_person")
    registry.reload_tools()
    required = {t.id: list(t.parameters.get("required", [])) for t in registry.list_tools()}
    log = [{"user_query": f"say hi to {n}", "tool_executed": "greet_person", "tool_args": {"name": n}, "outcome": "ok",
            "served_by": {"kind": "llm"}, "llm_decision": {"tool": "greet_person", "args": {"name": n}}}
           for n in ("sam", "alex", "sam", "alex")]
    rules = pm.mine(log, required)
    assert [(r["triggers"][0], r["status"]) for r in rules] == [("say hi to {name}", "active")]


def test_claude_code_briefing_names_this_os():
    from daemon.agent.claude_code_agent import task_rules
    from daemon.os_interface import get_os
    text = task_rules()
    assert get_os().claude_code_context in text and "save_skill" in text
