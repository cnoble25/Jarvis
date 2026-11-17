"""
Anthropic Claude LLM Orchestrator Provider
Connects Anthropic Claude 3 Haiku, 3.5 Haiku, and 4 Haiku API to Jarvis tool execution and conversational loop.
"""

import os
import json
import urllib.request
from typing import Dict, Any, List, Optional
from daemon.providers.base import BaseLLMProvider
from daemon.providers.factory import ProviderRegistry


MODEL_MAPPING = {
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


@ProviderRegistry.register_llm("anthropic_llm")
class AnthropicLLMProvider(BaseLLMProvider):
    def __init__(self, api_key: Optional[str] = None, model_name: str = "claude-haiku-4-5-20251001"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model_name = model_name

    def get_available_models(self) -> List[str]:
        return [
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-5-20250929",
            "claude-sonnet-4-6"
        ]

    def process_voice_query(
        self,
        user_query: str,
        history: List[Dict[str, str]],
        system_prompt: str
    ) -> Dict[str, Any]:
        active_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not active_key:
            print("[AnthropicLLM Error] ANTHROPIC_API_KEY not found in environment, settings, or .env file.", flush=True)
            return {"tool": "none", "args": {}, "spoken_summary": "Anthropic API key is missing. Please enter your API key in settings."}

        target_model = MODEL_MAPPING.get(self.model_name, self.model_name)

        messages = []
        for past in history[-4:]:
            role = "user" if past.get("role") == "user" else "assistant"
            messages.append({"role": role, "content": past.get("content", "")})

        messages.append({"role": "user", "content": user_query})

        candidate_models = [target_model]
        for fallback in ["claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250929", "claude-sonnet-4-6"]:
            if fallback not in candidate_models:
                candidate_models.append(fallback)

        system_blocks = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"}
            }
        ]

        for m in candidate_models:
            payload = {
                "model": m,
                "max_tokens": 300,
                "system": system_blocks,
                "messages": messages
            }

            try:
                req = urllib.request.Request(
                    "https://api.anthropic.com/v1/messages",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": active_key,
                        "anthropic-version": "2023-06-01",
                        "anthropic-beta": "prompt-caching-2024-07-31"
                    }
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode())
                    content_blocks = data.get("content", [])
                    text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text").strip()

                    # Log prompt caching stats (only on cache creation or debug mode)
                    usage = data.get("usage", {})
                    cache_read = usage.get("cache_read_input_tokens", 0)
                    cache_created = usage.get("cache_creation_input_tokens", 0)
                    if not cache_created and isinstance(usage.get("cache_creation"), dict):
                        cache_created = usage["cache_creation"].get("ephemeral_5m_input_tokens", 0)
                    
                    if cache_created > 0:
                        print(f"[AnthropicLLM Caching] Initialized prompt cache ({cache_created} system tokens cached)", flush=True)
                    elif os.environ.get("JARVIS_DEBUG_LLM"):
                        print(f"[AnthropicLLM Debug] Cache Read: {cache_read} | Input: {usage.get('input_tokens', 0)} | Output: {usage.get('output_tokens', 0)}", flush=True)

                    from daemon.utils.json_utils import extract_json_payload
                    return extract_json_payload(text)
            except urllib.error.HTTPError as http_err:
                err_body = http_err.read().decode("utf-8", errors="ignore")
                print(f"[AnthropicLLM Error] Model '{m}' HTTP {http_err.code}: {err_body}", flush=True)
                if http_err.code == 404 and m != candidate_models[-1]:
                    continue
                if http_err.code == 404:
                    return {"tool": "none", "args": {}, "spoken_summary": "Anthropic API Error: Account credits required at console.anthropic.com"}
                return {"tool": "none", "args": {}, "spoken_summary": f"Anthropic API Error ({http_err.code})."}
            except Exception as e:
                print(f"[AnthropicLLM Error] Query processing error: {e}", flush=True)
                return {"tool": "none", "args": {}, "spoken_summary": "Error reaching Anthropic Claude server."}

        return {"tool": "none", "args": {}, "spoken_summary": "Unable to connect to Anthropic API."}

    def get_provider_info(self) -> Dict[str, Any]:
        model = getattr(self, "model_name", "claude-haiku-4-5-20251001")
        models = self.get_available_models() if hasattr(self, "get_available_models") else []
        return {
            "id": "anthropic_llm",
            "name": f"Anthropic Claude ({model})",
            "type": "cloud",
            "model_name": model,
            "models": models
        }
