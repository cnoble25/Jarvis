"""Playing synthesized speech: the same on every OS except for which player runs the WAV."""

import os
import time
import wave
from typing import Optional

import numpy as np

from .base import OSInterface


def play_samples(samples, sample_rate: int, block: bool = True, os_interface: Optional[OSInterface] = None) -> bool:
    """
    Play float32 samples in [-1, 1]. The OS's own player goes through the system mixer, so speech
    plays cleanly over music; without one, sounddevice plays it directly.
    """
    if os_interface is None:
        from . import get_os
        os_interface = get_os()
    samples = np.asarray(samples, dtype=np.float32).flatten()
    if samples.size == 0:
        return False

    wav_path = os.path.join(os_interface.temp_audio_dir(), f"jarvis_tts_{os.getpid()}_{os.urandom(4).hex()}.wav")
    played = False
    try:
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes((np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes())
        played = os_interface.play_wav(wav_path, block=block)
    except Exception as err:
        print(f"[OS Audio Warning] System player failed: {err}. Falling back to sounddevice.", flush=True)
    if played and not block:
        _remove_later(wav_path, len(samples) / float(sample_rate))
    else:
        _remove(wav_path)
    if played:
        return True

    try:
        import sounddevice as sd
        sd.play(samples, sample_rate, latency="high")
        if block:
            sd.wait()
        return True
    except Exception as err:
        print(f"[OS Audio Error] sounddevice playback failed: {err}", flush=True)
        return False


def _remove(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


def _remove_later(path: str, seconds: float):
    """A non-blocking play still reads the file: delete it once it has had time to finish."""
    import threading

    def _later():
        time.sleep(seconds + 5)
        _remove(path)

    threading.Thread(target=_later, daemon=True, name="JarvisTTSCleanup").start()
