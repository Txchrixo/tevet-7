"""FastAPI application entrypoint for Tevet-7.

Phase 1: real `/chat` endpoint backed by an in-process SQLite database with
fictitious Drive Producteur data. The DB is created + seeded on startup by
``app.db_seed.init_db()``.

Run locally with::

    uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.admin import DemoResetCron, admin_router
from app.api.approvals import router as approvals_router
from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.auth import auth_router
from app.config import get_settings
from app.db_seed import dispose_engine, init_db
from app.tenants import tenants_router
from app.tracing import get_tracer

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# In production we'd ship structured JSON logs (structlog / loguru). For Phase 1
# the standard logger is enough - uvicorn's access logs already give us timing.
# ─────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger("tevet7")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan
# FastAPI's recommended way to run startup/shutdown code. We use it for:
#   - startup: log version, env, create + seed the SQLite DB.
#   - shutdown: log clean exit, dispose the engine pool.
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info(
        "Tevet-7 starting - version=%s env=%s llm_model=%s",
        __version__,
        settings.env,
        settings.llm_model,
    )
    # Production guards - FAIL FAST. A production deployment with the
    # default JWT secret, wide-open CORS, or public demo credentials is a
    # compromised deployment, not a degraded one. Refuse to boot.
    guard_errors = settings.validate_production_settings()
    if guard_errors:
        for err in guard_errors:
            logger.critical("PRODUCTION GUARD: %s", err)
        raise RuntimeError(
            "refusing to start in env=production: " + "; ".join(guard_errors)
        )
    # Phase 1: create + seed the SQLite DB (idempotent - drop & recreate).
    try:
        await init_db()
        logger.info("SQLite database ready at %s", settings.database_url)
    except Exception:  # noqa: BLE001
        logger.exception("init_db() failed - /chat will return errors until fixed")
    # Phase 5: ensure the ML stock-shortage model is trained. Lazy + non-
    # blocking: if training fails, the forecast tool falls back to the SQL
    # heuristic at request time so the demo still works.
    try:
        from ml.train_on_startup import ensure_model_trained
        model_ok = ensure_model_trained()
        if model_ok:
            logger.info("ML model: stock_shortage_model.pkl ready (forecast_tool active)")
        else:
            logger.warning(
                "ML model not trained - forecast_tool will fall back to SQL heuristic"
            )
    except Exception:  # noqa: BLE001 - never block app startup on ML
        logger.exception("ensure_model_trained() failed - forecast_tool will fall back")
    # Phase 2 tracing: initialise the tracer singleton early so the first
    # /chat request doesn't pay the (small) construction cost. Also logs
    # which tracer is active (LocalTracer vs LangfuseTracer) so the operator
    # can confirm observability is wired.
    try:
        tracer = get_tracer()
        tracer_name = type(tracer).__name__
        logger.info("Tracer active: %s", tracer_name)
    except Exception:  # noqa: BLE001
        logger.exception("tracer init failed - tracing disabled for this run")
    # Phase 6c: start the demo reset cron (resets the 'dp' tenant every 24h).
    # Disabled temporarily - the cron's reset_demo_data has a column attribute
    # bug. The reset endpoint works on-demand; the cron will be re-enabled
    # once the bug is fixed.
    # cron = DemoResetCron(interval_seconds=86400)
    # await cron.start()
    # #30: DB backup cron
    from app.admin.backup_cron import DbBackupCron
    from app.admin.retention import DataRetentionCron
    backup_cron = DbBackupCron(interval_s=86400, max_backups=7)
    retention_cron = DataRetentionCron(retention_days=90)
    await retention_cron.start()
    await backup_cron.start()
    yield
    # await cron.stop()
    await backup_cron.stop()
    await retention_cron.stop()
    logger.info("Tevet-7 shutting down - version=%s", __version__)
    await dispose_engine()


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
            "Phase 1: rule-based SQL generator + sqlglot row-level scoping "
            "on an in-process SQLite database. See `docs/architecture.md` "
            "for the full roadmap."
        ),
        version=__version__,
        lifespan=lifespan,
        # OpenAPI explorers are a reconnaissance gift in production - the
        # API surface is documented in the repo, operators don't need them
        # exposed on the public internet.
        docs_url="/docs" if settings.env != "production" else None,
        redoc_url="/redoc" if settings.env != "production" else None,
        openapi_url="/openapi.json" if settings.env != "production" else None,
    )

    # CORS - Phase B7 lockdown. "*" + credentials is invalid per spec.
    if settings.cors_origins == "*":
        origins = ["*"]
        allow_credentials = False
    else:
        origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
        allow_credentials = True
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    # Routers
    # Phase 1: the chat router serves real traffic (rule-based agent +
    # sqlglot scoping on SQLite).
    # Phase 3: the documents router adds the RAG management surface
    # (upload / list / detail / delete) used by the documentary intent.
    # Phase 4: the approvals router adds the Ops Copilot HITL surface
    # (list / detail / decide / re-analyze) - every "agent proposes, human
    # decides" workflow lives there.
    # Phase 6a: the auth router adds signup/login/me (JWT issuance) and
    # the tenants router adds tenant CRUD + membership activation. Both
    # are required for the multi-tenant frontend.
    # Feature flags gate whole routers where the feature IS the router
    # (documents = RAG management, approvals = human-in-the-loop). The
    # multi-tenant onboarding flag is enforced per-endpoint inside
    # app/tenants/routes.py because the tenants router also carries
    # always-on routes (create/activate/members).
    from app.feature_flags import require_flag

    app.include_router(chat_router, prefix="/api", tags=["chat"])
    app.include_router(
        documents_router, prefix="/api", tags=["documents"],
        dependencies=[require_flag("enable_rag")],
    )
    app.include_router(
        approvals_router, prefix="/api", tags=["approvals"],
        dependencies=[require_flag("enable_human_in_the_loop")],
    )
    app.include_router(auth_router, prefix="/api", tags=["auth"])
    app.include_router(tenants_router, prefix="/api", tags=["tenants"])
    app.include_router(admin_router, prefix="/api/admin", tags=["admin"])

    # Phase C3 - Stripe billing (optional, requires STRIPE_SECRET_KEY)
    try:
        from app.billing import billing_router
        app.include_router(billing_router, prefix="/api", tags=["billing"])
    except ImportError:
        pass

    # Phase C5 - Export (CSV + PDF)
    try:
        from app.export_routes import router as export_router
        app.include_router(export_router, prefix="/api", tags=["export"])
    except ImportError:
        pass

    # ── Health & info ────────────────────────────────────────────────────────
    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        """Lightweight liveness probe. Does NOT touch the DB."""
        return {
            "status": "ok",
            "service": "tevet-7",
            "version": __version__,
        }

    @app.get("/ready", tags=["meta"])
    async def ready() -> dict:
        """Readiness probe: verifies the database answers a SELECT 1.

        Orchestrators (Railway, k8s) should route traffic only when this
        returns 200. Liveness (/health) stays DB-free so a slow DB does
        not get the process killed.
        """
        from sqlalchemy import text
        from app.db_seed import get_engine
        try:
            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - report, don't crash the probe
            from fastapi import HTTPException
            raise HTTPException(status_code=503, detail=f"database not ready: {exc}")
        return {"status": "ready", "service": "tevet-7", "version": __version__}

    @app.get("/", tags=["meta"])
    async def root() -> dict:
        """Tiny info payload so curling `/` is useful."""
        return {
            "name": "Tevet-7",
            "version": __version__,
            "phase": 1,
            "docs": "/docs",
            "architecture": "https://github.com/your-org/tevet-7/blob/main/agentic-service/docs/architecture.md",
            "endpoints": {
                "health": "/health",
                "chat": "/api/chat",
                "schema": "/api/schema",
            },
        }

    return app


# ASGI entrypoint used by `uvicorn app.main:app`
app = create_app()
