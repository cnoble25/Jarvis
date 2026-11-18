"""
ElevenLabs TTS provider: registration, settings, and synthesis with a mocked client.
Nothing here calls the ElevenLabs service or plays sound.
"""

import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from daemon.providers.factory import ProviderFactory, ProviderRegistry
from daemon.providers.tts.elevenlabs_tts_provider import DEFAULT_MODEL, SAMPLE_RATE, ElevenLabsTTSProvider

DANIEL = "onwK4e9ZLuTAKqWW03F9"


def pcm_bytes(seconds: float = 0.2) -> bytes:
    t = np.linspace(0, seconds, int(SAMPLE_RATE * seconds), False)
    return (0.5 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16).tobytes()


def provider_with_client(**kwargs):
    p = ElevenLabsTTSProvider(api_key="test_api_key", **kwargs)
    p._client = MagicMock()
    p._client.text_to_speech.convert.return_value = iter([pcm_bytes()[:1001], pcm_bytes()[1001:]])
    return p


def test_registration():
    assert ProviderRegistry.get_tts_provider_class("elevenlabs") is ElevenLabsTTSProvider
    assert ProviderRegistry.get_tts_provider_class("ElevenLabs") is ElevenLabsTTSProvider


def test_defaults_and_info():
    p = ElevenLabsTTSProvider(api_key="k")
    assert p.voice == DANIEL and p.model == DEFAULT_MODEL == "eleven_turbo_v2"
    info = p.get_provider_info()
    assert info["id"] == "elevenlabs_tts" and "Daniel" in info["name"] and info["model"] == DEFAULT_MODEL
    assert DANIEL in p.get_available_voices()


def test_unknown_voice_is_offered_first():
    p = ElevenLabsTTSProvider(voice="customVoiceId123", api_key="k")
    assert p.get_available_voices()[0] == "customVoiceId123"


def test_factory_lists_elevenlabs():
    factory = ProviderFactory()
    assert "elevenlabs" in [x["id"] for x in factory.get_available_tts_providers()]


def test_missing_api_key_raises():
    # Built inside the patch: another test may have loaded the real key from .env into the environment.
    with patch.dict(os.environ, {"ELEVENLABS_API_KEY": ""}):
        p = ElevenLabsTTSProvider(api_key="")
        with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
            p._synthesize_audio("Hello", voice="", speed=1.0)


def test_synthesis_requests_pcm_with_the_chosen_model():
    p = provider_with_client(voice=DANIEL, model="eleven_turbo_v2_5")
    samples, sr = p._synthesize_audio("Testing", voice=DANIEL, speed=1.0)
    p._client.text_to_speech.convert.assert_called_once_with(
        text="Testing", voice_id=DANIEL, model_id="eleven_turbo_v2_5", output_format=f"pcm_{SAMPLE_RATE}")
    assert sr == SAMPLE_RATE and samples.dtype == np.float32
    assert len(samples) == int(SAMPLE_RATE * 0.2) and 0.4 < np.abs(samples).max() <= 1.0


def test_speak_plays_through_the_player_without_sound():
    p = provider_with_client()
    p.player_cmd = "/usr/bin/pw-play"
    with patch("daemon.providers.base.subprocess.run") as run:
        assert p.speak("") is False
        assert p.speak("Testing playback", block=True) is True
    assert run.call_args[0][0][0] == "/usr/bin/pw-play"
