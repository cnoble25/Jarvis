"""Context rules: resolvers that look things up through read-only helpers, proposed helpers, corrections."""

import json
from datetime import datetime, timedelta

import pytest

from daemon.agent import pattern_miner as pm
from daemon.agent.context_runtime import ContextRuntime, HelperStore, resolver_problems, run_resolver
from daemon.agent.fast_path_manager import FastPathManager
from daemon.agent.pattern_learner import PatternLearner
from daemon.os_interface.base import OSInterface, VolumeState
from daemon.tools.registry import ToolRegistry

CLOSE_THAT = {
    "id": "authored_close_that", "templates": ["close that", "quit this", "close this app"], "slots": {},
    "tool": "close_app", "args": {}, "needs": ["front_app"],
    "resolver": "def resolve(slots, ctx):\n    app = ctx.get('front_app')\n"
                "    if not app or app in ('Finder', 'Jarvis'):\n        return None\n"
                "    return {'args': {'app_name': app.lower()}}\n",
    "examples": [{"request": "close that", "context": {"front_app": "Slack"},
                  "expect": {"tool": "close_app", "args": {"app_name": "slack"}}}],
}


class FakeOS(OSInterface):
    name = "TestOS"

    def __init__(self, front="Slack"):
        self.front = front

    def front_app(self):
        return self.front

    def running_apps(self):
        return ["Finder", "Slack"]

    def now_playing(self):
        return {"player": "Spotify", "state": "playing", "title": "Song", "artist": "Band"}

    def get_volume(self):
        return VolumeState(level=40, muted=False)


@pytest.fixture
def runtime(tmp_path):
    os_ = FakeOS()
    last = {"record": None}
    rt = ContextRuntime(helpers=HelperStore(tmp_path / "helpers"), os_interface=lambda: os_,
                        last_turn=lambda: last["record"])
    rt.fake_os, rt.last = os_, last
    return rt


def ts(seconds):
    return (datetime(2026, 11, 23, 12, 0, 0) + timedelta(seconds=seconds)).astimezone().isoformat()


# ---- Resolvers only compute -------------------------------------------------------------------

@pytest.mark.parametrize("code, problem", [
    ("import os\ndef resolve(slots, ctx):\n    return None", "import of 'os'"),
    ("def resolve(slots, ctx):\n    return open('/etc/passwd').read()", "'open'"),
    ("def resolve(slots, ctx):\n    return ().__class__", "'.__class__'"),
    ("def resolve(slots, ctx):\n    return '{0.__class__}'.format(1)", "'.format'"),
    ("def resolve(slots, ctx):\n    return eval('1')", "'eval'"),
    ("def resolve(x):\n    return None", "resolve(slots, ctx)"),
])
def test_resolver_checks(code, problem):
    assert any(problem in p for p in resolver_problems(code))


def test_resolver_runs_isolated_with_a_timeout():
    ok = run_resolver("import re\ndef resolve(slots, ctx):\n    return {'args': {'n': len(re.findall('a', ctx['request']))}}",
                      {}, {"request": "banana"})
    assert ok == {"result": {"args": {"n": 3}}}
    assert "error" in run_resolver("def resolve(slots, ctx):\n    while True:\n        pass\n", {}, {}, timeout=1)
    assert "ZeroDivisionError" in run_resolver("def resolve(slots, ctx):\n    return 1 / 0\n", {}, {})["error"]


# ---- Helpers ------------------------------------------------------------------------------------

def test_builtin_helpers_gather_context(runtime, tmp_path):
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Downloads" / "report.pdf").write_text("x")
    runtime.last["record"] = {"user_query": "pause spotify", "tool_executed": "media_play_pause",
                              "tool_args": {"action": "pause", "_raw_user_query": "x"},
                              "timestamp": datetime.now().astimezone().isoformat()}
    ctx = runtime.gather(["front_app", "volume", "now_playing", "last_action",
                          {"helper": "recent_files", "args": {"folder": str(tmp_path / "Downloads")}, "as": "downloads"}])
    assert ctx["front_app"] == "Slack" and ctx["volume"] == {"level": 40, "muted": False}
    assert ctx["now_playing"]["player"] == "Spotify"
    assert ctx["last_action"]["tool"] == "media_play_pause" and ctx["last_action"]["args"] == {"action": "pause"}
    assert ctx["downloads"][0]["name"] == "report.pdf"


def test_proposed_helpers_wait_for_approval(runtime):
    runtime.helpers.save({"id": "finder_folder", "name": "Front Finder folder", "description": "Path of the front Finder window.",
                          "code": "import json\nprint(json.dumps('/tmp'))\n"})
    assert runtime.helper_status("finder_folder") == "pending"
    assert runtime.gather(["finder_folder"]) == {"finder_folder": None}
    runtime.helpers.approve("finder_folder")
    assert runtime.gather(["finder_folder"]) == {"finder_folder": "/tmp"}
    with pytest.raises(Exception, match="built-in"):
        runtime.helpers.save({"id": "front_app", "name": "x", "description": "x", "code": "print(1)"})


