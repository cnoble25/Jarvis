"""
Audio Recorder Module
Captures microphone input using sounddevice and processes audio via VAD.
"""

import threading
import queue
import numpy as np
import sounddevice as sd
from .vad_filter import VADFilter


class AudioRecorder:
    def __init__(self, sample_rate: int = 16000, device: int | str | None = None):
        """
        Initialize AudioRecorder.
        
        :param sample_rate: Audio sampling rate in Hz (default: 16000).
        :param device: Input audio device index or name (None for system default).
        """
        self.sample_rate = sample_rate
        self.device = device
        self.channels = 1  # Mono
        self.dtype = "float32"
        
        self.is_recording = False
        self._audio_queue = queue.Queue()
        self._frames = []
        self._stream = None
        self._vad_filter = VADFilter(sample_rate=self.sample_rate)

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: dict, status: sd.CallbackFlags):
        """
        Internal callback function invoked by sounddevice for each recorded audio chunk.
        """
        if status:
            print(f"[AudioRecorder Warning] Stream status: {status}", flush=True)
        if self.is_recording:
            # indata is 2D array of shape (frames, channels), copy frame data
            self._audio_queue.put(indata.copy())

    def start_recording(self):
        """
        Starts recording audio from microphone.
        """
        if self.is_recording:
            return

        self._frames.clear()
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

        self.is_recording = True

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=self.dtype,
            device=self.device,
            callback=self._audio_callback,
            blocksize=512
        )
        self._stream.start()
        print("[AudioRecorder] Started recording audio...", flush=True)

    def stop_recording(self) -> np.ndarray | None:
        """
        Stops recording audio, trims silence via VAD, and returns clean float32 PCM numpy array.
        
        :return: 1D numpy array of float32 PCM samples, or None if invalid/empty speech.
        """
        if not self.is_recording:
            return None

        self.is_recording = False

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        # Drain queue into frames array
        collected_chunks = []
        while not self._audio_queue.empty():
            try:
                chunk = self._audio_queue.get_nowait()
                collected_chunks.append(chunk)
            except queue.Empty:
                break

        if not collected_chunks:
            print("[AudioRecorder] No audio frames collected.", flush=True)
            return None

        # Concatenate 2D chunks into 1D float32 array
        full_pcm = np.concatenate(collected_chunks, axis=0).flatten()
        print(f"[AudioRecorder] Raw recorded audio length: {len(full_pcm) / self.sample_rate:.2f}s", flush=True)

        # Apply VAD silence trimming
        trimmed_pcm = self._vad_filter.trim_silence(full_pcm)

        if not self._vad_filter.is_valid_speech(trimmed_pcm):
            print("[AudioRecorder] VAD discarded recording (too short or no speech detected).", flush=True)
            return None

        print(f"[AudioRecorder] Trimmed audio speech length: {len(trimmed_pcm) / self.sample_rate:.2f}s", flush=True)
        return trimmed_pcm

    @staticmethod
    def list_devices():
        """
        Returns a list of available input sound devices.
        """
        return sd.query_devices()
