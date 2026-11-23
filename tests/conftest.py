"""
Tests never touch the real ~/.config/jarvis or ~/.local/share/jarvis: HOME points at a throwaway folder
before any Jarvis module is imported (several compute their paths from it at import time).
"""

import os
import tempfile

_fake_home = tempfile.mkdtemp(prefix="jarvis-test-home-")
os.environ["HOME"] = _fake_home
os.environ.pop("XDG_CONFIG_HOME", None)
os.environ.pop("XDG_DATA_HOME", None)

import pytest


@pytest.fixture(autouse=True)
def _no_speech_model(monkeypatch):
    """No test needs a real Whisper model; building a provider factory would otherwise load (or download) one."""
    from daemon.stt import stt_engine

    def fake_init(self, model_size="base.en", device="cpu", compute_type="int8", *args, **kwargs):
        self.model, self.device, self.compute_type, self._tokenizer = None, "cpu", "int8", None

    monkeypatch.setattr(stt_engine.STTEngine, "__init__", fake_init)
