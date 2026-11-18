"""
Faster-Whisper Local STT Provider (Story 2.1)
Wraps local CTranslate2 Faster-Whisper into the BaseSTTProvider interface.

Decodes several candidate transcriptions and picks the one that most likely makes sense as
a Jarvis request (see daemon/stt/reranker.py). The alternatives it considered are kept on
`last_alternatives` so the daemon can log and show them.
"""

from typing import Any, Callable, Dict, Iterable, List, Optional, Union

import numpy as np

from daemon.providers.base import AbstractBaseSTTEngine
from daemon.providers.factory import ProviderRegistry
from daemon.stt.reranker import CommandVocabulary, rerank
from daemon.stt.stt_engine import STTEngine

DEFAULT_MODEL = "large-v3-turbo"


@ProviderRegistry.register_stt("faster_whisper")
class FasterWhisperSTTProvider(AbstractBaseSTTEngine):
    def __init__(self, model_size: str = DEFAULT_MODEL, device: str = "auto", compute_type: str = "default", eager_load: bool = True):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.vocabulary = CommandVocabulary()
        self.last_alternatives: List[Dict[str, Any]] = []
        self._engine: Optional[STTEngine] = None
        if eager_load:
            print(f"[FasterWhisperSTTProvider] Pre-loading Faster-Whisper '{model_size}' on startup...", flush=True)
            self._ensure_engine()

    def set_vocabulary_source(self, source: Callable[[], Iterable[str]]):
        """Phrases Jarvis knows (shortcut phrases, command examples, macro names), read live by the reranker."""
        self.vocabulary.set_sources(source)

    def _ensure_engine(self):
        if self._engine is None:
            self._engine = STTEngine(model_size=self.model_size, device=self.device, compute_type=self.compute_type)

    def _transcribe_audio(self, float32_pcm: np.ndarray, raw_input: Union[bytes, np.ndarray], sample_rate: int) -> str:
        self._ensure_engine()
        self.last_alternatives = []
        hotwords = self.vocabulary.hotwords
        try:
            candidates = self._engine.transcribe_nbest(float32_pcm, hotwords=hotwords)
            text, alternatives = rerank(candidates, self.vocabulary)
            self.last_alternatives = alternatives
            if alternatives:
                top = ", ".join(f"{a['text']!r} {a['probability']:.0%}" for a in alternatives[:3])
                print(f"[FasterWhisperSTTProvider] Candidates: {top}", flush=True)
            return text
        except Exception as err:
            print(f"[FasterWhisperSTTProvider] n-best decoding failed ({err}); using plain transcription.", flush=True)
            return self._engine.transcribe_buffer(float32_pcm, sample_rate=sample_rate, hotwords=hotwords)

    def get_provider_info(self) -> Dict[str, Any]:
        model_size = getattr(self, "model_size", DEFAULT_MODEL)
        engine = getattr(self, "_engine", None)
        where = "GPU" if engine is not None and engine.device == "cuda" else "CPU" if engine is not None else "Local"
        return {
            "id": "faster_whisper",
            "name": f"Faster-Whisper {where} ({model_size})",
            "type": "local",
            "model_size": model_size,
        }
