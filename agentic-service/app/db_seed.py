"""SQLite schema + fictitious Drive Producteur data.

Phase 1: the Tevet-7 agentic service runs against an in-process SQLite
database so the demo is self-contained (no Postgres / Docker needed). This
module owns:

1. The SQLAlchemy ``MetaData`` that mirrors ``app/schema.yaml`` (producers,
   shops, products, stocks, orders, order_items, pickup_bookings, payments).
2. A seed routine that populates 7 fictitious producers with realistic
   French agricultural data - different catalogs and sales volumes per
   producer so the row-level scoping demo is tangible.
3. ``init_db()`` - idempotent: drops + recreates all tables and reseeds.
4. ``get_engine()`` - lazy singleton async engine.

The data is FICTITIOUS. Producer names, SIRET, IBAN, addresses are all
invented for the demo.
"""

from __future__ import annotations

import logging
import math
import random
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings

logger = logging.getLogger("tevet7.db_seed")

# Commission rate applied by the marketplace on every order (stored as a
# constant, NOT in the DB). Used by the orchestrator to compute net revenue.
COMMISSION_RATE = 0.12

# Consistent PRNG so the seeded data is deterministic across runs (makes the
# "Marie's top product is Tomates" guarantee stable).
_RNG = random.Random(20240601)

metadata = MetaData()

# ─────────────────────────────────────────────────────────────────────────────
# Table definitions (mirror app/schema.yaml)
# ─────────────────────────────────────────────────────────────────────────────

producers = Table(
    "producers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("legal_name", String, nullable=False),
    Column("display_name", String, nullable=False),
    Column("email", String, nullable=False),
    Column("phone", String, nullable=False),
    Column("siret", String, nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("is_active", Boolean, nullable=False, default=True),
)

shops = Table(
    "shops",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("producer_id", Integer, ForeignKey("producers.id"), nullable=False, index=True),
    Column("name", String, nullable=False),
    Column("address", String, nullable=False),
    Column("city", String, nullable=False),
    Column("postal_code", String, nullable=False),
    Column("latitude", Float, nullable=True),
    Column("longitude", Float, nullable=True),
    Column("opening_hours", String, nullable=True),
    Column("is_active", Boolean, nullable=False, default=True),
)

products = Table(
    "products",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("producer_id", Integer, ForeignKey("producers.id"), nullable=False, index=True),
    Column("shop_id", Integer, ForeignKey("shops.id"), nullable=False, index=True),
    Column("sku", String, nullable=False),
    Column("name", String, nullable=False),
    Column("category", String, nullable=False),
    Column("unit", String, nullable=False),
    Column("price_eur", Float, nullable=False),
    Column("vat_rate", Float, nullable=False, default=0.055),
    Column("is_organic", Boolean, nullable=False, default=False),
    Column("is_available", Boolean, nullable=False, default=True),
    Column("created_at", DateTime, nullable=False),
    # ── Phase 5 ML columns ────────────────────────────────────────────────
    # Three columns the RandomForest forecast model uses as features. They
    # are derived from the existing ``category`` + ``weights`` at seed time so
    # we don't have to extend the ``_PRODUCERS`` tuple schema. ``base_popularity``
    # is the normalised sales weight (0..1); ``is_perishable`` flags categories
    # that rotate fast (légumes, fruits, viande, produits laitiers);
    # ``seasonality_peak_month`` is the 1..12 month when demand peaks.
    Column("base_popularity", Float, nullable=False, default=1.0),
    Column("is_perishable", Boolean, nullable=False, default=False),
    Column("seasonality_peak_month", Integer, nullable=True),
)

stocks = Table(
    "stocks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("producer_id", Integer, ForeignKey("producers.id"), nullable=False, index=True),
    Column("product_id", Integer, ForeignKey("products.id"), nullable=False, index=True),
    Column("shop_id", Integer, ForeignKey("shops.id"), nullable=False, index=True),
    Column("quantity", Float, nullable=False),
    Column("reserved", Float, nullable=False, default=0),
    Column("available", Float, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

orders = Table(
    "orders",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("producer_id", Integer, ForeignKey("producers.id"), nullable=False, index=True),
    Column("customer_id", Integer, nullable=False),
    Column("shop_id", Integer, ForeignKey("shops.id"), nullable=False, index=True),
    Column("pickup_slot", DateTime, nullable=True),
    Column("total_amount", Float, nullable=False),
    Column("status", String, nullable=False),
    Column("created_at", DateTime, nullable=False, index=True),
    Column("updated_at", DateTime, nullable=False),
)

order_items = Table(
    "order_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("order_id", Integer, ForeignKey("orders.id"), nullable=False, index=True),
    Column("producer_id", Integer, ForeignKey("producers.id"), nullable=False, index=True),
    Column("product_id", Integer, ForeignKey("products.id"), nullable=False, index=True),
    Column("quantity", Float, nullable=False),
    Column("unit_price_eur", Float, nullable=False),
    Column("line_total_eur", Float, nullable=False),
)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 5 - ML training table: daily stock snapshots per (product, date).
# ─────────────────────────────────────────────────────────────────────────────
# One row per (product_id, date) over the 90+ day history window. Each row
# captures the start-of-day stock_level, the day's actual sales (sum of
# order_items.quantity for that product on that date), the restock quantity
# applied that day, and a stockout_flag set to 1 when daily_sales >
# stock_level (rupture).
#
# This is the **training data source** for the RandomForest stock-shortage
# model - see ``ml/train_stock_model.py``. The forecast tool at inference
# time builds features from this same table (sales_7d, sales_3d, sales_1d,
# days_since_last_stockout, avg_sales_30d) plus the current ``stocks``
# snapshot, so the live features match the training distribution.
#
# The rupture target is computed by the training script as
# ``stockout_next_3d = 1 if stockout_flag=1 in any of date+1, date+2, date+3``.
stock_history = Table(
    "stock_history",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("producer_id", Integer, ForeignKey("producers.id"), nullable=False, index=True),
    Column("product_id", Integer, ForeignKey("products.id"), nullable=False, index=True),
    Column("date", DateTime, nullable=False, index=True),  # snapshot date (midnight)
    Column("stock_level", Float, nullable=False),         # start-of-day stock
    Column("reserved", Float, nullable=False, default=0),
    Column("available", Float, nullable=False),            # start-of-day available
    Column("daily_sales", Float, nullable=False, default=0),    # demand that day
    Column("restocked_qty", Float, nullable=False, default=0),  # restock applied that day
    Column("stockout_flag", Boolean, nullable=False, default=False),
    Column("day_of_week", Integer, nullable=False),       # 0=Mon .. 6=Sun
    Column("is_weekend", Boolean, nullable=False),        # True if Fri(4) or Sat(5)
    Column("month", Integer, nullable=False),             # 1..12
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)

pickup_bookings = Table(
    "pickup_bookings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("producer_id", Integer, ForeignKey("producers.id"), nullable=False, index=True),
    Column("shop_id", Integer, ForeignKey("shops.id"), nullable=False, index=True),
    Column("customer_id", Integer, nullable=False),
    Column("slot_start", DateTime, nullable=False),
    Column("slot_end", DateTime, nullable=False),
    Column("status", String, nullable=False),
    Column("created_at", DateTime, nullable=False),
)

payments = Table(
    "payments",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("order_id", Integer, ForeignKey("orders.id"), nullable=False, index=True),
    Column("producer_id", Integer, ForeignKey("producers.id"), nullable=False, index=True),
    Column("provider", String, nullable=False),
    Column("provider_ref", String, nullable=False),
    Column("amount_eur", Float, nullable=False),
    Column("status", String, nullable=False),
    Column("captured_at", DateTime, nullable=True),
    Column("created_at", DateTime, nullable=False),
)


# ─────────────────────────────────────────────────────────────────────────────
# Documentary RAG tables (Task 23 / Phase 3 - RAG layer)
# ─────────────────────────────────────────────────────────────────────────────
# Two physical tables plus one FTS5 virtual table.
#
# ``documents`` - one row per uploaded document (PDF, text, manual note).
#   ``producer_id`` is NULL for tenant-wide documents (CGV, FAQ, etc.) or
#   an int for producer-private documents.
#
# ``document_chunks`` - paragraph-sized chunks (200-400 chars) ready for
#   full-text search. Each chunk carries the same ``tenant_id`` and
#   ``producer_id`` as its parent document so the RAG tool can apply
#   row-level scoping at search time without joining back to ``documents``.
#
# ``document_chunks_fts`` - SQLite FTS5 virtual table (BM25 ranking) that
#   mirrors ``document_chunks``. We chose MANUAL sync (not triggers) so
#   the ingest pipeline keeps full control of the FTS content and so the
#   DELETE endpoint can remove the FTS rows explicitly (FTS5 external
#   content tables are trickier to keep in sync than a manual mirror).
#
#   We chose FTS5 over pgvector / OpenAI embeddings on purpose:
#   - No external API key needed (vs OpenAI embeddings).
#   - No Postgres/Docker to run (in-process SQLite only).
#   - Sufficient for a small corpus (< 100 chunks per tenant).
#   - Embeddings-ready architecture: ``RagSearchTool.search()`` is the
#     single point of swap - replace the FTS5 SELECT with a vector
#     similarity query in Phase 6 without touching the orchestrator.
documents = Table(
    "documents",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("tenant_id", String, nullable=False, default="dp", index=True),
    Column("title", String, nullable=False),
    Column("source_type", String, nullable=False),  # "pdf" | "text" | "manual"
    Column("source_filename", String, nullable=True),
    Column("content_raw", Text, nullable=False),
    Column("producer_id", Integer, nullable=True, index=True),  # NULL = tenant-wide
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)

document_chunks = Table(
    "document_chunks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("document_id", Integer, ForeignKey("documents.id"), nullable=False, index=True),
    Column("chunk_index", Integer, nullable=False),
    Column("content", Text, nullable=False),
    Column("tenant_id", String, nullable=False, default="dp", index=True),
    Column("producer_id", Integer, nullable=True, index=True),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)


# ─────────────────────────────────────────────────────────────────────────────
# Ops Copilot - human-in-the-loop onboarding tables (Task 26 / Phase 4)
# ─────────────────────────────────────────────────────────────────────────────
# Two tables that materialise the HITL contract: the agent pre-analyzes
# a producer-onboarding dossier, writes its structured analysis into
# ``approval_requests.agent_analysis`` (JSON) + ``proposed_decision`` +
# ``proposed_reason``, and waits. A human admin later closes the loop via
# ``POST /api/approvals/{id}/decide`` which flips ``approval_requests.status``
# AND ``producer_onboardings.status`` in the same transaction.
#
# Design notes
# ------------
# * ``producer_onboardings`` mirrors the dossier structure described in the
#   DP onboarding procedure (one of the 4 RAG documents): legal_name, SIRET,
#   RIB, ID, professional certificate, declared address vs document address.
#   ``siret_valid`` is the result of the (out-of-band) SIRENE API call - we
#   store it rather than call INSEE live so the demo is self-contained.
# * ``approval_requests`` is intentionally generic (``request_type`` column)
#   so Phase 5+ can reuse it for ticket classification, refund approval,
#   etc. - every "agent proposes, human decides" workflow lives here.
# * ``trace_id`` carries the Langfuse trace_id of the agent's pre-analysis
#   so the audit trail links the human decision back to the agent run.
producer_onboardings = Table(
    "producer_onboardings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("tenant_id", String, nullable=False, default="dp", index=True),
    Column("legal_name", String, nullable=False),
    Column("siret", String, nullable=False),
    Column("siret_valid", Boolean, nullable=False, default=False),
    Column("email", String, nullable=True),
    Column("phone", String, nullable=True),
    Column("declared_address", String, nullable=True),
    Column("rib_document_present", Boolean, nullable=False, default=False),
    Column("id_document_present", Boolean, nullable=False, default=False),
    Column("professional_certificate_present", Boolean, nullable=False, default=False),
    Column("professional_certificate_expiry", String, nullable=True),  # ISO date
    Column("document_address", String, nullable=True),
    Column("submitted_at", DateTime, nullable=False, default=datetime.utcnow),
    Column("status", String, nullable=False, default="pending"),  # pending|approved|rejected
    Column("rejection_reason", String, nullable=True),
)

approval_requests = Table(
    "approval_requests",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("tenant_id", String, nullable=False, default="dp", index=True),
    Column(
        "onboarding_id",
        Integer,
        ForeignKey("producer_onboardings.id"),
        nullable=False,
        index=True,
    ),
    Column("request_type", String, nullable=False, default="onboarding_analysis"),
    Column("agent_analysis", Text, nullable=True),  # JSON string
    Column("proposed_decision", String, nullable=False, default="approve"),
    # "approve" | "reject" | "request_info"
    Column("proposed_reason", Text, nullable=True),
    Column("status", String, nullable=False, default="pending"),
    # "pending" | "approved" | "rejected" | "overridden"
    Column("decided_by", String, nullable=True),
    Column("decided_at", DateTime, nullable=True),
    Column("human_reason", Text, nullable=True),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
    Column("trace_id", String, nullable=True),  # Langfuse trace_id of the agent run
)


# ─────────────────────────────────────────────────────────────────────────────
# Observability - traces table (Task 18 / Phase 2 tracing)
# ─────────────────────────────────────────────────────────────────────────────
# One row per ``/api/chat`` request, written by ``LocalTracer.end_trace``.
# The ``traces`` table is created in the same ``metadata.create_all`` call
# as the business tables - no separate migration. JSON-shaped fields
# (``tool_calls``, ``steps``) are stored as TEXT (JSON-encoded) because
# SQLite has no native JSON column type and we want the schema portable to
# Postgres without changes.
traces_table = Table(
    "traces",
    metadata,
    Column("id", String, primary_key=True),  # uuid4 hex
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow, index=True),
    Column("tenant_id", String, nullable=False, default="dp", index=True),
    Column("user_message", Text, nullable=False),
    Column("identity_id", String, nullable=True, index=True),
    Column("producer_id", Integer, nullable=True, index=True),
    Column("role", String, nullable=True),
    Column("intent", String, nullable=True),
    Column("sql_generated", Text, nullable=True),
    Column("sql_valid", Boolean, nullable=False, default=False),
    Column("scope_applied", Boolean, nullable=False, default=False),
    Column("security_incident", Boolean, nullable=False, default=False),
    Column("refused", Boolean, nullable=False, default=False),
    Column("tool_calls", Text, nullable=True),  # JSON list[{name,latency_ms,success}]
    Column("steps", Text, nullable=True),  # JSON list[{index,title,status,duration_ms}]
    Column("tokens_in", Integer, nullable=False, default=0),
    Column("tokens_out", Integer, nullable=False, default=0),
    Column("cost_usd", Float, nullable=False, default=0.0),
    Column("latency_ms", Integer, nullable=False, default=0),
    Column("error", Text, nullable=True),
    Column("response_answer", Text, nullable=True),  # first 500 chars of the answer
)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 6a - Auth + multi-tenant platform tables
# ─────────────────────────────────────────────────────────────────────────────
# Three new tables that turn Tevet-7 from a single-tenant demo into a
# multi-tenant platform. They are created in the same ``metadata.create_all``
# call as the business tables (no separate migration) and live in the SAME
# SQLite file. The CORE agentic (agents/tools/tracing) never imports these
# tables - only ``app/auth`` and ``app/tenants`` do. The HTTP layer
# (app/api/*) extracts the identity from the JWT and passes plain
# ``role``/``producer_id``/``tenant_id`` strings down to the orchestrator.
#
# Schema:
#   users               - id, email (unique), name, password_hash (bcrypt), created_at
#   tenants             - id (str, e.g. "dp"), name, slug (unique), is_demo,
#                         created_at, owner_user_id (FK→users.id)
#   tenant_memberships  - id, user_id, tenant_id, role, producer_id,
#                         is_active, created_at. UNIQUE(user_id, tenant_id).
#                         A user has at most one is_active=True row at a time
#                         (enforced by set_active_membership in app.tenants.service).
users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String, nullable=False, unique=True, index=True),
    Column("name", String, nullable=False),
    Column("password_hash", String, nullable=False),
    Column("is_platform_owner", Boolean, nullable=False, default=False),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)

