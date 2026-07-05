"""Gemini adapter — Google AI Studio (free tier, OpenAI-compatible endpoint)."""

from __future__ import annotations

from app.agents.llm_adapters.base import BaseOpenAIAdapter


class GeminiAdapter(BaseOpenAIAdapter):
    """Gemini — Google AI Studio free tier, OpenAI-compatible endpoint."""

    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
    DEFAULT_MODEL = "gemini-2.0-flash-001"
    DEFAULT_TIMEOUT = 25.0
