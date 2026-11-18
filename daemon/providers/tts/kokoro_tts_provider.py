"""
Kokoro-ONNX Local TTS Provider (Story 2.4)
Wraps local Kokoro-ONNX engine into AbstractBaseTTSEngine interface.
"""

import threading
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from daemon.providers.base import AbstractBaseTTSEngine
from daemon.providers.factory import ProviderRegistry
from daemon.tts.tts_engine import TTSEngine


@ProviderRegistry.register_tts("kokoro")
class KokoroTTSProvider(AbstractBaseTTSEngine):
    def __init__(self, voice: str = "af_kore"):
        super().__init__()
        self.voice = voice
        self._engine: Optional[TTSEngine] = None
        self._engine_lock = threading.Lock()

    def _ensure_engine(self):
        with self._engine_lock:
            if self._engine is None:
                self._engine = TTSEngine()

    def warm_up(self):
        """Load the model and run one synthesis now, so the first reply isn't the slow one."""
        self._ensure_engine()
        self._engine.warm_up(self.voice)

    def _synthesize_audio(self, text: str, voice: str, speed: float) -> Tuple[np.ndarray, int]:
        self._ensure_engine()
        target_voice = voice or self.voice
        samples, sample_rate = self._engine.kokoro.create(text, voice=target_voice, speed=speed, lang="en-us")
        return samples, sample_rate

    def get_available_voices(self) -> List[str]:
        return ["af_kore", "af_sky", "af_bella", "am_adam", "am_michael", "bf_emma", "bm_george"]

    def get_default_voice(self) -> str:
        return self.voice

    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "id": "kokoro_tts",
            "name": f"Kokoro-ONNX {'GPU' if self._engine is not None and self._engine.device == 'GPU' else 'Local'} ({self.voice})",
            "type": "local",
            "voice": self.voice
        }

