"""GLM bridge adapter — GLM-4.6 via the Node.js glm-bridge mini-service.

The bridge exposes an OpenAI-compatible HTTP API on localhost:3030, so this
adapter extends ``BaseOpenAIAdapter`` and reuses all the shared protocol
logic. GLM is the PRIMARY provider — free, no geo-block, function-calling
capable via the Z.ai SDK.
"""

from __future__ import annotations

from app.agents.llm_adapters.base import BaseOpenAIAdapter


class GlmBridgeAdapter(BaseOpenAIAdapter):
    """GLM-4.6 via the local Node bridge (OpenAI-compatible HTTP)."""

    DEFAULT_BASE_URL = "http://localhost:3030/v1"
    DEFAULT_MODEL = "glm-4.6"
    DEFAULT_TIMEOUT = 30.0  # GLM via the bridge adds ~50ms hop

    def __init__(self, name: str = "glm-4.6", bridge_url: str | None = None) -> None:
        super().__init__(
            api_key="glm-bridge-no-key-needed",
            base_url=bridge_url or self.DEFAULT_BASE_URL,
            model=self.DEFAULT_MODEL,
            name=name,
            timeout=self.DEFAULT_TIMEOUT,
        )