tenants = Table(
    "tenants",
    metadata,
    Column("id", String, primary_key=True),  # e.g. "dp" (== slug)
    Column("name", String, nullable=False),
    Column("slug", String, nullable=False, unique=True, index=True),
    Column("is_demo", Boolean, nullable=False, default=False),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
    Column("owner_user_id", Integer, ForeignKey("users.id"), nullable=True),
)

tenant_memberships = Table(
    "tenant_memberships",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "user_id",
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    ),
    Column(
        "tenant_id",
        String,
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
    ),
    Column("role", String, nullable=False),  # "producer"|"admin"|"customer"
    Column("producer_id", Integer, nullable=True),  # row-level scope; NULL for admin
    Column("is_active", Boolean, nullable=False, default=False),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
    # UNIQUE(user_id, tenant_id) - a user can be a member of a tenant at
    # most once. Enforced by SQLite via the composite unique below.
    UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),
)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 6b - Onboarding backend (tenant_configs)
# ─────────────────────────────────────────────────────────────────────────────
# One row per tenant storing the onboarding wizard output:
#
#   connector_type   - "sqlite_demo" | "postgres" | "csv"
#   connection_url   - the tenant's Postgres URL (NULL for sqlite_demo / csv)
#   csv_path         - path to the uploaded CSV file (NULL for postgres / sqlite_demo)
#   schema_config    - JSON string with the same shape as app/schema.yaml
#                      (tables, columns, scope, allowed_for_roles, ...). Saved
#                      by the onboarding wizard after the user reviews the
#                      auto-detected draft.
#   roles_config     - JSON string with the tenant's role definitions + scope
#                      columns (e.g. {"producer": {"scope_column": "producer_id"},
#                                     "admin": {"scope_column": null}, ...}).
#   onboarded        - bool, False until the user completes the wizard. The
#                      chat endpoint refuses to run for tenants where this is
#                      False (returns a clear "complete onboarding" message).
#
# The demo tenant "dp" is seeded with connector_type="sqlite_demo",
# schema_config=<app/schema.yaml as JSON>, onboarded=True - so the demo
# keeps working unchanged (the factory returns a SqliteConnector for it).
tenant_configs = Table(
    "tenant_configs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "tenant_id",
        String,
        ForeignKey("tenants.id"),
        nullable=False,
        unique=True,
        index=True,
    ),
    Column("connector_type", String, nullable=False, default="sqlite_demo"),
    # "sqlite_demo" | "postgres" | "csv"
    Column("connection_url", String, nullable=True),  # for postgres
    Column("csv_path", String, nullable=True),  # for csv
    Column("schema_config", Text, nullable=True),  # JSON string
    Column("roles_config", Text, nullable=True),  # JSON string
    Column("onboarded", Boolean, nullable=False, default=False),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
    Column("updated_at", DateTime, nullable=False, default=datetime.utcnow),
)


# ─────────────────────────────────────────────────────────────────────────────
# LLM response cache (Phase A/SOLID refactor)
# ─────────────────────────────────────────────────────────────────────────────
# Caches LLM responses by prompt hash so repeated questions return instantly
# without consuming tokens. Critical for dev: the eval runs 78+ calls; the
# 2nd pass is 100% cached.
llm_cache = Table(
    "llm_cache",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("prompt_hash", String, nullable=False, unique=True, index=True),
    Column("response_json", Text, nullable=False),
    Column("model", String, nullable=False),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)


# ─────────────────────────────────────────────────────────────────────────────
# Conversation persistence (Phase B4)
# ─────────────────────────────────────────────────────────────────────────────
conversations = Table(
    "conversations",
    metadata,
    Column("id", String, primary_key=True),  # uuid4 hex
    Column("tenant_id", String, ForeignKey("tenants.id"), nullable=False, index=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=True),
    Column("title", String, nullable=True),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
    Column("updated_at", DateTime, nullable=False, default=datetime.utcnow),
)

messages = Table(
    "messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("conversation_id", String, ForeignKey("conversations.id"), nullable=False, index=True),
    Column("role", String, nullable=False),  # 'user' | 'assistant'
    Column("content", Text, nullable=False),
    Column("sql", Text, nullable=True),
    Column("tokens_in", Integer, nullable=False, default=0),
    Column("tokens_out", Integer, nullable=False, default=0),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)


