"""Application configuration via pydantic-settings.

All environment variables are read through this module — never call
``os.getenv`` directly elsewhere. This gives us:

- A single source of truth (this file ↔ ``.env.example``).
- Type validation (e.g. ``TOKEN_QUOTA_PER_TENANT_PER_DAY`` is an int).
- Easy overriding in tests via ``get_settings.cache_clear()`` + env injection.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed settings for Tevet-7.

    Every field here has a matching entry in ``.env.example``. Keep them
    in sync when adding new variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # tolerate unknown env vars (e.g. PATH injected by IDEs)
    )

    # ── Database ─────────────────────────────────────────────────────────────
    # Phase 1 uses an in-process SQLite database (no Postgres needed) so the
    # service runs without external infrastructure. The URL points to a file
    # `dev.db` in the working directory; `init_db()` (see app/db_seed.py)
    # creates and seeds it on startup.
    #
    # NOTE: a sibling Next.js project may export a `DATABASE_URL` env var of
    # its own (e.g. `file:/path/to/custom.db`). The model_validator below
    # ignores any value that is not a valid SQLAlchemy URL so the SQLite
    # default takes over.
    database_url: str = Field(
        default="sqlite+aiosqlite:///./dev.db",
        description="Async SQLAlchemy URL for the tenant business database (SQLite in Phase 1).",
    )

    @field_validator("database_url", mode="after")
    @classmethod
    def _coerce_sqlite_default(cls, v: str) -> str:
        """If DATABASE_URL is not a valid SQLAlchemy URL (e.g. the Next.js
        project's ``file:/...``), fall back to the in-process SQLite default.
        """
        if not v or not any(
            v.startswith(scheme)
            for scheme in (
                "sqlite+aiosqlite:///",
                "sqlite:///",
                "postgresql+asyncpg://",
                "postgresql://",
                "mysql+aiomysql://",
            )
        ):
            return "sqlite+aiosqlite:///./dev.db"
        return v

    # ── LLM ──────────────────────────────────────────────────────────────────
    # Provider-agnostic: works with OpenAI, DeepSeek, OpenRouter, Groq,
    # Mistral, any OpenAI-compatible endpoint. Just change base_url + key + model.
    openai_api_key: str = Field(default="sk-replace-me", description="LLM API key (works with any OpenAI-compatible provider).")
    llm_model: str = Field(default="gpt-4o-mini", description="Default chat model (e.g. gpt-4o-mini, deepseek-chat, meta-llama/llama-3.3-70b-instruct).")
    llm_base_url: str = Field(
        default="",
        description="OpenAI-compatible base URL. Empty = OpenAI default. "
        "Examples: https://openrouter.ai/api/v1, https://api.deepseek.com, "
        "https://api.groq.com/openai/v1, https://api.mistral.ai/v1",
    )
    embedding_model: str = Field(
        default="text-embedding-3-small", description="Default embedding model for RAG."
    )

    # ── Langfuse ─────────────────────────────────────────────────────────────
    # Tracer backend. When BOTH ``langfuse_public_key`` and
    # ``langfuse_secret_key`` are set to non-placeholder values, the tracing
    # factory returns a ``LangfuseTracer`` (ships events to Langfuse in
    # addition to the local SQLite ``traces`` table). When either is None /
    # the placeholder, the factory falls back to ``LocalTracer`` only —
    # this is the dev-mode default. See ``app/tracing/factory.py``.
    langfuse_public_key: str | None = Field(
        default=None,
        description="Langfuse public key. None = use LocalTracer only.",
    )
    langfuse_secret_key: str | None = Field(
        default=None,
        description="Langfuse secret key. None = use LocalTracer only.",
    )
    langfuse_host: str | None = Field(
        default=None,
        description=(
            "Langfuse host URL. None = Langfuse Cloud "
            "(https://cloud.langfuse.com). Set to a self-hosted URL in "
            "production if you run your own Langfuse instance."
        ),
    )

    # ── Drive Producteur connector (dev fallback) ────────────────────────────
    dp_api_base_url: str = Field(default="https://api.drive-producteur.example.com/v1")
    dp_api_token: str = Field(default="replace-me")

    # ── Auth ─────────────────────────────────────────────────────────────────
    jwt_secret: str = Field(default="replace-me-with-openssl-rand-base64-32")
    jwt_algorithm: str = Field(default="HS256")

    # ── Demo reset cron (Phase 6c) ────────────────────────────────────────────
    demo_reset_enabled: bool = Field(
        default=True,
        description="Enable the demo tenant reset cron (every 24h).",
    )
    demo_reset_interval_seconds: int = Field(
        default=86400,
        description="Demo reset interval in seconds (default 24h).",
    )

    # ── Quotas ───────────────────────────────────────────────────────────────
    token_quota_per_tenant_per_day: int = Field(
        default=200_000,
        description="Hard cap on tokens consumed per tenant per UTC day.",
    )

    # ── Feature flags (phase gates) ──────────────────────────────────────────
    enable_rag: bool = Field(default=False)
    enable_human_in_the_loop: bool = Field(default=False)
    enable_multi_tenant_onboarding: bool = Field(default=False)

    # ── Runtime ──────────────────────────────────────────────────────────────
    env: Literal["development", "staging", "production"] = Field(default="development")
    log_level: str = Field(default="INFO")
    cors_origins: str = Field(
        default="*",
        description="Comma-separated list of allowed origins, or '*' for all.",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance.

    Cached because pydantic-settings re-reads the env file on every
    instantiation — we don't want that on every request. Tests can reset the
    cache with ``get_settings.cache_clear()``.
    """
    return Settings()
