"""Background learning: grade uncached requests, let a locked-down Claude Code write rules, verify them."""

import json

import pytest

from daemon.agent import pattern_miner as pm
from daemon.agent.fast_path_manager import FastPathManager
from daemon.agent.pattern_learner import PatternLearner
from daemon.tools.registry import ToolRegistry

TIMER = {"templates": ["set a timer for {n} minutes", "{n} minute timer", "set a {n} minute timer"],
         "slots": {"n": {"kind": "number"}}, "tool": "set_timer", "args": {"duration": "{n}m", "label": "Timer"},
         "reason": "The words decide the timer length."}


def turn(query, tool="set_timer", args=None, outcome="ok", **extra):
    args = {"duration": "10m", "label": "Timer"} if args is None else args
    return {"user_query": query, "tool_executed": tool, "tool_args": args, "outcome": outcome,
            "served_by": {"kind": "llm"}, "llm_decision": {"tool": tool, "args": args},
            "timestamp": "2026-11-23T12:00:00", **extra}


class Grader:
    def __init__(self, verdict):
        self.verdict, self.prompts = verdict, []

    def process_voice_query(self, prompt, history, system):
        self.prompts.append((prompt, system))
        return self.verdict


class FakeSession:
    """Plays Claude Code: tries the rule, then saves it (or whatever script it's given)."""

    def __init__(self, script):
        self.script = script

    def __call__(self, prompt, decide, call_tool):
        self.prompt, self.decide, self.call_tool = prompt, decide, call_tool
        return self

    def run(self):
        self.results = [json.loads(self.call_tool(name, args)["text"]) for name, args in self.script]
        return {"ok": True, "text": "Saved a timer rule."}


@pytest.fixture
def env(tmp_path):
    registry = ToolRegistry(config_dir=str(tmp_path / "tools"))
    registry.register_tool({  # a stand-in: this version of Jarvis has no timer tool
        "id": "set_timer", "name": "Set a timer", "description": "Starts a countdown timer.",
        "parameters": {"type": "object", "properties": {"duration": {"type": "string"}, "label": {"type": "string"}},
                       "required": ["duration"]},
        "execution": {"type": "command_template", "template": "echo {duration}"}})
    fast = FastPathManager(rules_path=tmp_path / "rules.json")
    log = []

    def make(verdict=None, script=(), **kw):
        session = FakeSession(list(script))
        learner = PatternLearner(fast, registry, records=lambda: log,
                                 grader=lambda: Grader(verdict or {"cache": True, "reason": "routine"}),
                                 app_exists=lambda name: name in {"figma", "slack"}, session_factory=session, **kw)
        return learner, session
    return registry, fast, log, make


# ---- Authored rules ---------------------------------------------------------------------------

def test_authored_rule_fills_slots_into_arguments():
    hit = pm.predict_authored(TIMER, pm.normalize("Hey Jarvis, can you set a timer for 25 minutes?"), lambda n: False)
    assert hit == {"tool": "set_timer", "args": {"duration": "25m", "label": "Timer"}, "slots": {"n": 25}}
    assert pm.predict_authored(TIMER, pm.normalize("5 minute timer please"), lambda n: False)["args"]["duration"] == "5m"
    assert pm.predict_authored(TIMER, pm.normalize("set a timer for the pasta"), lambda n: False) is None


def test_enum_slots_map_words_to_values():
    rule = {"templates": ["make it {how}"], "slots": {"how": {"kind": "enum", "values": {"louder": "5%+", "quieter": "5%-"}}},
            "tool": "volume_control", "args": {"action": "{how}"}}
    assert pm.predict_authored(rule, ["make", "it", "louder"], lambda n: False)["args"] == {"action": "5%+"}
    assert pm.predict_authored(rule, ["make", "it", "purple"], lambda n: False) is None


def test_authored_rule_problems():
    tools = {"set_timer": ["duration"], "execute_terminal_command": ["command"]}
    assert pm.authored_problems(TIMER, tools) == []
    bad = dict(TIMER, tool="execute_terminal_command", args={"command": "{n}"})
    assert any("never replayed" in p for p in pm.authored_problems(bad, tools))
    assert any("fixed word" in p for p in pm.authored_problems(dict(TIMER, templates=["{n}"]), tools))
    assert any("undeclared" in p for p in pm.authored_problems(dict(TIMER, args={"duration": "{m}m"}), tools))
    assert any("needs the argument" in p for p in pm.authored_problems(dict(TIMER, args={"label": "x {n}"}), tools))


