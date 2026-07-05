"""Rate limiter for auth endpoints (brute-force protection).

5 attempts per minute per IP. Sliding window in-memory.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

logger = logging.getLogger("tevet7.auth_rate_limit")

_AUTH_WINDOW_S = 60.0
_AUTH_MAX_ATTEMPTS = 5
_ip_attempt_log: dict[str, deque[float]] = defaultdict(deque)


def check_auth_rate_limit(ip: str) -> tuple[bool, float]:
    now = time.monotonic()
    log = _ip_attempt_log[ip]
    cutoff = now - _AUTH_WINDOW_S
    while log and log[0] < cutoff:
        log.popleft()
    if len(log) >= _AUTH_MAX_ATTEMPTS:
        retry_after = log[0] + _AUTH_WINDOW_S - now
        return False, max(0.1, retry_after)
    log.append(now)
    return True, 0.0


def get_client_ip(request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def clear_auth_rate_limit() -> None:
    _ip_attempt_log.clear()