# ─────────────────────────────────────────────────────────────────────────────
# Engine singleton
# ─────────────────────────────────────────────────────────────────────────────

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """Return the lazy singleton async engine for the SQLite DB."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            future=True,
        )
    return _engine


# ─────────────────────────────────────────────────────────────────────────────
# Seed data
# ─────────────────────────────────────────────────────────────────────────────

# Producer 42 - Marie Dubois, Ferme du Vallon (vegetables).
# Producer 99 - Pierre Martin, Verger de la Côte (apples/pears/cider).
# Producer 17 - Maraîchers du Soleil (vegetables, organic, larger).
# Producer 58 - Élevage des Prés (meat).
# Producer 23 - Fromagerie du Col (dairy / cheese).
# Producer 71 - Apiculteur des Cimes (honey).
# Producer 34 - Vignoble des Bruyères (wine).

_PRODUCERS = [
    {
        "id": 42,
        "legal_name": "EARL Dubois",
        "display_name": "Ferme du Vallon",
        "email": "marie.dubois@ferme-du-vallon.fr",
        "phone": "+33 4 50 12 34 56",
        "siret": "812 345 678 00012",
        "shop": {
            "name": "Ferme du Vallon - Annecy",
            "address": "12 route du Vallon",
            "city": "Annecy",
            "postal_code": "74000",
            "lat": 45.9021,
            "lng": 6.1280,
        },
        "products": [
            ("Tomates cœur de bœuf", "légumes", "kg", 4.50, True),
            ("Courgettes", "légumes", "pièce", 1.20, True),
            ("Carottes en bottes", "légumes", "botte", 2.80, True),
            ("Salade laitue", "légumes", "pièce", 1.80, True),
            ("Poireaux", "légumes", "botte", 3.20, True),
            ("Radis roses", "légumes", "botte", 2.20, False),
            ("Aubergines", "légumes", "kg", 4.20, False),
            ("Poivrons rouges", "légumes", "kg", 5.00, True),
            ("Blettes", "légumes", "botte", 2.90, False),
            ("Courges butternut", "légumes", "kg", 3.50, False),
        ],
        # weights control sales volume distribution (first product = top seller)
        "weights": [142, 98, 76, 65, 54, 33, 28, 22, 18, 12],
        "orders_per_month": {"current": 312, "june": 188},
    },
    {
        "id": 99,
        "legal_name": "GAEC Martin",
        "display_name": "Verger de la Côte",
        "email": "pierre.martin@verger-de-la-cote.fr",
        "phone": "+33 4 50 98 76 54",
        "siret": "823 456 789 00099",
        "shop": {
            "name": "Verger de la Côte - Cruseilles",
            "address": "5 chemin des Pommiers",
            "city": "Cruseilles",
            "postal_code": "74350",
            "lat": 46.0421,
            "lng": 6.1085,
        },
        "products": [
            ("Pommes Gala", "fruits", "kg", 2.80, False),
            ("Poires Conference", "fruits", "kg", 3.20, False),
            ("Jus de pomme", "boissons", "litre", 4.50, False),
            ("Cidre brut", "boissons", "litre", 6.80, False),
            ("Pommes à cuire", "fruits", "kg", 2.20, False),
            ("Compote maison", "épicerie", "pot", 3.80, False),
            ("Abricots", "fruits", "kg", 5.50, True),
            ("Mirabelles", "fruits", "kg", 6.20, False),
            ("Gelée de coings", "épicerie", "pot", 5.20, False),
            ("Pommeau de Savoie", "boissons", "litre", 9.50, False),
        ],
        "weights": [128, 84, 72, 56, 48, 31, 22, 18, 14, 9],
        "orders_per_month": {"current": 298, "june": 174},
    },
    {
        "id": 17,
        "legal_name": "SAS Maraîchers du Soleil",
        "display_name": "Maraîchers du Soleil",
        "email": "contact@maraichers-soleil.fr",
        "phone": "+33 4 50 11 22 33",
        "siret": "801 234 567 00017",
        "shop": {
            "name": "Maraîchers du Soleil - Rumilly",
            "address": "8 route des Champs",
            "city": "Rumilly",
            "postal_code": "74150",
            "lat": 45.8633,
            "lng": 6.0051,
        },
        "products": [
            ("Tomates grappe", "légumes", "kg", 3.20, False),
            ("Concombres", "légumes", "pièce", 1.50, False),
            ("Salades batavia", "légumes", "pièce", 1.60, True),
            ("Épinards frais", "légumes", "botte", 2.40, True),
            ("Betteraves rouges", "légumes", "kg", 2.20, False),
            ("Oignons jaunes", "légumes", "kg", 1.80, False),
            ("Ail rose", "légumes", "pièce", 1.20, False),
            ("Courgettes vertes", "légumes", "pièce", 1.10, False),
            ("Fraises Mara des Bois", "fruits", "barquette", 4.80, True),
            ("Framboises", "fruits", "barquette", 5.20, True),
            ("Citrouilles", "légumes", "pièce", 6.50, False),
        ],
        "weights": [110, 88, 72, 60, 52, 44, 38, 30, 24, 18, 8],
        "orders_per_month": {"current": 245, "june": 132},
    },
    {
        "id": 58,
        "legal_name": "EARL Élevage des Prés",
        "display_name": "Élevage des Prés",
        "email": "contact@elevage-des-pres.fr",
        "phone": "+33 4 50 65 43 21",
        "siret": "814 567 890 00058",
        "shop": {
            "name": "Élevage des Prés - La Roche-sur-Foron",
            "address": "23 route des Prés",
            "city": "La Roche-sur-Foron",
            "postal_code": "74800",
            "lat": 46.0667,
            "lng": 6.3167,
        },
        "products": [
            ("Steak haché 5% MG", "viande", "kg", 14.50, False),
            ("Entrecôte de bœuf", "viande", "kg", 26.00, False),
            ("Poulet fermier entier", "viande", "pièce", 12.50, False),
            ("Saucisses de Toulouse", "charcuterie", "kg", 13.20, False),
            ("Jambon cru de Savoie", "charcuterie", "kg", 28.00, False),
            ("Côte de porc", "viande", "kg", 11.80, False),
            ("Pommes de terre grenaille", "légumes", "kg", 2.50, False),
            ("Œufs frais", "épicerie", "boîte de 6", 3.20, True),
            ("Escalopes de dinde", "viande", "kg", 12.00, False),
            ("Rôti de veau", "viande", "kg", 22.50, False),
        ],
        "weights": [95, 42, 70, 58, 36, 48, 32, 64, 28, 22],
        "orders_per_month": {"current": 178, "june": 96},
    },
    {
        "id": 23,
        "legal_name": "SCEA Fromagerie du Col",
        "display_name": "Fromagerie du Col",
        "email": "contact@fromagerie-du-col.fr",
        "phone": "+33 4 50 78 90 12",
        "siret": "825 678 901 00023",
        "shop": {
            "name": "Fromagerie du Col - Thônes",
            "address": "1 place du Col",
            "city": "Thônes",
            "postal_code": "74230",
            "lat": 45.8867,
            "lng": 6.3217,
        },
        "products": [
            ("Tomme de Savoie", "produits laitiers", "kg", 18.50, False),
            ("Reblochon AOP", "produits laitiers", "kg", 22.00, False),
            ("Beaufort d'été", "produits laitiers", "kg", 32.00, False),
            ("Raclette nature", "produits laitiers", "kg", 16.50, False),
            ("Raclette fumée", "produits laitiers", "kg", 18.20, False),
            ("Tomme de chèvre", "produits laitiers", "kg", 24.00, False),
            ("Yaourt nature", "produits laitiers", "pot de 125g", 0.90, False),
            ("Fromage blanc", "produits laitiers", "pot de 500g", 3.20, False),
            ("Persillé des Aravis", "produits laitiers", "kg", 28.50, False),
            ("Carré frais aux herbes", "produits laitiers", "pièce", 2.80, False),
        ],
        "weights": [88, 102, 56, 78, 64, 42, 130, 95, 28, 36],
        "orders_per_month": {"current": 203, "june": 117},
    },
    {
        "id": 71,
        "legal_name": "Apiculteur des Cimes",
        "display_name": "Apiculteur des Cimes",
        "email": "contact@apiculteur-des-cimes.fr",
        "phone": "+33 4 50 34 56 78",
        "siret": "836 789 012 00071",
        "shop": {
            "name": "Apiculteur des Cimes - Sallanches",
            "address": "4 route des Ruchers",
            "city": "Sallanches",
            "postal_code": "74700",
            "lat": 45.9444,
            "lng": 6.6306,
        },
        "products": [
            ("Miel de montagne", "épicerie", "pot de 500g", 8.50, False),
            ("Miel de sapin", "épicerie", "pot de 500g", 12.00, False),
            ("Miel de fleurs", "épicerie", "pot de 500g", 7.80, False),
            ("Pollen frais", "épicerie", "pot de 250g", 9.50, False),
            ("Propolis", "épicerie", "pot de 30g", 14.00, False),
            ("Gelée royale", "épicerie", "pot de 10g", 18.00, False),
            ("Cire d'abeille", "épicerie", "pièce de 500g", 6.50, False),
            ("Pain d'épices", "épicerie", "pièce", 5.50, False),
            ("Nougat blanc", "épicerie", "barquette de 200g", 7.20, False),
        ],
        "weights": [62, 38, 55, 22, 18, 12, 8, 42, 28],
        "orders_per_month": {"current": 96, "june": 58},
    },
    {
        "id": 34,
        "legal_name": "Vignoble des Bruyères",
        "display_name": "Vignoble des Bruyères",
        "email": "contact@vignoble-des-bruyeres.fr",
        "phone": "+33 4 50 21 43 65",
        "siret": "847 890 123 00034",
        "shop": {
            "name": "Vignoble des Bruyères - Frangy",
            "address": "17 route des Vignes",
            "city": "Frangy",
            "postal_code": "74270",
            "lat": 45.9933,
            "lng": 5.9217,
        },
        "products": [
            ("Vin rouge Savoie AOP", "boissons", "bouteille 75cl", 11.50, False),
            ("Vin blanc Roussette", "boissons", "bouteille 75cl", 12.80, False),
            ("Vin rosé", "boissons", "bouteille 75cl", 9.50, False),
            ("Vin rouge Gamay", "boissons", "bouteille 75cl", 9.80, False),
            ("Vin pétillant Crémant", "boissons", "bouteille 75cl", 16.50, False),
            ("Vin moût de raisin", "boissons", "bouteille 50cl", 6.20, False),
            ("Vin rouge Mondeuse", "boissons", "bouteille 75cl", 14.50, False),
            ("Marc de Savoie", "boissons", "bouteille 70cl", 28.00, False),
            ("Vin blanc Apremont", "boissons", "bouteille 75cl", 11.20, False),
        ],
        "weights": [85, 78, 62, 50, 38, 18, 42, 14, 60],
        "orders_per_month": {"current": 156, "june": 88},
    },
]

# Reference "now" - fixed to make June visible in the dataset for the
# "combien j'ai gagné en juin" question. We pretend the demo runs in
# mid-July 2024 so June is a complete prior month.
_REFERENCE_NOW = datetime(2024, 7, 15, 10, 0, 0)
_JUNE_START = datetime(2024, 6, 1, 0, 0, 0)
_JUNE_END = datetime(2024, 6, 30, 23, 59, 59)
_CURRENT_MONTH_START = datetime(2024, 7, 1, 0, 0, 0)

# ── Phase 5 ML history window ──────────────────────────────────────────────
# 90 days of history (2024-04-15 → 2024-07-14) + the current demo day
# (2024-07-15). The seed generates orders across the full window using a
# daily demand model (weekend_boost + seasonality + gaussian noise) so the
# RandomForest has 90+ days × ~10 products × 7 producers ≈ 6300+ rows of
# training data in ``stock_history``.
_HISTORY_START = datetime(2024, 4, 15, 0, 0, 0)
_HISTORY_END = datetime(2024, 7, 14, 23, 59, 59)
_HISTORY_DAYS = 91  # 2024-04-15 → 2024-07-14 inclusive

# Per-producer average orders/day (Phase 5). Tuned so the 91-day window +
# July-current yields ~5000 orders total (was 2341 with the old June+July
# split). The values reflect each producer's catalogue size + customer base:
# Marie (vegetables, high volume) > Pierre (orchard) > Maraîchers > Élevage
# ≈ Fromagerie > Vignoble > Apiculteur (niche, low volume).
_PRODUCER_DAILY_ORDERS: dict[int, float] = {
    42: 8.5,   # Marie - Ferme du Vallon
    99: 8.0,   # Pierre - Verger de la Côte
    17: 7.0,   # Maraîchers du Soleil
    58: 6.5,   # Élevage des Prés
    23: 7.0,   # Fromagerie du Col
    71: 5.0,   # Apiculteur des Cimes
    34: 6.0,   # Vignoble des Bruyères
}

# Per-category seasonality peak month (1..12). Used by both the seed demand
# generator (so the rupture signal is correlated with the season) and the
# ML feature builder (so the model learns seasonal demand).
# légumes → July (summer tomatoes/courgettes), fruits → September (apples),
# viande/charcuterie → July (BBQ), produits laitiers → December (raclette),
# épicerie/boissons → December (holidays).
_CATEGORY_PEAK_MONTH: dict[str, int] = {
    "légumes": 7,
    "fruits": 9,
    "viande": 7,
    "charcuterie": 7,
    "produits laitiers": 12,
    "épicerie": 12,
    "boissons": 12,
}

# Categories that rotate fast (perishable) - the seed gives them a smaller
# stock buffer and smaller restock quantity so they rupture more often.
_PERISHABLE_CATEGORIES = {"légumes", "fruits", "viande", "charcuterie", "produits laitiers"}


def _derive_product_meta(category: str, weight: int, max_weight: int) -> dict[str, Any]:
    """Derive the three ML feature columns for a product row.

    Returns ``{base_popularity, is_perishable, seasonality_peak_month}``.
    ``base_popularity`` is normalised to 0.1..1.0 (small floor so even the
    least-popular product has non-zero demand); ``is_perishable`` is True
    for fast-rotating categories; ``seasonality_peak_month`` comes from
    the lookup table above (None if the category is unknown).
    """
    norm = (weight / max_weight) if max_weight > 0 else 1.0
    base_popularity = max(0.1, round(norm, 3))
    return {
        "base_popularity": base_popularity,
        "is_perishable": category in _PERISHABLE_CATEGORIES,
        "seasonality_peak_month": _CATEGORY_PEAK_MONTH.get(category),
    }


def _seasonality_factor(month: int, peak_month: int | None) -> float:
    """Cosine seasonality factor in [0.6, 1.0].

    1.0 at the peak month, 0.6 at the opposite month. Used to multiply the
    daily demand so summer vegetables get a demand bump in July, etc. The
    amplitude (0.2) is intentionally modest so off-season producers (e.g.
    Fromagerie peaking in December) still rupture during the April-July
    seed window - otherwise the RandomForest would never see a positive
    example for those producers and the forecast demo would be flat.
    """
    if peak_month is None:
        return 1.0
    return 0.8 + 0.2 * math.cos((month - peak_month) * 2.0 * math.pi / 12.0)


def _generate_orders_and_history(
    producer_id: int,
    shop_id: int,
    product_rows: list[dict[str, Any]],
    weights: list[int],
    base_orders_per_day: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build orders + stock_history rows for one producer over the 91-day
    history window plus July-current (2024-04-15 → 2024-07-15).

    Returns ``(orders, stock_history_rows)``.

    Demand model
    ------------
    For each day d and each product p:
        daily_demand[p, d] = max(0, round(
            base_popularity[p] * scale
            * weekend_boost(d)
            * seasonality_factor(month(d), peak_month[p])
            * gauss(1, 0.2)
        ))
    where ``scale = 1.5`` maps base_popularity (0.1..1.0) to ~0.15..1.5
    units/day, and ``weekend_boost = 1.4`` on Fri/Sat else 1.0.

    Orders per day
    --------------
    Each day gets ``round(base_orders_per_day * gauss(1, 0.15))`` orders.
    Each order picks 1-5 products weighted by popularity, with quantity 1-6.

    Stock simulation
    ----------------
    Each product starts with ``reorder_point + random`` units. Every 7 days
    (per-product restock offset) it gets ``reorder_qty`` units added. Daily
    sales decrement the stock; if daily_sales > stock_level the product
    ruptures that day (stockout_flag=1, stock_level → 0). Perishables get a
    tighter buffer (3 days) than shelf-stable products (5 days) so they
    rupture more often.
    """
    orders_out: list[dict[str, Any]] = []
    stock_history_out: list[dict[str, Any]] = []
    order_id_pool = _RNG.randint(1000, 99999)
    statuses = ["pending", "paid", "ready_for_pickup", "completed", "completed", "completed", "cancelled"]

    max_w = max(weights) if weights else 1
    # Per-product rolling stock state.
    product_state: dict[int, dict[str, Any]] = {}
    for idx, p in enumerate(product_rows):
        meta = _derive_product_meta(p["category"], weights[idx], max_w)
        # Inject the meta into the product row so the caller can persist it.
        p["base_popularity"] = meta["base_popularity"]
        p["is_perishable"] = meta["is_perishable"]
        p["seasonality_peak_month"] = meta["seasonality_peak_month"]
        # Demand scale 2.0 (Phase 5 bump from 1.5) so even off-season producers
        # see enough demand to rupture during the 91-day window.
        avg_daily_demand = max(0.5, meta["base_popularity"] * 2.0)
        buffer_days = 3 if meta["is_perishable"] else 4
        # Restock 5 days of demand every 7 days → 2-day deficit per cycle.
        # Both perishables and non-perishables use the same restock quantity
        # so all producers rupture occasionally (was 5/7 split, which left
        # dairy/wine/honey producers with 0 ruptures in training data).
        reorder_qty = avg_daily_demand * 5
        product_state[p["id"]] = {
            "stock_level": avg_daily_demand * buffer_days + _RNG.uniform(0, 5),
            "reorder_qty": reorder_qty,
            "reorder_point": avg_daily_demand * buffer_days,
            "avg_daily_demand": avg_daily_demand,
            "last_stockout_day": -10,
            "restock_day_offset": _RNG.randint(0, 6),
        }

    # Generate per-day demand for the full history window.
    daily_demand: dict[tuple[int, int], float] = {}
    for day_idx in range(_HISTORY_DAYS):
        date = _HISTORY_START + timedelta(days=day_idx)
        dow = date.weekday()
        is_weekend = dow in (4, 5)
        weekend_boost = 1.4 if is_weekend else 1.0
        month = date.month
        for p in product_rows:
            # Demand scale 2.0 (Phase 5 bump from 1.5).
            base = p["base_popularity"] * 2.0
            seasonality = _seasonality_factor(month, p["seasonality_peak_month"])
            noise = _RNG.gauss(1, 0.2)
            demand = base * weekend_boost * seasonality * noise
            demand = max(0, round(demand))
            daily_demand[(p["id"], day_idx)] = float(demand)

    # ── Generate orders per day ──
    for day_idx in range(_HISTORY_DAYS):
        date = _HISTORY_START + timedelta(days=day_idx)
        n_orders_today = max(0, int(round(base_orders_per_day * _RNG.gauss(1, 0.15))))
        for _ in range(n_orders_today):
            order_id_pool += 1
            ts = date + timedelta(
                hours=_RNG.uniform(8, 19),
                minutes=_RNG.uniform(0, 59),
                seconds=_RNG.uniform(0, 59),
            )
            n_items = _RNG.choices([1, 2, 3, 4, 5], weights=[40, 30, 15, 10, 5])[0]
            chosen_products = _RNG.choices(product_rows, weights=weights, k=n_items)
            line_total = 0.0
            items: list[dict[str, Any]] = []
            for prod in chosen_products:
                qty = float(_RNG.randint(1, 6))
                price = round(prod["price_eur"] * _RNG.uniform(0.95, 1.05), 2)
                lt = round(qty * price, 2)
                line_total += lt
                items.append(
                    {
                        "order_id": order_id_pool,
                        "producer_id": producer_id,
                        "product_id": prod["id"],
                        "quantity": qty,
                        "unit_price_eur": price,
                        "line_total_eur": lt,
                    }
                )
            status = _RNG.choice(statuses)
            total = round(line_total, 2)
            orders_out.append(
                {
                    "id": order_id_pool,
                    "producer_id": producer_id,
                    "customer_id": _RNG.randint(1, 5000),
                    "shop_id": shop_id,
                    "pickup_slot": ts + timedelta(hours=_RNG.randint(1, 72)),
                    "total_amount": total,
                    "status": status,
                    "created_at": ts,
                    "updated_at": ts + timedelta(hours=1),
                    "items": items,
                }
            )

        # ── Stock simulation for this day ──
        dow = date.weekday()
        is_weekend = dow in (4, 5)
        for p in product_rows:
            pid = p["id"]
            state = product_state[pid]
            demand_today = daily_demand[(pid, day_idx)]
            stock_start = state["stock_level"]
            # Restock at the start of the day if it's the restock day.
            restocked = 0.0
            if day_idx % 7 == state["restock_day_offset"]:
                restocked = state["reorder_qty"]
                stock_start += restocked
            # Apply demand; rupture if demand exceeds available stock.
            stockout = False
            available_after = stock_start - demand_today
            if available_after < 0:
                stockout = True
                available_after = 0.0
            stock_history_out.append(
                {
                    "producer_id": producer_id,
                    "product_id": pid,
                    "date": date,
                    "stock_level": round(stock_start, 2),
                    "reserved": 0.0,
                    "available": round(max(stock_start, 0.0), 2),
                    "daily_sales": round(demand_today, 2),
                    "restocked_qty": round(restocked, 2),
                    "stockout_flag": stockout,
                    "day_of_week": dow,
                    "is_weekend": is_weekend,
                    "month": date.month,
                    "created_at": _REFERENCE_NOW,
                }
            )
            state["stock_level"] = available_after
            if stockout:
                state["last_stockout_day"] = day_idx

    return orders_out, stock_history_out


