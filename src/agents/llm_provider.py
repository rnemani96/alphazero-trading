"""
src/agents/llm_provider.py
══════════════════════════
Compatibility shim: re-exports LLMProvider from src/llm/llm_provider.py
if that module exists, else provides a standalone implementation.

main.py imports: from src.agents.llm_provider import LLMProvider
README says:    from src.llm.llm_provider import LLMProvider

Both paths work now.
"""

from __future__ import annotations
import os
import logging
from typing import Any, Optional

logger = logging.getLogger("LLMProvider")

# ── Try importing the full implementation from src.llm ────────────────────────
try:
    from src.llm.llm_provider import LLMProvider   # type: ignore
    logger.debug("LLMProvider: loaded from src.llm")
except ImportError:
    # ── Standalone fallback implementation ────────────────────────────────────
    class LLMProvider:  # type: ignore
        """
        Multi-AI provider with automatic fallback.

        Priority (auto mode):
          1. Claude  (ANTHROPIC_API_KEY)
          2. OpenAI  (OPENAI_API_KEY)
          3. Gemini  (GOOGLE_API_KEY)
          4. Local   (Ollama / no API key needed)
        """

        def __init__(self, provider: str = 'none', model: str = '', api_key: str = ''):
            self.provider = provider
            self.model    = model
            self.api_key  = api_key
            self._client: Any = None
            self._init_client()

        def _init_client(self):
            if self.provider == 'claude':
                try:
                    import anthropic
                    self._client = anthropic.Anthropic(api_key=self.api_key)
                    logger.info("LLMProvider: Claude (Anthropic) ready")
                except Exception as e:
                    logger.warning(f"LLMProvider: Claude init failed — {e}")
            elif self.provider == 'openai':
                try:
                    import openai
                    self._client = openai.OpenAI(api_key=self.api_key)
                    logger.info("LLMProvider: OpenAI ready")
                except Exception as e:
                    logger.warning(f"LLMProvider: OpenAI init failed — {e}")
            elif self.provider == 'gemini':
                try:
                    import google.generativeai as genai
                    genai.configure(api_key=self.api_key)
                    self._client = genai.GenerativeModel(self.model or 'gemini-pro')
                    logger.info("LLMProvider: Gemini ready")
                except Exception as e:
                    logger.warning(f"LLMProvider: Gemini init failed — {e}")
            else:
                logger.info("LLMProvider: running without LLM (no API key set)")

        @classmethod
        def create(
            cls,
            provider: Optional[str] = None,
            api_key:  Optional[str] = None,
        ) -> 'LLMProvider':
            """
            Factory — auto-detects available provider from environment.
            """
            explicit = provider or os.getenv('LLM_PROVIDER', 'auto')

            candidates = []
            if explicit and explicit != 'auto':
                candidates = [explicit]
            else:
                candidates = ['claude', 'openai', 'gemini', 'local']

            for p in candidates:
                key = api_key or cls._get_key(p)
                model = cls._default_model(p)
                if key or p == 'local':
                    inst = cls(provider=p, model=model, api_key=key or '')
                    if inst._client is not None or p == 'local':
                        return inst

            # Nothing available
            return cls(provider='none')

        @staticmethod
        def _get_key(provider: str) -> str:
            mapping = {
                'claude': os.getenv('ANTHROPIC_API_KEY', ''),
                'openai': os.getenv('OPENAI_API_KEY', ''),
                'gemini': os.getenv('GOOGLE_API_KEY', ''),
            }
            return mapping.get(provider, '')

        @staticmethod
        def _default_model(provider: str) -> str:
            mapping = {
                'claude': 'claude-sonnet-4-6',
                'openai': 'gpt-4o',
                'gemini': 'gemini-pro',
                'local':  'llama3',
            }
            return mapping.get(provider, '')

        def complete(self, prompt: str, system: str = '', max_tokens: int = 500) -> str:
            """
            Send a completion request and return the response text.
            Returns empty string if no LLM is configured.
            """
            if self._client is None:
                return ''
            try:
                if self.provider == 'claude':
                    msgs = [{'role': 'user', 'content': prompt}]
                    resp = self._client.messages.create(
                        model=self.model or 'claude-sonnet-4-6',
                        max_tokens=max_tokens,
                        system=system or 'You are a professional quantitative trading analyst.',
                        messages=msgs,
                    )
                    return resp.content[0].text if resp.content else ''

                elif self.provider == 'openai':
                    msgs = []
                    if system:
                        msgs.append({'role': 'system', 'content': system})
                    msgs.append({'role': 'user', 'content': prompt})
                    resp = self._client.chat.completions.create(
                        model=self.model or 'gpt-4o',
                        messages=msgs,
                        max_tokens=max_tokens,
                    )
                    return resp.choices[0].message.content or ''

                elif self.provider == 'gemini':
                    resp = self._client.generate_content(prompt)
                    return resp.text or ''

            except Exception as e:
                logger.warning(f"LLMProvider.complete error ({self.provider}): {e}")
            return ''

        def is_available(self) -> bool:
            return self._client is not None

        def __repr__(self) -> str:
            available = '✓' if self.is_available() else '✗'
            return f"LLMProvider({self.provider} {self.model} {available})"


__all__ = ['LLMProvider']
