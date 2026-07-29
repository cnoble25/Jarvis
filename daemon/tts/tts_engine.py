import os
import io
import wave
import shutil
import subprocess
import numpy as np
import urllib.request
import sounddevice as sd
from kokoro_onnx import Kokoro


class TTSEngine:
    MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
    VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

    def __init__(self, assets_dir: str | None = None):
        """
        Initialize local Kokoro-ONNX TTS Engine.
        Automatically downloads/caches model weights and voices locally.
        """
        if assets_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            assets_dir = os.path.join(base_dir, "assets")
        
        os.makedirs(assets_dir, exist_ok=True)
        self.model_path = os.path.join(assets_dir, "kokoro-v1.0.onnx")
        self.voices_path = os.path.join(assets_dir, "voices-v1.0.bin")

        self._ensure_assets()

        print(f"[TTSEngine] Loading Kokoro-ONNX model from '{self.model_path}'...", flush=True)
        self.kokoro = Kokoro(self.model_path, self.voices_path)
        print("[TTSEngine] Kokoro-ONNX TTS engine initialized successfully.", flush=True)

        # Detect native PipeWire/PulseAudio player (pw-play / paplay) to prevent audio choppiness when music plays concurrently
        self.player_cmd = shutil.which("pw-play") or shutil.which("paplay") or shutil.which("aplay")
        if self.player_cmd:
            print(f"[TTSEngine] Detected native PipeWire audio player: '{self.player_cmd}' (Concurrent audio mixing enabled)", flush=True)

    def _ensure_assets(self):
        """
        Ensures ONNX model and voices file exist locally.
        """
        if not os.path.exists(self.model_path):
            print(f"[TTSEngine] Downloading Kokoro ONNX model to {self.model_path}...", flush=True)
            urllib.request.urlretrieve(self.MODEL_URL, self.model_path)
        if not os.path.exists(self.voices_path):
            print(f"[TTSEngine] Downloading voices configuration to {self.voices_path}...", flush=True)
            urllib.request.urlretrieve(self.VOICES_URL, self.voices_path)

    def speak(self, text: str, voice: str = "af_kore", speed: float = 1.0, block: bool = True):
        """
        Synthesizes text into 24kHz audio and plays through system speakers with zero choppiness.
        
        :param text: Text string for Jarvis to speak.
        :param voice: Voice ID (e.g., 'am_adam', 'af_bella', 'af_sarah', 'am_michael').
        :param speed: Playback speed multiplier (default 1.0).
        :param block: If True, waits until audio finishes playing before returning.
        """
        if not text or not text.strip():
            return

        print(f"[TTSEngine] 🔊 Speaking: \"{text}\"", flush=True)
        samples, sample_rate = self.kokoro.create(text, voice=voice, speed=speed, lang="en-us")

        # 1. Primary: Native PipeWire/PulseAudio audio player (pw-play / paplay)
        # Prevents ALSA/PortAudio xrun buffer underruns when music/videos play simultaneously.
        if self.player_cmd:
            temp_dir = "/dev/shm" if os.path.exists("/dev/shm") else "/tmp"
            wav_path = os.path.join(temp_dir, f"jarvis_tts_{os.getpid()}.wav")
            try:
                # Convert float32 numpy samples [-1.0, 1.0] to int16 PCM WAV
                int16_samples = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
                with wave.open(wav_path, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(int16_samples.tobytes())

                if block:
                    subprocess.run([self.player_cmd, wav_path], check=False)
                else:
                    subprocess.Popen([self.player_cmd, wav_path])
                return
            except Exception as e:
                print(f"[TTSEngine Warning] Native PipeWire player failed: {e}. Falling back to sounddevice.", flush=True)
            finally:
                if block and os.path.exists(wav_path):
                    try:
                        os.remove(wav_path)
                    except OSError:
                        pass

        # 2. Fallback: sounddevice with latency='high' to prevent xruns
        sd.play(samples, sample_rate, latency='high')
        if block:
            sd.wait()

    def get_available_voices(self) -> list[str]:
        """
        Returns list of available voice IDs.
        """
        return self.kokoro.get_voices()
