"""
AlphaZero Capital — Universal LLM Provider
src/agents/llm_provider.py

Single interface for EVERY major LLM backend.
Set LLM_PROVIDER in .env — or leave as 'auto' and it detects what you have.

Cloud  : openrouter | claude | openai | gemini
Local  : ollama | lmstudio | local_api | huggingface
Other  : null (disables AI features gracefully)

.env keys:
  LLM_PROVIDER=auto
  LLM_MODEL=                           # optional model override
  OPENROUTER_API_KEY=sk-or-...
  ANTHROPIC_API_KEY=sk-ant-...
  OPENAI_API_KEY=sk-...
  GOOGLE_API_KEY=...
  OLLAMA_URL=http://localhost:11434
  OLLAMA_MODEL=llama3:8b
  LMSTUDIO_URL=http://localhost:1234
  LMSTUDIO_MODEL=local-model
  LOCAL_API_URL=http://localhost:8000
  LOCAL_API_KEY=
  LOCAL_API_MODEL=
"""
from __future__ import annotations
import os, logging, socket
from abc import ABC, abstractmethod
from typing import Dict, List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── Base ─────────────────────────────────────────────────────────────────────
class BaseLLMProvider(ABC):
    def __init__(self, model: str, api_key: str = ''):
        self.model = model; self.api_key = api_key
    @abstractmethod
    def chat(self, prompt: str, max_tokens: int = 2000, temperature: float = 0.3) -> str: ...
    def chat_with_history(self, messages: List[Dict], max_tokens=2000, temperature=0.3) -> str:
        combined = '\n'.join(f"{m['role'].upper()}: {m['content']}" for m in messages)
        return self.chat(combined, max_tokens, temperature)
    def get_cost_estimate(self, i: int, o: int) -> float: return 0.0
    def __str__(self): return f"{self.__class__.__name__}({self.model})"

# ── OpenAI-compatible base (OpenRouter / LM Studio / Ollama / OpenAI) ────────
class _OAICompat(BaseLLMProvider):
    def __init__(self, model, api_key, base_url, extra_headers=None):
        super().__init__(model, api_key)
        try: from openai import OpenAI
        except ImportError: raise ImportError("pip install openai")
        import openai
        self._client = openai.OpenAI(api_key=api_key or 'not-needed', base_url=base_url)
        self._hdrs = extra_headers or {}
    def chat(self, prompt, max_tokens=2000, temperature=0.3):
        r = self._client.chat.completions.create(model=self.model, max_tokens=max_tokens,
            temperature=temperature, messages=[{'role':'user','content':prompt}], extra_headers=self._hdrs)
        return r.choices[0].message.content or ''
    def chat_with_history(self, messages, max_tokens=2000, temperature=0.3):
        r = self._client.chat.completions.create(model=self.model, max_tokens=max_tokens,
            temperature=temperature, messages=messages, extra_headers=self._hdrs)
        return r.choices[0].message.content or ''

# ── Cloud providers ───────────────────────────────────────────────────────────
class OpenRouterProvider(_OAICompat):
    _P = {'anthropic/claude-3-haiku':(0.25,1.25),'anthropic/claude-3-sonnet':(3,15),
          'anthropic/claude-3-opus':(15,75),'openai/gpt-4o':(5,15),'openai/gpt-4o-mini':(0.15,0.6),
          'meta-llama/llama-3-8b-instruct':(0.2,0.2),'meta-llama/llama-3-70b-instruct':(0.9,0.9)}
    def __init__(self, api_key, model='anthropic/claude-3-haiku'):
        super().__init__(model, api_key, 'https://openrouter.ai/api/v1',
            {'HTTP-Referer':'https://alphazero-capital.ai','X-Title':'AlphaZero Capital'})
        logger.info(f"OpenRouter → {model}")
    def get_cost_estimate(self, i, o):
        ip,op = self._P.get(self.model,(3,15)); return (i*ip+o*op)/1e6

