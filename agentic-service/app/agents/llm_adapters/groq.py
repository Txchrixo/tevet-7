"""Groq adapter — Groq Cloud (Llama models, fast inference)."""

from __future__ import annotations

from app.agents.llm_adapters.base import BaseOpenAIAdapter


class GroqAdapter(BaseOpenAIAdapter):
    """Groq Cloud — Llama models, 14k req/day free, 500 tok/s.

    NOTE: geo-blocked from Hong Kong (sandbox IP). Circuit-breaks fast.
    """

    DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
    DEFAULT_MODEL = "llama-3.3-70b-versatile"
    DEFAULT_TIMEOUT = 20.0
