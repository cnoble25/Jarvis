"""
Pluggable AI Engine Abstract Base Classes (Story 1.1)
Defines standard provider interface contracts for STT, LLM Orchestrator, and TTS engines.
"""

from abc import ABC, abstractmethod
import os
import time
import wave
import shutil
import subprocess
import numpy as np
from typing import Dict, Any, List, Optional, Tuple, Union


class BaseSTTProvider(ABC):
    """
    Abstract Base Class for STT Providers with built-in buffer normalization,
    audio validation, and hallucination post-processing.
    """
    # Phrases Whisper invents on silence. Multi-word ones are removed wherever they appear;
    # short ones ("you", "thank you", "bye") only when they are the whole utterance, so real
    # speech like "what did you say" is left alone.
    HALLUCINATION_PHRASES = ["thanks for watching", "subtitles by", "amara.org", "[blank_audio]"]
    HALLUCINATION_UTTERANCES = {"you", "thank you", "thanks", "bye", "okay"}

    # Alternatives the provider considered for the last transcription, most likely first:
    # [{"text": str, "probability": float, ...}]. Providers without n-best leave it empty.
    last_alternatives: List[Dict[str, Any]] = []

    def transcribe_buffer(self, pcm_data: Union[bytes, np.ndarray], sample_rate: int = 16000) -> str:
        """
        Public template method invoked by the application.
        Standardizes audio data, validates audio energy/duration, invokes child subclass _transcribe_audio hook,
        and cleans hallucinations.
        """
        self.last_alternatives = []
        if pcm_data is None or len(pcm_data) == 0:
            return ""

        # Standardize buffer to float32 1D numpy array [-1.0, 1.0]
        if isinstance(pcm_data, bytes):
            if len(pcm_data) % 2 != 0:
                pcm_data = pcm_data[:len(pcm_data) - (len(pcm_data) % 2)]
            float32_pcm = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
        else:
            float32_pcm = pcm_data.astype(np.float32) if pcm_data.dtype != np.float32 else pcm_data
            float32_pcm = float32_pcm.flatten()

        # Minimum duration check (< 0.1s is invalid)
        if len(float32_pcm) < (sample_rate * 0.1):
            return ""

        # Silence check (RMS energy threshold)
        rms = float(np.sqrt(np.mean(float32_pcm ** 2))) if len(float32_pcm) > 0 else 0.0
        if rms < 1e-4:
            return ""

        try:
            raw_text = self._transcribe_audio(float32_pcm, pcm_data, sample_rate)
        except Exception as err:
            print(f"[{self.__class__.__name__} Error] Transcription failed: {err}", flush=True)
            return ""

        return self._clean_hallucinations(raw_text)

    @abstractmethod
    def _transcribe_audio(self, float32_pcm: np.ndarray, raw_input: Union[bytes, np.ndarray], sample_rate: int) -> str:
        """
        Child hook: Execute actual model inference (e.g. Faster-Whisper, Gemini API).
        """
        pass

    def _clean_hallucinations(self, text: str) -> str:
        if not text:
            return ""
        import re
        cleaned = text.strip()
        for phrase in self.HALLUCINATION_PHRASES:
            pattern = re.escape(phrase) + r"[!\?.,]*"
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
        bare = re.sub(r"[^a-z ]+", "", cleaned.lower()).strip()
        if bare in self.HALLUCINATION_UTTERANCES:
            return ""
        return cleaned

    @abstractmethod
    def get_provider_info(self) -> Dict[str, Any]:
        """
        Returns provider metadata dictionary (name, id, type: 'local' | 'cloud').
        """
        pass


# Alias for backward/forward compatibility
AbstractBaseSTTEngine = BaseSTTProvider


