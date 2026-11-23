"""The system prompt's cached prefix must not change when the date, focus mode or memory profile do."""

from pathlib import Path

from daemon.agent.orchestrator import AgentOrchestrator
from daemon.providers.base import VOLATILE_CONTEXT_TAG, split_system_prompt
from daemon.providers.llm.anthropic_llm_provider import build_system_blocks
from daemon.tools.registry import ToolRegistry


class Provider:
    def get_provider_info(self):
        return {"name": "Anthropic Claude (test)"}


def orchestrator(tmp_path):
    return AgentOrchestrator(registry=ToolRegistry(config_dir=str(tmp_path / "tools")), llm_provider=Provider())


def test_profile_changes_leave_the_cached_part_alone(tmp_path):
    o = orchestrator(tmp_path)
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text("# User Profile\n- Preferred IDE: Kakoune-7731")
    b.write_text("# User Profile\n- Preferred IDE: Sublime")
    stable_a, volatile_a = split_system_prompt(o.build_system_prompt(a))
    stable_b, volatile_b = split_system_prompt(o.build_system_prompt(b))
    assert stable_a == stable_b
    assert "Kakoune-7731" in volatile_a and "Sublime" in volatile_b
    assert "Kakoune-7731" not in stable_a


def test_changing_context_is_last(tmp_path):
    prompt = orchestrator(tmp_path).build_system_prompt(tmp_path / "none.md")
    tail = prompt[prompt.index(VOLATILE_CONTEXT_TAG):]
    assert "<current_time>" in tail and "<focus_mode_status>" in tail
    assert "<available_tools>" not in tail  # the big stable parts all come before it


def test_only_the_stable_block_is_cached():
    blocks = build_system_blocks(f"RULES AND TOOLS\n{VOLATILE_CONTEXT_TAG}\n  <current_time>Today</current_time>\n")
    assert [("cache_control" in b) for b in blocks] == [True, False]
    assert build_system_blocks("") == []  # the memory profiler sends none: the API rejects empty blocks
    assert build_system_blocks("no tag here")[0]["cache_control"] == {"type": "ephemeral"}


def test_macros_are_listed_in_a_stable_order(tmp_path, monkeypatch):
    import daemon.macros.macro_manager as mm
    macros = {"zeta": {"name": "Zeta", "steps": []}, "alpha": {"name": "Alpha", "steps": []}}
    monkeypatch.setattr(mm, "get_macro_manager", lambda: type("M", (), {"list_macros": lambda self: macros})())
    prompt = orchestrator(tmp_path).build_system_prompt(tmp_path / "none.md")
    assert prompt.index("'alpha'") < prompt.index("'zeta'")


# ---- Requests per model (fake client: nothing is sent) ------------------------------------------

from types import SimpleNamespace

import daemon.providers.llm.anthropic_llm_provider as anth


def fake_client(monkeypatch, *, stop_reason="end_turn", text='{"tool": "none", "args": {}, "spoken_summary": "Hi."}'):
    sent = []

    def create(**kwargs):
        sent.append(kwargs)
        content = [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)]
        return SimpleNamespace(content=content, stop_reason=stop_reason, stop_details=None,
                               usage=SimpleNamespace(cache_read_input_tokens=0, cache_creation_input_tokens=0, output_tokens=5))

    monkeypatch.setattr(anth, "_client", lambda key: SimpleNamespace(messages=SimpleNamespace(create=create)))
    return sent


def test_haiku_5_5_gets_low_effort_and_room_to_think(monkeypatch):
    sent = fake_client(monkeypatch)
    res = anth.AnthropicLLMProvider(api_key="k", model_name="claude-haiku-5-5").process_voice_query("hi", [], "RULES")
    assert sent[0]["model"] == "claude-haiku-5-5"
    assert sent[0]["output_config"] == {"effort": "low"} and sent[0]["max_tokens"] >= 1024
    assert res["spoken_summary"] == "Hi."  # the answer is read past the thinking block


def test_haiku_4_5_requests_are_unchanged(monkeypatch):
    sent = fake_client(monkeypatch)
    anth.AnthropicLLMProvider(api_key="k", model_name="claude-haiku-4-5-20251001").process_voice_query("hi", [], "RULES")
    assert "output_config" not in sent[0] and sent[0]["max_tokens"] == 300  # Haiku 4.5 rejects effort


def test_a_refusal_is_said_plainly(monkeypatch):
    fake_client(monkeypatch, stop_reason="refusal", text="")
    res = anth.AnthropicLLMProvider(api_key="k", model_name="claude-haiku-5-5").process_voice_query("x", [], "RULES")
    assert res == {"tool": "none", "args": {}, "spoken_summary": "Sorry, I can't help with that one."}


def test_haiku_5_5_is_offered_in_settings():
    assert "claude-haiku-5-5" in anth.AnthropicLLMProvider(api_key="k").get_available_models()


# ---- Compact prompt sections ---------------------------------------------------------------------

def test_tools_are_listed_compactly(tmp_path):
    reg = ToolRegistry(config_dir=str(tmp_path / "tools"))
    text = reg.get_llm_tool_descriptions()
    assert '- volume_control: ' in text and '  e.g. "Turn up the volume" -> ' in text
    assert "Parameters JSON Schema" not in text and "Cause (User Request)" not in text


def test_apps_are_listed_by_name():
    from daemon.os_interface.base import AppEntry
    from daemon.tools.app_scanner import AppScanner
    s = AppScanner.__new__(AppScanner)
    s.apps = {}
    for i, name in enumerate(["Spotify", "Ghostty", "Xcode"]):
        e = AppEntry(f"/A/{name}.app", name, name, [], f"com.x.{i}")
        s.apps[name.lower()] = e
    summary = s.get_prompt_app_summary(limit=2)
    assert summary.endswith(": Ghostty, Spotify (and 1 more)") and "com.x" not in summary