async def init_db() -> None:
    """Create all tables and seed fictitious Drive Producteur data.

    Idempotent: drops every table first, then recreates and reseeds. Safe
    to call on every startup.
    """
    engine = get_engine()
    # Drop + recreate (idempotent). The FTS5 virtual table is NOT part of
    # ``metadata`` (SQLAlchemy Core does not model virtual tables), so we
    # drop + recreate it explicitly with raw SQL below.
    async with engine.begin() as conn:
        # Drop the FTS5 virtual table first (if it exists) - it references
        # ``document_chunks`` so it must go before ``metadata.drop_all``
        # cascades the parent table.
        await conn.execute(text("DROP TABLE IF EXISTS document_chunks_fts"))
        await conn.run_sync(metadata.drop_all)
        await conn.run_sync(metadata.create_all)
        # Create the FTS5 virtual table. ``tokenize = 'porter unicode61'``
        # gives us case-insensitive search + English-stemmer-for-French
        # (good enough for the demo; a French stemmer would be a Phase 6
        # improvement). The ``UNINDEXED`` columns (``document_id``,
        # ``tenant_id``, ``producer_id``) are stored but not tokenised -
        # we filter on them at query time.
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5("
                "content, document_id UNINDEXED, tenant_id UNINDEXED, "
                "producer_id UNINDEXED, tokenize = 'porter unicode61')"
            )
        )
    logger.info("SQLite tables created at %s", engine.url)

    # Seed
    async with engine.begin() as conn:
        # ── producers + shops + products + stocks ──
        all_product_rows: dict[int, list[dict[str, Any]]] = {}
        for prod in _PRODUCERS:
            created_at = _REFERENCE_NOW - timedelta(days=_RNG.randint(400, 900))
            await conn.execute(
                producers.insert().values(
                    id=prod["id"],
                    legal_name=prod["legal_name"],
                    display_name=prod["display_name"],
                    email=prod["email"],
                    phone=prod["phone"],
                    siret=prod["siret"],
                    created_at=created_at,
                    is_active=True,
                )
            )
            shop = prod["shop"]
            shop_id = prod["id"] * 10 + 1
            await conn.execute(
                shops.insert().values(
                    id=shop_id,
                    producer_id=prod["id"],
                    name=shop["name"],
                    address=shop["address"],
                    city=shop["city"],
                    postal_code=shop["postal_code"],
                    latitude=shop["lat"],
                    longitude=shop["lng"],
                    opening_hours="Mar-Sam 09:00-19:00",
                    is_active=True,
                )
            )

            product_rows: list[dict[str, Any]] = []
            max_w = max(prod["weights"]) if prod["weights"] else 1
            for idx, (pname, cat, unit, price, bio) in enumerate(prod["products"]):
                pid = prod["id"] * 100 + idx + 1
                # Phase 5 ML meta - derived from category + weight so we
                # don't have to extend the _PRODUCERS tuple schema.
                meta = _derive_product_meta(cat, prod["weights"][idx], max_w)
                row = {
                    "id": pid,
                    "producer_id": prod["id"],
                    "shop_id": shop_id,
                    "sku": f"{prod['id']}-{idx + 1:03d}",
                    "name": pname,
                    "category": cat,
                    "unit": unit,
                    "price_eur": price,
                    "vat_rate": 0.055 if cat in ("légumes", "fruits", "épicerie") else 0.20,
                    "is_organic": bio,
                    "is_available": True,
                    "created_at": created_at + timedelta(days=30 + idx),
                    "base_popularity": meta["base_popularity"],
                    "is_perishable": meta["is_perishable"],
                    "seasonality_peak_month": meta["seasonality_peak_month"],
                }
                product_rows.append(row)
                await conn.execute(products.insert().values(**row))

                # Stock - placeholder; the real current snapshot is written
                # AFTER the order+history simulation below (we set it to the
                # end-of-day stock_level on the last simulated day). For now
                # we insert a conservative placeholder so the stocks table
                # exists with the right producer scoping; the post-simulation
                # UPDATE overwrites quantity/reserved/available.
                await conn.execute(
                    stocks.insert().values(
                        id=pid,  # one stock row per product
                        producer_id=prod["id"],
                        product_id=pid,
                        shop_id=shop_id,
                        quantity=20.0,
                        reserved=0.0,
                        available=20.0,
                        updated_at=_REFERENCE_NOW,
                    )
                )
            all_product_rows[prod["id"]] = product_rows

        # ── Phase 5 - generate orders + stock_history per producer ──
        # Replaces the old _generate_orders(n_june, n_current) call. Each
        # producer gets a 91-day history window with daily demand modelled
        # as base_popularity × weekend_boost × seasonality × gaussian noise.
        # The stock_history rows drive the ML training; the orders drive
        # the existing top_products / net_revenue / weekly_sales SQL paths.
        all_orders: list[dict[str, Any]] = []
        all_stock_history: list[dict[str, Any]] = []
        # Per-product final stock_level (end of simulation) so we can UPDATE
        # the stocks table after the loop.
        final_stock_by_product: dict[int, dict[str, float]] = {}
        for prod in _PRODUCERS:
            shop_id = prod["id"] * 10 + 1
            product_rows = all_product_rows[prod["id"]]
            weights = prod["weights"]
            base_daily = _PRODUCER_DAILY_ORDERS.get(prod["id"], 5.0)
            orders_for_prod, history_for_prod = _generate_orders_and_history(
                producer_id=prod["id"],
                shop_id=shop_id,
                product_rows=product_rows,
                weights=weights,
                base_orders_per_day=base_daily,
            )
            all_orders.extend(orders_for_prod)
            all_stock_history.extend(history_for_prod)
            # Capture the last snapshot per product to UPDATE the stocks
            # table after this loop (last-write-wins: history_for_prod is
            # ordered by day, so the last row per product is the latest).
            # NOTE: snap["stock_level"] is the START-of-day level. The
            # end-of-day level is start - daily_sales (restock was already
            # added to start). Cap at 0 - rupture zeroes the stock.
            for snap in history_for_prod:
                end_of_day = snap["stock_level"] - snap["daily_sales"]
                final_stock_by_product[snap["product_id"]] = {
                    "stock_level": max(end_of_day, 0.0),
                }

        # Force one or two products per producer into a low-stock situation
        # so the "stock manquant samedi" demo returns something interesting.
        # We do this AFTER the simulation by zeroing the restock on the last
        # simulated day for the 4th product (idx=3) of each producer - same
        # pattern as the pre-Phase-5 seed, so existing eval cases (eval-007
        # … eval-011) keep their expected low-stock references.
        for prod in _PRODUCERS:
            product_rows = all_product_rows[prod["id"]]
            for idx in (3, 5):
                if idx < len(product_rows):
                    pid = product_rows[idx]["id"]
                    if pid in final_stock_by_product:
                        final_stock_by_product[pid]["stock_level"] = _RNG.uniform(2.0, 7.0)

        # UPDATE the stocks table with the final per-product stock_level.
        for pid, info in final_stock_by_product.items():
            level = round(float(info["stock_level"]), 2)
            await conn.execute(
                stocks.update()
                .where(stocks.c.product_id == pid)
                .values(
                    quantity=level,
                    reserved=0.0,
                    available=level,
                    updated_at=_REFERENCE_NOW,
                )
            )

        # Insert the stock_history rows (one INSERT per row - fine for
        # ~7000 rows; SQLite handles it in well under a second).
        sh_counter = 0
        for snap in all_stock_history:
            sh_counter += 1
            await conn.execute(
                stock_history.insert().values(
                    id=sh_counter,
                    producer_id=snap["producer_id"],
                    product_id=snap["product_id"],
                    date=snap["date"],
                    stock_level=snap["stock_level"],
                    reserved=snap["reserved"],
                    available=snap["available"],
                    daily_sales=snap["daily_sales"],
                    restocked_qty=snap["restocked_qty"],
                    stockout_flag=snap["stockout_flag"],
                    day_of_week=snap["day_of_week"],
                    is_weekend=snap["is_weekend"],
                    month=snap["month"],
                    created_at=snap["created_at"],
                )
            )

        # Insert orders + items + payments
        order_counter = 0
        for ord in all_orders:
            await conn.execute(
                orders.insert().values(
                    id=ord["id"],
                    producer_id=ord["producer_id"],
                    customer_id=ord["customer_id"],
                    shop_id=ord["shop_id"],
                    pickup_slot=ord["pickup_slot"],
                    total_amount=ord["total_amount"],
                    status=ord["status"],
                    created_at=ord["created_at"],
                    updated_at=ord["updated_at"],
                )
            )
            for item in ord["items"]:
                await conn.execute(
                    order_items.insert().values(
                        id=order_counter + 1,
                        order_id=item["order_id"],
                        producer_id=item["producer_id"],
                        product_id=item["product_id"],
                        quantity=item["quantity"],
                        unit_price_eur=item["unit_price_eur"],
                        line_total_eur=item["line_total_eur"],
                    )
                )
                order_counter += 1

            # Payment - only if not cancelled/pending
            if ord["status"] not in ("cancelled", "pending"):
                captured_at = ord["created_at"] + timedelta(hours=_RNG.randint(1, 12))
                pay_status = "captured"
                if ord["status"] == "cancelled":
                    pay_status = "refunded"
                await conn.execute(
                    payments.insert().values(
                        id=order_counter + 1,
                        order_id=ord["id"],
                        producer_id=ord["producer_id"],
                        provider=_RNG.choice(["stripe", "paygreen", "mollie"]),
                        provider_ref=f"pi_{ord['id']}_{_RNG.randint(1000, 9999)}",
                        amount_eur=ord["total_amount"],
                        status=pay_status,
                        captured_at=captured_at,
                        created_at=ord["created_at"],
                    )
                )
                order_counter += 1

            # Pickup booking for some orders
            if _RNG.random() < 0.5:
                slot_start = ord["pickup_slot"]
                await conn.execute(
                    pickup_bookings.insert().values(
                        id=order_counter + 1,
                        producer_id=ord["producer_id"],
                        shop_id=ord["shop_id"],
                        customer_id=ord["customer_id"],
                        slot_start=slot_start,
                        slot_end=slot_start + timedelta(minutes=30),
                        status=(
                            "fulfilled" if ord["status"] == "completed"
                            else "confirmed" if ord["status"] in ("paid", "ready_for_pickup")
                            else "cancelled" if ord["status"] == "cancelled"
                            else "pending"
                        ),
                        created_at=ord["created_at"] - timedelta(hours=2),
                    )
                )
                order_counter += 1

    # Sanity-check log: how many rows per producer
    async with engine.connect() as conn:
        result = await conn.execute(
            select(producers.c.id, producers.c.display_name)
        )
        producer_rows = result.fetchall()
        for pid, name in producer_rows:
            r = await conn.execute(
                select(func.count()).select_from(orders).where(orders.c.producer_id == pid)
            )
            n = r.scalar_one()
            r2 = await conn.execute(
                select(func.count()).select_from(stock_history).where(
                    stock_history.c.producer_id == pid
                )
            )
            n_sh = r2.scalar_one()
            r3 = await conn.execute(
                select(func.count()).select_from(stock_history).where(
                    (stock_history.c.producer_id == pid)
                    & (stock_history.c.stockout_flag.is_(True))
                )
            )
            n_rupt = r3.scalar_one()
            logger.info(
                "Producer %s (%s): %d orders, %d stock_history rows (%d ruptures)",
                pid, name, n, n_sh, n_rupt,
            )
        r_total_sh = await conn.execute(select(func.count()).select_from(stock_history))
        n_total_sh = r_total_sh.scalar_one()
        r_total_rupt = await conn.execute(
            select(func.count()).select_from(stock_history).where(
                stock_history.c.stockout_flag.is_(True)
            )
        )
        n_total_rupt = r_total_rupt.scalar_one()
    logger.info(
        "Database seeded - %d producers, %d orders, %d stock_history rows "
        "(%d ruptures - %.1f%% prevalence)",
        len(_PRODUCERS), len(all_orders), n_total_sh, n_total_rupt,
        (100.0 * n_total_rupt / n_total_sh) if n_total_sh else 0.0,
    )

    # ── Documentary RAG seed - 4 fictitious DP documents ──
    # These power the documentary intent (CGV, FAQ, onboarding procedure,
    # pickup policy). All four are tenant-wide (producer_id=NULL) so every
    # producer sees them. They are FICTITIOUS, written for the demo.
    for doc in _DP_DOCUMENTS:
        await ingest_document(
            tenant_id="dp",
            title=doc["title"],
            source_type="manual",
            content=doc["content"],
            producer_id=None,
        )
    async with engine.connect() as conn:
        r = await conn.execute(select(func.count()).select_from(documents))
        n_docs = r.scalar_one()
        r = await conn.execute(select(func.count()).select_from(document_chunks))
        n_chunks = r.scalar_one()
    logger.info(
        "RAG seed - %d documents, %d chunks (CGV, FAQ, Onboarding, Retrait)",
        n_docs, n_chunks,
    )

    # ── Phase 4 - Ops Copilot HITL seed ──
    # 4 fictitious onboarding dossiers + their pre-analyzed approval_requests.
    # The ``agent_analysis`` / ``proposed_decision`` / ``proposed_reason``
    # fields are PRE-FILLED by calling OpsCopilotAgent.analyze_onboarding()
    # during seeding so the admin UI shows the agent's proposal immediately
    # (no lazy-compute on first open). The approval_requests.status stays
    # "pending" - the admin will close the loop via POST /api/approvals/{id}/decide.
    await _seed_onboardings(engine)

    # ── Phase 6a - Auth + multi-tenant platform seed ──
    # Create the demo "dp" tenant + 3 demo users (marie/pierre/admin,
    # password "tevet7demo") + their memberships. Idempotent - safe to
    # call on every startup. The frontend logs in with these credentials
    # to obtain a JWT carrying the tenant context (tenant_id="dp",
    # role="producer", producer_id=42).
    try:
        from app.tenants.service import seed_demo_tenant
        await seed_demo_tenant()
        logger.info("Phase 6a demo tenant + users seeded (dp, marie, pierre, admin)")
    except Exception:  # noqa: BLE001 - never block app startup on auth seed
        logger.exception("seed_demo_tenant() failed - auth endpoints may not work")

    # ── Phase 6b - Onboarding backend: seed the demo tenant's config ──
    # The demo tenant "dp" gets a tenant_configs row with
    # connector_type="sqlite_demo" so the connector factory returns a
    # SqliteConnector for it (same as before - backward compat). The
    # schema_config is the full app/schema.yaml content (the demo's
    # business contract). The roles_config captures the producer/admin
    # scope columns used by the rewriter.
    try:
        await seed_demo_tenant_config()
        logger.info("Phase 6b demo tenant_configs row seeded (dp, sqlite_demo)")
    except Exception:  # noqa: BLE001 - never block app startup
        logger.exception("seed_demo_tenant_config() failed - onboarding endpoints may not work")


