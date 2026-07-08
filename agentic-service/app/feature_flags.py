"""Feature-flag enforcement as FastAPI dependencies.

The flags in ``app.config.Settings`` (``enable_rag``,
``enable_human_in_the_loop``, ``enable_multi_tenant_onboarding``) are
operational kill switches: features default ON, but an operator can flip
one to false (env var) and the feature's endpoints return 503 without a
redeploy.

Usage - gate a whole router::

    app.include_router(
        documents_router,
        dependencies=[require_flag("enable_rag")],
    )

or a single endpoint::

    @router.post("/tenants/{id}/onboarding/start",
                 dependencies=[require_flag("enable_multi_tenant_onboarding")])
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from app.config import Settings, get_settings

# Flags that may be gated. Guarding against typos at import time keeps a
# misspelled flag from silently gating nothing.
_KNOWN_FLAGS = frozenset(
    {"enable_rag", "enable_human_in_the_loop", "enable_multi_tenant_onboarding"}
)


def require_flag(flag_name: str):
    """Return a FastAPI dependency that 503s when ``flag_name`` is off.

    Raises ``ValueError`` immediately (import time) for unknown flags.
    """
    if flag_name not in _KNOWN_FLAGS:
        raise ValueError(
            f"unknown feature flag {flag_name!r} - known: {sorted(_KNOWN_FLAGS)}"
        )

    def _check(settings: Settings = Depends(get_settings)) -> None:
        if not getattr(settings, flag_name):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"feature disabled ({flag_name}=false)",
            )

    return Depends(_check)
