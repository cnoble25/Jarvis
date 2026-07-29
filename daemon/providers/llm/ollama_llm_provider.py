"""
Ollama Local LLM Orchestrator Provider (Story 2.3)
Wraps local Ollama API server into BaseLLMProvider interface.
"""

import json
import urllib.request
from typing import Dict, Any, List, Optional
from daemon.providers.base import BaseLLMProvider


class OllamaLLMProvider(BaseLLMProvider):
    def __init__(self, ollama_url: str = "http://localhost:11434", model_name: str = "qwen3.5:9b"):
        self.ollama_url = ollama_url.rstrip("/")
        self.model_name = model_name

    def get_available_models(self) -> List[str]:
        try:
            req = urllib.request.Request(f"{self.ollama_url}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    return [m.get("name") for m in data.get("models", [])]
        except Exception:
            pass
        return []

    def process_voice_query(
        self,
        user_query: str,
        history: List[Dict[str, str]],
        system_prompt: str
    ) -> Dict[str, Any]:
        available_models = self.get_available_models()
        target_model = self.model_name
        if available_models and target_model not in available_models:
            base_name = target_model.split(":")[0]
            matched = [m for m in available_models if target_model in m or base_name in m]
            if matched:
                target_model = matched[0]
            else:
                target_model = available_models[0]

        messages = [{"role": "system", "content": system_prompt}]
        for past in history[-2:]:
            messages.append(past)
        messages.append({"role": "user", "content": user_query})

        payload = {
            "model": target_model,
            "messages": messages,
            "format": "json",
            "stream": False,
            "think": False,
            "keep_alive": "10m",
            "options": {
                "num_ctx": 4096,
                "num_predict": 300,
                "temperature": 0.2
            }
        }

        try:
            req = urllib.request.Request(
                f"{self.ollama_url}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode())
                content = data.get("message", {}).get("content", "").strip()

                from daemon.utils.json_utils import extract_json_payload
                return extract_json_payload(content)
        except Exception as e:
            print(f"[OllamaLLM Error] Query processing error: {e}", flush=True)
            return {"tool": "none", "args": {}, "spoken_summary": "Error reaching local Ollama server."}

    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "id": "ollama_llm",
            "name": f"Ollama Local ({self.model_name})",
            "type": "local",
            "model_name": self.model_name
        }
