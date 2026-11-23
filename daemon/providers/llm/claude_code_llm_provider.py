"""
Claude Code LLM Provider: routes a request through the locally installed, unmodified `claude`
CLI in headless mode (`claude -p`), signed in with the user's own Claude Code login.

Jarvis never reads or stores Claude credentials; it only runs the `claude` binary. Claude Code
gets no built-in tools (no file edits, no shell) and no MCP servers: it chooses among Jarvis's
own commands exactly like the other providers, returning {"tool", "args", "spoken_summary"}.

Usage counts against the signed-in Claude Code plan. Personal use only.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from daemon.providers.base import BaseLLMProvider
from daemon.providers.factory import ProviderRegistry

MODELS = ["haiku", "sonnet", "opus"]
WORK_DIR = Path.home() / ".local" / "share" / "jarvis" / "claude-code"
TIMEOUT_SECONDS = 60
MAX_SPOKEN_CHARS = 220
_FALLBACK_BINARIES = ["/home/linuxbrew/.linuxbrew/bin/claude", str(Path.home() / ".local/bin/claude"),
                      "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]

# Appended to Jarvis's system prompt: the reply is spoken and shown in the small HUD pill.
VOICE_RULES = """

You are answering through Jarvis, a voice assistant on the user's Linux desktop.
Reply with ONLY one JSON object in the format described above: no prose around it, no code fences.
"spoken_summary" is read aloud and shown in a small on-screen pill, so keep it to at most two short
sentences (under 35 words), plain speech, no markdown, lists, URLs or code."""


def find_claude() -> Optional[str]:
    return shutil.which("claude") or next((p for p in _FALLBACK_BINARIES if os.access(p, os.X_OK)), None)


def _shorten(text: str, limit: int = MAX_SPOKEN_CHARS) -> str:
    """Keep spoken replies pill-sized: cut at a sentence end, else a word boundary."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for mark in (". ", "! ", "? "):
        idx = cut.rfind(mark)
        if idx > limit * 0.4:
            return cut[: idx + 1]
    return cut.rsplit(" ", 1)[0].rstrip(",;:") + "…"


@ProviderRegistry.register_llm("claude_code")
class ClaudeCodeLLMProvider(BaseLLMProvider):
    def __init__(self, model_name: str = "haiku"):
        self.model_name = model_name if model_name in MODELS else "haiku"

    def get_available_models(self) -> List[str]:
        return list(MODELS)

    def process_voice_query(self, user_query: str, history: List[Dict[str, str]], system_prompt: str) -> Dict[str, Any]:
        binary = find_claude()
        if not binary:
            return {"tool": "none", "args": {}, "spoken_summary": "Claude Code isn't installed on this computer."}

        lines = []
        recent = history[-4:]
        if recent:
            lines.append("Earlier in this conversation:")
            for turn in recent:
                who = "User" if turn.get("role") == "user" else "Jarvis"
                lines.append(f"{who}: {turn.get('content', '')}")
            lines.append("")
        lines.append(f"User request (spoken, transcribed by speech recognition): {user_query}")
        prompt = "\n".join(lines)

        # Use the CLI's own Claude Code login, not an API key Jarvis may have loaded from .env.
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        WORK_DIR.mkdir(parents=True, exist_ok=True)  # Empty folder: no project CLAUDE.md, hooks or MCP config load.
        cmd = [
            binary, "-p",
            "--output-format", "json",
            "--model", self.model_name,
            "--tools", "",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--system-prompt", system_prompt + VOICE_RULES,
        ]
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                  timeout=TIMEOUT_SECONDS, cwd=WORK_DIR, env=env)
        except subprocess.TimeoutExpired:
            return {"tool": "none", "args": {}, "spoken_summary": "Claude Code took too long to answer."}
        except Exception as err:
            print(f"[ClaudeCodeLLM Error] Couldn't run claude: {err}", flush=True)
            return {"tool": "none", "args": {}, "spoken_summary": "Couldn't start Claude Code."}

        try:
            envelope = json.loads(proc.stdout)
        except Exception:
            print(f"[ClaudeCodeLLM Error] Unexpected output (exit {proc.returncode}): {proc.stdout[:300]} {proc.stderr[:300]}", flush=True)
            return {"tool": "none", "args": {}, "spoken_summary": "Claude Code gave an answer I couldn't read."}

        result_text = str(envelope.get("result", ""))
        if envelope.get("is_error") or proc.returncode != 0:
            print(f"[ClaudeCodeLLM Error] {result_text[:300]}", flush=True)
            hint = "Run claude once in a terminal to sign in." if "login" in result_text.lower() or "auth" in result_text.lower() else ""
            return {"tool": "none", "args": {}, "spoken_summary": _shorten(f"Claude Code couldn't answer. {hint}".strip())}

        from daemon.utils.json_utils import extract_json_payload
        parsed = extract_json_payload(result_text)
        if not isinstance(parsed, dict) or not any(k in parsed for k in ("tool", "spoken_summary")):
            parsed = {"tool": "none", "args": {}, "spoken_summary": result_text}
        parsed["spoken_summary"] = _shorten(parsed.get("spoken_summary") or parsed.get("response") or "")
        if os.environ.get("JARVIS_DEBUG_LLM"):
            print(f"[ClaudeCodeLLM Debug] api_ms={envelope.get('duration_api_ms')} total_ms={envelope.get('duration_ms')}", flush=True)
        return parsed

    def get_provider_info(self) -> Dict[str, Any]:
        model = getattr(self, "model_name", "haiku")
        return {
            "id": "claude_code",
            "name": f"Claude Code ({model})",
            "type": "cloud",
            "model_name": model,
            "models": list(MODELS),
        }
