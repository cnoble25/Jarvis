"""
Speech-to-Text (STT) Module
Uses Faster-Whisper for high-speed local audio transcription.
"""

import numpy as np
from faster_whisper import WhisperModel


class STTEngine:
    def __init__(
        self,
        model_size: str = "base.en",
        device: str = "auto",
        compute_type: str = "default",
        cpu_threads: int = 4
    ):
        """
        Initialize Faster-Whisper STT Engine.
        
        :param model_size: Whisper model size ('tiny.en', 'base.en', 'small.en', 'medium.en').
        :param device: Device to run model on ('cuda', 'cpu', 'auto').
        :param compute_type: Model quantization ('float16', 'int8', 'float32', 'default').
        :param cpu_threads: Number of CPU threads for inference.
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        
        print(f"[STTEngine] Loading Faster-Whisper model '{model_size}' on device '{device}'...", flush=True)
        self.model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
            cpu_threads=cpu_threads
        )
        print("[STTEngine] Faster-Whisper model loaded successfully.", flush=True)

    def transcribe_buffer(self, pcm_data: np.ndarray, sample_rate: int = 16000) -> str:
        """
        Transcribes a 1D float32 PCM numpy array directly in memory.
        
        :param pcm_data: 1D numpy array of float32 PCM audio samples [-1.0, 1.0].
        :param sample_rate: Audio sampling rate in Hz (default 16000).
        :return: Clean transcribed text string.
        """
        if pcm_data is None or len(pcm_data) == 0:
            return ""

        # Ensure float32 1D array
        if pcm_data.dtype != np.float32:
            pcm_data = pcm_data.astype(np.float32)

        # Transcribe in-memory audio array
        segments, info = self.model.transcribe(
            pcm_data,
            beam_size=5,
            language="en",
            vad_filter=False  # We already apply VADFilter before passing buffer
        )

        transcription = " ".join([segment.text.strip() for segment in segments]).strip()
        
        # Clean common whisper hallucination artifacts on silence/quiet input
        hallucinations = ["Thanks for watching!", "Thank you.", "[BLANK_AUDIO]", "Subtitles by", "Amara.org"]
        for artifact in hallucinations:
            if artifact.lower() in transcription.lower():
                transcription = transcription.replace(artifact, "").strip()

        return transcription