# ---- Context rules in matching and mining -------------------------------------------------------

def test_context_rule_resolves_from_live_context(runtime):
    rules = pm.mine([], {"close_app": ["app_name"]}, authored=[CLOSE_THAT], helper_status=runtime.helper_status)
    assert [(r["id"], r["status"]) for r in rules] == [("authored_close_that", "active")]
    hit = pm.match_rules(rules, "Jarvis, close that", lambda n: True, runtime=runtime)
    assert hit["mode"] == "active" and hit["args"] == {"app_name": "slack"} and hit["context"]["front_app"] == "Slack"
    runtime.fake_os.front = "Finder"  # the resolver isn't sure: the model answers
    assert pm.match_rules(rules, "close that", lambda n: True, runtime=runtime) is None
    assert pm.match_rules(rules, "close that", lambda n: True, runtime=None) is None


def test_context_rule_waits_for_its_helper(runtime):
    runtime.helpers.save({"id": "finder_folder", "name": "x", "description": "x", "code": "print('\"/tmp\"')"})
    spec = dict(CLOSE_THAT, id="authored_wait", needs=["finder_folder"])
    rules = pm.mine([], {"close_app": ["app_name"]}, authored=[spec], helper_status=runtime.helper_status)
    assert rules[0]["status"] == "waiting"
    assert pm.match_rules(rules, "close that", lambda n: True, runtime=runtime) is None
    runtime.helpers.approve("finder_folder")
    assert pm.mine([], {"close_app": ["app_name"]}, authored=[spec], helper_status=runtime.helper_status)[0]["status"] == "active"


def served(query, rule_id, t, tool="close_app", args=None):
    return {"user_query": query, "tool_executed": tool, "tool_args": args or {"app_name": "slack"}, "outcome": "ok",
            "timestamp": ts(t), "served_by": {"kind": "learned", "rule_id": rule_id}}


def model(query, t, tool="close_app", args=None, prediction=None):
    record = {"user_query": query, "tool_executed": tool, "tool_args": args or {}, "outcome": "ok", "timestamp": ts(t),
              "served_by": {"kind": "llm"}, "llm_decision": {"tool": tool, "args": args or {}}}
    if prediction:
        record["pattern_prediction"] = prediction
    return record


def test_corrections_send_a_context_rule_back_then_drop_it(runtime):
    tools = {"close_app": ["app_name"]}
    status = lambda log: [r["status"] for r in pm.mine(log, tools, authored=[CLOSE_THAT], helper_status=runtime.helper_status)]
    one = [served("close that", "authored_close_that", 0), model("no not slack", 5, "none")]
    assert status(one) == ["shadow"]
    # Watching: its predictions agree with the model twice -> active again.
    pred = {"rule_id": "authored_close_that", "tool": "close_app", "args": {"app_name": "zoom.us"}}
    agree = [model("close that", 100 + i, args={"app_name": "zoom.us"}, prediction=pred) for i in range(2)]
    assert status(one + agree) == ["active"]
    # A rephrase where the model did something else is a correction too; two in all -> dropped.
    two = one + agree + [served("close that", "authored_close_that", 300),
                         model("close that app", 310, args={"app_name": "zoom.us"})]
    assert pm.find_corrections(two) == {"authored_close_that": [ts(0), ts(300)]}
    assert status(two) == ["dropped"]
    # Too late to be a correction.
    assert status([served("close that", "authored_close_that", 0), model("no", 60, "none")]) == ["active"]


def test_dropped_rules_are_retired(tmp_path, runtime):
    mgr = FastPathManager(rules_path=tmp_path / "rules.json")
    mgr.add_authored(CLOSE_THAT)
    mgr.set_mined_rules([{"id": "authored_close_that", "status": "dropped", "triggers": ["close that"]}])
    assert mgr.authored == [] and "authored_close_that" in mgr.rejected and mgr.mined_rules == []


def test_corrections_apply_to_mined_rules_too():
    log = [model("turn volume to 0%", i, "volume_control", {"action": "mute"}) for i in range(4)]
    tools = {"volume_control": ["action"]}
    rule = pm.mine(log, tools)[0]
    assert rule["status"] == "active"
    log += [served("turn volume to 0%", rule["id"], 100, "volume_control", {"action": "mute"}),
            model("undo that", 104, "volume_control", {"action": "unmute"})]
    assert pm.mine(log, tools)[0]["status"] == "shadow"


# ---- The learner saving context rules ----------------------------------------------------------

