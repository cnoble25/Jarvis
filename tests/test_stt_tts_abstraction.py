"""
Unit and Integration Tests for STT & TTS Engine Abstraction
Tests buffer normalization, silent audio checks, hallucination post-processing,
RAM disk temp file lifecycle, provider registry, and custom child provider creation.
"""

import os
import unittest
import numpy as np
from daemon.providers.base import AbstractBaseSTTEngine, AbstractBaseTTSEngine
from daemon.providers.factory import ProviderRegistry, ProviderFactory


class DummySTTProvider(AbstractBaseSTTEngine):
    """Test subclass of AbstractBaseSTTEngine."""
    def __init__(self, mock_return: str = "mocked speech transcript"):
        self.mock_return = mock_return
        self.last_float32_pcm = None
        self.last_sample_rate = None

    def _transcribe_audio(self, float32_pcm: np.ndarray, raw_input, sample_rate: int) -> str:
        self.last_float32_pcm = float32_pcm
        self.last_sample_rate = sample_rate
        return self.mock_return

    def get_provider_info(self):
        return {"id": "dummy_stt", "name": "Dummy STT", "type": "local"}


class DummyTTSProvider(AbstractBaseTTSEngine):
    """Test subclass of AbstractBaseTTSEngine."""
    def __init__(self, voice: str = "voice_a"):
        super().__init__()
        self.voice = voice
        self.last_text = None
        self.last_voice = None
        self.last_speed = None

    def _synthesize_audio(self, text: str, voice: str, speed: float):
        self.last_text = text
        self.last_voice = voice
        self.last_speed = speed
        # Generate 0.5s of 440Hz sine wave at 16kHz
        t = np.linspace(0, 0.5, int(16000 * 0.5), False)
        samples = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        return samples, 16000

    def get_available_voices(self):
        return ["voice_a", "voice_b"]

    def get_default_voice(self):
        return self.voice

    def get_provider_info(self):
        return {"id": "dummy_tts", "name": "Dummy TTS", "type": "local"}


class TestSTTTTSAbstraction(unittest.TestCase):
    def test_stt_validation_empty_and_short(self):
        stt = DummySTTProvider()
        # Empty input
        self.assertEqual(stt.transcribe_buffer(None), "")
        self.assertEqual(stt.transcribe_buffer(b""), "")
        self.assertEqual(stt.transcribe_buffer(np.array([])), "")

        # Short audio buffer (< 0.1s at 16kHz = 1600 samples)
        short_bytes = b"\x00\x00" * 100
        self.assertEqual(stt.transcribe_buffer(short_bytes), "")

        # Silence buffer (all zeros)
        silence_bytes = b"\x00\x00" * 3200
        self.assertEqual(stt.transcribe_buffer(silence_bytes), "")

    def test_stt_buffer_normalization_and_hallucination_filter(self):
        stt = DummySTTProvider(mock_return="Subtitles by Amara.org Thanks for watching! Hello world.")
        
        # Valid non-silent 0.5s audio array
        sample_rate = 16000
        t = np.linspace(0, 0.5, int(sample_rate * 0.5), False)
        audio_array = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)

        result = stt.transcribe_buffer(audio_array, sample_rate=sample_rate)
        # Hallucinations stripped
        self.assertEqual(result, "Hello world.")
        self.assertIsNotNone(stt.last_float32_pcm)
        self.assertEqual(stt.last_sample_rate, 16000)

    def test_stt_bytes_normalization(self):
        stt = DummySTTProvider(mock_return="Valid text")
        sample_rate = 16000
        int16_samples = (np.sin(np.linspace(0, 100, 3200)) * 10000).astype(np.int16)
        raw_bytes = int16_samples.tobytes()

        result = stt.transcribe_buffer(raw_bytes, sample_rate=sample_rate)
        self.assertEqual(result, "Valid text")
        self.assertTrue(isinstance(stt.last_float32_pcm, np.ndarray))

    def test_tts_validation_and_speak(self):
        tts = DummyTTSProvider()
        # Empty text
        self.assertFalse(tts.speak(""))
        self.assertFalse(tts.speak("   "))

        # Valid speak call
        success = tts.speak("Hello Jarvis testing TTS engine abstraction", voice="voice_b", block=True)
        self.assertTrue(success)
        self.assertEqual(tts.last_text, "Hello Jarvis testing TTS engine abstraction")
        self.assertEqual(tts.last_voice, "voice_b")

    def test_provider_registry(self):
        @ProviderRegistry.register_stt("test_custom_stt")
        class CustomSTT(DummySTTProvider):
            pass

        @ProviderRegistry.register_tts("test_custom_tts")
        class CustomTTS(DummyTTSProvider):
            pass

        stt_cls = ProviderRegistry.get_stt_provider_class("test_custom_stt")
        tts_cls = ProviderRegistry.get_tts_provider_class("test_custom_tts")

        self.assertEqual(stt_cls, CustomSTT)
        self.assertEqual(tts_cls, CustomTTS)

    def test_voice_enumeration_and_provider_lists(self):
        @ProviderRegistry.register_tts("voice_test_tts")
        class VoiceTestTTS(DummyTTSProvider):
            def get_available_voices(self):
                return ["custom_voice_1", "custom_voice_2", "custom_voice_3"]

        factory = ProviderFactory()
        tts_providers = factory.get_available_tts_providers()
        tts_ids = [p["id"] for p in tts_providers]
        self.assertIn("kokoro", tts_ids)
        self.assertIn("voice_test_tts", tts_ids)

        voices = factory.get_voices_for_provider("voice_test_tts")
        self.assertEqual(voices, ["custom_voice_1", "custom_voice_2", "custom_voice_3"])


if __name__ == "__main__":
    unittest.main()

