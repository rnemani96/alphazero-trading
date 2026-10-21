"""
src/agents/llm_provider.py
══════════════════════════
Universal LLM Gateway for AlphaZero Capital.

Supports ANY local LLM or ANY cloud API:
  • Local LLMs:
      - Ollama (http://localhost:11434, e.g. llama3.2, qwen2.5, gemma3, deepseek-r1)
      - LM Studio (http://localhost:1234)
      - vLLM / LocalAI / llama.cpp (http://localhost:8000 or custom)
  • Cloud APIs:
      - OpenRouter (100+ models via openrouter.ai)
      - Groq (ultra-fast Llama-3.3, DeepSeek)
      - DeepSeek API (deepseek-chat, deepseek-reasoner)
      - OpenAI (GPT-4o, GPT-4o-mini, o1, o3-mini)
      - Google Gemini (gemini-2.0-flash, gemini-1.5-pro via OpenAI-compatible or GenAI)
      - Anthropic Claude (claude-3-5-sonnet, claude-3-opus)
      - Mistral AI (mistral-large, mistral-small)
      - Together AI
      - Custom OpenAI-compatible endpoints (any base_url + api_key)

Auto-detects available local servers and cloud API keys seamlessly.
Provides both direct text completion and an OpenAI-standard client interface
(client.chat.completions.create) for 100% interoperability with all agents.
"""

from __future__ import annotations
import os
import json
import logging
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("LLMProvider")


# ── Standalone Lightweight OpenAI-compatible Client (zero-dependency fallback) ──
class _MockMessage:
    def __init__(self, content: str):
        self.content = content


class _MockChoice:
    def __init__(self, content: str):
        self.message = _MockMessage(content)


class _MockUsage:
    def __init__(self, prompt_tokens: int = 0, completion_tokens: int = 0, total_tokens: int = 0):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens or (prompt_tokens + completion_tokens)


class _MockChatCompletion:
    def __init__(self, content: str, total_tokens: int = 0):
        self.choices = [_MockChoice(content)]
        self.usage = _MockUsage(total_tokens=total_tokens)


