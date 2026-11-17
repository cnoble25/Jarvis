"""
Unit Tests for LLM Provider Registry and Dynamic Factory Instantiation
"""

import unittest
from daemon.providers.factory import ProviderRegistry, ProviderFactory
from daemon.providers.llm.ollama_llm_provider import OllamaLLMProvider
from daemon.providers.llm.gemini_llm_provider import GeminiLLMProvider
from daemon.providers.llm.anthropic_llm_provider import AnthropicLLMProvider


class TestLLMRegistry(unittest.TestCase):
    def setUp(self):
        # Trigger provider discovery
        ProviderRegistry.discover_providers()

    def test_llm_provider_registration(self):
        ollama_cls = ProviderRegistry.get_llm_provider_class("ollama")
        gemini_cls = ProviderRegistry.get_llm_provider_class("gemini_llm")
        anthropic_cls = ProviderRegistry.get_llm_provider_class("anthropic_llm")

        self.assertEqual(ollama_cls, OllamaLLMProvider)
        self.assertEqual(gemini_cls, GeminiLLMProvider)
        self.assertEqual(anthropic_cls, AnthropicLLMProvider)

    def test_list_llm_providers(self):
        llm_providers = ProviderRegistry.list_llm_providers()
        provider_ids = [p["id"] for p in llm_providers]

        self.assertIn("ollama", provider_ids)
        self.assertIn("gemini_llm", provider_ids)
        self.assertIn("anthropic_llm", provider_ids)

        for p in llm_providers:
            self.assertIn("id", p)
            self.assertIn("name", p)
            self.assertIn("type", p)
            self.assertIn("models", p)
            self.assertIsInstance(p["models"], list)
            self.assertGreater(len(p["models"]), 0, f"Provider {p['id']} should have models")

    def test_factory_get_available_llm_providers(self):
        factory = ProviderFactory()
        available = factory.get_available_llm_providers()
        provider_ids = [p["id"] for p in available]

        self.assertIn("ollama", provider_ids)
        self.assertIn("gemini_llm", provider_ids)
        self.assertIn("anthropic_llm", provider_ids)

    def test_factory_instantiate_llm_providers(self):
        factory = ProviderFactory()

        # Instantiate Ollama
        ollama_inst = factory._instantiate_llm_provider("ollama:qwen3.5:9b")
        self.assertIsInstance(ollama_inst, OllamaLLMProvider)
        self.assertEqual(ollama_inst.model_name, "qwen3.5:9b")

        # Instantiate Gemini
        gemini_inst = factory._instantiate_llm_provider("gemini_llm:gemini-3.6-flash")
        self.assertIsInstance(gemini_inst, GeminiLLMProvider)
        self.assertEqual(gemini_inst.model_name, "gemini-3.6-flash")

        # Instantiate Anthropic
        anthropic_inst = factory._instantiate_llm_provider("anthropic_llm:claude-haiku-4-5-20251001")
        self.assertIsInstance(anthropic_inst, AnthropicLLMProvider)
        self.assertEqual(anthropic_inst.model_name, "claude-haiku-4-5-20251001")


if __name__ == "__main__":
    unittest.main()
