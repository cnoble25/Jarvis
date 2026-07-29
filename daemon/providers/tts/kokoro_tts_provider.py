"""
Kokoro-ONNX Local TTS Provider (Story 2.4)
Wraps local Kokoro-ONNX engine into BaseTTSProvider interface.
"""

from typing import Dict, Any, List, Optional
from daemon.providers.base import BaseTTSProvider
from daemon.tts.tts_engine import TTSEngine


class KokoroTTSProvider(BaseTTSProvider):
    def __init__(self, voice: str = "af_kore"):
        self.voice = voice
        self._engine: Optional[TTSEngine] = None

    def _ensure_engine(self):
        if self._engine is None:
            self._engine = TTSEngine(voice=self.voice)

    def speak(self, text: str, voice: Optional[str] = None, block: bool = True) -> bool:
        self._ensure_engine()
        target_voice = voice or self.voice
        return self._engine.speak(text, voice=target_voice, block=block)

    def get_available_voices(self) -> List[str]:
        return ["af_kore", "af_sky", "af_bella", "am_adam", "am_michael", "bf_emma", "bm_george"]

    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "id": "kokoro_tts",
            "name": f"Kokoro-ONNX Local ({self.voice})",
            "type": "local",
            "voice": self.voice
        }