class _HTTPChatCompletions:
    """Provides client.chat.completions.create(...) over raw HTTP."""
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def create(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any
    ) -> Any:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choice = data.get("choices", [{}])[0]
                msg = choice.get("message", {})
                content = msg.get("content", "")
                usage = data.get("usage", {})
                total_tokens = usage.get("total_tokens", len(content) // 4)
                return _MockChatCompletion(content, total_tokens)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            logger.error(f"HTTPChatCompletions error ({url}) {e.code}: {err_body}")
            raise RuntimeError(f"LLM API request failed [{e.code}]: {err_body}") from e
        except Exception as e:
            logger.error(f"HTTPChatCompletions error ({url}): {e}")
            raise


class _HTTPClient:
    """Drop-in OpenAI client replacement using pure HTTP."""
    def __init__(self, base_url: str, api_key: str):
        self.chat = type("Chat", (), {"completions": _HTTPChatCompletions(base_url, api_key)})()


class LLMProvider:
    """
    Universal Multi-Provider LLM Gateway.
    
    Can connect to:
      • ollama      — local Ollama instance (http://localhost:11434/v1)
      • lmstudio    — local LM Studio instance (http://localhost:1234/v1)
      • vllm        — local vLLM or custom local engine
      • openrouter  — OpenRouter.ai (100+ models)
      • groq        — Groq fast inference
      • deepseek    — DeepSeek official API
      • openai      — OpenAI official API
      • gemini      — Google Gemini OpenAI-compatible API
      • claude      — Anthropic Claude API
      • mistral     — Mistral AI API
      • together    — Together AI API
      • custom      — Any user-provided base_url + api_key
    """

    DEFAULT_ENDPOINTS = {
        "ollama": "http://localhost:11434/v1",
        "lmstudio": "http://localhost:1234/v1",
        "vllm": "http://localhost:8000/v1",
        "local": "http://localhost:11434/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        "groq": "https://api.groq.com/openai/v1",
        "deepseek": "https://api.deepseek.com",
        "openai": "https://api.openai.com/v1",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
        "mistral": "https://api.mistral.ai/v1",
        "together": "https://api.together.xyz/v1",
    }

    DEFAULT_MODELS = {
        "ollama": "llama3.2:3b",
        "lmstudio": "local-model",
        "vllm": "local-model",
        "local": "llama3.2:3b",
        "openrouter": "meta-llama/llama-3-70b-instruct",
        "groq": "llama-3.3-70b-versatile",
        "deepseek": "deepseek-chat",
        "openai": "gpt-4o-mini",
        "gemini": "gemini-2.0-flash",
        "claude": "claude-3-5-sonnet-20241022",
        "mistral": "mistral-small-latest",
        "together": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "custom": "default",
    }

    def __init__(
        self,
        provider: str = "none",
        model: str = "",
        api_key: str = "",
        base_url: str = "",
    ):
        self.provider = provider.lower()
        self.base_url = base_url or self._resolve_base_url(self.provider)
        self.api_key = api_key or self._resolve_api_key(self.provider)
        self.model = model or self._resolve_model(self.provider)
        self.client: Any = None
        self._init_client()

    def _resolve_base_url(self, provider: str) -> str:
        # Check custom base url first
        custom_base = os.getenv("LLM_BASE_URL", "").strip()
        if custom_base:
            return custom_base

        if provider in ("ollama", "local"):
            return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/v1"
        elif provider == "lmstudio":
            return os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234").rstrip("/") + "/v1"
        elif provider == "vllm":
            return os.getenv("VLLM_BASE_URL", "http://localhost:8000").rstrip("/") + "/v1"
        return self.DEFAULT_ENDPOINTS.get(provider, "")

    def _resolve_api_key(self, provider: str) -> str:
        custom_key = os.getenv("LLM_API_KEY", "").strip()
        if custom_key:
            return custom_key

        mapping = {
            "openrouter": os.getenv("OPENROUTER_API_KEY", ""),
            "openai": os.getenv("OPENAI_API_KEY", ""),
            "groq": os.getenv("GROQ_API_KEY", ""),
            "deepseek": os.getenv("DEEPSEEK_API_KEY", ""),
            "gemini": os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY", ""),
            "claude": os.getenv("ANTHROPIC_API_KEY", ""),
            "anthropic": os.getenv("ANTHROPIC_API_KEY", ""),
            "mistral": os.getenv("MISTRAL_API_KEY", ""),
            "together": os.getenv("TOGETHER_API_KEY", ""),
            "ollama": "ollama",     # Dummy key for OpenAI SDK compatibility
            "lmstudio": "lm-studio",
            "local": "local",
        }
        return mapping.get(provider, "")

    def _resolve_model(self, provider: str) -> str:
        # Global override
        env_model = os.getenv("LLM_MODEL", "").strip()
        if env_model:
            return env_model

        if provider in ("ollama", "local"):
            ollama_m = os.getenv("OLLAMA_MODEL", "").strip()
            if ollama_m:
                return ollama_m
            # Detect installed models in Ollama
            detected = self._detect_ollama_models()
            if detected:
                return detected[0]
            return self.DEFAULT_MODELS.get("ollama", "llama3.2:3b")

        elif provider == "openrouter":
            return os.getenv("OPENROUTER_MODEL") or self.DEFAULT_MODELS["openrouter"]
        elif provider == "groq":
            return os.getenv("GROQ_MODEL") or self.DEFAULT_MODELS["groq"]
        elif provider == "deepseek":
            return os.getenv("DEEPSEEK_MODEL") or self.DEFAULT_MODELS["deepseek"]

        return self.DEFAULT_MODELS.get(provider, "default")

    @staticmethod
    def _detect_ollama_models(host_url: str = "http://localhost:11434") -> List[str]:
        """Queries local Ollama to find available models."""
        try:
            req = urllib.request.Request(f"{host_url.rstrip('/')}/api/tags", headers={"User-Agent": "AlphaZero"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                return models
        except Exception:
            return []

    @staticmethod
    def _is_server_alive(url: str, timeout: float = 1.0) -> bool:
        """Checks if a local HTTP server is responding."""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AlphaZero"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status in (200, 301, 302, 404, 405)
        except Exception:
            return False

    def _init_client(self):
        if self.provider == "none":
            self.client = None
            return

        # Handle native Anthropic SDK if explicitly requested and base_url is not set
        if self.provider in ("claude", "anthropic") and not self.base_url:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key)
                logger.info(f"LLMProvider: Claude (Anthropic native SDK) ready — model: {self.model}")
                return
            except Exception as e:
                logger.debug(f"Native Anthropic init fallback: {e}")
                # Fallback to OpenRouter or proxy if available
                if os.getenv("OPENROUTER_API_KEY"):
                    self.provider = "openrouter"
                    self.base_url = "https://openrouter.ai/api/v1"
                    self.api_key = os.getenv("OPENROUTER_API_KEY")
                    self.model = f"anthropic/{self.model}"

        # Standard OpenAI SDK initialization with custom base_url
        try:
            from openai import OpenAI
            self.client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key or "none",
            )
            logger.info(f"LLMProvider: [{self.provider.upper()}] ready via OpenAI SDK — model: {self.model} (base_url: {self.base_url})")
            return
        except Exception as e:
            logger.debug(f"OpenAI SDK init failed ({e}), using zero-dependency HTTP client wrapper")

        # Zero-dependency HTTP fallback client
        try:
            self.client = _HTTPClient(base_url=self.base_url, api_key=self.api_key)
            logger.info(f"LLMProvider: [{self.provider.upper()}] ready via native HTTPClient — model: {self.model} (base_url: {self.base_url})")
        except Exception as exc:
            logger.warning(f"LLMProvider init failed for {self.provider}: {exc}")
            self.client = None

    @classmethod
    def create(
        cls,
        config: Optional[Any] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> "LLMProvider":
        """
        Factory method:
          1. Honors explicit arguments or config dict
          2. Auto-detects local Ollama / LM Studio if running
          3. Auto-detects cloud API keys (OpenRouter, Groq, DeepSeek, OpenAI, Gemini, Claude)
          4. Returns ready-to-use LLMProvider with zero-crash guarantee
        """
        cfg_dict: Dict[str, Any] = {}
        if config:
            if isinstance(config, dict):
                cfg_dict = config
            elif hasattr(config, "__dict__"):
                cfg_dict = vars(config)

        chosen_provider = (
            provider
            or cfg_dict.get("llm_provider")
            or os.getenv("LLM_PROVIDER")
            or "auto"
        ).lower()

        chosen_model = (
            model
            or cfg_dict.get("llm_model")
            or os.getenv("LLM_MODEL")
            or ""
        )

        chosen_key = (
            api_key
            or cfg_dict.get("openrouter_api_key")
            or cfg_dict.get("llm_api_key")
            or os.getenv("LLM_API_KEY")
            or ""
        )

        chosen_base = (
            base_url
            or cfg_dict.get("llm_base_url")
            or os.getenv("LLM_BASE_URL")
            or ""
        )

        # Explicit non-auto provider
        if chosen_provider != "auto":
            return cls(
                provider=chosen_provider,
                model=chosen_model,
                api_key=chosen_key,
                base_url=chosen_base,
            )

        # ── Auto-Detection Hierarchy ──
        # 1. Check custom LLM_BASE_URL
        if os.getenv("LLM_BASE_URL"):
            return cls(provider="custom", model=chosen_model, api_key=chosen_key, base_url=chosen_base)

        # 2. Check Local Ollama (port 11434)
        ollama_host = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        if cls._is_server_alive(ollama_host):
            models = cls._detect_ollama_models(ollama_host)
            logger.info(f"LLMProvider [AUTO]: Detected local Ollama with models: {models}")
            return cls(
                provider="ollama",
                model=chosen_model or (models[0] if models else "llama3.2:3b"),
                api_key="ollama",
                base_url=f"{ollama_host.rstrip('/')}/v1",
            )

        # 3. Check Local LM Studio (port 1234)
        lm_host = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234")
        if cls._is_server_alive(lm_host):
            logger.info("LLMProvider [AUTO]: Detected local LM Studio running on port 1234")
            return cls(provider="lmstudio", model=chosen_model or "local-model", base_url=f"{lm_host.rstrip('/')}/v1")

        # 4. Check Cloud API Keys in order of flexibility & speed
        if os.getenv("OPENROUTER_API_KEY"):
            return cls(provider="openrouter", model=chosen_model or "meta-llama/llama-3-70b-instruct")

        if os.getenv("GROQ_API_KEY"):
            return cls(provider="groq", model=chosen_model or "llama-3.3-70b-versatile")

        if os.getenv("DEEPSEEK_API_KEY"):
            return cls(provider="deepseek", model=chosen_model or "deepseek-chat")

        if os.getenv("OPENAI_API_KEY"):
            return cls(provider="openai", model=chosen_model or "gpt-4o-mini")

        if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
            return cls(provider="gemini", model=chosen_model or "gemini-2.0-flash")

        if os.getenv("ANTHROPIC_API_KEY"):
            return cls(provider="claude", model=chosen_model or "claude-3-5-sonnet-20241022")

        if os.getenv("MISTRAL_API_KEY"):
            return cls(provider="mistral", model=chosen_model or "mistral-small-latest")

        # Default fallback: Ollama (if user starts it later) or none
        logger.info("LLMProvider: No active local LLM or cloud API keys found; operating in standby mode")
        return cls(provider="ollama", model="llama3.2:3b", base_url="http://localhost:11434/v1")

    def complete(self, prompt: str, system: str = "", max_tokens: int = 1500, temperature: float = 0.7) -> str:
        """Direct text completion with any provider."""
        if not self.is_available():
            return ""

        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        return self.chat(messages, max_tokens=max_tokens, temperature=temperature)

    def chat(self, messages: List[Dict[str, str]], max_tokens: int = 1500, temperature: float = 0.7) -> str:
        """Chat completion returning string content."""
        if not self.is_available():
            return ""

        try:
            # Handle native Anthropic SDK if client is anthropic.Anthropic
            if hasattr(self.client, "messages") and hasattr(self.client.messages, "create"):
                # Separate system message for Anthropic
                system_content = ""
                user_msgs = []
                for m in messages:
                    if m.get("role") == "system":
                        system_content += m.get("content", "") + "\n"
                    else:
                        user_msgs.append(m)

                resp = self.client.messages.create(
                    model=self.model,
                    system=system_content.strip() or "You are a quantitative trading intelligence agent.",
                    messages=user_msgs,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return resp.content[0].text if resp.content else ""

            # OpenAI SDK or HTTPChatCompletions
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return resp.choices[0].message.content or ""

        except Exception as e:
            logger.warning(f"LLMProvider.chat error ({self.provider}/{self.model}): {e}")
            return ""

    def test_connection(self) -> Tuple[bool, str]:
        """Quickly pings the configured LLM to test connectivity."""
        if not self.is_available():
            return False, "No client initialized"
        try:
            resp = self.complete("Reply with 'READY'", max_tokens=10, temperature=0.1)
            if resp:
                return True, f"Success: {resp.strip()[:60]}"
            return False, "Empty response received"
        except Exception as e:
            return False, str(e)

    def is_available(self) -> bool:
        return self.client is not None

    def get_info(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "available": self.is_available(),
        }

    def __repr__(self) -> str:
        status = "READY" if self.is_available() else "OFFLINE"
        return f"<LLMProvider [{self.provider.upper()}] model='{self.model}' status=[{status}]>"


__all__ = ["LLMProvider"]
