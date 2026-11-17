import os
import io
import numpy as np
import soundfile as sf
from typing import Dict, Any, List, Optional, Tuple
from daemon.providers.base import AbstractBaseTTSEngine
from daemon.providers.factory import ProviderRegistry


@ProviderRegistry.register_tts("elevenlabs")
@ProviderRegistry.register_tts("elevenlabs_tts")
@ProviderRegistry.register_tts("ElevenLabs")
class ElevenLabsTTSProvider(AbstractBaseTTSEngine):
    def __init__(self, voice: str = "JBFqnCBsd6RMkjVDRZzb", api_key: Optional[str] = None):
        super().__init__()
        self.voice = voice
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")

    def _synthesize_audio(self, text: str, voice: str, speed: float) -> Tuple[np.ndarray, int]:
        target_voice = voice or self.voice
        api_key = getattr(self, "api_key", None) if getattr(self, "api_key", None) is not None else os.environ.get("ELEVENLABS_API_KEY", "")
        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY is required for ElevenLabs TTS")

        from elevenlabs.client import ElevenLabs
        client = ElevenLabs(api_key=api_key)

        audio = client.text_to_speech.convert(
            text=text,
            voice_id=target_voice,
            model_id="eleven_v3",
            output_format="mp3_44100_128"
        )

        audio_bytes = b"".join(audio) if hasattr(audio, "__iter__") and not isinstance(audio, (bytes, bytearray)) else bytes(audio)
        samples, sample_rate = sf.read(io.BytesIO(audio_bytes), dtype="float32")
        return samples, sample_rate

    def get_available_voices(self) -> List[str]:
        return ["JBFqnCBsd6RMkjVDRZzb", "21m00Tcm4TlvDq8ikWAM"]

    def get_default_voice(self) -> str:
        return self.voice

    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "id": "elevenlabs_tts",
            "name": f"ElevenLabs ({self.voice})",
            "type": "Online",
            "voice": self.voice
        }