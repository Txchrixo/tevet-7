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
    # Drop + recreate (idempotent)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
        await conn.run_sync(metadata.create_all)
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


async def dispose_engine() -> None:
    """Dispose the engine pool (called on app shutdown)."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
    _engine = None
