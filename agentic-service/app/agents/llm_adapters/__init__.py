"""LLM provider adapters - SOLID single-responsibility per provider.

Package structure:
  - ``base.py``       - BaseOpenAIAdapter + shared helpers + client cache
  - ``groq.py``       - GroqAdapter
  - ``deepseek.py``   - DeepSeekAdapter
  - ``openrouter.py`` - OpenRouterAdapter
  - ``gemini.py``     - GeminiAdapter
  - ``glm_bridge.py`` - GlmBridgeAdapter

Each adapter has ONE responsibility: its provider's configuration. All
OpenAI-protocol logic is shared via the base.
"""

from app.agents.llm_adapters.base import (
    BaseOpenAIAdapter,
    build_usage,
    extract_cache_metrics,
    parse_tool_calls,
    tool_calls_to_openai_dict,
)
from app.agents.llm_adapters.deepseek import DeepSeekAdapter
from app.agents.llm_adapters.gemini import GeminiAdapter
from app.agents.llm_adapters.glm_bridge import GlmBridgeAdapter
from app.agents.llm_adapters.groq import GroqAdapter
from app.agents.llm_adapters.openrouter import OpenRouterAdapter

__all__ = [
    "BaseOpenAIAdapter",
    "GroqAdapter",
    "DeepSeekAdapter",
    "OpenRouterAdapter",
    "GeminiAdapter",
    "GlmBridgeAdapter",
    "parse_tool_calls",
    "extract_cache_metrics",
    "tool_calls_to_openai_dict",
    "build_usage",
]
