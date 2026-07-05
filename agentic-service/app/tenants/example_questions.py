"""Schema-driven example question generator (Phase 6d).

Generates a small set of natural-language French questions from a tenant's
``schema_config`` so the Producer Copilot sidebar's "Exemples" section
reflects the tenant's ACTUAL tables/columns (not hardcoded Drive
Producteur questions). Used by ``GET /api/tenants/{tenant_id}/example-questions``.

Algorithm
---------

For each table in the schema_config (in declared order), pick the most
relevant question based on the available column types:

  1. **Metric × group** - a numeric column (non-id, non-geo) plus a
     categorical varchar column (``category``, ``provider``, ``city``,
     ``unit``, ``role``, ``type``, ``brand``, ``country``, ...).
       → ``"Quel est le total de {metric} par {group} ?"``
  2. **Status column** - a varchar column named ``status``.
       → ``"Combien de {table} par statut ?"``
  3. **Metric only** - a numeric column with no categorical group.
       → ``"Quel est le total de {metric} ?"``
  4. **Date column** - a ``timestamp`` / ``date`` / ``datetime`` column.
       → ``"Quelles sont les {table} des 7 derniers jours ?"``
  5. **Name column** - a varchar column named ``name`` / ``label`` /
     ``title`` / ``display_name`` / ``legal_name``.
       → ``"Quels sont les 5 {table} les plus fréquents ?"``
  6. **Fallback** - none of the above.
       → ``"Combien y a-t-il de {table} ?"``

Audit / forbidden tables (``users``, ``audit_logs``, ``compliance_flags``,
``api_keys``, ``webhooks``, anything starting with ``audit_``) are skipped.

The generator returns at most ``max_questions`` items, one per table, in
the order the tables appear in the schema. If the schema_config is empty
or has no tables, the caller (the HTTP endpoint) returns 3 generic
fallback questions instead (see :data:`GENERIC_QUESTIONS`).
"""

from __future__ import annotations

from typing import Any, Iterable

# ─────────────────────────────────────────────────────────────────────────────
# Type / name vocabularies
# ─────────────────────────────────────────────────────────────────────────────

# Coarse type vocabulary used by schema.yaml + the auto-detector in
# app/connectors/postgres_connector.py::_pg_type_to_schema.
_NUMERIC_TYPES = {"integer", "decimal", "float", "numeric", "real", "double", "money"}
_VARCHAR_TYPES = {"varchar", "text", "string", "character", "character varying"}
_DATE_TYPES = {"timestamp", "date", "datetime", "timestamptz"}

# Columns whose names match these patterns are excluded from the "metric"
# set even when their type is numeric - they're identifiers or geo coords.
_ID_COLUMN_NAMES = {"id", "uid", "uuid"}
_GEO_COLUMN_NAMES = {"latitude", "longitude", "lat", "lng", "lon"}

# Varchar columns that are good "group" candidates (categorical, not
# free-form text, not a name).
_GROUP_COLUMN_NAMES = {
    "category", "provider", "city", "unit", "role", "type",
    "country", "region", "department", "brand", "supplier",
}

# Varchar columns whose value is a human-readable name/label.
_NAME_COLUMN_NAMES = {
    "name", "label", "title", "display_name", "legal_name",
    "first_name", "last_name", "full_name",
}

# Tables whose names indicate they're audit / system tables and should
# never appear in the example questions.
_FORBIDDEN_TABLE_PREFIXES = ("audit_", "_audit")
_FORBIDDEN_TABLE_NAMES = {
    "users", "audit_logs", "compliance_flags", "api_keys", "webhooks",
    "payout_bank_accounts",
}


# ─────────────────────────────────────────────────────────────────────────────
# Column classification helpers
# ─────────────────────────────────────────────────────────────────────────────


