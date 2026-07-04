"""SQLite schema + fictitious Drive Producteur data.

Phase 1: the Tevet-7 agentic service runs against an in-process SQLite
database so the demo is self-contained (no Postgres / Docker needed). This
module owns:

1. The SQLAlchemy ``MetaData`` that mirrors ``app/schema.yaml`` (producers,
   shops, products, stocks, orders, order_items, pickup_bookings, payments).
2. A seed routine that populates 7 fictitious producers with realistic
   French agricultural data — different catalogs and sales volumes per
   producer so the row-level scoping demo is tangible.
3. ``init_db()`` — idempotent: drops + recreates all tables and reseeds.
4. ``get_engine()`` — lazy singleton async engine.

The data is FICTITIOUS. Producer names, SIRET, IBAN, addresses are all
invented for the demo.
"""

from __future__ import annotations

import logging
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
# Documentary RAG tables (Task 23 / Phase 3 — RAG layer)
# ─────────────────────────────────────────────────────────────────────────────
# Two physical tables plus one FTS5 virtual table.
#
# ``documents`` — one row per uploaded document (PDF, text, manual note).
#   ``producer_id`` is NULL for tenant-wide documents (CGV, FAQ, etc.) or
#   an int for producer-private documents.
#
# ``document_chunks`` — paragraph-sized chunks (200-400 chars) ready for
#   full-text search. Each chunk carries the same ``tenant_id`` and
#   ``producer_id`` as its parent document so the RAG tool can apply
#   row-level scoping at search time without joining back to ``documents``.
#
# ``document_chunks_fts`` — SQLite FTS5 virtual table (BM25 ranking) that
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
#     single point of swap — replace the FTS5 SELECT with a vector
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
# Ops Copilot — human-in-the-loop onboarding tables (Task 26 / Phase 4)
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
#   ``siret_valid`` is the result of the (out-of-band) SIRENE API call — we
#   store it rather than call INSEE live so the demo is self-contained.
# * ``approval_requests`` is intentionally generic (``request_type`` column)
#   so Phase 5+ can reuse it for ticket classification, refund approval,
#   etc. — every "agent proposes, human decides" workflow lives here.
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
# Observability — traces table (Task 18 / Phase 2 tracing)
# ─────────────────────────────────────────────────────────────────────────────
# One row per ``/api/chat`` request, written by ``LocalTracer.end_trace``.
# The ``traces`` table is created in the same ``metadata.create_all`` call
# as the business tables — no separate migration. JSON-shaped fields
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

# Producer 42 — Marie Dubois, Ferme du Vallon (vegetables).
# Producer 99 — Pierre Martin, Verger de la Côte (apples/pears/cider).
# Producer 17 — Maraîchers du Soleil (vegetables, organic, larger).
# Producer 58 — Élevage des Prés (meat).
# Producer 23 — Fromagerie du Col (dairy / cheese).
# Producer 71 — Apiculteur des Cimes (honey).
# Producer 34 — Vignoble des Bruyères (wine).

