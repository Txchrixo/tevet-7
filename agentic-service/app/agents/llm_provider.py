"""LLMProvider - universal abstraction over LLM SDKs.

Protocol (interface) that every provider adapter implements. The ModelRouter
is agnostic - it calls ``provider.chat(...)`` and gets back a normalized
``ChatResult``. Each provider owns its SDK/HTTP wiring.

Data shapes:
  - ``ChatResult``: content, tool_calls (normalized), usage, model, stream.
  - ``ToolCall``: id, name, arguments (dict - already parsed).
  - ``Usage``: prompt/completion/cache_hit/cache_miss tokens.
  - ``StreamDelta``: content + usage (on final chunk).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, runtime_checkable


@dataclass
class ToolCall:
    """A single function/tool call requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    """Token usage (normalized across providers)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0


@dataclass
class ChatResult:
    """Normalized LLM response.

    For non-streaming: ``content`` + ``tool_calls`` + ``usage`` are set.
    For streaming: ``stream`` is an async iterator yielding ``StreamDelta``.
    """

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    stream: AsyncIterator["StreamDelta"] | None = None
    raw: Any = None  # the raw provider response (for cache serialization)


@dataclass
class StreamDelta:
    """One chunk from a streaming response."""

    content: str = ""
    usage: Usage | None = None  # set on the final chunk


@runtime_checkable
class LLMProvider(Protocol):
    """Universal LLM provider interface.

    Each provider implements ``chat()``. The ModelRouter calls providers in
    order; the first success wins. Providers raise on failure (router
    catches + moves to the next).
    """

    name: str

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict | None = None,
        temperature: float = 0.0,
        max_tokens: int = 800,
        stream: bool = False,
        **kwargs: Any,
    ) -> ChatResult:
        """Call the LLM. Raise on any failure (router catches)."""
        ...
