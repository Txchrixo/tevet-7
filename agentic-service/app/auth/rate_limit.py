"""Sliding-window rate limiters (in-memory, per-process).

Two consumers:

- Auth endpoints: 5 attempts / minute / IP (brute-force protection).
  Module-level functions kept for backward compatibility with
  ``app.auth.routes`` and the existing tests.
- Chat endpoints: 120 requests / minute / tenant (LLM cost abuse
  protection). Both ``/api/chat`` and ``/api/chat/stream`` share ONE
  limiter instance so a tenant cannot double its budget by mixing the
  two endpoints.

The generic :class:`SlidingWindowRateLimiter` is the single implementation;
the auth helpers delegate to a module-level instance of it.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

logger = logging.getLogger("tevet7.rate_limit")


class SlidingWindowRateLimiter:
    """Sliding-window counter keyed by an arbitrary string (IP, tenant...).

    ``check(key)`` returns ``(allowed, retry_after_seconds)``. When allowed,
    the event is recorded; when denied, ``retry_after_seconds`` tells the
    caller what to put in the ``Retry-After`` header.

    In-memory and per-process by design: good enough for a single-instance
    deployment. A multi-instance deployment should move this behind Redis -
    the interface stays the same.
    """

    def __init__(self, max_events: int, window_seconds: float) -> None:
        if max_events < 1:
            raise ValueError("max_events must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._log: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> tuple[bool, float]:
        now = time.monotonic()
        log = self._log[key]
        cutoff = now - self.window_seconds
        while log and log[0] < cutoff:
            log.popleft()
        if len(log) >= self.max_events:
            retry_after = log[0] + self.window_seconds - now
            return False, max(0.1, retry_after)
        log.append(now)
        return True, 0.0

    def clear(self) -> None:
        self._log.clear()


# ── Auth: 5 attempts / minute / IP ───────────────────────────────────────────

_auth_limiter = SlidingWindowRateLimiter(max_events=5, window_seconds=60.0)

# ── Chat: 120 requests / minute / tenant (shared by /chat and /chat/stream) ──

chat_limiter = SlidingWindowRateLimiter(max_events=120, window_seconds=60.0)


def check_auth_rate_limit(ip: str) -> tuple[bool, float]:
    return _auth_limiter.check(ip)


def get_client_ip(request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def clear_auth_rate_limit() -> None:
    _auth_limiter.clear()