def _column_type(c: dict[str, Any]) -> str:
    """Coerce a column's type to a lowercase coarse type string.

    Accepts both the schema.yaml form (``decimal``, ``varchar``, ``timestamp``)
    and the information_schema form (``character varying``, ``timestamp without
    time zone``). Strips SQL size/precision suffixes:
    ``varchar(255)`` → ``varchar``, ``decimal(10,2)`` → ``decimal``.
    """
    t = (c.get("type") or c.get("data_type") or "").strip().lower()
    if "(" in t:
        t = t.split("(", 1)[0].strip()
    return t


def _column_name(c: dict[str, Any]) -> str:
    """Return the column's name (supports both ``name`` and ``column_name`` keys)."""
    return (c.get("name") or c.get("column_name") or "").strip()


def _is_id_column(name: str) -> bool:
    n = name.lower()
    if n in _ID_COLUMN_NAMES:
        return True
    return n.endswith("_id") or n.endswith("id")


def _is_geo_column(name: str) -> bool:
    return name.lower() in _GEO_COLUMN_NAMES


def _is_metric(name: str, ctype: str) -> bool:
    """A numeric column we'd actually SUM/AVG (excludes ids + geo coords)."""
    if ctype not in _NUMERIC_TYPES:
        return False
    if _is_id_column(name) or _is_geo_column(name):
        return False
    return True


def _is_status(name: str, ctype: str) -> bool:
    return name.lower() == "status" and ctype in _VARCHAR_TYPES


def _is_date(name: str, ctype: str) -> bool:
    return ctype in _DATE_TYPES


def _is_group(name: str, ctype: str) -> bool:
    """A varchar column good for grouping (categorical, not status, not a name)."""
    n = name.lower()
    if ctype not in _VARCHAR_TYPES:
        return False
    if _is_status(name, ctype):
        return False
    if n in _NAME_COLUMN_NAMES:
        return False
    return n in _GROUP_COLUMN_NAMES


def _is_name(name: str, ctype: str) -> bool:
    return name.lower() in _NAME_COLUMN_NAMES and ctype in _VARCHAR_TYPES


def _is_forbidden_table(name: str) -> bool:
    n = name.lower()
    if n in _FORBIDDEN_TABLE_NAMES:
        return True
    return any(n.startswith(p) for p in _FORBIDDEN_TABLE_PREFIXES)


# ─────────────────────────────────────────────────────────────────────────────
# Per-table question generation
# ─────────────────────────────────────────────────────────────────────────────


def _humanize_table_name(name: str) -> str:
    """Convert a table name to a human-readable French label.

    'order_items' → 'lignes de commande'
    'products' → 'produits'
    'stocks' → 'stocks'
    'orders' → 'commandes'
    'producers' → 'producteurs'
    'shops' → 'points de vente'
    'payments' → 'paiements'
    'pickup_bookings' → 'réservations de retrait'
    Generic: replace _ with space, add French article.
    """
    n = name.lower().replace("-", "_")
    known = {
        "orders": "commandes",
        "order_items": "lignes de commande",
        "products": "produits",
        "producers": "producteurs",
        "stocks": "stocks",
        "shops": "points de vente",
        "payments": "paiements",
        "pickup_bookings": "réservations de retrait",
        "documents": "documents",
        "users": "utilisateurs",
        "tenants": "tenants",
    }
    if n in known:
        return known[n]
    # Generic: replace _ with space.
    return n.replace("_", " ")


def _humanize_column_name(name: str) -> str:
    """Convert a column name to a human-readable French label.

    'price_eur' → 'prix'
    'total_amount' → 'montant total'
    'quantity' → 'quantité'
    'units_sold' → 'unités vendues'
    'category' → 'catégorie'
    """
    n = name.lower()
    known = {
        "price_eur": "prix",
        "total_amount": "montant total",
        "quantity": "quantité",
        "units_sold": "unités vendues",
        "revenue": "chiffre d'affaires",
        "amount": "montant",
        "category": "catégorie",
        "status": "statut",
        "name": "nom",
        "display_name": "nom",
        "legal_name": "nom légal",
        "created_at": "date de création",
        "email": "email",
        "phone": "téléphone",
        "is_active": "actif",
        "is_organic": "bio",
        "vat_rate": "TVA",
        "unit": "unité",
        "available": "disponible",
        "reserved": "réservé",
        "stock_level": "niveau de stock",
    }
    if n in known:
        return known[n]
    # Generic: replace _ with space.
    return n.replace("_", " ")