async def _seed_onboardings(engine: AsyncEngine) -> None:
    """Insert 4 fictitious onboarding dossiers + their pre-analyzed approval_requests.

    See the comment block on ``producer_onboardings`` for the schema and the
    Phase 4 HITL contract. The agent's pre-analysis is run inline (with the
    real tracer) so each seed-time analysis gets a trace_id persisted on the
    approval_requests row - that ties the human decision back to the agent
    run that proposed it.
    """
    # Local import to avoid a circular dependency at module load time
    # (app.agents.ops_copilot imports app.tracing.base only, but keeping
    # the import local makes the dependency direction explicit).
    import json as _json

    from app.agents.ops_copilot import OpsCopilotAgent
    from app.tracing import get_tracer

    now = datetime.utcnow()
    # Build the 4 dossier dicts. The order here is also the order of the
    # auto-increment ids (1, 2, 3, 4) - relied on by the eval cases and
    # the curl verifications in the worklog.
    dossiers: list[dict[str, Any]] = [
        {
            "tenant_id": "dp",
            "legal_name": "Ferme des Collines",
            "siret": "12345678900012",
            "siret_valid": True,
            "email": "contact@ferme-des-collines.fr",
            "phone": "+33 4 73 11 22 33",
            "declared_address": "15 route des Collines, 63000 Clermont-Ferrand",
            "rib_document_present": True,
            "id_document_present": True,
            "professional_certificate_present": True,
            "professional_certificate_expiry": "2027-12-31",  # future → valid
            "document_address": "15 route des Collines, 63000 Clermont-Ferrand",
            "submitted_at": now,
            "status": "pending",
            "rejection_reason": None,
        },
        {
            "tenant_id": "dp",
            "legal_name": "Maraîchage Bio Soleil",
            "siret": "98765432100025",
            "siret_valid": True,
            "email": "contact@bio-soleil.fr",
            "phone": "+33 4 75 44 55 66",
            "declared_address": "8 chemin du Soleil, 26000 Valence",
            "rib_document_present": True,
            "id_document_present": True,
            "professional_certificate_present": False,  # ← missing
            "professional_certificate_expiry": None,
            "document_address": "8 chemin du Soleil, 26000 Valence",
            "submitted_at": now,
            "status": "pending",
            "rejection_reason": None,
        },
        {
            "tenant_id": "dp",
            "legal_name": "Élevage du Vernet",
            "siret": "11111111111111",
            "siret_valid": False,  # ← SIRENE check failed (legal blocker)
            "email": "contact@elevage-vernet.fr",
            "phone": "+33 5 61 77 88 99",
            "declared_address": "3 lieu-dit le Vernet, 31000 Toulouse",
            "rib_document_present": True,
            "id_document_present": True,
            "professional_certificate_present": True,
            "professional_certificate_expiry": "2027-03-15",  # future → cert OK
            "document_address": "3 lieu-dit le Vernet, 31000 Toulouse",
            "submitted_at": now,
            "status": "pending",
            "rejection_reason": None,
        },
        {
            "tenant_id": "dp",
            "legal_name": "Vignoble des Coteaux",
            "siret": "22222222222222",
            "siret_valid": True,
            "email": "contact@vignoble-coteaux.fr",
            "phone": "+33 3 80 22 33 44",
            "declared_address": "21 rue des Vignes, 21200 Beaune",
            "rib_document_present": True,
            "id_document_present": True,
            "professional_certificate_present": True,
            "professional_certificate_expiry": "2023-05-01",  # ← expired (past)
            "document_address": "4 route des Coteaux, 71100 Chalon-sur-Saône",  # ← mismatch
            "submitted_at": now,
            "status": "pending",
            "rejection_reason": None,
        },
    ]

    # 1) Insert the 4 onboarding rows and capture their auto-incremented ids.
    onboarding_ids: list[int] = []
    async with engine.begin() as conn:
        for ob in dossiers:
            result = await conn.execute(
                producer_onboardings.insert()
                .values(**ob)
                .returning(producer_onboardings.c.id)
            )
            ob_id = int(result.scalar_one())
            onboarding_ids.append(ob_id)

    # 2) Run the agent pre-analysis OUTSIDE the seeding transaction so each
    #    analyze_onboarding() call can write its own trace row without
    #    nested-transaction contention on SQLite.
    agent = OpsCopilotAgent(tracer=get_tracer())
    approval_rows: list[dict[str, Any]] = []
    for ob, ob_id in zip(dossiers, onboarding_ids):
        analysis = await agent.analyze_onboarding({**ob, "id": ob_id})
        approval_rows.append({
            "tenant_id": "dp",
            "onboarding_id": ob_id,
            "request_type": "onboarding_analysis",
            "agent_analysis": _json.dumps(analysis.to_dict(), ensure_ascii=False),
            "proposed_decision": analysis.proposed_decision,
            "proposed_reason": analysis.proposed_reason,
            "status": "pending",  # ← admin has not decided yet
            "decided_by": None,
            "decided_at": None,
            "human_reason": None,
            "created_at": now,
            "trace_id": analysis.trace_id,
        })
        logger.info(
            "Onboarding seed - id=%d legal_name=%r proposed=%s confidence=%d trace_id=%s",
            ob_id, ob["legal_name"], analysis.proposed_decision,
            analysis.confidence, analysis.trace_id,
        )

    # 3) Insert the 4 approval_requests rows.
    async with engine.begin() as conn:
        for row in approval_rows:
            await conn.execute(approval_requests.insert().values(**row))

    logger.info(
        "Ops Copilot seed - %d onboarding dossiers + %d pre-analyzed approval_requests",
        len(dossiers), len(approval_rows),
    )


