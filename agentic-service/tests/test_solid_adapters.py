"""Tests for the SOLID LLM adapter architecture."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

_AGENTIC = Path(__file__).resolve().parent.parent
if str(_AGENTIC) not in sys.path:
    sys.path.insert(0, str(_AGENTIC))

import pytest

from app.agents.llm_adapters import (
    BaseOpenAIAdapter,
    DeepSeekAdapter,
    GeminiAdapter,
    GlmBridgeAdapter,
    GroqAdapter,
    OpenRouterAdapter,
    build_usage,
    extract_cache_metrics,
    parse_tool_calls,
    tool_calls_to_openai_dict,
)
from app.agents.llm_provider import ChatResult, ToolCall, Usage
from app.agents.model_router import ModelRouter, _CircuitState
from app.agents.provider_factory import build_providers, clear_cache


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────


def test_parse_tool_calls_extracts_name_and_args() -> None:
    msg = MagicMock()
    tc = MagicMock()
    tc.id = "call_123"
    tc.function = MagicMock()
    tc.function.name = "execute_sql_query"
    tc.function.arguments = '{"sql": "SELECT 1"}'
    msg.tool_calls = [tc]
    result = parse_tool_calls(msg)
    assert len(result) == 1
    assert result[0].id == "call_123"
    assert result[0].name == "execute_sql_query"
    assert result[0].arguments == {"sql": "SELECT 1"}


def test_parse_tool_calls_empty() -> None:
    msg = MagicMock()
    msg.tool_calls = None
    assert parse_tool_calls(msg) == []


def test_extract_cache_metrics_deepseek_native() -> None:
    usage = MagicMock()
    usage.prompt_cache_hit_tokens = 500
    usage.prompt_cache_miss_tokens = 200
    usage.prompt_tokens = 700
    hit, miss = extract_cache_metrics(usage)
    assert hit == 500
    assert miss == 200


def test_extract_cache_metrics_none() -> None:
    assert extract_cache_metrics(None) == (0, 0)


def test_tool_calls_to_openai_dict_round_trip() -> None:
    original = [
        ToolCall(id="call_1", name="execute_sql_query", arguments={"sql": "SELECT 1"}),
        ToolCall(id="call_2", name="search_documents", arguments={"query": "test"}),
    ]
    dicts = tool_calls_to_openai_dict(original)
    assert len(dicts) == 2
    assert dicts[0]["id"] == "call_1"
    assert dicts[0]["type"] == "function"
    assert dicts[0]["function"]["name"] == "execute_sql_query"
    assert json.loads(dicts[0]["function"]["arguments"]) == {"sql": "SELECT 1"}


def test_build_usage_normalizes() -> None:
    usage_obj = MagicMock()
    usage_obj.prompt_tokens = 1000
    usage_obj.completion_tokens = 200
    usage_obj.prompt_cache_hit_tokens = 500
    usage_obj.prompt_cache_miss_tokens = 500
    usage_obj.prompt_tokens_details = None
    usage = build_usage(usage_obj)
    assert usage.prompt_tokens == 1000
    assert usage.completion_tokens == 200
    assert usage.cache_hit_tokens == 500


# ─────────────────────────────────────────────────────────────────────────────
# Provider adapter defaults
# ─────────────────────────────────────────────────────────────────────────────


def test_groq_adapter_defaults() -> None:
    adapter = GroqAdapter(api_key="gsk-test")
    assert "groq.com" in adapter._base_url
    assert "llama" in adapter._model


def test_deepseek_adapter_defaults() -> None:
    adapter = DeepSeekAdapter(api_key="sk-test")
    assert "deepseek.com" in adapter._base_url
    assert adapter._model == "deepseek-chat"


def test_openrouter_adapter_defaults() -> None:
    adapter = OpenRouterAdapter(api_key="sk-or-test")
    assert "openrouter.ai" in adapter._base_url
    assert ":free" in adapter._model


def test_gemini_adapter_defaults() -> None:
    adapter = GeminiAdapter(api_key="test-key")
    assert "googleapis.com" in adapter._base_url
    assert "gemini" in adapter._model


def test_glm_bridge_adapter_defaults() -> None:
    adapter = GlmBridgeAdapter()
    assert "localhost:3030" in adapter._base_url
    assert adapter._model == "glm-4.6"
    assert adapter.name == "glm-4.6"


def test_adapter_custom_name_overrides_default() -> None:
    adapter = DeepSeekAdapter(api_key="sk-test", name="deepseek/custom")
    assert adapter.name == "deepseek/custom"


# ─────────────────────────────────────────────────────────────────────────────
# Client cache (perf)
# ─────────────────────────────────────────────────────────────────────────────


def test_client_cache_reuses_same_client() -> None:
    from app.agents.llm_adapters.base import _get_client
    import app.agents.llm_adapters.base as base_mod
    base_mod._client_cache.clear()
    c1 = _get_client("sk-test", "https://api.example.com/v1", 20.0)
    c2 = _get_client("sk-test", "https://api.example.com/v1", 20.0)
    assert c1 is c2


def test_client_cache_different_keys_different_clients() -> None:
    from app.agents.llm_adapters.base import _get_client
    import app.agents.llm_adapters.base as base_mod
    base_mod._client_cache.clear()
    c1 = _get_client("sk-key-1", "https://api.example.com/v1", 20.0)
    c2 = _get_client("sk-key-2", "https://api.example.com/v1", 20.0)
    assert c1 is not c2


# ─────────────────────────────────────────────────────────────────────────────
# CircuitState
# ─────────────────────────────────────────────────────────────────────────────


def test_circuit_state_starts_closed() -> None:
    cs = _CircuitState()
    assert not cs.is_open(0.0)
    assert cs.consecutive_failures == 0


def test_circuit_state_opens_after_threshold() -> None:
    cs = _CircuitState()
    cs.consecutive_failures = 3
    cs.open_until = 100.0
    assert cs.is_open(50.0)
    assert not cs.is_open(150.0)


def test_circuit_state_record_success_resets() -> None:
    cs = _CircuitState()
    cs.consecutive_failures = 2
    cs.open_until = 100.0
    cs.record_success()
    assert cs.consecutive_failures == 0
    assert cs.open_until == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# ProviderFactory
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_factory_cache():
    clear_cache()
    yield
    clear_cache()


def _mock_settings(**overrides) -> object:
    defaults = {
        "groq_api_key": "",
        "groq_model": "llama-3.3-70b-versatile",
        "deepseek_api_key": "",
        "deepseek_base_url": "https://api.deepseek.com/v1",
        "deepseek_model": "deepseek-chat",
        "openai_api_key": "sk-replace-me",
        "llm_base_url": "https://openrouter.ai/api/v1",
        "llm_fallback_models": "meta-llama/llama-3.3-70b-instruct:free",
        "gemini_api_key": "",
        "gemini_base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini_model": "gemini-2.0-flash-001",
    }
    defaults.update(overrides)
    return type("Settings", (), defaults)()


def test_factory_returns_glm_always() -> None:
    """GLM is always present (no API key needed — uses the sandbox SDK)."""
    settings = _mock_settings()
    providers = build_providers(settings)
    assert providers is not None
    assert len(providers) == 1
    assert providers[0].name == "glm-4.6"


def test_factory_includes_deepseek_when_key_set() -> None:
    settings = _mock_settings(deepseek_api_key="sk-deepseek-test")
    providers = build_providers(settings)
    names = [p.name for p in providers]
    assert "deepseek/deepseek-chat" in names


def test_factory_priority_order() -> None:
    settings = _mock_settings(
        deepseek_api_key="sk-ds",
        openai_api_key="sk-or",
        gemini_api_key="gem",
        groq_api_key="gsk",
    )
    providers = build_providers(settings)
    names = [p.name for p in providers]
    assert names[0] == "glm-4.6"
    assert names[-1] == "groq/llama-3.3-70b-versatile"


def test_factory_caches_result() -> None:
    settings = _mock_settings(deepseek_api_key="sk-ds")
    providers1 = build_providers(settings)
    providers2 = build_providers(settings)
    assert providers1 is providers2


def test_factory_skips_placeholder_openai_key() -> None:
    settings = _mock_settings(openai_api_key="sk-replace-me")
    providers = build_providers(settings)
    names = [p.name for p in providers]
    assert not any("openrouter" in n for n in names)
