"""ProviderFactory — builds the LLM provider chain from config (cached).

Translates ``Settings`` into ``list[LLMProvider]``. The chain is built in
priority order: GLM (via bridge) → DeepSeek → OpenRouter → Gemini → Groq.
Cached globally (singleton clients for perf).
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.llm_provider import LLMProvider

logger = logging.getLogger("tevet7.provider_factory")

_cached_providers: list[LLMProvider] | None = None
_cached_settings_sig: str | None = None


def _settings_signature(settings: Any) -> str:
    parts = [
        settings.groq_api_key, settings.groq_model,
        settings.deepseek_api_key, settings.deepseek_base_url, settings.deepseek_model,
        settings.openai_api_key, settings.llm_base_url, settings.llm_fallback_models,
        settings.gemini_api_key, settings.gemini_base_url, settings.gemini_model,
    ]
    return "|".join(str(p) for p in parts)


def build_providers(settings: Any) -> list[LLMProvider] | None:
    """Build the provider chain from settings. Cached globally."""
    global _cached_providers, _cached_settings_sig
    sig = _settings_signature(settings)
    if _cached_settings_sig == sig and _cached_providers is not None:
        return _cached_providers

    from app.agents.llm_adapters import (
        DeepSeekAdapter,
        GeminiAdapter,
        GlmBridgeAdapter,
        GroqAdapter,
        OpenRouterAdapter,
    )

    providers: list[LLMProvider] = []

    # 1. GLM via the Node bridge — PRIMARY (free, no geo-block, sandbox SDK).
    providers.append(GlmBridgeAdapter(name="glm-4.6"))

    # 2. DeepSeek direct — backup.
    if settings.deepseek_api_key:
        providers.append(DeepSeekAdapter(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            name=f"deepseek/{settings.deepseek_model}",
        ))

    # 3. OpenRouter — tertiary (free models).
    if settings.openai_api_key and settings.openai_api_key != "sk-replace-me":
        or_models = [
            m.strip() for m in settings.llm_fallback_models.split(",") if m.strip()
        ]
        for m in or_models:
            providers.append(OpenRouterAdapter(
                api_key=settings.openai_api_key,
                base_url=settings.llm_base_url,
                model=m,
                name=f"openrouter/{m}",
            ))

    # 4. Gemini — last resort.
    if settings.gemini_api_key:
        providers.append(GeminiAdapter(
            api_key=settings.gemini_api_key,
            base_url=settings.gemini_base_url,
            model=settings.gemini_model,
            name=f"gemini/{settings.gemini_model}",
        ))

    # 5. Groq — bonus (geo-blocked from HK, circuit-breaks fast).
    if settings.groq_api_key:
        providers.append(GroqAdapter(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            name=f"groq/{settings.groq_model}",
        ))

    if not providers:
        logger.warning("No LLM providers configured — using rule-based only")
        _cached_providers = None
    else:
        logger.info(
            "ProviderFactory built %d providers: %s",
            len(providers), ", ".join(p.name for p in providers),
        )
        _cached_providers = providers
    _cached_settings_sig = sig
    return _cached_providers


def clear_cache() -> None:
    """Clear the provider cache (for tests)."""
    global _cached_providers, _cached_settings_sig
    _cached_providers = None
    _cached_settings_sig = None
