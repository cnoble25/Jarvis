"""
Unit and Integration Tests for ElevenLabs TTS Provider
Tests provider registration, voice enumeration, metadata, API key validation,
mocked audio synthesis, and live synthesis if an API key is available.
"""

import os
import io
import unittest
from unittest.mock import patch, MagicMock
import numpy as np
import soundfile as sf

from daemon.providers.tts.elevenlabs_tts_provider import ElevenLabsTTSProvider
from daemon.providers.factory import ProviderRegistry, ProviderFactory


def generate_dummy_wav_bytes(duration_sec: float = 0.2, sample_rate: int = 22050) -> bytes:
    """Helper to create valid WAV audio bytes for mocking audio synthesis responses."""
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), False)
    samples = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    buffer = io.BytesIO()
    sf.write(buffer, samples, sample_rate, format='WAV')
    return buffer.getvalue()


class TestElevenLabsTTSProvider(unittest.TestCase):

    def test_provider_registration(self):
        """Test that ElevenLabsTTSProvider is properly registered in ProviderRegistry."""
        cls_lower = ProviderRegistry.get_tts_provider_class("elevenlabs")
        cls_cap = ProviderRegistry.get_tts_provider_class("ElevenLabs")
        self.assertEqual(cls_lower, ElevenLabsTTSProvider)
        self.assertEqual(cls_cap, ElevenLabsTTSProvider)

    def test_provider_info_and_voices(self):
        """Test provider metadata and available voice list."""
        provider = ElevenLabsTTSProvider(voice="JBFqnCBsd6RMkjVDRZzb")
        info = provider.get_provider_info()
        self.assertEqual(info["id"], "elevenlabs_tts")
        self.assertEqual(info["type"], "Online")
        self.assertIn("JBFqnCBsd6RMkjVDRZzb", info["name"])
        self.assertEqual(provider.get_default_voice(), "JBFqnCBsd6RMkjVDRZzb")

        voices = provider.get_available_voices()
        self.assertIsInstance(voices, list)
        self.assertIn("JBFqnCBsd6RMkjVDRZzb", voices)
        self.assertGreater(len(voices), 1)

    def test_factory_integration(self):
        """Test that ProviderFactory lists elevenlabs and its voices."""
        factory = ProviderFactory()
        available = factory.get_available_tts_providers()
        provider_ids = [p["id"] for p in available]
        self.assertIn("elevenlabs", provider_ids)

        voices = factory.get_voices_for_provider("elevenlabs")
        self.assertIn("JBFqnCBsd6RMkjVDRZzb", voices)

    def test_missing_api_key_raises_error(self):
        """Test that synthesizing without an API key raises ValueError."""
        provider = ElevenLabsTTSProvider(api_key="")
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": ""}, clear=True):
            provider.api_key = ""
            with self.assertRaises(ValueError) as ctx:
                provider._synthesize_audio("Hello", voice="", speed=1.0)
            self.assertIn("ELEVENLABS_API_KEY is not set", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_synthesize_audio_http_mocked(self, mock_urlopen):
        """Test audio synthesis using mocked HTTP API response."""
        dummy_wav = generate_dummy_wav_bytes(duration_sec=0.2, sample_rate=22050)
        
        mock_response = MagicMock()
        mock_response.read.return_value = dummy_wav
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        provider = ElevenLabsTTSProvider(api_key="test_api_key")
        # Ensure client is None so HTTP path is exercised
        provider._client = None

        samples, sr = provider._synthesize_audio("Hello world", voice="JBFqnCBsd6RMkjVDRZzb", speed=1.0)
        self.assertIsInstance(samples, np.ndarray)
        self.assertEqual(sr, 22050)
        self.assertGreater(len(samples), 0)

    def test_speak_abstraction_mocked(self):
        """Test speak() high-level interface from AbstractBaseTTSEngine."""
        dummy_wav = generate_dummy_wav_bytes(duration_sec=0.1, sample_rate=16000)

        provider = ElevenLabsTTSProvider(api_key="test_api_key")
        provider._client = None

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = dummy_wav
            mock_response.__enter__.return_value = mock_response
            mock_urlopen.return_value = mock_response

            # speak empty text returns False
            self.assertFalse(provider.speak(""))

            # speak non-empty text calls synthesis
            success = provider.speak("Testing speak abstraction", block=True)
            self.assertTrue(success)

    def test_sdk_synthesis_mocked(self):
        """Test synthesis using mocked ElevenLabs client SDK."""
        dummy_wav = generate_dummy_wav_bytes(duration_sec=0.2, sample_rate=44100)

        mock_client = MagicMock()
        mock_client.text_to_speech.convert.return_value = dummy_wav

        provider = ElevenLabsTTSProvider(api_key="test_api_key")
        provider._client = mock_client

        samples, sr = provider._synthesize_audio("Testing SDK path", voice="21m00Tcm4TlvDq8ikWAM", speed=1.0)
        self.assertIsInstance(samples, np.ndarray)
        self.assertEqual(sr, 44100)
        mock_client.text_to_speech.convert.assert_called_once_with(
            text="Testing SDK path",
            voice_id="21m00Tcm4TlvDq8ikWAM",
            model_id="eleven_v3",
            output_format="mp3_44100_128"
        )


if __name__ == "__main__":
    unittest.main()
