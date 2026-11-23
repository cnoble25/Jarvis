"""
Anthropic Claude LLM provider, on the official `anthropic` SDK.

Latency notes (a voice turn waits on this call):
- One client per API key, reused: its connection pool keeps the HTTPS connection open between
  requests, so a turn doesn't pay a fresh TCP + TLS handshake.
- prepare() is called when the talk shortcut is pressed. If the pooled connection may have
  expired, it opens one with a free Models API request while the user is still speaking.
- The system prompt's stable part (instructions, tools, apps: ~5.8K tokens) is cached. The date,
  focus mode and memory profile come after it in their own uncached block, so the profile being
  rewritten every few turns doesn't throw the cache away. Haiku 4.5 only caches 4096+ tokens.
"""

import os
import threading
import time
from typing import Any, Dict, List, Optional

from daemon.providers.base import BaseLLMProvider, split_system_prompt
from daemon.providers.factory import ProviderRegistry

MODEL_MAPPING = {
    "haiku-5.5": "claude-haiku-5-5",
    "claude-haiku-5-5": "claude-haiku-5-5",

    "haiku-4.5": "claude-haiku-4-5-20251001",
    "claude-haiku-4-5-20251001": "claude-haiku-4-5-20251001",

    "haiku-4": "claude-haiku-4-5-20251001",
    "claude-4-haiku": "claude-haiku-4-5-20251001",

    "haiku-3.5": "claude-haiku-4-5-20251001",
    "claude-3-5-haiku-20241022": "claude-haiku-4-5-20251001",

    "haiku-3": "claude-haiku-4-5-20251001",
    "claude-3-haiku-20240307": "claude-haiku-4-5-20251001",

    "sonnet-4.5": "claude-sonnet-4-5-20250929",
    "claude-sonnet-4-5-20250929": "claude-sonnet-4-5-20250929",
    "sonnet-4.6": "claude-sonnet-4-6",
    "claude-sonnet-4-6": "claude-sonnet-4-6"
}
FALLBACK_MODELS = ["claude-haiku-5-5", "claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250929", "claude-sonnet-4-6"]
# Per-model request settings. Claude Haiku 5.5 thinks by default and its thinking counts toward
# max_tokens, so it gets room for that, and low effort: a quick spoken reply, little or no thinking
# on simple requests. Older models reject `effort` and answer in well under 300 tokens.
REQUEST_SETTINGS = {
    "claude-haiku-5-5": {"max_tokens": 1024, "output_config": {"effort": "low"}},
}
DEFAULT_REQUEST_SETTINGS = {"max_tokens": 300}
KEEPALIVE_SECONDS = 120.0  # keep the idle connection this long (the SDK default is 5s)
PREPARE_IF_IDLE = 4.0      # re-open the connection on key press if it's been idle at least this long

_clients: Dict[str, Any] = {}
_clients_lock = threading.Lock()


def _client(api_key: str):
    """One SDK client per key, shared, so its pooled connection is reused across turns."""
    import anthropic
    import httpx2
    with _clients_lock:
        client = _clients.get(api_key)
        if client is None:
            http = anthropic.DefaultHttpxClient(limits=httpx2.Limits(
                max_connections=10, max_keepalive_connections=4, keepalive_expiry=KEEPALIVE_SECONDS))
            client = anthropic.Anthropic(api_key=api_key, http_client=http, timeout=30.0, max_retries=1)
            _clients[api_key] = client
        return client


def build_system_blocks(system_prompt: str) -> List[Dict[str, Any]]:
    """
    Cache the stable prefix; send the volatile tail (date, focus mode, profile) after the breakpoint.
    Empty parts are left out: the API rejects an empty block (the memory profiler sends no prompt).
    """
    stable, volatile = split_system_prompt(system_prompt)
    blocks = []
    if stable.strip():
        blocks.append({"type": "text", "text": stable, "cache_control": {"type": "ephemeral"}})
    if volatile.strip():
        blocks.append({"type": "text", "text": volatile})
    return blocks


