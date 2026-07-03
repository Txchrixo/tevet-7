"""FastAPI application entrypoint for Tevet-7.

Phase 0: This module exposes a minimal but real FastAPI app — health check,
root info, CORS, and lifespan logging. The real ``/chat`` router is imported
but returns HTTP 501 (see ``app/api/chat.py``).

Run locally with::

    uvicorn app.main:app --reload --port 8000

Phase 1 will wire in the real agent orchestrator and SSE streaming.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.chat import router as chat_router
from app.config import get_settings

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# In production we'd ship structured JSON logs (structlog / loguru). For Phase 0
# the standard logger is enough — uvicorn's access logs already give us timing.
# ─────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger("tevet7")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan
# FastAPI's recommended way to run startup/shutdown code. We use it for:
#   - startup: log version, env, validate required settings
#   - shutdown: log clean exit, flush Langfuse spans (Phase 1)
# We deliberately do NOT open the DB connection pool here — the engine is
# lazy-initialized on first use, and tests may want to override it.
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info(
        "Tevet-7 starting — version=%s env=%s llm_model=%s",
        __version__,
        settings.env,
        settings.llm_model,
    )
    if settings.openai_api_key in {"", "sk-replace-me"}:
        logger.warning(
            "OPENAI_API_KEY is not configured — /chat will fail in Phase 1. "
            "Set it in .env before enabling the chat router."
        )
    # TODO(Phase 1): initialise Langfuse client, warm up the LLM client,
    # pre-load schema.yaml into a per-tenant cache, etc.
    yield
    logger.info("Tevet-7 shutting down — version=%s", __version__)
    # TODO(Phase 1): await langfuse_client.flush() to ship pending traces.


# ─────────────────────────────────────────────────────────────────────────────
# App factory
# ─────────────────────────────────────────────────────────────────────────────
def create_app() -> FastAPI:
    """Build the FastAPI app. Kept as a function for testability."""
    settings = get_settings()

    app = FastAPI(
        title="Tevet-7",
        description=(
            "Configurable enterprise AI agent platform. "
            "First tenant: Drive Producteur (Producer Copilot).\n\n"
            "Phase 0: skeleton only — `/chat` returns HTTP 501. "
            "See `docs/architecture.md` for the full roadmap."
        ),
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — wide open in dev, locked down via CORS_ORIGINS in prod.
    origins = (
        ["*"] if settings.cors_origins == "*" else settings.cors_origins.split(",")
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    # Phase 1: the chat router will actually serve traffic.
    app.include_router(chat_router, prefix="/api", tags=["chat"])

    # ── Health & info ────────────────────────────────────────────────────────
    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        """Lightweight liveness probe. Does NOT touch the DB."""
        return {
            "status": "ok",
            "service": "tevet-7",
            "version": __version__,
        }

    @app.get("/", tags=["meta"])
    async def root() -> dict:
        """Tiny info payload so curling `/` is useful."""
        return {
            "name": "Tevet-7",
            "version": __version__,
            "phase": 0,
            "docs": "/docs",
            "architecture": "https://github.com/your-org/tevet-7/blob/main/agentic-service/docs/architecture.md",
            "endpoints": {
                "health": "/health",
                "chat (Phase 1)": "/api/chat",
            },
        }

    return app


# ASGI entrypoint used by `uvicorn app.main:app`
app = create_app()
