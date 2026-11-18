"""
ElevenLabs text-to-speech.

- The model is a setting (`elevenlabs_model`, default eleven_turbo_v2: ElevenLabs' low-latency
  English model); the voice is `tts_voice`.
- One client is reused, so its HTTPS connection stays open between replies.
- Audio comes back as raw 16-bit PCM at 24 kHz: nothing to decode before playback.
"""

import os
import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from daemon.providers.base import AbstractBaseTTSEngine
from daemon.providers.factory import ProviderRegistry

DEFAULT_MODEL = "eleven_turbo_v2"
SAMPLE_RATE = 24000
# Voice IDs offered in Settings; any other ID can be set in settings.json.
KNOWN_VOICES = {
    "onwK4e9ZLuTAKqWW03F9": "Daniel",
    "JBFqnCBsd6RMkjVDRZzb": "George",
    "21m00Tcm4TlvDq8ikWAM": "Rachel",
}


@ProviderRegistry.register_tts("elevenlabs")
@ProviderRegistry.register_tts("elevenlabs_tts")
@ProviderRegistry.register_tts("ElevenLabs")
class ElevenLabsTTSProvider(AbstractBaseTTSEngine):
    def __init__(self, voice: str = "onwK4e9ZLuTAKqWW03F9", api_key: Optional[str] = None, model: Optional[str] = None):
        super().__init__()
        self.voice = voice
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self.model = model or DEFAULT_MODEL
        self._client = None
        self._client_lock = threading.Lock()

    def _get_client(self):
        api_key = self.api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY is required for ElevenLabs TTS")
        with self._client_lock:
            if self._client is None:
                from elevenlabs.client import ElevenLabs
                self._client = ElevenLabs(api_key=api_key)
            return self._client

    def _synthesize_audio(self, text: str, voice: str, speed: float) -> Tuple[np.ndarray, int]:
        audio = self._get_client().text_to_speech.convert(
            text=text,
            voice_id=voice or self.voice,
            model_id=self.model,
            output_format=f"pcm_{SAMPLE_RATE}",
        )
        raw = b"".join(audio) if not isinstance(audio, (bytes, bytearray)) else bytes(audio)
        samples = np.frombuffer(raw[: len(raw) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
        return samples, SAMPLE_RATE

    def warm_up(self):
        """Open the client (and its connection pool) before the first reply; no audio is billed."""
        try:
            self._get_client()
        except Exception as err:
            print(f"[ElevenLabsTTS] Not ready: {err}", flush=True)

    def get_available_voices(self) -> List[str]:
        voices = list(KNOWN_VOICES)
        return voices if self.voice in voices else [self.voice] + voices

    def get_default_voice(self) -> str:
        return self.voice

    def get_provider_info(self) -> Dict[str, Any]:
        name = KNOWN_VOICES.get(self.voice, self.voice)
        return {
            "id": "elevenlabs_tts",
            "name": f"ElevenLabs {name} ({self.model})",
            "type": "Online",
            "voice": self.voice,
            "model": self.model,
        }