async def seed_demo_tenant_config() -> None:
    """Seed the demo tenant ``dp`` config row in ``tenant_configs``.

    Idempotent - safe to call on every startup. The row has:
      - connector_type = "sqlite_demo"  (→ SqliteConnector in the factory)
      - connection_url = None
      - csv_path       = None
      - schema_config  = the full app/schema.yaml content (JSON-encoded)
      - roles_config   = {"producer": {"scope_column": "producer_id"},
                          "admin": {"scope_column": null},
                          "customer": {"scope_column": "producer_id"}}
      - onboarded      = True

    The schema_config is loaded from disk so we don't duplicate the YAML
    content in this module. The roles_config mirrors the scoping convention
    defined in app/schema.yaml (row-level scope by producer_id).
    """
    import json as _json
    from pathlib import Path as _Path

    import yaml as _yaml

    engine = get_engine()
    now = datetime.utcnow()
    schema_path = _Path(__file__).resolve().parent / "schema.yaml"
    schema_yaml_text = schema_path.read_text(encoding="utf-8")
    schema_dict = _yaml.safe_load(schema_yaml_text) or {}
    roles_config = {
        "producer": {"scope_column": "producer_id"},
        "admin": {"scope_column": None},
        "customer": {"scope_column": "producer_id"},
    }

    async with engine.connect() as conn:
        r = await conn.execute(
            select(tenant_configs.c.id).where(tenant_configs.c.tenant_id == "dp")
        )
        existing = r.fetchone()
    if existing is not None:
        # Update the schema_config + roles_config + onboarded flag in case
        # the YAML file changed since the last startup (idempotent reseed).
        async with engine.begin() as txn:
            await txn.execute(
                tenant_configs.update().where(tenant_configs.c.tenant_id == "dp").values(
                    connector_type="sqlite_demo",
                    connection_url=None,
                    csv_path=None,
                    schema_config=_json.dumps(schema_dict, ensure_ascii=False),
                    roles_config=_json.dumps(roles_config, ensure_ascii=False),
                    onboarded=True,
                    updated_at=now,
                )
            )
        logger.info("seed_demo_tenant_config - refreshed dp tenant_configs row")
        return
    async with engine.begin() as txn:
        await txn.execute(
            tenant_configs.insert().values(
                tenant_id="dp",
                connector_type="sqlite_demo",
                connection_url=None,
                csv_path=None,
                schema_config=_json.dumps(schema_dict, ensure_ascii=False),
                roles_config=_json.dumps(roles_config, ensure_ascii=False),
                onboarded=True,
                created_at=now,
                updated_at=now,
            )
        )
    logger.info("seed_demo_tenant_config - created dp tenant_configs row")


