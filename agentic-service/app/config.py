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

from pydantic import Field
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

    # ── Database (control plane) ─────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://tevet7:tevet7_dev_password@localhost:5432/tevet7",
        description="Async SQLAlchemy URL for the control-plane DB.",
    )

    # ── LLM ──────────────────────────────────────────────────────────────────
    openai_api_key: str = Field(default="sk-replace-me", description="OpenAI API key.")
    llm_model: str = Field(default="gpt-4o-mini", description="Default chat model.")
    embedding_model: str = Field(
        default="text-embedding-3-small", description="Default embedding model for RAG."
    )

    # ── Langfuse ─────────────────────────────────────────────────────────────
    langfuse_public_key: str = Field(default="pk-lf-replace-me")
    langfuse_secret_key: str = Field(default="sk-lf-replace-me")
    langfuse_host: str = Field(default="http://localhost:3001")

    # ── Drive Producteur connector (dev fallback) ────────────────────────────
    dp_api_base_url: str = Field(default="https://api.drive-producteur.example.com/v1")
    dp_api_token: str = Field(default="replace-me")

    # ── Auth ─────────────────────────────────────────────────────────────────
    jwt_secret: str = Field(default="replace-me-with-openssl-rand-base64-32")
    jwt_algorithm: str = Field(default="HS256")

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
