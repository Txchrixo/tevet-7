"""Token-cost estimation.

Phase 1 has no real LLM (the orchestrator returns *simulated* token counts),
but we still compute a cost estimate per trace so the inspector UI and the
``/api/traces`` list can show "$0.0003 per request" alongside latency. This
becomes meaningful in Phase 2 when we plug a real LLM in.

The pricing table below is a snapshot of public list prices (USD per 1K
tokens) as of mid-2024. **It is not authoritative** — production should read
from a config file or a pricing API. For the demo it's a constant table.
"""

from __future__ import annotations

from app.config import get_settings

# Pricing table — USD per 1K tokens.
#   (input_per_1k, output_per_1k)
#
# Source: public vendor list prices. Update when prices change.
_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.000150, 0.000600),
    "gpt-4-turbo": (0.010, 0.030),
    "gpt-4": (0.030, 0.060),
    "gpt-3.5-turbo": (0.000500, 0.001500),
    # Anthropic
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-5-sonnet-20240620": (0.003, 0.015),
    "claude-3-haiku": (0.000250, 0.001250),
    "claude-3-opus": (0.015, 0.075),
    # Fallback (unknown model) — use gpt-4o-mini pricing as a conservative default
    "_default": (0.000150, 0.000600),
}


def compute_cost(tokens_in: int, tokens_out: int, model: str | None = None) -> float:
    """Return the estimated USD cost for ``tokens_in`` + ``tokens_out`` on ``model``.

    If ``model`` is None, falls back to ``Settings.llm_model`` (default
    ``gpt-4o-mini``). Unknown models fall back to the ``_default`` pricing
    row so the cost is never zero (which would hide runaway usage).
    """
    if model is None:
        model = get_settings().llm_model
    pin, pout = _PRICING.get(model, _PRICING["_default"])
    return round((tokens_in / 1000.0) * pin + (tokens_out / 1000.0) * pout, 6)
