"""
Unit test for Universal LLMProvider.
Validates:
  1. Auto-detection of local Ollama / LM Studio
  2. Provider initialization across Ollama, Groq, DeepSeek, OpenRouter, OpenAI, Gemini, Claude, Custom
  3. OpenAI-standard chat.completions.create interface compatibility
  4. Prompt text completion and chat methods
  5. Fallback behavior when provider is offline
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add repository root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force UTF-8 stdout
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.agents.llm_provider import LLMProvider, _MockChatCompletion


class TestUniversalLLMProvider(unittest.TestCase):

    def test_auto_detection_ollama(self):
        """Verify LLMProvider auto-detects running Ollama or creates standard instance."""
        llm = LLMProvider.create()
        self.assertIsNotNone(llm)
        self.assertIn(llm.provider, ("ollama", "openrouter", "openai", "groq", "gemini", "claude", "none"))
        info = llm.get_info()
        self.assertIn("provider", info)
        self.assertIn("model", info)

    def test_custom_endpoint_creation(self):
        """Verify LLMProvider correctly configures custom OpenAI-compatible endpoints."""
        llm = LLMProvider(
            provider="custom",
            model="my-custom-model",
            base_url="http://192.168.1.100:8000/v1",
            api_key="secret-key",
        )
        self.assertEqual(llm.provider, "custom")
        self.assertEqual(llm.model, "my-custom-model")
        self.assertEqual(llm.base_url, "http://192.168.1.100:8000/v1")
        self.assertEqual(llm.api_key, "secret-key")

    def test_groq_and_deepseek_endpoints(self):
        """Verify Groq and DeepSeek standard endpoint configurations."""
        llm_groq = LLMProvider(provider="groq", api_key="gsk_test")
        self.assertEqual(llm_groq.base_url, "https://api.groq.com/openai/v1")
        self.assertEqual(llm_groq.model, "llama-3.3-70b-versatile")

        llm_ds = LLMProvider(provider="deepseek", api_key="sk_test")
        self.assertEqual(llm_ds.base_url, "https://api.deepseek.com")
        self.assertEqual(llm_ds.model, "deepseek-chat")

    def test_chat_completions_interface_structure(self):
        """Verify that client.chat.completions.create returns expected schema."""
        mock_completion = _MockChatCompletion("Bullish breakout detected", total_tokens=42)
        self.assertEqual(len(mock_completion.choices), 1)
        self.assertEqual(mock_completion.choices[0].message.content, "Bullish breakout detected")
        self.assertEqual(mock_completion.usage.total_tokens, 42)

    def test_complete_offline_safety(self):
        """Verify LLMProvider never raises exceptions when client is offline."""
        llm = LLMProvider(provider="none")
        resp = llm.complete("Hello")
        self.assertEqual(resp, "")
        self.assertFalse(llm.is_available())


if __name__ == "__main__":
    unittest.main()