class BaseLLMProvider(ABC):
    @abstractmethod
    def process_voice_query(
        self,
        user_query: str,
        history: List[Dict[str, str]],
        system_prompt: str
    ) -> Dict[str, Any]:
        """
        Process user voice query with multi-turn conversation chain and tool definitions.
        
        :param user_query: Transcribed text query.
        :param history: List of past turn dictionaries [{'role': 'user'|'assistant', 'content': '...'}].
        :param system_prompt: Full system prompt including tools and user profile.
        :return: Response dictionary containing 'tool', 'args', 'spoken_summary', and 'final_spoken_summary'.
        """
        pass

    @abstractmethod
    def get_available_models(self) -> List[str]:
        """
        Returns list of model names supported by this provider.
        """
        pass

    @abstractmethod
    def get_provider_info(self) -> Dict[str, Any]:
        """
        Returns provider metadata dictionary.
        """
        pass


class BaseTTSProvider(ABC):
    """
    Abstract Base Class for TTS Providers.
    Encapsulates PipeWire/PulseAudio mixing, RAM disk file generation, and sounddevice fallback.
    """

    def __init__(self):
        # Detect native PipeWire/PulseAudio player for concurrent audio mixing
        self.player_cmd = shutil.which("pw-play") or shutil.which("paplay") or shutil.which("aplay")

    def speak(self, text: str, voice: Optional[str] = None, speed: float = 1.0, block: bool = True) -> bool:
        """
        Synthesize text to speech and play audio response.
        
        :param text: Text string to speak.
        :param voice: Optional voice ID or name.
        :param speed: Playback speed multiplier.
        :param block: If True, blocks until playback completes.
        :return: True if successful, False otherwise.
        """
        if not text or not text.strip():
            return False

        target_voice = voice or self.get_default_voice()

        synth_started = time.perf_counter()
        try:
            samples, sample_rate = self._synthesize_audio(text, target_voice, speed)
        except Exception as err:
            print(f"[{self.__class__.__name__} Error] Audio synthesis failed: {err}", flush=True)
            return False

        if samples is None or len(samples) == 0:
            return False

        # Ensure float32 1D numpy array
        samples = np.asarray(samples, dtype=np.float32).flatten()

        # Primary route: Native PipeWire/PulseAudio audio player (pw-play / paplay)
        if self.player_cmd:
            temp_dir = "/dev/shm" if os.path.exists("/dev/shm") else "/tmp"
            wav_path = os.path.join(temp_dir, f"jarvis_tts_{os.getpid()}_{os.urandom(4).hex()}.wav")
            try:
                int16_samples = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
                with wave.open(wav_path, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(int16_samples.tobytes())

                self.last_synth_seconds = time.perf_counter() - synth_started
                self.last_playback_started = time.perf_counter()
                if block:
                    subprocess.run([self.player_cmd, wav_path], check=False)
                else:
                    subprocess.Popen([self.player_cmd, wav_path])
                return True
            except Exception as err:
                print(f"[BaseTTSProvider Warning] Native player failed: {err}. Falling back to sounddevice.", flush=True)
            finally:
                if block and os.path.exists(wav_path):
                    try:
                        os.remove(wav_path)
                    except OSError:
                        pass

        # Fallback route: sounddevice with high latency buffer
        try:
            import sounddevice as sd
            sd.play(samples, sample_rate, latency='high')
            if block:
                sd.wait()
            return True
        except Exception as err:
            print(f"[BaseTTSProvider Error] sounddevice playback failed: {err}", flush=True)
            return False

    @abstractmethod
    def _synthesize_audio(self, text: str, voice: str, speed: float) -> Tuple[np.ndarray, int]:
        """
        Child hook: Synthesizes text into 1D float32 numpy audio samples [-1.0, 1.0] and sample rate.
        """
        pass

    @abstractmethod
    def get_available_voices(self) -> List[str]:
        """
        Returns list of available voice IDs.
        """
        pass

    def get_default_voice(self) -> str:
        voices = self.get_available_voices()
        return voices[0] if voices else "default"

    @abstractmethod
    def get_provider_info(self) -> Dict[str, Any]:
        """
        Returns provider metadata dictionary.
        """
        pass


# Alias for backward/forward compatibility
AbstractBaseTTSEngine = BaseTTSProvider