def test_authored_rules_are_verified_like_mined_ones():
    tools = {"set_timer": ["duration"]}
    spec = dict(TIMER, id="authored_x")
    one = [turn("set a timer for 10 minutes")]
    rules = pm.mine(one, tools, authored=[spec])
    assert [(r["kind"], r["status"]) for r in rules] == [("authored", "shadow")]
    two = one + [turn("25 minute timer", args={"duration": "25m", "label": "Timer"})]
    assert [r["status"] for r in pm.mine(two, tools, authored=[spec]) if r["kind"] == "authored"] == ["active"]
    # The model doing something else for a matching request drops it.
    clash = two + [turn("set a timer for 3 minutes", args={"duration": "180s", "label": "Timer"})]
    assert [r for r in pm.mine(clash, tools, authored=[spec]) if r["kind"] == "authored"] == []
    hit = pm.match_rules(pm.mine(two, tools, authored=[spec]), "set a timer for 7 minutes", lambda n: False)
    assert hit["mode"] == "active" and hit["args"]["duration"] == "7m"


# ---- The learner ------------------------------------------------------------------------------

def test_prefilter_skips_what_isnt_worth_a_model_call(env):
    _, fast, _, make = env
    learner, _ = make(enabled=lambda: True)
    assert learner.skip_reason(turn("open a terminal", tool="execute_terminal_command", args={"command": "x"}))
    assert learner.skip_reason({**turn("set a timer for 10 minutes"), "served_by": {"kind": "fast_path"}})
    assert learner.skip_reason(turn("set a timer for 10 minutes", outcome="failed"))
    assert learner.skip_reason({**turn("set a timer for 10 minutes"), "pattern_prediction": {"rule_id": "x"}})
    assert learner.skip_reason(turn("tell me a joke", tool="none", args={}))
    assert learner.skip_reason(turn("set a timer for 10 minutes")) == ""
    fast.record_grade("set a timer for 10 minutes", {"cache": False})
    assert learner.skip_reason(turn("set a timer for 10 minutes")) == "already graded"
    off, _ = make(enabled=lambda: False)
    assert off.skip_reason(turn("set a 5 minute timer")) == "background learning is off"


def test_grader_says_no_so_claude_code_never_runs(env):
    _, fast, log, make = env
    log.append(turn("set a timer for 10 minutes"))
    learner, session = make(verdict={"cache": False, "reason": "one-off"},
                            script=[("save_pattern", {"rule": TIMER})])
    assert learner.learn(log[-1]) is None
    assert not hasattr(session, "results")
    assert fast.graded["set a timer for 10 minutes"]["cache"] is False


def test_claude_code_tests_then_saves_a_rule(env):
    _, fast, log, make = env
    log.append(turn("set a timer for 10 minutes"))
    saved_calls = []
    learner, session = make(script=[("test_pattern", {"rule": TIMER, "phrases": ["15 minute timer", "set a timer for the pasta"]}),
                                    ("save_pattern", {"rule": TIMER})], on_saved=lambda: saved_calls.append(1))
    rule = learner.learn(log[-1])
    tested = session.results[0]
    assert tested["problems"] == [] and tested["agreeing"] == 1
    assert [p["matches"] for p in tested["phrases"]] == [True, False]
    assert rule["tool"] == "set_timer" and fast.authored[0]["id"] == rule["id"] and saved_calls == [1]
    assert rule["source_request"] == "set a timer for 10 minutes"


def test_save_refuses_contradictions_and_rules_that_miss_their_request(env):
    _, fast, log, make = env
    log += [turn("set a timer for 10 minutes"), turn("set a timer for 3 minutes", args={"duration": "180s", "label": "Timer"})]
    learner, _ = make()
    clash = learner.save(TIMER, log[0])
    assert clash["saved"] is False and clash["contradictions"]
    miss = learner.save(dict(TIMER, templates=["start a {n} minute countdown"]), log[0])
    assert miss["saved"] is False and "doesn't reproduce" in miss["problems"][0]
    assert fast.authored == []


def test_background_claude_code_can_only_read_and_use_the_two_tools(env):
    _, _, log, make = env
    log.append(turn("set a timer for 10 minutes"))
    learner, session = make(script=[])
    learner.learn(log[-1])
    allow = lambda name: session.decide(name, {})["behavior"]
    assert allow("Read") == allow("Grep") == allow("mcp__jarvis__save_pattern") == "allow"
    for name in ("Bash", "Write", "Edit", "WebFetch", "mcp__jarvis__app_launcher"):
        assert allow(name) == "deny"
    assert session.call_tool("app_launcher", {})["is_error"]


def test_daily_limit(env):
    _, _, log, make = env
    log.append(turn("set a timer for 10 minutes"))
    learner, session = make(script=[], daily_limit=1)
    learner.learn(log[-1])
    session.results = "untouched"
    learner.learn(turn("set a 5 minute timer"))
    assert session.results == "untouched"


def test_deleting_an_authored_rule_keeps_it_from_coming_back(env):
    _, fast, log, make = env
    log.append(turn("set a timer for 10 minutes"))
    learner, _ = make()
    rule = learner.save(TIMER, log[0])["rule"]
    assert fast.delete_rule(rule["id"]) and fast.authored == []
    again = learner.save(TIMER, log[0])
    assert again["saved"] is False and "deleted" in again["problems"][0]