def _table_question(table: dict[str, Any]) -> str | None:
    """Generate one example question for ``table``, or ``None`` if the
    table should be skipped (audit table, no columns, etc.).

    Uses humanized names (not raw column names) so the user never sees
    'price_eur' - they see 'prix'.
    """
    tname = (table.get("name") or "").strip()
    if not tname or _is_forbidden_table(tname):
        return None
    columns = table.get("columns") or []
    if not columns:
        return None

    tname_human = _humanize_table_name(tname)
    metrics = [c for c in columns if _is_metric(_column_name(c), _column_type(c))]
    groups = [c for c in columns if _is_group(_column_name(c), _column_type(c))]
    statuses = [c for c in columns if _is_status(_column_name(c), _column_type(c))]
    dates = [c for c in columns if _is_date(_column_name(c), _column_type(c))]
    names = [c for c in columns if _is_name(_column_name(c), _column_type(c))]

    # Priority 1: metric × group → "total du prix par catégorie".
    if metrics and groups:
        metric_label = _humanize_column_name(_column_name(metrics[0]))
        group_label = _humanize_column_name(_column_name(groups[0]))
        return f"Quel est le total {metric_label} par {group_label} ?"
    # Priority 2: status column → count by status.
    if statuses:
        return f"Combien de {tname_human} par statut ?"
    # Priority 3: metric only → simple total.
    if metrics:
        metric_label = _humanize_column_name(_column_name(metrics[0]))
        return f"Quel est le total {metric_label} ?"
    # Priority 4: date column → last-7-days filter.
    if dates:
        return f"Quelles sont les {tname_human} des 7 derniers jours ?"
    # Priority 5: name column → top 5.
    if names:
        return f"Quels sont les 5 {tname_human} les plus fréquents ?"
    # Priority 6: fallback count.
    return f"Combien y a-t-il de {tname_human} ?"


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def generate_example_questions(
    schema_config: dict[str, Any] | None,
    max_questions: int = 5,
) -> list[dict[str, str]]:
    """Generate up to ``max_questions`` example questions from a
    tenant's ``schema_config``. Returns a list of ``{id, label}`` dicts.

    If ``schema_config`` is None, empty, or has no tables, returns an
    empty list - the caller is responsible for falling back to generic
    questions (see :data:`GENERIC_QUESTIONS`).
    """
    if not schema_config or not isinstance(schema_config, dict):
        return []
    tables = schema_config.get("tables")
    if not tables or not isinstance(tables, Iterable):
        return []
    out: list[dict[str, str]] = []
    seen_labels: set[str] = set()
    for i, t in enumerate(tables):
        if not isinstance(t, dict):
            continue
        label = _table_question(t)
        if not label or label in seen_labels:
            continue
        seen_labels.add(label)
        out.append({"id": f"q{i + 1}", "label": label})
        if len(out) >= max_questions:
            break
    return out


# Generic questions returned when the tenant is not onboarded yet (no
# schema_config saved, or schema_config has no tables). These work
# against ANY data source since they don't reference any column name.
GENERIC_QUESTIONS: list[dict[str, str]] = [
    {"id": "q1", "label": "Combien de lignes dans ma table ?"},
    {"id": "q2", "label": "Quelles sont les 5 dernières entrées ?"},
    {"id": "q3", "label": "Quel est le total de chaque colonne numérique ?"},
]
