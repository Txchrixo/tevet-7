"""Tests for Phase A3 — Conversation memory + intent detection fix."""

from __future__ import annotations

import sys
from pathlib import Path

_AGENTIC = Path(__file__).resolve().parent.parent
if str(_AGENTIC) not in sys.path:
    sys.path.insert(0, str(_AGENTIC))

import pytest

from app.agents.orchestrator import classify_question


# ─────────────────────────────────────────────────────────────────────────────
# Intent detection fix (broader analytical signals)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("question,expected", [
    ("mes ventes", "weekly_sales"),
    ("top produits", "top_products"),
    ("stock", "stock_shortfall"),
    ("commandes", "weekly_sales"),
    ("argent", "net_revenue"),
    ("juin", "weekly_sales"),
    ("que deviennent mes commandes", "weekly_sales"),
    ("dis-moi ce qui se vend", "weekly_sales"),
    ("montre-moi mes stats", "weekly_sales"),
    ("Quels sont mes 5 produits les plus vendus ce mois-ci ?", "top_products"),
    ("Combien j'ai gagné en juin ?", "net_revenue"),
    ("Ventes de la semaine ?", "weekly_sales"),
    ("Quels produits risquent de me manquer ?", "stock_shortfall"),
    ("Comment fonctionnent les commissions ?", "documentary"),
])
def test_classify_question_broader_signals(question: str, expected: str) -> None:
    """The classifier catches broader analytical signals (not just 'unknown')."""
    result = classify_question(question, "producer")
    assert result == expected, f"expected {expected}, got {result} for: {question!r}"


def test_classify_question_greeting_is_unknown() -> None:
    """Greetings correctly classify as 'unknown' (handled by greeting guard)."""
    assert classify_question("salut", "producer") == "unknown"
    assert classify_question("hey", "producer") == "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Conversation memory (system prompt rule)
# ─────────────────────────────────────────────────────────────────────────────


def test_system_prompt_includes_conversation_memory_rule() -> None:
    """The system prompt must mention conversation memory / follow-ups."""
    from unittest.mock import MagicMock
    from app.agents.llm_orchestrator import LLMOrchestrator
    orch = LLMOrchestrator(
        sql_tool=MagicMock(scope_column="producer_id", scope_value=42),
        role="producer",
        producer_id=42,
        schema={"tables": []},
        router=MagicMock(),
    )
    prompt = orch._build_system_prompt()
    assert "CONVERSATION MEMORY" in prompt
    assert "mois dernier" in prompt.lower() or "follow-up" in prompt.lower()


def test_history_window_is_10_messages() -> None:
    """The orchestrator keeps last 10 messages (5 turns) for context."""
    import inspect
    from app.agents.llm_orchestrator import LLMOrchestrator
    src = inspect.getsource(LLMOrchestrator.run)
    assert "history[-10:]" in src, "run() must use history[-10:] (10-message window)"