@ProviderRegistry.register_llm("anthropic_llm")
class AnthropicLLMProvider(BaseLLMProvider):
    def __init__(self, api_key: Optional[str] = None, model_name: str = "claude-haiku-4-5-20251001"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model_name = model_name
        self._last_used = 0.0
        self.last_timing: Dict[str, float] = {}

    def get_available_models(self) -> List[str]:
        return list(FALLBACK_MODELS)

    def _key(self) -> str:
        return self.api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    def prepare(self):
        """Open the HTTPS connection ahead of the request (free: a Models API lookup)."""
        key = self._key()
        if not key or time.monotonic() - self._last_used < PREPARE_IF_IDLE:
            return
        started = time.perf_counter()
        try:
            _client(key).models.retrieve(MODEL_MAPPING.get(self.model_name, self.model_name))
            self._last_used = time.monotonic()
            if os.environ.get("JARVIS_DEBUG_LLM"):
                print(f"[AnthropicLLM] Connection ready in {time.perf_counter() - started:.2f}s.", flush=True)
        except Exception as err:
            print(f"[AnthropicLLM] Couldn't pre-open the connection: {err}", flush=True)

    def process_voice_query(
        self,
        user_query: str,
        history: List[Dict[str, str]],
        system_prompt: str
    ) -> Dict[str, Any]:
        import anthropic

        key = self._key()
        if not key:
            print("[AnthropicLLM Error] ANTHROPIC_API_KEY not found in environment, settings, or .env file.", flush=True)
            return {"tool": "none", "args": {}, "spoken_summary": "Anthropic API key is missing. Please enter your API key in settings."}

        messages = []
        for past in history[-4:]:
            role = "user" if past.get("role") == "user" else "assistant"
            messages.append({"role": role, "content": past.get("content", "")})
        messages.append({"role": "user", "content": user_query})

        system_blocks = build_system_blocks(system_prompt)
        target_model = MODEL_MAPPING.get(self.model_name, self.model_name)
        candidates = [target_model] + [m for m in FALLBACK_MODELS if m != target_model]

        client = _client(key)
        for model in candidates:
            started = time.perf_counter()
            try:
                response = client.messages.create(
                    model=model,
                    messages=messages,
                    **REQUEST_SETTINGS.get(model, DEFAULT_REQUEST_SETTINGS),
                    **({"system": system_blocks} if system_blocks else {}),
                )
            except anthropic.NotFoundError as err:
                print(f"[AnthropicLLM Error] Model '{model}' not found: {err.message}", flush=True)
                if model != candidates[-1]:
                    continue
                return {"tool": "none", "args": {}, "spoken_summary": "Anthropic API Error: Account credits required at console.anthropic.com"}
            except anthropic.RateLimitError:
                return {"tool": "none", "args": {}, "spoken_summary": "Anthropic is rate limiting requests. Try again in a moment."}
            except anthropic.APIStatusError as err:
                print(f"[AnthropicLLM Error] Model '{model}' HTTP {err.status_code}: {err.message}", flush=True)
                return {"tool": "none", "args": {}, "spoken_summary": f"Anthropic API Error ({err.status_code})."}
            except anthropic.APIConnectionError as err:
                print(f"[AnthropicLLM Error] Connection failed: {err}", flush=True)
                return {"tool": "none", "args": {}, "spoken_summary": "Error reaching Anthropic Claude server."}

            self._last_used = time.monotonic()
            usage = response.usage
            self.last_timing = {
                "seconds": round(time.perf_counter() - started, 3),
                "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
                "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
                "output_tokens": usage.output_tokens,
            }
            if self.last_timing["cache_write"]:
                print(f"[AnthropicLLM Caching] Wrote prompt cache ({self.last_timing['cache_write']} tokens).", flush=True)
            if os.environ.get("JARVIS_DEBUG_LLM"):
                print(f"[AnthropicLLM Debug] {self.last_timing}", flush=True)

            if response.stop_reason == "refusal":  # Claude Haiku 5.5's safety classifiers can decline
                print(f"[AnthropicLLM] {model} declined the request ({getattr(response.stop_details, 'category', None)}).", flush=True)
                return {"tool": "none", "args": {}, "spoken_summary": "Sorry, I can't help with that one."}
            # Read text blocks by type: a response can begin with (empty) thinking blocks.
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            if not text and response.stop_reason == "max_tokens":
                print(f"[AnthropicLLM] {model} used its whole token limit before answering.", flush=True)
                return {"tool": "none", "args": {}, "spoken_summary": "That took me too long to work out. Try asking more simply."}
            from daemon.utils.json_utils import extract_json_payload
            return extract_json_payload(text)

        return {"tool": "none", "args": {}, "spoken_summary": "Unable to connect to Anthropic API."}

    def get_provider_info(self) -> Dict[str, Any]:
        model = getattr(self, "model_name", "claude-haiku-4-5-20251001")
        return {
            "id": "anthropic_llm",
            "name": f"Anthropic Claude ({model})",
            "type": "cloud",
            "model_name": model,
            "models": self.get_available_models(),
        }
