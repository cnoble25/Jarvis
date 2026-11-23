"""Learned shortcuts: mining the transcript log for requests that can skip the model."""

import json

from daemon.agent import pattern_miner as pm
from daemon.agent.fast_path_manager import FastPathManager

TOOLS = {"app_launcher": ["app_name"], "volume_control": ["action"], "set_timer": ["duration"],
         "media_play_pause": [], "execute_terminal_command": ["command"]}
APPS = {"figma", "discord", "slack", "google chrome"}
app_exists = lambda name: name in APPS


def turn(query, tool="none", args=None, outcome="ok", served="llm", confidence=None, **extra):
    record = {"user_query": query, "tool_executed": tool, "tool_args": args or {}, "outcome": outcome,
              "timestamp": "2026-11-23T10:00:00", **extra}
    if served is not None:
        record["served_by"] = {"kind": served}
        if served == "llm":
            record["llm_decision"] = {"tool": tool, "args": args or {}}
    if confidence is not None:
        record["heard_alternatives"] = [{"text": query, "probability": confidence}]
    return record


def mine(records, **kw):
    return pm.mine(records, TOOLS, app_exists=app_exists, **kw)


def by_template(rules):
    return {r["triggers"][0]: r for r in rules}


def test_normalize_drops_address_politeness_and_punctuation():
    assert pm.normalize("Hey Jarvis, can you open Chrome for me please?") == ["open", "chrome"]
    assert pm.normalize("Jarvis: set volume to 50%.") == ["set", "volume", "to", "50%"]
    assert pm.normalize("please") == ["please"]  # never strip a request down to nothing


def test_app_slot_generalizes_once_two_apps_agree():
    log = [turn("open figma", "app_launcher", {"app_name": "figma"}),
           turn("Open Discord.", "app_launcher", {"app_name": "discord"})] * 2
    rule = by_template(mine(log))["open {app_name}"]
    assert rule["status"] == "active" and rule["support"] == 4
    hit = pm.match_rules([rule], "jarvis open slack please", app_exists)
    assert hit["mode"] == "active" and hit["args"] == {"app_name": "slack"}
    assert pm.match_rules([rule], "open the pod bay doors", app_exists) is None  # not an installed app


def test_single_value_slot_matches_only_what_was_seen():
    log = [turn("open figma", "app_launcher", {"app_name": "figma"})] * 4
    rule = by_template(mine(log))["open {app_name}"]
    assert rule["slots"]["app_name"]["kind"] == "enum"
    assert pm.match_rules([rule], "open figma", app_exists)["args"] == {"app_name": "figma"}
    assert pm.match_rules([rule], "open slack", app_exists) is None


def test_shadow_until_enough_support():
    log = [turn("turn volume to 0%", "volume_control", {"action": "mute"})] * 3
    rule = by_template(mine(log))["turn volume to 0%"]
    assert rule["status"] == "shadow"
    log.append(turn("turn volume to 0%", "volume_control", {"action": "mute"}))
    assert by_template(mine(log))["turn volume to 0%"]["status"] == "active"


def test_any_disagreement_with_the_model_drops_the_rule():
    log = [turn("turn volume to 0%", "volume_control", {"action": "mute"})] * 5
    log.append(turn("turn volume to 0%", "volume_control", {"action": "0%"}))
    assert "turn volume to 0%" not in by_template(mine(log))


def test_a_rule_matching_a_request_the_model_answered_differently_is_dropped():
    # "open {app_name}" also matches "open slack", where the model chose to reply instead.
    log = [turn("open figma", "app_launcher", {"app_name": "figma"}),
           turn("open discord", "app_launcher", {"app_name": "discord"})] * 2
    log.append(turn("open slack", "none"))
    assert "open {app_name}" not in by_template(mine(log))


def test_latest_failure_keeps_a_rule_in_shadow():
    log = [turn("set a 10 minute timer", "set_timer", {"duration": "10m"})] * 4
    log.append(turn("set a 10 minute timer", "set_timer", {"duration": "10m"}, outcome="failed"))
    assert by_template(mine(log))["set a 10 minute timer"]["status"] == "shadow"


def test_never_learns_unsafe_tools_shortcut_turns_or_missing_args():
    log = ([turn("run the audit", "execute_terminal_command", {"command": "/tmp/x/audit.sh"})] * 5
           + [turn("pause the music", "media_play_pause", {}, served="fast_path")] * 5
           + [turn("open chrome", "app_launcher", {})] * 5)
    assert mine(log) == []


def test_skips_requests_a_builtin_shortcut_already_handles():
    log = [turn("mute volume", "volume_control", {"action": "toggle"})] * 5
    assert mine(log, handled_elsewhere=lambda q: "mute" in q) == []


def test_deleted_rules_stay_deleted():
    log = [turn("turn volume to 0%", "volume_control", {"action": "mute"})] * 4
    rule_id = mine(log)[0]["id"]
    assert mine(log, rejected=[rule_id]) == []


def test_older_logs_without_served_by_still_count():
    log = [turn("turn volume to 0%", "volume_control", {"action": "mute"}, served=None)] * 4
    assert by_template(mine(log))["turn volume to 0%"]["status"] == "active"
    routed = [turn("open spotify", "claude_code_task", {"task": "x"}, served=None, route={"label": "Claude Code"})] * 4
    assert mine(routed) == []


