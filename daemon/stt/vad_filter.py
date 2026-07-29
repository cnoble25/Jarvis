"""
Voice Activity Detection (VAD) Filter Module
Trims silence from recorded PCM audio streams.
"""

import numpy as np


class VADFilter:
    def __init__(self, energy_threshold: float = 0.01, padding_ms: int = 200, sample_rate: int = 16000):
        """
        Initialize VAD filter with energy threshold and padding.
        
        :param energy_threshold: Minimum RMS amplitude threshold to consider as speech.
        :param padding_ms: Milliseconds of padding to preserve before and after detected speech.
        :param sample_rate: Audio sample rate in Hz.
        """
        self.energy_threshold = energy_threshold
        self.padding_samples = int((padding_ms / 1000.0) * sample_rate)
        self.sample_rate = sample_rate

    def trim_silence(self, pcm_data: np.ndarray) -> np.ndarray:
        """
        Trims leading and trailing silence from float32 PCM audio data.
        
        :param pcm_data: 1D numpy array of float32 audio samples [-1.0, 1.0].
        :return: Trimmed 1D numpy array of float32 audio samples.
        """
        if pcm_data is None or len(pcm_data) == 0:
            return np.array([], dtype=np.float32)

        # Ensure float32 format
        if pcm_data.dtype != np.float32:
            pcm_data = pcm_data.astype(np.float32)

        # Calculate frame energies (frame size = 32ms = 512 samples at 16kHz)
        frame_size = 512
        num_frames = len(pcm_data) // frame_size

        if num_frames == 0:
            return pcm_data

        frame_energies = [
            np.sqrt(np.mean(pcm_data[i * frame_size : (i + 1) * frame_size] ** 2))
            for i in range(num_frames)
        ]

        # Find first and last speech frames
        speech_indices = [i for i, energy in enumerate(frame_energies) if energy >= self.energy_threshold]

        if not speech_indices:
            # No speech detected above threshold
            return np.array([], dtype=np.float32)

        start_frame = speech_indices[0]
        end_frame = speech_indices[-1]

        # Convert frame indices to sample indices with padding
        start_sample = max(0, (start_frame * frame_size) - self.padding_samples)
        end_sample = min(len(pcm_data), ((end_frame + 1) * frame_size) + self.padding_samples)

        return pcm_data[start_sample:end_sample]

    def is_valid_speech(self, pcm_data: np.ndarray, min_duration_sec: float = 0.3) -> bool:
        """
        Validates if the trimmed audio buffer contains sufficient speech duration.
        """
        if pcm_data is None or len(pcm_data) == 0:
            return False

        duration = len(pcm_data) / self.sample_rate
        return duration >= min_duration_sec