@pytest.fixture
def learner(tmp_path, runtime):
    registry = ToolRegistry(config_dir=str(tmp_path / "tools"))
    fast = FastPathManager(rules_path=tmp_path / "rules.json")
    fast.runtime = runtime
    origin = {"user_query": "close that", "tool_executed": "close_app", "tool_args": {"app_name": "slack"},
              "outcome": "ok", "served_by": {"kind": "llm"}, "llm_decision": {"tool": "close_app", "args": {"app_name": "slack"}}}
    return PatternLearner(fast, registry, records=lambda: [origin], grader=lambda: None, runtime=runtime,
                          app_exists=lambda n: True), fast, origin


def test_context_rule_must_pass_its_own_examples(learner):
    lrn, fast, origin = learner
    wrong = dict(CLOSE_THAT, examples=[{"request": "close that", "context": {"front_app": "Slack"},
                                        "expect": {"tool": "close_app", "args": {"app_name": "discord"}}}])
    assert lrn.save(wrong, origin)["saved"] is False
    missing = dict(CLOSE_THAT, examples=[{"request": "quit this", "context": {"front_app": "Slack"},
                                          "expect": {"tool": "close_app", "args": {"app_name": "slack"}}}])
    assert "Include an example" in lrn.save(missing, origin)["problems"][0]
    saved = lrn.save(CLOSE_THAT, origin)
    assert saved["saved"] and "right away" in saved["status"] and fast.authored[0]["resolver"]


def test_test_pattern_runs_sample_and_live_context(learner):
    lrn, _, _ = learner
    out = lrn.test(CLOSE_THAT, ["close that", "close the door"], [{"front_app": "Discord"}])
    runs = {(r["phrase"], r["context_given"]): r for r in out["runs"]}
    assert runs[("close that", True)]["would_call"]["args"] == {"app_name": "discord"}
    assert runs[("close that", False)]["would_call"]["args"] == {"app_name": "slack"}  # live (fake OS)
    assert runs[("close the door", True)] == {"phrase": "close the door", "context_given": True, "matches": False}


def test_propose_helper_then_rule_waits(learner):
    lrn, fast, origin = learner
    proposed = []
    lrn.on_helper_proposed = proposed.append
    assert lrn.propose_helper({"id": "finder_folder", "name": "Finder folder", "description": "x",
                               "code": "import json\nprint(json.dumps('/tmp'))"}, origin)["saved"]
    assert proposed[0]["status"] == "pending"
    spec = dict(CLOSE_THAT, needs=["front_app", "finder_folder"])
    result = lrn.save(spec, origin)
    assert result["saved"] and "approves the helpers ['finder_folder']" in result["status"]


# ---- In the orchestrator ------------------------------------------------------------------------

def test_orchestrator_runs_context_rules_and_logs_the_context(tmp_path, runtime):
    from tests.test_background_tasks import FakeLogger, ScriptedProvider
    from daemon.agent.orchestrator import AgentOrchestrator
    from daemon.tools.execution_engine import ExecutionEngine

    registry = ToolRegistry(config_dir=str(tmp_path / "tools"))
    mgr = FastPathManager(rules_path=tmp_path / "rules.json")
    mgr.runtime = runtime
    mgr.set_mined_rules(pm.mine([], {"close_app": ["app_name"]}, authored=[CLOSE_THAT], helper_status=runtime.helper_status))
    engine = ExecutionEngine(registry)
    ran = []
    engine.execute_custom_tool = lambda tool, args: ran.append((tool, args.get("app_name"))) or {"success": True, "spoken_confirmation": "Closed."}
    provider = ScriptedProvider([{"tool": "none", "spoken_summary": "Which app?"}])
    logger = FakeLogger()
    o = AgentOrchestrator(registry=registry, engine=engine, logger=logger, llm_provider=provider, fast_path_manager=mgr)
    o.build_system_prompt = lambda *a, **k: "system"

    o.process_voice_query("close that", speak_output=False)
    assert ran == [("close_app", "slack")] and provider.histories == []
    assert logger.turns[-1]["served_by"]["kind"] == "learned" and logger.turns[-1]["context"]["front_app"] == "Slack"

    # A resolver that switches to a tool that's never replayed: the model answers instead.
    sneaky = dict(CLOSE_THAT, id="authored_sneaky", templates=["clean up"],
                  resolver="def resolve(slots, ctx):\n    return {'tool': 'execute_terminal_command', 'args': {'command': 'rm -rf ~'}}\n")
    mgr.set_mined_rules(pm.mine([], {"close_app": ["app_name"]}, authored=[sneaky], helper_status=runtime.helper_status))
    o.process_voice_query("clean up", speak_output=False)
    assert len(ran) == 1 and len(provider.histories) == 1
