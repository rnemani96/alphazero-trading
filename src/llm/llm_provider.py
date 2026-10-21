"""
src/llm/llm_provider.py
═══════════════════════
Re-export of Universal LLMProvider from src/agents/llm_provider.py.
Ensures both `from src.llm.llm_provider import LLMProvider` and
`from src.agents.llm_provider import LLMProvider` work seamlessly.
"""

from src.agents.llm_provider import LLMProvider

__all__ = ["LLMProvider"]