async def dispose_engine() -> None:
    """Dispose the engine pool (called on app shutdown)."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
    _engine = None


# ─────────────────────────────────────────────────────────────────────────────
# Documentary RAG - chunking + ingest
# ─────────────────────────────────────────────────────────────────────────────


def _chunk_text(content: str, target_size: int = 320, max_size: int = 480) -> list[str]:
    """Split ``content`` into paragraph-sized chunks for FTS5 indexing.

    Strategy:
      1. Split on double newlines (paragraph boundaries).
      2. Each paragraph becomes a candidate chunk.
      3. If a paragraph is longer than ``max_size``, hard-split it at the
         last whitespace before ``target_size`` (preserves word boundaries).
      4. Discard empty chunks.

    The 320-char target keeps chunks small enough to cite cleanly in an
    LLM answer (Phase 6) yet big enough to carry a full clause of the CGV.
    """
    chunks: list[str] = []
    for para in content.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_size:
            chunks.append(para)
            continue
        # Hard-split long paragraphs at word boundaries.
        cursor = 0
        while cursor < len(para):
            end = cursor + target_size
            if end >= len(para):
                chunks.append(para[cursor:].strip())
                break
            # Walk back to the previous whitespace.
            while end > cursor and para[end] not in (" ", "\n"):
                end -= 1
            if end == cursor:  # single word longer than target_size
                end = cursor + target_size
            chunks.append(para[cursor:end].strip())
            cursor = end
    return [c for c in chunks if c]


async def ingest_document(
    tenant_id: str,
    title: str,
    source_type: str,
    content: str,
    producer_id: int | None = None,
    source_filename: str | None = None,
) -> int:
    """Insert a document + its chunks, sync the FTS5 table, return doc id.

    Called by:
      - ``init_db()`` to seed the 4 fictitious DP documents.
      - ``POST /api/documents`` to ingest an uploaded PDF or text file.

    The FTS5 table is synced manually (not via triggers) - see the comment
    on ``document_chunks_fts`` above for the rationale.
    """
    engine = get_engine()
    now = datetime.utcnow()
    chunks = _chunk_text(content)
    async with engine.begin() as conn:
        result = await conn.execute(
            documents.insert().values(
                tenant_id=tenant_id,
                title=title,
                source_type=source_type,
                source_filename=source_filename,
                content_raw=content,
                producer_id=producer_id,
                created_at=now,
            ).returning(documents.c.id)
        )
        doc_id = result.scalar_one()
        for idx, chunk in enumerate(chunks):
            await conn.execute(
                document_chunks.insert().values(
                    document_id=doc_id,
                    chunk_index=idx,
                    content=chunk,
                    tenant_id=tenant_id,
                    producer_id=producer_id,
                    created_at=now,
                )
            )
            # Manual FTS5 sync.
            await conn.execute(
                text(
                    "INSERT INTO document_chunks_fts "
                    "(content, document_id, tenant_id, producer_id) "
                    "VALUES (:content, :doc_id, :tenant_id, :producer_id)"
                ),
                {
                    "content": chunk,
                    "doc_id": doc_id,
                    "tenant_id": tenant_id,
                    "producer_id": producer_id,
                },
            )
    logger.info(
        "ingest_document - doc_id=%d title=%r chunks=%d tenant=%s producer=%s",
        doc_id, title, len(chunks), tenant_id, producer_id,
    )
    return doc_id


async def delete_document(doc_id: int) -> bool:
    """Delete a document, its chunks, and its FTS5 rows. Returns True if deleted.

    Order matters for FTS5: delete from the virtual table first (it has no
    FK constraints), then ``document_chunks``, then ``documents``.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        # Verify existence first (so we can return False cleanly).
        existing = await conn.execute(
            select(documents.c.id).where(documents.c.id == doc_id)
        )
        if existing.fetchone() is None:
            return False
        # 1. FTS5 virtual table (manual sync - no cascade).
        await conn.execute(
            text("DELETE FROM document_chunks_fts WHERE document_id = :doc_id"),
            {"doc_id": doc_id},
        )
        # 2. document_chunks.
        await conn.execute(
            document_chunks.delete().where(document_chunks.c.document_id == doc_id)
        )
        # 3. documents.
        await conn.execute(
            documents.delete().where(documents.c.id == doc_id)
        )
    logger.info("delete_document - doc_id=%d deleted", doc_id)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Seed documents (fictitious, French) - Drive Producteur
# ─────────────────────────────────────────────────────────────────────────────

