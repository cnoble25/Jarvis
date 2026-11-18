"""
Speech-to-Text (STT) Module
Faster-Whisper transcription, on the GPU when one is available, with n-best candidates.
"""

from typing import List, Optional, Tuple

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.tokenizer import Tokenizer

from daemon.stt.cuda_libs import cuda_available

SAMPLE_RATE = 16000
# n-best decoding covers one Whisper window; longer audio falls back to plain transcription.
NBEST_MAX_SECONDS = 28


class STTEngine:
    def __init__(
        self,
        model_size: str = "large-v3-turbo",
        device: str = "auto",
        compute_type: str = "default",
        cpu_threads: int = 4
    ):
        """
        :param model_size: Whisper model ('base.en', 'small.en', 'distil-large-v3.5', 'large-v3-turbo', ...).
        :param device: 'cuda', 'cpu' or 'auto' (GPU when CTranslate2 can use it, otherwise CPU).
        :param compute_type: 'default' picks float16 on GPU and int8 on CPU.
        """
        self.model_size = model_size
        if device == "auto":
            device = "cuda" if cuda_available() else "cpu"
        elif device == "cuda":
            cuda_available()
        if compute_type == "default":
            compute_type = "float16" if device == "cuda" else "int8"

        print(f"[STTEngine] Loading Faster-Whisper '{model_size}' on {device} ({compute_type})...", flush=True)
        try:
            self.model = WhisperModel(model_size, device=device, compute_type=compute_type, cpu_threads=cpu_threads)
        except Exception as err:
            if device != "cuda":
                raise
            print(f"[STTEngine] GPU load failed ({err}); falling back to CPU int8.", flush=True)
            device, compute_type = "cpu", "int8"
            self.model = WhisperModel(model_size, device=device, compute_type=compute_type, cpu_threads=cpu_threads)
        self.device = device
        self.compute_type = compute_type
        self._tokenizer = Tokenizer(
            self.model.hf_tokenizer, self.model.model.is_multilingual, task="transcribe", language="en"
        )
        print(f"[STTEngine] Faster-Whisper '{model_size}' ready on {device}.", flush=True)

    def transcribe_buffer(self, pcm_data: np.ndarray, sample_rate: int = SAMPLE_RATE, hotwords: Optional[str] = None) -> str:
        """Plain best-path transcription of a 1D float32 PCM array in [-1, 1]."""
        if pcm_data is None or len(pcm_data) == 0:
            return ""
        segments, _ = self.model.transcribe(
            pcm_data.astype(np.float32, copy=False),
            beam_size=5,
            language="en",
            vad_filter=False,  # The recorder already trims silence.
            hotwords=hotwords,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def transcribe_nbest(
        self, pcm_data: np.ndarray, hotwords: Optional[str] = None, n: int = 5
    ) -> List[Tuple[str, float]]:
        """
        Up to n candidate transcriptions with their length-normalized log-probabilities,
        most likely first. Audio longer than one Whisper window returns a single plain result.
        """
        if pcm_data is None or len(pcm_data) == 0:
            return []
        audio = pcm_data.astype(np.float32, copy=False)
        if len(audio) > NBEST_MAX_SECONDS * SAMPLE_RATE:
            return [(self.transcribe_buffer(audio, hotwords=hotwords), 0.0)]

        extractor = self.model.feature_extractor
        features = extractor(audio)[:, : extractor.nb_max_frames]
        if features.shape[-1] < extractor.nb_max_frames:
            features = np.pad(features, ((0, 0), (0, extractor.nb_max_frames - features.shape[-1])))
        encoded = self.model.encode(features)

        # Decode twice from the same encoding: hotwords help with names ("Steam", "Discord") but can
        # crowd out a correct plain word ("pause"), so pool both candidate lists for the reranker.
        candidates: List[Tuple[str, float]] = []
        for words in ([hotwords, None] if hotwords else [None]):
            prompt = self.model.get_prompt(self._tokenizer, [], without_timestamps=True, hotwords=words)
            result = self.model.model.generate(
                encoded,
                [prompt],
                beam_size=max(5, n),
                num_hypotheses=n,
                return_scores=True,
                length_penalty=1.0,
                max_length=96,
                suppress_blank=True,
                suppress_tokens=[-1],
            )[0]
            candidates.extend(
                (self._tokenizer.decode(ids).strip(), float(score))
                for ids, score in zip(result.sequences_ids, result.scores)
            )
        return sorted(candidates, key=lambda c: c[1], reverse=True)