def test_noise_needs_repeats_low_confidence_and_no_action():
    noise = [turn("the video.", "none", confidence=c) for c in (0.5, 0.4, 0.33)]
    rule = by_template(mine(noise))["the video"]
    assert rule["kind"] == "noise" and rule["status"] == "active"
    # Heard clearly or typed now: answered normally.
    assert pm.match_rules([rule], "the video", app_exists, heard_confidence=0.3)["mode"] == "ignore"
    assert pm.match_rules([rule], "the video", app_exists, heard_confidence=0.9) is None
    assert pm.match_rules([rule], "the video", app_exists, heard_confidence=None) is None
    # One confident hearing in the log, or a time the model acted on it: not noise.
    assert mine(noise + [turn("the video", "none", confidence=0.95)]) == []
    assert mine(noise + [turn("the video", "media_play_pause", {}, confidence=0.4)]) == []
    assert mine(noise[:2]) == []


def test_report_counts_what_active_rules_would_skip():
    log = [turn("turn volume to 0%", "volume_control", {"action": "mute"})] * 4 + [turn("hello", "none")]
    text = pm.report(log, mine(log), app_exists)
    assert "Model decisions in the log: 5; active rules would have skipped 4 (80%)" in text


# ---- FastPathManager storage ---------------------------------------------------------------------

def test_old_rules_file_is_migrated_and_unsafe_shortcuts_dropped(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps([
        {"id": "learned_a", "triggers": ["audit"], "tool": "execute_terminal_command", "args": {"command": "/tmp/a.sh"}},
        {"id": "learned_b", "triggers": ["focus tunes"], "tool": "media_play_pause", "args": {"action": "play"}},
    ]))
    mgr = FastPathManager(rules_path=path)
    assert [r["id"] for r in mgr.learned_rules] == ["learned_b"]
    assert json.loads(path.read_text())["version"] == 2
    # Legacy shortcuts now match the whole request, not any sentence containing the phrase.
    assert mgr.match_learned("focus tunes please", app_exists=app_exists)["tool"] == "media_play_pause"
    assert mgr.match_learned("put on some focus tunes for the audit", app_exists=app_exists) is None


def test_deleting_a_mined_rule_rejects_it(tmp_path):
    mgr = FastPathManager(rules_path=tmp_path / "rules.json")
    rules = mine([turn("turn volume to 0%", "volume_control", {"action": "mute"})] * 4)
    assert mgr.set_mined_rules(rules) and not mgr.set_mined_rules(rules)
    assert mgr.delete_rule(rules[0]["id"])
    reloaded = FastPathManager(rules_path=tmp_path / "rules.json")
    assert reloaded.mined_rules == [] and reloaded.rejected == [rules[0]["id"]]


# ---- In the orchestrator -------------------------------------------------------------------------

def test_orchestrator_uses_learned_rules(tmp_path):
    from tests.test_background_tasks import FakeLogger, FakeRegistry, ScriptedProvider
    from daemon.agent.orchestrator import AgentOrchestrator
    from daemon.tools.execution_engine import ExecutionEngine

    mgr = FastPathManager(rules_path=tmp_path / "rules.json")
    mgr.set_mined_rules(mine([turn("the video", "none", confidence=0.4)] * 3
                             + [turn("turn volume to 0%", "volume_control", {"action": "mute"})] * 4
                             + [turn("make it quiet", "volume_control", {"action": "mute"})] * 2))
    provider = ScriptedProvider([{"tool": "none", "spoken_summary": "Sure."}])
    logger = FakeLogger()
    engine = ExecutionEngine(FakeRegistry(), dry_run=True)
    engine.execute_custom_tool = lambda tool, args: {"success": True, "spoken_confirmation": f"ran {tool}"}
    o = AgentOrchestrator(registry=FakeRegistry(), engine=engine, logger=logger, llm_provider=provider,
                          fast_path_manager=mgr)
    o.build_system_prompt = lambda *a, **k: "system"

    # Noise heard faintly: no model call, no reply.
    logger.pending = {"heard_alternatives": [{"text": "the video.", "probability": 0.3}]}
    assert o.process_voice_query("The video.", speak_output=False)["ignored"]
    assert logger.turns[-1]["served_by"]["kind"] == "noise"

    # Active rule: runs the tool without the model.
    res = o.process_voice_query("Jarvis, turn volume to 0%", speak_output=False)
    assert res["final_spoken_summary"] == "ran volume_control"
    volume_rule = next(r for r in mgr.mined_rules if r["triggers"] == ["turn volume to 0%"])
    assert logger.turns[-1]["served_by"] == {"kind": "learned", "rule_id": volume_rule["id"]}
    assert provider.histories == []

    # Shadow rule: the model answers, and the log keeps both decisions side by side.
    o.process_voice_query("make it quiet", speak_output=False)
    last = logger.turns[-1]
    assert len(provider.histories) == 1
    assert last["served_by"]["kind"] == "llm" and last["llm_decision"] == {"tool": "none", "args": {}}
    assert last["pattern_prediction"]["tool"] == "volume_control"
