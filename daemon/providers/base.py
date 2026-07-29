"""
Pluggable AI Engine Abstract Base Classes (Story 1.1)
Defines standard provider interface contracts for STT, LLM Orchestrator, and TTS engines.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class BaseSTTProvider(ABC):
    @abstractmethod
    def transcribe_buffer(self, pcm_data: bytes) -> str:
        """
        Transcribe raw PCM audio buffer into text.
        
        :param pcm_data: Raw 16kHz mono 16-bit PCM audio bytes.
        :return: Transcribed text string.
        """
        pass

    @abstractmethod
    def get_provider_info(self) -> Dict[str, Any]:
        """
        Returns provider metadata dictionary (name, id, type: 'local' | 'cloud').
        """
        pass


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
    @abstractmethod
    def speak(self, text: str, voice: Optional[str] = None, block: bool = True) -> bool:
        """
        Synthesize text to speech and play audio response.
        
        :param text: Text string to speak.
        :param voice: Optional voice ID or name.
        :param block: If True, blocks until playback completes.
        :return: True if successful, False otherwise.
        """
        pass

    @abstractmethod
    def get_available_voices(self) -> List[str]:
        """
        Returns list of available voice IDs.
        """
        pass

    @abstractmethod
    def get_provider_info(self) -> Dict[str, Any]:
        """
        Returns provider metadata dictionary.
        """
        pass
