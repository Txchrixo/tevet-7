"""DeepSeek adapter - DeepSeek direct API (paid, high quality, cheap)."""

from __future__ import annotations

from app.agents.llm_adapters.base import BaseOpenAIAdapter


class DeepSeekAdapter(BaseOpenAIAdapter):
    """DeepSeek direct - paid but cheap, function calling, prompt caching."""

    DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
    DEFAULT_MODEL = "deepseek-chat"
    DEFAULT_TIMEOUT = 20.0
