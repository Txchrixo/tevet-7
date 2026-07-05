"""OpenRouter adapter - aggregator (free models via :free suffix)."""

from __future__ import annotations

from app.agents.llm_adapters.base import BaseOpenAIAdapter


class OpenRouterAdapter(BaseOpenAIAdapter):
    """OpenRouter - aggregator, free models, rate-limited."""

    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
    DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
    DEFAULT_TIMEOUT = 20.0