class ClaudeProvider(BaseLLMProvider):
    def __init__(self, api_key, model='claude-haiku-4-5-20251001'):
        super().__init__(model, api_key)
        try: import anthropic; self._c = anthropic.Anthropic(api_key=api_key)
        except ImportError: raise ImportError("pip install anthropic")
        logger.info(f"Claude → {model}")
    def chat(self, prompt, max_tokens=2000, temperature=0.3):
        r = self._c.messages.create(model=self.model, max_tokens=max_tokens, temperature=temperature,
            messages=[{'role':'user','content':prompt}]); return r.content[0].text
    def chat_with_history(self, messages, max_tokens=2000, temperature=0.3):
        r = self._c.messages.create(model=self.model, max_tokens=max_tokens,
            temperature=temperature, messages=messages); return r.content[0].text
    def get_cost_estimate(self, i, o):
        r={'opus':(15,75),'sonnet':(3,15),'haiku':(0.25,1.25)}
        for k,(ip,op) in r.items():
            if k in self.model: return (i*ip+o*op)/1e6
        return (i*3+o*15)/1e6

class OpenAIProvider(_OAICompat):
    _P={'gpt-4o':(5,15),'gpt-4o-mini':(0.15,0.6),'gpt-4-turbo':(10,30),'gpt-3.5-turbo':(0.5,1.5)}
    def __init__(self, api_key, model='gpt-4o-mini'):
        super().__init__(model, api_key, 'https://api.openai.com/v1')
        logger.info(f"OpenAI → {model}")
    def get_cost_estimate(self, i, o):
        for k,(ip,op) in self._P.items():
            if k in self.model: return (i*ip+o*op)/1e6
        return (i*5+o*15)/1e6

class GeminiProvider(BaseLLMProvider):
    def __init__(self, api_key, model='gemini-1.5-flash'):
        super().__init__(model, api_key)
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self._g = genai; self._m = genai.GenerativeModel(model)
        except ImportError: raise ImportError("pip install google-generativeai")
        logger.info(f"Gemini → {model}")
    def chat(self, prompt, max_tokens=2000, temperature=0.3):
        cfg = self._g.types.GenerationConfig(max_output_tokens=max_tokens, temperature=temperature)
        return self._m.generate_content(prompt, generation_config=cfg).text
    def get_cost_estimate(self, i, o): return (i*0.35+o*1.05)/1e6

# ── Local providers ───────────────────────────────────────────────────────────
class OllamaProvider(_OAICompat):
    """Ollama local server. Setup: curl -fsSL https://ollama.ai/install.sh | sh && ollama pull llama3:8b"""
    def __init__(self, model='llama3:8b', base_url='http://localhost:11434'):
        super().__init__(model, 'ollama', f"{base_url.rstrip('/')}/v1")
        logger.info(f"Ollama → {model} @ {base_url}")

class LMStudioProvider(_OAICompat):
    """LM Studio local server. Load model in LM Studio, start Local Server."""
    def __init__(self, model='local-model', base_url='http://localhost:1234'):
        super().__init__(model, 'lmstudio', f"{base_url.rstrip('/')}/v1")
        logger.info(f"LM Studio → {model} @ {base_url}")

class LocalAPIProvider(_OAICompat):
    """Any OpenAI-compatible server (vLLM, text-gen-webui, etc.)"""
    def __init__(self, model, base_url, api_key='none'):
        super().__init__(model, api_key, base_url)
        logger.info(f"Local API → {model} @ {base_url}")

class HuggingFaceProvider(BaseLLMProvider):
    """Run HuggingFace Hub models locally. pip install transformers torch accelerate"""
    def __init__(self, model='microsoft/phi-2'):
        super().__init__(model)
        try:
            from transformers import pipeline
            logger.info(f"Loading HuggingFace: {model}…")
            self._pipe = pipeline('text-generation', model=model, device_map='auto', trust_remote_code=True)
            logger.info(f"HuggingFace → {model}")
        except ImportError: raise ImportError("pip install transformers torch accelerate")
    def chat(self, prompt, max_tokens=2000, temperature=0.3):
        out = self._pipe(prompt, max_new_tokens=max_tokens, temperature=temperature, do_sample=True)
        return out[0]['generated_text'][len(prompt):].strip()

class NullProvider(BaseLLMProvider):
    """No-op fallback. LLM features return empty strings instead of crashing."""
    def __init__(self):
        super().__init__('none')
        logger.warning("LLM not configured — AI features disabled. Add an API key to .env")
    def chat(self, *a, **k): return '[LLM not configured]'