_DP_DOCUMENTS: list[dict[str, str]] = [
    {
        "title": "CGV Drive Producteur",
        "content": """Conditions Générales de Vente - Drive Producteur (marketplace click & collect)

Article 1 - Objet
Les présentes Conditions Générales de Vente régissent les relations entre les producteurs partenaires de la marketplace Drive Producteur (ci-après « le Producteur ») et la société éditrice de la plateforme (ci-après « DP »). La marketplace met en relation directe les producteurs locaux et les clients finals via un système de commande en ligne et de retrait en point de vente.

Article 2 - Inscription du producteur
L'inscription d'un nouveau producteur est conditionnée à la validation de son dossier d'onboarding : SIRET en cours de validité, extrait Kbis ou équivalent, RIB au nom de la raison sociale, pièce d'identité du représentant légal et justificatif professionnel (numéro d'agrément, certification bio, etc.). DP se réserve un délai de 5 jours ouvrés pour valider ou refuser le dossier.

Article 3 - Commission marketplace
DP perçoit une commission de 12 % sur le montant HT de chaque commande validée. Cette commission couvre l'hébergement de la boutique en ligne, le paiement en ligne sécurisé, le support client de premier niveau et les outils de gestion des créneaux de retrait. La commission est prélevée à la source : le producteur perçoit directement le montant net (HT moins 12 %) sur son RIB.

Article 4 - Paiement au producteur
Le paiement des commandes validées est effectué sous 7 jours ouvrés après la confirmation de retrait par le client. Les paiements sont regroupés en un virement hebdomadaire chaque mardi. Un relevé détaillé des commandes et de la commission prélevée est disponible dans l'espace producteur. En cas de litige sur une commande, le paiement de la commande concernée est suspendu jusqu'à résolution.

Article 5 - Créneaux de retrait (click & collect)
Chaque producteur définit librement ses créneaux de retrait dans son espace producteur (onglet « Créneaux »). Les créneaux doivent être configurés au moins 48 heures à l'avance. Un créneau a une durée minimale de 30 minutes. Le producteur s'engage à être présent au point de vente pendant la totalité de la plage horaire ouverte au retrait.

Article 6 - Annulation par le client
Le client peut annuler sa commande gratuitement jusqu'à 24 heures avant le créneau de retrait. Au-delà, l'annulation est soumise à l'accord du producteur. Un client qui ne se présente pas au créneau de retrait (no-show) déclenche automatiquement la procédure décrite à l'article 7.

Article 7 - No-show client
En cas de non-présentation du client au créneau de retrait convenu, le producteur conserve la marchandise. La commande est marquée « no_show » dans l'espace producteur après 1 heure de retard. Le paiement est néanmoins versé au producteur (la commande a été préparée et le créneau bloqué). Le producteur peut proposer un nouveau créneau de retrait dans les 24 heures au client, sans obligation.

Article 8 - Annulation par le producteur
Le producteur peut annuler une commande en cas de rupture de stock, de problème qualité ou de force majeure. L'annulation doit être notifiée via l'espace producteur avant le créneau de retrait. Le client est intégralement remboursé. En cas d'annulations répétées (plus de 5 % des commandes sur un mois), DP peut suspendre temporairement le catalogue du producteur.

Article 9 - Litiges
Tout litige relatif à une commande (qualité, quantité, retard) doit être signalé via l'espace producteur dans un délai de 48 heures après le retrait. DP joue un rôle de médiateur entre le producteur et le client. À défaut de résolution amiable sous 15 jours, les parties peuvent saisir la juridiction compétente du siège social de DP.

Article 10 - Modification des CGV
DP se réserve le droit de modifier les présentes CGV. Les modifications entrent en vigueur 30 jours après leur notification aux producteurs par email. Les producteurs peuvent résilier leur partenariat sans frais dans ce délai de 30 jours s'ils n'acceptent pas les nouvelles conditions.""",
    },
    {
        "title": "FAQ Producteurs",
        "content": """FAQ Producteurs - Drive Producteur

Q : Comment ajouter un produit à mon catalogue ?
R : Rendez-vous dans l'espace producteur, onglet « Catalogue », puis cliquez sur « Ajouter un produit ». Renseignez le nom du produit, la catégorie (légumes, fruits, produits laitiers, viande, épicerie, boissons), l'unité de vente (kg, pièce, botte, litre, barquette), le prix TTC et la disponibilité. Pensez à ajouter une photo - les produits avec photo se vendent en moyenne 2,5 fois mieux. Le produit apparaît sur la marketplace dans les 5 minutes.

Q : Comment fonctionnent les commissions ?
R : DP perçoit une commission de 12 % sur le montant HT de chaque commande. La commission est prélevée à la source : vous percevez directement le montant net (HT moins 12 %) sur votre RIB. Aucune facturation séparée. Le détail des commissions est disponible dans l'espace producteur, onglet « Paiements ».

Q : Que faire si un client ne vient pas récupérer sa commande ?
R : Si un client ne se présente pas au créneau de retrait, la commande est automatiquement marquée « no_show » après 1 heure de retard. Vous conservez la marchandise et le paiement est néanmoins versé (la commande a été préparée et le créneau bloqué). Vous pouvez, sans obligation, proposer un nouveau créneau de retrait au client dans les 24 heures via l'espace producteur. Au-delà de 24 heures, la commande est définitivement clôturée.

Q : Comment modifier mes créneaux de retrait ?
R : Allez dans l'espace producteur, onglet « Créneaux ». Vous pouvez ajouter, modifier ou supprimer des créneaux. Les modifications doivent être faites au moins 48 heures à l'avance. Un créneau a une durée minimale de 30 minutes. Pensez à anticiper les périodes de forte affluence (week-ends, veilles de fêtes) en ouvrant plus de créneaux.

Q : Quand suis-je payé ?
R : Les paiements sont effectués sous 7 jours ouvrés après la confirmation de retrait par le client. Les virements sont regroupés hebdomadairement, chaque mardi. Vous recevez un email de notification à chaque virement avec le relevé détaillé des commandes.

Q : Comment suspendre temporairement ma boutique ?
R : Dans l'espace producteur, onglet « Paramètres », activez le mode « Pause boutique ». Tous vos produits deviennent indisponibles sur la marketplace mais restent visibles dans votre catalogue. Vous pouvez réactiver la boutique à tout moment.

Q : Comment être mis en avant sur la marketplace ?
R : DP met en avant les producteurs qui : (1) ont une photo de profil et une description de leur exploitation, (2) proposent au moins 8 produits avec photos, (3) respectent leurs créneaux de retrait (taux de no-show < 5 %), (4) ont un délai de réponse aux messages clients inférieur à 24 heures.""",
    },
    {
        "title": "Procédure d'onboarding producteur",
        "content": """Procédure d'onboarding producteur - Drive Producteur

Cette procédure décrit les étapes de validation d'un nouveau producteur sur la marketplace Drive Producteur. Elle s'adresse à l'équipe Ops DP ainsi qu'aux producteurs candidats.

Étape 1 - Création du compte
Le producteur candidat crée son compte sur drive-producteur.fr/onboarding. Il renseigne : raison sociale, nom commercial (display_name), email de contact, téléphone, adresse du siège social. Un email de vérification est envoyé. Le producteur clique sur le lien de vérification pour activer son compte. Le compte est alors en statut « pending ».

Étape 2 - Documents légaux obligatoires
Le producteur téléverse les documents légaux suivants via son espace producteur, onglet « Documents » :
  - SIRET en cours de validité (extrait SIRENE de moins de 3 mois).
  - RIB au nom de la raison sociale (obligatoire pour les virements).
  - Pièce d'identité du représentant légal (recto-verso).
  - Justificatif professionnel : numéro d'agrément, certificat de qualification professionnelle, attestation de certification bio, ou Kbis de moins de 3 mois pour les SARL/EURL.
Champs obligatoires : tous les champs du formulaire sont obligatoires. Aucune soumission partielle n'est acceptée.

Étape 3 - Validation SIRENE
L'équipe Ops DP vérifie le SIRET via l'API SIRENE de l'INSEE. Les points vérifiés : (a) le SIRET existe bien, (b) l'activité déclarée correspond à une production agricole ou artisanale compatible avec la marketplace, (c) l'établissement n'est pas en liquidation judiciaire, (d) l'adresse du siège correspond à l'adresse déclarée par le producteur. Cette étape prend en moyenne 2 jours ouvrés.

Motifs de rejet courants à l'étape 3 :
  - SIRET inexistant ou invalide.
  - Activité non agricole (ex. restauration, commerce de gros).
  - Établissement en liquidation ou redressement judiciaire.
  - Adresse du siège incohérente avec le point de vente déclaré.

Étape 4 - Configuration du catalogue
Une fois le dossier validé (étapes 2 + 3), le producteur configure son catalogue : ajout des produits (nom, catégorie, unité, prix, photo), définition des créneaux de retrait, paramétrage du point de vente (adresse, horaires, coordonnées GPS). L'équipe Ops DP accompagne le producteur sur cette étape si nécessaire.

Étape 5 - Activation
Lorsque le catalogue contient au moins 5 produits et qu'au moins 3 créneaux de retrait sont configurés, l'équipe Ops DP active la boutique. Le producteur reçoit un email de confirmation. La boutique est visible sur la marketplace dans les 24 heures. Un suivi qualité est réalisé à J+7, J+30 et J+90 pour vérifier le bon démarrage.

Délai total moyen : 5 jours ouvrés (dont 2 jours pour la validation SIRENE, 1 jour pour la vérification des documents, 2 jours pour la configuration du catalogue par le producteur).""",
    },
    {
        "title": "Politique de retrait (click & collect)",
        "content": """Politique de retrait - Drive Producteur (click & collect)

Cette politique détaille les règles applicables aux retraits de commandes en point de vente.

Créneaux de retrait
Chaque producteur définit ses propres créneaux de retrait dans son espace producteur. Les créneaux sont configurés au moins 48 heures à l'avance. Un créneau a une durée minimale de 30 minutes. Le producteur s'engage à être présent au point de vente pendant toute la plage horaire ouverte. Les créneaux sont visibles par les clients lors de la commande.

Retard client
Le client est considéré en retard s'il se présente après l'heure de fin de son créneau. Une tolérance de 15 minutes est accordée. Au-delà, le producteur peut refuser la remise de la commande et la marquer comme « no_show ».

No-show (non-présentation client)
Si le client ne se présente pas dans l'heure qui suit la fin de son créneau, la commande est automatiquement marquée « no_show » dans l'espace producteur. La marchandise reste la propriété du producteur. Le paiement est néanmoins versé au producteur (la commande a été préparée et le créneau bloqué). Le producteur peut, sans obligation, proposer un nouveau créneau de retrait dans les 24 heures. Au-delà, la commande est définitivement clôturée.

Modification de créneau par le client
Le client peut modifier son créneau de retrait gratuitement jusqu'à 24 heures avant le créneau initialement choisi. La modification se fait via l'espace client. Au-delà de 24 heures, la modification n'est plus possible - le client doit annuler et recommander.

Annulation par le client
Annulation gratuite jusqu'à 24 heures avant le créneau. Au-delà, l'annulation est soumise à l'accord du producteur (notification via l'espace client). Si le producteur refuse l'annulation tardive, le client est facturé et la commande est conservée à disposition pendant 24 heures.

Annulation par le producteur
Le producteur peut annuler une commande en cas de rupture de stock, de problème qualité ou de force majeure. L'annulation doit être notifiée avant le créneau de retrait via l'espace producteur. Le client est intégralement remboursé. Des annulations répétées (> 5 % des commandes sur un mois) peuvent entraîner la suspension temporaire du catalogue producteur par DP.""",
    },
]