_PRODUCERS = [
    {
        "id": 42,
        "legal_name": "EARL Dubois",
        "display_name": "Ferme du Vallon",
        "email": "marie.dubois@ferme-du-vallon.fr",
        "phone": "+33 4 50 12 34 56",
        "siret": "812 345 678 00012",
        "shop": {
            "name": "Ferme du Vallon — Annecy",
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
            "name": "Verger de la Côte — Cruseilles",
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
            "name": "Maraîchers du Soleil — Rumilly",
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
            "name": "Élevage des Prés — La Roche-sur-Foron",
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
            "name": "Fromagerie du Col — Thônes",
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
            "name": "Apiculteur des Cimes — Sallanches",
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
            "name": "Vignoble des Bruyères — Frangy",
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

# Reference "now" — fixed to make June visible in the dataset for the
# "combien j'ai gagné en juin" question. We pretend the demo runs in
# mid-July 2024 so June is a complete prior month.
_REFERENCE_NOW = datetime(2024, 7, 15, 10, 0, 0)
_JUNE_START = datetime(2024, 6, 1, 0, 0, 0)
_JUNE_END = datetime(2024, 6, 30, 23, 59, 59)
_CURRENT_MONTH_START = datetime(2024, 7, 1, 0, 0, 0)


def _generate_orders(
    producer_id: int,
    shop_id: int,
    product_rows: list[dict[str, Any]],
    weights: list[int],
    n_current: int,
    n_june: int,
) -> list[dict[str, Any]]:
    """Build a list of order dicts (header + items) for one producer."""
    orders_out: list[dict[str, Any]] = []
    statuses = ["pending", "paid", "ready_for_pickup", "completed", "completed", "completed", "cancelled"]
    order_id_pool = _RNG.randint(1000, 99999)

    def _make_orders_for_period(n: int, start: datetime, end: datetime) -> None:
        nonlocal order_id_pool
        if end <= start:
            return
        for _ in range(n):
            order_id_pool += 1
            # random timestamp in window
            delta = (end - start).total_seconds()
            ts = start + timedelta(seconds=_RNG.uniform(0, delta))
            # Number of line items
            n_items = _RNG.choices([1, 2, 3, 4, 5], weights=[40, 30, 15, 10, 5])[0]
            chosen_products = _RNG.choices(
                product_rows, weights=weights, k=n_items
            )
            line_total = 0.0
            items: list[dict[str, Any]] = []
            for prod in chosen_products:
                qty = float(_RNG.randint(1, 6))
                # small random price variance around catalogue price
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

    _make_orders_for_period(n_june, _JUNE_START, _JUNE_END)
    _make_orders_for_period(n_current, _CURRENT_MONTH_START, _REFERENCE_NOW)
    return orders_out


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
        # Drop the FTS5 virtual table first (if it exists) — it references
        # ``document_chunks`` so it must go before ``metadata.drop_all``
        # cascades the parent table.
        await conn.execute(text("DROP TABLE IF EXISTS document_chunks_fts"))
        await conn.run_sync(metadata.drop_all)
        await conn.run_sync(metadata.create_all)
        # Create the FTS5 virtual table. ``tokenize = 'porter unicode61'``
        # gives us case-insensitive search + English-stemmer-for-French
        # (good enough for the demo; a French stemmer would be a Phase 6
        # improvement). The ``UNINDEXED`` columns (``document_id``,
        # ``tenant_id``, ``producer_id``) are stored but not tokenised —
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
            for idx, (pname, cat, unit, price, bio) in enumerate(prod["products"]):
                pid = prod["id"] * 100 + idx + 1
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
                }
                product_rows.append(row)
                await conn.execute(products.insert().values(**row))

                # Stock — varies by product (some low for the "rupture" demo)
                base_qty = _RNG.uniform(5, 50)
                reserved = _RNG.uniform(0, min(base_qty * 0.3, 10))
                # Force one or two products into a low-stock situation so the
                # "stock manquant samedi" demo returns something interesting.
                if idx == 3:  # 4th product
                    base_qty = _RNG.uniform(2, 6)
                    reserved = base_qty - 1
                await conn.execute(
                    stocks.insert().values(
                        id=pid,  # one stock row per product
                        producer_id=prod["id"],
                        product_id=pid,
                        shop_id=shop_id,
                        quantity=round(base_qty, 2),
                        reserved=round(reserved, 2),
                        available=round(max(base_qty - reserved, 0), 2),
                        updated_at=_REFERENCE_NOW - timedelta(hours=_RNG.randint(1, 48)),
                    )
                )
            all_product_rows[prod["id"]] = product_rows

        # ── orders + order_items + payments + pickup_bookings ──
        # Build the orders structure first (in-memory), then insert in batches.
        all_orders: list[dict[str, Any]] = []
        for prod in _PRODUCERS:
            shop_id = prod["id"] * 10 + 1
            product_rows = all_product_rows[prod["id"]]
            weights = prod["weights"]
            orders_for_prod = _generate_orders(
                producer_id=prod["id"],
                shop_id=shop_id,
                product_rows=product_rows,
                weights=weights,
                n_current=prod["orders_per_month"]["current"],
                n_june=prod["orders_per_month"]["june"],
            )
            all_orders.extend(orders_for_prod)

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

            # Payment — only if not cancelled/pending
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
            logger.info("Producer %s (%s): %d orders seeded", pid, name, n)
    logger.info("Database seeded — %d producers, %d orders total", len(_PRODUCERS), len(all_orders))

    # ── Documentary RAG seed — 4 fictitious DP documents ──
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
        "RAG seed — %d documents, %d chunks (CGV, FAQ, Onboarding, Retrait)",
        n_docs, n_chunks,
    )

    # ── Phase 4 — Ops Copilot HITL seed ──
    # 4 fictitious onboarding dossiers + their pre-analyzed approval_requests.
    # The ``agent_analysis`` / ``proposed_decision`` / ``proposed_reason``
    # fields are PRE-FILLED by calling OpsCopilotAgent.analyze_onboarding()
    # during seeding so the admin UI shows the agent's proposal immediately
    # (no lazy-compute on first open). The approval_requests.status stays
    # "pending" — the admin will close the loop via POST /api/approvals/{id}/decide.
    await _seed_onboardings(engine)


async def _seed_onboardings(engine: AsyncEngine) -> None:
    """Insert 4 fictitious onboarding dossiers + their pre-analyzed approval_requests.

    See the comment block on ``producer_onboardings`` for the schema and the
    Phase 4 HITL contract. The agent's pre-analysis is run inline (with the
    real tracer) so each seed-time analysis gets a trace_id persisted on the
    approval_requests row — that ties the human decision back to the agent
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
    # auto-increment ids (1, 2, 3, 4) — relied on by the eval cases and
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
            "Onboarding seed — id=%d legal_name=%r proposed=%s confidence=%d trace_id=%s",
            ob_id, ob["legal_name"], analysis.proposed_decision,
            analysis.confidence, analysis.trace_id,
        )

    # 3) Insert the 4 approval_requests rows.
    async with engine.begin() as conn:
        for row in approval_rows:
            await conn.execute(approval_requests.insert().values(**row))

    logger.info(
        "Ops Copilot seed — %d onboarding dossiers + %d pre-analyzed approval_requests",
        len(dossiers), len(approval_rows),
    )


async def dispose_engine() -> None:
    """Dispose the engine pool (called on app shutdown)."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
    _engine = None


# ─────────────────────────────────────────────────────────────────────────────
# Documentary RAG — chunking + ingest
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

    The FTS5 table is synced manually (not via triggers) — see the comment
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
        "ingest_document — doc_id=%d title=%r chunks=%d tenant=%s producer=%s",
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
        # 1. FTS5 virtual table (manual sync — no cascade).
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
    logger.info("delete_document — doc_id=%d deleted", doc_id)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Seed documents (fictitious, French) — Drive Producteur
# ─────────────────────────────────────────────────────────────────────────────

_DP_DOCUMENTS: list[dict[str, str]] = [
    {
        "title": "CGV Drive Producteur",
        "content": """Conditions Générales de Vente — Drive Producteur (marketplace click & collect)

Article 1 — Objet
Les présentes Conditions Générales de Vente régissent les relations entre les producteurs partenaires de la marketplace Drive Producteur (ci-après « le Producteur ») et la société éditrice de la plateforme (ci-après « DP »). La marketplace met en relation directe les producteurs locaux et les clients finals via un système de commande en ligne et de retrait en point de vente.

Article 2 — Inscription du producteur
L'inscription d'un nouveau producteur est conditionnée à la validation de son dossier d'onboarding : SIRET en cours de validité, extrait Kbis ou équivalent, RIB au nom de la raison sociale, pièce d'identité du représentant légal et justificatif professionnel (numéro d'agrément, certification bio, etc.). DP se réserve un délai de 5 jours ouvrés pour valider ou refuser le dossier.

Article 3 — Commission marketplace
DP perçoit une commission de 12 % sur le montant HT de chaque commande validée. Cette commission couvre l'hébergement de la boutique en ligne, le paiement en ligne sécurisé, le support client de premier niveau et les outils de gestion des créneaux de retrait. La commission est prélevée à la source : le producteur perçoit directement le montant net (HT moins 12 %) sur son RIB.

Article 4 — Paiement au producteur
Le paiement des commandes validées est effectué sous 7 jours ouvrés après la confirmation de retrait par le client. Les paiements sont regroupés en un virement hebdomadaire chaque mardi. Un relevé détaillé des commandes et de la commission prélevée est disponible dans l'espace producteur. En cas de litige sur une commande, le paiement de la commande concernée est suspendu jusqu'à résolution.

Article 5 — Créneaux de retrait (click & collect)
Chaque producteur définit librement ses créneaux de retrait dans son espace producteur (onglet « Créneaux »). Les créneaux doivent être configurés au moins 48 heures à l'avance. Un créneau a une durée minimale de 30 minutes. Le producteur s'engage à être présent au point de vente pendant la totalité de la plage horaire ouverte au retrait.

Article 6 — Annulation par le client
Le client peut annuler sa commande gratuitement jusqu'à 24 heures avant le créneau de retrait. Au-delà, l'annulation est soumise à l'accord du producteur. Un client qui ne se présente pas au créneau de retrait (no-show) déclenche automatiquement la procédure décrite à l'article 7.

Article 7 — No-show client
En cas de non-présentation du client au créneau de retrait convenu, le producteur conserve la marchandise. La commande est marquée « no_show » dans l'espace producteur après 1 heure de retard. Le paiement est néanmoins versé au producteur (la commande a été préparée et le créneau bloqué). Le producteur peut proposer un nouveau créneau de retrait dans les 24 heures au client, sans obligation.

Article 8 — Annulation par le producteur
Le producteur peut annuler une commande en cas de rupture de stock, de problème qualité ou de force majeure. L'annulation doit être notifiée via l'espace producteur avant le créneau de retrait. Le client est intégralement remboursé. En cas d'annulations répétées (plus de 5 % des commandes sur un mois), DP peut suspendre temporairement le catalogue du producteur.

Article 9 — Litiges
Tout litige relatif à une commande (qualité, quantité, retard) doit être signalé via l'espace producteur dans un délai de 48 heures après le retrait. DP joue un rôle de médiateur entre le producteur et le client. À défaut de résolution amiable sous 15 jours, les parties peuvent saisir la juridiction compétente du siège social de DP.

Article 10 — Modification des CGV
DP se réserve le droit de modifier les présentes CGV. Les modifications entrent en vigueur 30 jours après leur notification aux producteurs par email. Les producteurs peuvent résilier leur partenariat sans frais dans ce délai de 30 jours s'ils n'acceptent pas les nouvelles conditions.""",
    },
    {
        "title": "FAQ Producteurs",
        "content": """FAQ Producteurs — Drive Producteur

Q : Comment ajouter un produit à mon catalogue ?
R : Rendez-vous dans l'espace producteur, onglet « Catalogue », puis cliquez sur « Ajouter un produit ». Renseignez le nom du produit, la catégorie (légumes, fruits, produits laitiers, viande, épicerie, boissons), l'unité de vente (kg, pièce, botte, litre, barquette), le prix TTC et la disponibilité. Pensez à ajouter une photo — les produits avec photo se vendent en moyenne 2,5 fois mieux. Le produit apparaît sur la marketplace dans les 5 minutes.

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
        "content": """Procédure d'onboarding producteur — Drive Producteur

Cette procédure décrit les étapes de validation d'un nouveau producteur sur la marketplace Drive Producteur. Elle s'adresse à l'équipe Ops DP ainsi qu'aux producteurs candidats.

Étape 1 — Création du compte
Le producteur candidat crée son compte sur drive-producteur.fr/onboarding. Il renseigne : raison sociale, nom commercial (display_name), email de contact, téléphone, adresse du siège social. Un email de vérification est envoyé. Le producteur clique sur le lien de vérification pour activer son compte. Le compte est alors en statut « pending ».

Étape 2 — Documents légaux obligatoires
Le producteur téléverse les documents légaux suivants via son espace producteur, onglet « Documents » :
  - SIRET en cours de validité (extrait SIRENE de moins de 3 mois).
  - RIB au nom de la raison sociale (obligatoire pour les virements).
  - Pièce d'identité du représentant légal (recto-verso).
  - Justificatif professionnel : numéro d'agrément, certificat de qualification professionnelle, attestation de certification bio, ou Kbis de moins de 3 mois pour les SARL/EURL.
Champs obligatoires : tous les champs du formulaire sont obligatoires. Aucune soumission partielle n'est acceptée.

Étape 3 — Validation SIRENE
L'équipe Ops DP vérifie le SIRET via l'API SIRENE de l'INSEE. Les points vérifiés : (a) le SIRET existe bien, (b) l'activité déclarée correspond à une production agricole ou artisanale compatible avec la marketplace, (c) l'établissement n'est pas en liquidation judiciaire, (d) l'adresse du siège correspond à l'adresse déclarée par le producteur. Cette étape prend en moyenne 2 jours ouvrés.

Motifs de rejet courants à l'étape 3 :
  - SIRET inexistant ou invalide.
  - Activité non agricole (ex. restauration, commerce de gros).
  - Établissement en liquidation ou redressement judiciaire.
  - Adresse du siège incohérente avec le point de vente déclaré.

Étape 4 — Configuration du catalogue
Une fois le dossier validé (étapes 2 + 3), le producteur configure son catalogue : ajout des produits (nom, catégorie, unité, prix, photo), définition des créneaux de retrait, paramétrage du point de vente (adresse, horaires, coordonnées GPS). L'équipe Ops DP accompagne le producteur sur cette étape si nécessaire.

Étape 5 — Activation
Lorsque le catalogue contient au moins 5 produits et qu'au moins 3 créneaux de retrait sont configurés, l'équipe Ops DP active la boutique. Le producteur reçoit un email de confirmation. La boutique est visible sur la marketplace dans les 24 heures. Un suivi qualité est réalisé à J+7, J+30 et J+90 pour vérifier le bon démarrage.

Délai total moyen : 5 jours ouvrés (dont 2 jours pour la validation SIRENE, 1 jour pour la vérification des documents, 2 jours pour la configuration du catalogue par le producteur).""",
    },
    {
        "title": "Politique de retrait (click & collect)",
        "content": """Politique de retrait — Drive Producteur (click & collect)

Cette politique détaille les règles applicables aux retraits de commandes en point de vente.

Créneaux de retrait
Chaque producteur définit ses propres créneaux de retrait dans son espace producteur. Les créneaux sont configurés au moins 48 heures à l'avance. Un créneau a une durée minimale de 30 minutes. Le producteur s'engage à être présent au point de vente pendant toute la plage horaire ouverte. Les créneaux sont visibles par les clients lors de la commande.

Retard client
Le client est considéré en retard s'il se présente après l'heure de fin de son créneau. Une tolérance de 15 minutes est accordée. Au-delà, le producteur peut refuser la remise de la commande et la marquer comme « no_show ».

No-show (non-présentation client)
Si le client ne se présente pas dans l'heure qui suit la fin de son créneau, la commande est automatiquement marquée « no_show » dans l'espace producteur. La marchandise reste la propriété du producteur. Le paiement est néanmoins versé au producteur (la commande a été préparée et le créneau bloqué). Le producteur peut, sans obligation, proposer un nouveau créneau de retrait dans les 24 heures. Au-delà, la commande est définitivement clôturée.

Modification de créneau par le client
Le client peut modifier son créneau de retrait gratuitement jusqu'à 24 heures avant le créneau initialement choisi. La modification se fait via l'espace client. Au-delà de 24 heures, la modification n'est plus possible — le client doit annuler et recommander.

Annulation par le client
Annulation gratuite jusqu'à 24 heures avant le créneau. Au-delà, l'annulation est soumise à l'accord du producteur (notification via l'espace client). Si le producteur refuse l'annulation tardive, le client est facturé et la commande est conservée à disposition pendant 24 heures.

Annulation par le producteur
Le producteur peut annuler une commande en cas de rupture de stock, de problème qualité ou de force majeure. L'annulation doit être notifiée avant le créneau de retrait via l'espace producteur. Le client est intégralement remboursé. Des annulations répétées (> 5 % des commandes sur un mois) peuvent entraîner la suspension temporaire du catalogue producteur par DP.""",
    },
]