# ── Factory ───────────────────────────────────────────────────────────────────
def _reachable(url, timeout=1.0):
    try:
        p = urlparse(url); h = p.hostname or 'localhost'; port = p.port or 80
        with socket.create_connection((h, port), timeout=timeout): return True
    except: return False

class LLMProvider:
    """
    Universal factory.  Usage everywhere in the codebase:
        llm = LLMProvider.create()
        reply = llm.chat("Analyze this signal...")

    Provider auto-detection priority:
        OPENROUTER_API_KEY → ANTHROPIC_API_KEY → OPENAI_API_KEY → GOOGLE_API_KEY
        → Ollama (localhost:11434) → LM Studio (localhost:1234) → LOCAL_API_URL → Null
    """

    @staticmethod
    def create(provider: str = None, model: str = None, api_key: str = None) -> BaseLLMProvider:
        p = (provider or os.getenv('LLM_PROVIDER', 'auto')).lower().strip()
        m = model    or os.getenv('LLM_MODEL', '')
        if p == 'auto': return LLMProvider._auto(m, api_key)
        return LLMProvider._named(p, m, api_key)

    @staticmethod
    def _auto(model, api_key):
        def k(env): return api_key or os.getenv(env, '')
        if k('OPENROUTER_API_KEY'):
            return OpenRouterProvider(k('OPENROUTER_API_KEY'), model or 'anthropic/claude-3-haiku')
        if k('ANTHROPIC_API_KEY'):
            return ClaudeProvider(k('ANTHROPIC_API_KEY'), model or 'claude-haiku-4-5-20251001')
        if k('OPENAI_API_KEY'):
            return OpenAIProvider(k('OPENAI_API_KEY'), model or 'gpt-4o-mini')
        if k('GOOGLE_API_KEY'):
            return GeminiProvider(k('GOOGLE_API_KEY'), model or 'gemini-1.5-flash')
        url = os.getenv('OLLAMA_URL','http://localhost:11434')
        if _reachable(url): return OllamaProvider(model or os.getenv('OLLAMA_MODEL','llama3:8b'), url)
        url = os.getenv('LMSTUDIO_URL','http://localhost:1234')
        if _reachable(url): return LMStudioProvider(model or os.getenv('LMSTUDIO_MODEL','local-model'), url)
        url = os.getenv('LOCAL_API_URL','')
        if url: return LocalAPIProvider(model or os.getenv('LOCAL_API_MODEL','local'), url, os.getenv('LOCAL_API_KEY','none'))
        return NullProvider()

    @staticmethod
    def _named(p, m, api_key):
        def k(env): return api_key or os.getenv(env,'')
        if p == 'openrouter': return OpenRouterProvider(k('OPENROUTER_API_KEY'), m or 'anthropic/claude-3-haiku')
        if p in ('claude','anthropic'): return ClaudeProvider(k('ANTHROPIC_API_KEY'), m or 'claude-haiku-4-5-20251001')
        if p in ('openai','gpt'): return OpenAIProvider(k('OPENAI_API_KEY'), m or 'gpt-4o-mini')
        if p in ('gemini','google'): return GeminiProvider(k('GOOGLE_API_KEY'), m or 'gemini-1.5-flash')
        if p == 'ollama': return OllamaProvider(m or os.getenv('OLLAMA_MODEL','llama3:8b'), os.getenv('OLLAMA_URL','http://localhost:11434'))
        if p in ('lmstudio','lm_studio'): return LMStudioProvider(m or os.getenv('LMSTUDIO_MODEL','local-model'), os.getenv('LMSTUDIO_URL','http://localhost:1234'))
        if p in ('local_api','custom'): return LocalAPIProvider(m or os.getenv('LOCAL_API_MODEL','local'), os.getenv('LOCAL_API_URL','http://localhost:8000'), os.getenv('LOCAL_API_KEY','none'))
        if p in ('huggingface','hf'): return HuggingFaceProvider(m or 'microsoft/phi-2')
        return NullProvider()

    @staticmethod
    def describe():
        return (
            "LLM providers: openrouter | claude | openai | gemini | ollama | lmstudio | local_api | huggingface | null\n"
            "Set LLM_PROVIDER and relevant API key / URL in .env — or use auto-detection."
        )
