"""
Google Gemini Multimodal Voice STT Provider (Story 2.2)
Sends raw audio PCM buffer to Google Gemini Multimodal API for cloud speech transcription.
"""

import os
import io
import wave
import json
import urllib.request
import base64
from typing import Dict, Any, Optional
from daemon.providers.base import BaseSTTProvider


class GeminiVoiceSTTProvider(BaseSTTProvider):
    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-1.5-flash"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model_name = model_name

    def _pcm_to_wav(self, pcm_data: bytes, sample_rate: int = 16000) -> bytes:
        wav_io = io.BytesIO()
        with wave.open(wav_io, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_data)
        return wav_io.getvalue()

    def transcribe_buffer(self, pcm_data: bytes) -> str:
        active_key = self.api_key or os.environ.get("GEMINI_API_KEY", "")
        if not active_key:
            print("[GeminiSTT Error] GEMINI_API_KEY not found in environment, settings, or .env file.", flush=True)
            return ""

        wav_bytes = self._pcm_to_wav(pcm_data)
        base64_audio = base64.b64encode(wav_bytes).decode("utf-8")

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": "Transcribe the following audio accurately. Return ONLY the spoken text transcript with no extra commentary."},
                        {
                            "inline_data": {
                                "mime_type": "audio/wav",
                                "data": base64_audio
                            }
                        }
                    ]
                }
            ]
        }

        candidate_models = [self.model_name]
        for fallback in ["gemini-2.0-flash", "gemini-3.6-flash", "gemini-2.5-flash", "gemini-flash-latest"]:
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
                    text = "".join(p.get("text", "") for p in parts).strip()
                    return text
            except urllib.error.HTTPError as http_err:
                err_body = http_err.read().decode('utf-8', errors='ignore')
                print(f"[GeminiSTT Warning] Model '{target_model}' HTTP {http_err.code}: {err_body}", flush=True)
                if http_err.code in [404, 400] and target_model != candidate_models[-1]:
                    print(f"[GeminiSTT] Retrying with fallback model...", flush=True)
                    continue
            except Exception as e:
                print(f"[GeminiSTT Error] Transcription failed on model '{target_model}': {e}", flush=True)

        return ""

    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "id": "gemini_stt",
            "name": f"Google Gemini Multimodal Audio ({self.model_name})",
            "type": "cloud",
            "model_name": self.model_name
        }
