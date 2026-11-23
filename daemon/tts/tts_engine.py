import os
import urllib.request
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
        self.kokoro, self.device = self._load()
        print(f"[TTSEngine] Kokoro-ONNX TTS engine ready on {self.device}.", flush=True)

    def _load(self):
        """
        Kokoro on the GPU when onnxruntime-gpu and a CUDA device are available (about 0.1s per reply
        instead of 0.3-1s on the CPU), otherwise on the CPU.
        """
        try:
            import onnxruntime as ort
            if "CUDAExecutionProvider" in ort.get_available_providers():
                try:
                    ort.preload_dlls()  # the pip-installed CUDA / cuDNN libraries
                except Exception:
                    pass
                session = ort.InferenceSession(self.model_path, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
                if "CUDAExecutionProvider" in session.get_providers():
                    return Kokoro.from_session(session, self.voices_path), "GPU"
        except Exception as err:
            print(f"[TTSEngine] GPU unavailable for speech ({err}); using the CPU.", flush=True)
        return Kokoro(self.model_path, self.voices_path), "CPU"

    def warm_up(self, voice: str = "af_kore"):
        """The first synthesis prepares GPU kernels (~0.5-0.9s); do it before the first real reply."""
        import time
        started = time.perf_counter()
        self.kokoro.create("Ready.", voice=voice, speed=1.0, lang="en-us")
        print(f"[TTSEngine] Warmed up on {self.device} in {time.perf_counter() - started:.2f}s.", flush=True)

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

        from daemon.os_interface import play_samples
        play_samples(samples, sample_rate, block=block)

    def get_available_voices(self) -> list[str]:
        """
        Returns list of available voice IDs.
        """
        return self.kokoro.get_voices()
