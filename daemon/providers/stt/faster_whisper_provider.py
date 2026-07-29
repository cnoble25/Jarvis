"""
Faster-Whisper Local STT Provider (Story 2.1)
Wraps local CTranslate2 Faster-Whisper model into the BaseSTTProvider interface.
"""

import numpy as np
from typing import Dict, Any, Optional
from daemon.providers.base import BaseSTTProvider
from daemon.stt.stt_engine import STTEngine


class FasterWhisperSTTProvider(BaseSTTProvider):
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

    def transcribe_buffer(self, pcm_data: bytes) -> str:
        self._ensure_engine()
        if isinstance(pcm_data, bytes):
            audio_array = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
        else:
            audio_array = pcm_data
        return self._engine.transcribe_buffer(audio_array)

    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "id": "faster_whisper",
            "name": f"Faster-Whisper Local ({self.model_size})",
            "type": "local",
            "model_size": self.model_size
        }
