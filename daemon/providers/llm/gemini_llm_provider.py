"""
Google Gemini LLM Orchestrator Provider (Story 2.3)
Connects Google Gemini 1.5 Flash / Pro API to Jarvis tool execution and conversational loop.
"""

import os
import json
import urllib.request
from typing import Dict, Any, List, Optional
from daemon.providers.base import BaseLLMProvider


class GeminiLLMProvider(BaseLLMProvider):
    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-1.5-flash"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model_name = model_name

    def get_available_models(self) -> List[str]:
        return [
            "gemini-3.6-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-flash"
        ]

    def process_voice_query(
        self,
        user_query: str,
        history: List[Dict[str, str]],
        system_prompt: str
    ) -> Dict[str, Any]:
        active_key = self.api_key or os.environ.get("GEMINI_API_KEY", "")
        if not active_key:
            print("[GeminiLLM Error] GEMINI_API_KEY not found in environment, settings, or .env file.", flush=True)
            return {"tool": "none", "args": {}, "spoken_summary": "Gemini API key is missing. Please enter your key in settings."}

        # Construct contents array with System Instruction + History + User Query
        contents = []
        for past in history[-10:]:
            role = "user" if past.get("role") == "user" else "model"
            contents.append({"role": role, "parts": [{"text": past.get("content", "")}]})

        contents.append({"role": "user", "parts": [{"text": user_query}]})

        payload = {
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": contents,
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.2
            }
        }

        # Candidate models to try if selected model returns 404 / deprecated
        candidate_models = [self.model_name]
        for fallback in ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-2.0-flash", "gemini-flash-latest"]:
            if fallback not in candidate_models:
                candidate_models.append(fallback)

        for target_model in candidate_models:
            model_path = target_model if target_model.startswith("models/") else f"models/{target_model}"
            url = f"https://generativelanguage.googleapis.com/v1beta/{model_path}:generateContent?key={active_key}"
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode())
                    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    content_text = "".join(p.get("text", "") for p in parts).strip()
                    from daemon.utils.json_utils import extract_json_payload
                    return extract_json_payload(content_text)
            except urllib.error.HTTPError as http_err:
                err_body = http_err.read().decode('utf-8', errors='ignore')
                print(f"[GeminiLLM Warning] Model '{target_model}' HTTP {http_err.code}: {err_body}", flush=True)
                if http_err.code in [404, 400] and target_model != candidate_models[-1]:
                    print(f"[GeminiLLM] Retrying with fallback model...", flush=True)
                    continue
                return {"tool": "none", "args": {}, "spoken_summary": f"Gemini API Error: {http_err.reason}"}
            except Exception as e:
                print(f"[GeminiLLM Error] API request failed: {e}", flush=True)
                return {"tool": "none", "args": {}, "spoken_summary": "Error reaching Gemini LLM API."}

        return {"tool": "none", "args": {}, "spoken_summary": "Unable to connect to Google Gemini API."}

    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "id": "gemini_llm",
            "name": f"Google Gemini ({self.model_name})",
            "type": "cloud",
            "model_name": self.model_name
        }
