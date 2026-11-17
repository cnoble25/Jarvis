"""
Faster-Whisper Local STT Provider (Story 2.1)
Wraps local CTranslate2 Faster-Whisper model into the BaseSTTProvider interface.
"""

import numpy as np
from typing import Dict, Any, Optional, Union
from daemon.providers.base import AbstractBaseSTTEngine
from daemon.providers.factory import ProviderRegistry
from daemon.stt.stt_engine import STTEngine


@ProviderRegistry.register_stt("faster_whisper")
class FasterWhisperSTTProvider(AbstractBaseSTTEngine):
    def __init__(self, model_size: str = "base.en", device: str = "cpu", compute_type: str = "int8", eager_load: bool = True):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._engine: Optional[STTEngine] = None
        if eager_load:
            print(f"[FasterWhisperSTTProvider] Pre-loading Faster-Whisper '{model_size}' model into RAM on startup...", flush=True)
            self._ensure_engine()

    def _ensure_engine(self):
        if self._engine is None:
            self._engine = STTEngine(
                model_size=self.model_size,
                device=self.device,
                compute_type=self.compute_type
            )

    def _transcribe_audio(self, float32_pcm: np.ndarray, raw_input: Union[bytes, np.ndarray], sample_rate: int) -> str:
        self._ensure_engine()
        return self._engine.transcribe_buffer(float32_pcm, sample_rate=sample_rate)

    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "id": "faster_whisper",
            "name": f"Faster-Whisper Local ({self.model_size})",
            "type": "local",
            "model_size": self.model_size
        }

