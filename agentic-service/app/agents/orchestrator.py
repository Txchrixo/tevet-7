"""Agent orchestrator — Phase 1 (no LLM, rule-based).

Phase 1 deliberately avoids an LLM so the demo is deterministic and the
security argument (sqlglot row-level scoping) is the real focus. The
``SQLGenerator`` protocol in ``app.tools.sql_tool`` lets us swap in an
LLM-based generator in Phase 2 without touching this orchestrator.

Loop semantics
--------------

1. The orchestrator asks the ``SqlReadTool`` to translate the question
   into SQL (rule-based), validate + rewrite it (sqlglot), and execute
   it (read-only SQLite connection).
2. It inspects the ``ToolResult``:
   a. If ``success`` and no security incident: build the natural-language
      answer + ChartSpec from the query rows.
   b. If the tool explicitly refused (cross-producer question from a
      producer): build a polite refusal response.
   c. If a security incident was caught: build a refusal response.
3. Build the ``AgentResponse`` with the full audit trail: steps,
   security_checks, tokens, latency, etc.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.connectors.base import QueryResult
from app.tools.forecast_tool import (
    ForecastResult,
    ForecastTool,
    render_forecast_answer,
    render_forecast_chart,
)
from app.tools.rag_tool import RagSearchTool, RagResult
from app.tools.sql_tool import REFUSE_MARKER, SqlReadTool, ToolResult
from app.tracing.base import Span, TraceContext, Tracer

logger = logging.getLogger("tevet7.orchestrator")


# ─────────────────────────────────────────────────────────────────────────────
# Ops Copilot — known onboarding dossier names (Phase 4)
# ─────────────────────────────────────────────────────────────────────────────
# Used by ``_run_ops_copilot`` to map a free-text question like
# "Analyse le dossier d'onboarding de Ferme des Collines" to a
# producer_onboardings row. Loaded lazily on the first ops_analysis request.
#
# We don't ship a hardcoded list — we load the names from the DB so new
# dossiers submitted after startup are also resolvable through chat.
_OPS_ONBOARDING_NAMES: list[tuple[int, str]] | None = None


# ─────────────────────────────────────────────────────────────────────────────
# No-op tracer (used when callers don't supply one)
# ─────────────────────────────────────────────────────────────────────────────


class _NoopTracer:
    """Fallback tracer that does nothing — used when callers don't supply one.

    The chat API always passes a real tracer (LocalTracer or LangfuseTracer
    via :func:`app.tracing.get_tracer`); this class only exists so the
    orchestrator can be constructed in scripts and tests without a tracer.
    """

    def start_trace(self, user_message: str, identity: dict[str, Any]) -> TraceContext:
        return TraceContext(
            trace_id=TraceContext.new_trace_id(),
            user_message=user_message,
            identity=dict(identity),
        )

    def start_span(self, ctx: TraceContext, name: str, **metadata: Any) -> Span:
        span = Span(name=name, started_at=time.monotonic(), metadata=dict(metadata))
        ctx.spans.append(span)
        return span

    def end_span(
        self,
        ctx: TraceContext,
        span: Span,
        status: str = "ok",
        **metadata: Any,
    ) -> None:
        span.ended_at = time.monotonic()
        span.status = status
        if metadata:
            span.metadata.update(metadata)

    async def end_trace(self, ctx: TraceContext, result: dict[str, Any]) -> str:
        return ctx.trace_id

    def flush(self) -> None:
        return None

# ─────────────────────────────────────────────────────────────────────────────
# Tool protocol
# ─────────────────────────────────────────────────────────────────────────────


class Tool(Protocol):
    """Structural type every tool passed to the orchestrator must satisfy."""

    async def run(self, question: str) -> Any:  # ToolResult | ...
        ...


# ─────────────────────────────────────────────────────────────────────────────
# Result
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class StepTrace:
    """One step of the agent's reasoning/execution trace."""

    index: int
    title: str
    detail: str
    status: str  # "ok" | "blocked" | "warning"
    duration_ms: int


@dataclass
class SecurityCheck:
    """One row of the security checklist shown in the inspector."""

    label: str
    status: str  # "ok" | "blocked" | "warning"
    detail: str


@dataclass
class AgentResponse:
    """Structured response returned by ``AgentOrchestrator.run``.

    Fields mirror the JSON contract documented in ``app/api/chat.py`` so the
    FastAPI handler can serialise it 1:1.
    """

    answer: str
    sql: str | None = None
    scope_clause: str | None = None
    chart: dict[str, Any] | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    tool_calls: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    security_checks: list[dict[str, Any]] = field(default_factory=list)
    refused: bool = False
    tables_touched: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    trace_url: str | None = None
    # Phase 4 — Ops Copilot HITL: when the intent is ``ops_analysis``, this
    # field carries the full ``OpsAnalysis.to_dict()`` (issues,
    # proposed_decision, proposed_reason, confidence, checks, …) so the
    # chat endpoint can surface it in the JSON response. ``None`` for all
    # other intents.
    ops_analysis: dict[str, Any] | None = None
    # Phase 2 tracing — id of the row written to the ``traces`` table (and
    # optionally to Langfuse). ``None`` means tracing was disabled.
    trace_id: str | None = None
    # Phase 5 — ML forecast. When the intent is ``stock_shortfall`` and the
    # forecast_tool produced predictions, this carries the full ForecastResult
    # (top-k predictions, probability per product, top_factor, latency). Null
    # for all other intents and for the SQL-fallback path.
    forecast_predictions: list[dict[str, Any]] | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Intent classification (mirrors the rule-based generator's branching)
# ─────────────────────────────────────────────────────────────────────────────


def classify_question(question: str, role: str) -> str:
    """Return one of: ops_analysis | top_products | stock_shortfall |
    net_revenue | weekly_sales | cross_producer | documentary | unknown.

    Used by the formatter to pick the right answer template. The
    RuleBasedSQLGenerator mirrors this branching — keep them in sync.

    Classification priority (Phase 4):
        1. cross_producer  — admin-only aggregation across producers.
        2. ops_analysis    — admin-only Ops Copilot onboarding analysis
                             ("analyse le dossier", "valider un producteur",
                             "dossier d'onboarding", …).
        3. analytical (strong signals) — top_products, stock_shortfall,
                                          weekly_sales.
        4. documentary     — CGV / FAQ / onboarding / retrait questions.
        5. net_revenue     — money questions ("commission", "gagné", …).
        6. unknown         — fallback.

    The ``ops_analysis`` intent is checked ABOVE documentary so a question
    like "Analyse le dossier d'onboarding de Ferme des Collines" routes to
    the Ops Copilot agent (not the RAG documentary retriever) even though
    it contains "onboarding" (a documentary keyword).

    The documentary intent is detected when the question contains policy
    keywords ("comment", "quoi", "quelle", "procédure", "CGV", "FAQ",
    "comment faire", "que faire", "combien de temps", "quand", "où",
    "qui peut", "policy", "règle", "conditions") AND does NOT contain
    strong analytical signals ("combien j'ai vendu", "top produits",
    "stock", "gagné"). If ambiguous (e.g. "combien de temps pour être
    payé" — could be revenue or doc), prefer documentary.

    The net_revenue intent is checked AFTER documentary so that a question
    like "Comment fonctionnent les commissions ?" (which contains
    "commission") is classified as documentary, while "Détaille ma
    commission marketplace ?" (no documentary keyword) stays net_revenue.
    """
    q = question.lower()

    # 1. cross-producer ranking — admin-only.
    if "producteur" in q and ("commande" in q or "vente" in q):
        return "cross_producer"

    # 2. ops_analysis — admin-only Ops Copilot onboarding pre-analysis.
    #    Trigger phrases:
    #      - "analyse le dossier" / "analyser le dossier" / "analyse du dossier"
    #      - "dossier d onboarding" / "dossier d'onboarding"
    #      - "analyse le producteur" / "analyser le producteur"
    #      - "pré-analyse" / "pre-analyse" / "preanalyse"
    #    We deliberately do NOT trigger on bare "valider un producteur" or
    #    bare "onboarding" — those are documentary keywords ("Quelles pièces
    #    sont nécessaires pour valider un producteur ?" is a doc question
    #    about the onboarding procedure, NOT an ops analysis request). The
    #    distinguishing factor is the verb "analyse" / "analyser" or the
    #    compound noun "dossier d'onboarding".
    ops_keywords = (
        "analyse le dossier", "analyser le dossier", "analyse du dossier",
        "analyse le dossier d onboarding", "analyse le dossier d'onboarding",
        "dossier d onboarding", "dossier d'onboarding",
        "valider un dossier", "valider le dossier",
        "pré-analyse", "pre-analyse", "preanalyse",
        "analyse le producteur", "analyser le producteur",
        "analyse l onboarding", "analyser l onboarding",
        "analyse l'onboarding", "analyser l'onboarding",
    )
    if any(k in q for k in ops_keywords):
        return "ops_analysis"

    # 3. analytical intents with strong, unambiguous signals.
    if ("produit" in q or "vendu" in q or "vente" in q) and (
        "top" in q or "plus" in q or "best" in q or "meilleur" in q
    ):
        return "top_products"
    if any(k in q for k in ("stock", "manqu", "rupture", "samedi", "épuis")):
        return "stock_shortfall"
    if any(k in q for k in ("résumé", "resume", "semaine", "synthèse", "synthese")):
        return "weekly_sales"

    # 4. documentary — policy / FAQ / procedure questions.
    #    Checked BEFORE net_revenue so "Comment fonctionnent les
    #    commissions ?" routes to RAG (not to the revenue SQL).
    #    NOTE: we deliberately do NOT include "quel"/"quelle" here — too
    #    broad (it would catch "Quel est mon chiffre d'affaires ?" and
    #    route a revenue question to RAG). The specific question words
    #    "comment", "que faire", "combien de temps", "quand" are enough
    #    to cover the documentary intent.
    doc_keywords = (
        "comment", "quoi", "procédure", "procedure",
        "cgv", "faq", "comment faire", "que faire", "combien de temps",
        "quand", "où", "ou ", "qui peut", "policy", "règle", "regle",
        "conditions", "paiement", "payé", "paye", "créneau", "creneau",
        "retrait", "onboarding", "no-show", "no_show", "noshow",
        "ajouter", "modifier", "annuler", "remboursement", "litige",
        "document", "pièces", "pieces", "siret", "rib", "identité",
        "valider", "validation", "inscription", "catalogue",
    )
    if any(k in q for k in doc_keywords):
        return "documentary"

    # 5. net_revenue — money questions without a documentary keyword.
    if any(
        k in q for k in
        ("gagné", "gagne", "net", "commission", "chiffre", "ca ", "revenu", "recette")
    ):
        return "net_revenue"

    # 6. unknown.
    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Formatter — turns SQL rows into natural-language French + a ChartSpec
# ─────────────────────────────────────────────────────────────────────────────


# Producer display name lookup so we can say "Ferme du Vallon" rather than
# "producer 42" in the answers. Loaded lazily.
_PRODUCER_NAMES: dict[int, str] | None = None


async def _producer_name(producer_id: int) -> str:
    """Return the producer display name for the given id, falling back to
    ``producteur #{id}`` if the DB is unreachable.
    """
    global _PRODUCER_NAMES
    if _PRODUCER_NAMES is None:
        _PRODUCER_NAMES = {}
        try:
            from sqlalchemy import select

            from app.db_seed import get_engine, producers

            engine = get_engine()
            async with engine.connect() as conn:
                r = await conn.execute(select(producers.c.id, producers.c.display_name))
                for pid, name in r.fetchall():
                    _PRODUCER_NAMES[pid] = name
        except Exception:  # noqa: BLE001 — fallback to a generic label
            pass
    return _PRODUCER_NAMES.get(producer_id, f"producteur #{producer_id}")


def _format_eur(value: float) -> str:
    """Format a float as a French-euros string: ``1 234,56 €``."""
    try:
        s = f"{float(value):.2f}".replace(".", ",")
        # thousands separator (non-breaking space)
        int_part, _, dec = s.partition(",")
        int_part = f"{int(int_part):,}".replace(",", "\u202f")
        return f"{int_part},{dec} €"
    except Exception:  # noqa: BLE001
        return f"{value} €"


def _format_units(value: float, unit: str | None = None) -> str:
    try:
        v = int(value)
        return f"{v} {unit}" if unit else f"{v}"
    except Exception:  # noqa: BLE001
        return f"{value} {unit}" if unit else f"{value}"


async def _format_top_products(
    question: str, result: QueryResult, producer_id: int | None
) -> tuple[str, dict[str, Any] | None]:
    """Top-products answer + bar chart spec (markdown-formatted).

    Phase A1: column-name agnostic — finds the name/label column and the
    numeric columns by type, not by hardcoded alias names. Works with both
    the rule-based generator (AS units_sold, AS revenue) and the LLM
    generator (AS total_quantity, AS total_amount, etc.).
    """
    rows = result.as_dicts()
    if not rows:
        return (
            "Aucune vente enregistrée ce mois-ci pour votre exploitation.",
            None,
        )

    # ── Flexible column detection ──
    first_row = rows[0]
    all_keys = list(first_row.keys())

    # Find name/label column (for display).
    name_key = next(
        (k for k in all_keys if k.lower() in ("name", "product_name", "label", "title", "producer_name", "display_name")),
        all_keys[0] if all_keys else "name",
    )

    # Find units/quantity column (numeric, not revenue).
    units_key = next(
        (k for k in all_keys if any(w in k.lower() for w in ("unit", "quantity", "count", "qty", "total_quantity", "sold", "freq"))),
        None,
    )

    # Find revenue/amount column (numeric, money-related).
    revenue_key = next(
        (k for k in all_keys if any(w in k.lower() for w in ("revenue", "amount", "total", "sum", "money", "price", "ca"))),
        None,
    )

    # If no specific units/revenue found, use any remaining numeric columns.
    if not units_key and not revenue_key:
        # Just use all numeric columns.
        numeric_keys = [k for k in all_keys if k != name_key]
        if len(numeric_keys) >= 2:
            units_key = numeric_keys[0]
            revenue_key = numeric_keys[1]
        elif len(numeric_keys) == 1:
            units_key = numeric_keys[0]

    total_revenue = sum(float(r.get(revenue_key, 0)) for r in rows) if revenue_key else 0
    top_row = rows[0]
    top_name = top_row.get(name_key, "?")
    top_revenue = float(top_row.get(revenue_key, 0)) if revenue_key else 0
    top_pct = int((top_revenue / total_revenue * 100)) if total_revenue > 0 else 0
    if producer_id is not None:
        prod_name = await _producer_name(producer_id)
        intro = f"Vos **5 produits les plus vendus ce mois-ci** ({prod_name}) :\n\n"
    else:
        intro = "**Top 5 des produits les plus vendus ce mois-ci** :\n\n"
    lines: list[str] = []
    chart_data: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        name = row.get(name_key, "?")
        units = int(float(row.get(units_key, 0))) if units_key else 0
        revenue = float(row.get(revenue_key, 0)) if revenue_key else 0
        if revenue_key and units_key:
            lines.append(f"{i}. **{name}** — {units} unités · {_format_eur(revenue)}")
        elif units_key:
            lines.append(f"{i}. **{name}** — {units}")
        elif revenue_key:
            lines.append(f"{i}. **{name}** — {_format_eur(revenue)}")
        else:
            lines.append(f"{i}. **{name}**")
        chart_data.append({"name": name, "units_sold": float(units), "revenue": revenue})
    insight = (
        f"\n\nLes {top_name.lower()} représentent **{top_pct} %** de votre "
        "chiffre d'affaires du mois. Pensez à anticiper le réassort pour le week-end."
    ) if total_revenue > 0 else ""
    answer = intro + "\n".join(lines) + insight
    chart = {
        "type": "bar",
        "title": "Top 5 — ce mois-ci",
        "xKey": "name",
        "series": [
            {"key": "units_sold", "label": "Unités vendues", "color": "#A8C090"}
        ],
        "data": chart_data,
        "unit": "unités",
    }
    return answer, chart


async def _format_stock_shortfall(
    question: str, result: QueryResult, producer_id: int | None
) -> tuple[str, dict[str, Any] | None]:
    rows = result.as_dicts()
    if not rows:
        return (
            "Aucun produit en risque de rupture sur les prochains créneaux. "
            "Vos stocks sont confortables.",
            None,
        )
    threshold = 10
    intro = (
        f"Pour les **retraits de samedi**, {len(rows)} références "
        "risquent de vous manquer :\n\n"
    )
    table = "| Produit | Stock dispo. | Déficit |\n|---|---:|---:|\n"
    chart_data: list[dict[str, Any]] = []
    critical: list[str] = []
    for row in rows:
        name = row.get("name", "?")
        avail = float(row.get("available", 0))
        deficit = max(threshold - avail, 0)
        table += f"| {name} | {int(avail)} | **-{int(deficit)}** |\n"
        chart_data.append({"name": name, "available": avail, "deficit": deficit})
        if deficit >= 5:
            critical.append(name)
    if critical:
        reco = (
            f"\nJe recommande de réapprovisionner **{critical[0]}** "
            "avant vendredi 18h. Les autres références sont limites mais couvrables."
        )
    else:
        reco = (
            "\nJe recommande de surveiller ces références, mais elles restent "
            "couvrables pour les prochains créneaux."
        )
    answer = intro + table + reco
    chart = {
        "type": "bar",
        "title": "Stock disponible — produits à risque",
        "xKey": "name",
        "series": [
            {"key": "available", "label": "Stock disponible", "color": "#A8C090"},
        ],
        "data": chart_data,
        "unit": "unités",
    }
    return answer, chart


async def _format_net_revenue(
    question: str, result: QueryResult, producer_id: int | None
) -> tuple[str, dict[str, Any] | None]:
    rows = result.as_dicts()
    if not rows:
        return "Aucune donnée de revenu sur la période demandée.", None
    row = rows[0]
    gross = float(row.get("gross_revenue", 0))
    net = float(row.get("net_revenue", 0))
    n_orders = int(row.get("order_count", 0))
    month_label = row.get("month_label", "ce mois-ci")
    commission = gross - net
    avg_basket = (gross / n_orders) if n_orders > 0 else 0.0
    prod_name = ""
    if producer_id is not None:
        prod_name = f" — {await _producer_name(producer_id)}"
    answer = (
        f"**Synthèse de vos revenus** — {month_label}{prod_name}\n\n"
        f"- **Brut** : {_format_eur(gross)} ({n_orders} commandes)\n"
        f"- **Commission marketplace** (12 %) : {_format_eur(commission)}\n"
        f"- **Net perçu** : {_format_eur(net)}\n\n"
        f"Votre panier moyen est de **{_format_eur(avg_basket)}**."
    )
    return answer, None


async def _format_weekly_sales(
    question: str, result: QueryResult, producer_id: int | None
) -> tuple[str, dict[str, Any] | None]:
    rows = result.as_dicts()
    if not rows:
        return "Aucune vente enregistrée cette semaine.", None
    total_rev = sum(float(r.get("revenue", 0)) for r in rows)
    total_orders = sum(int(r.get("order_count", 0)) for r in rows)
    avg_basket = (total_rev / total_orders) if total_orders > 0 else 0.0
    prod_name = ""
    if producer_id is not None:
        prod_name = f" — {await _producer_name(producer_id)}"
    answer = (
        f"**Résumé de vos ventes de la semaine**{prod_name}\n\n"
        f"- **{total_orders} commandes** sur {len(rows)} jours d'activité\n"
        f"- **Chiffre d'affaires** : {_format_eur(total_rev)}\n"
        f"- **Panier moyen** : {_format_eur(avg_basket)}\n\n"
        "Le graphique ci-dessous montre l'évolution quotidienne."
    )
    chart = {
        "type": "line",
        "title": "Ventes — cette semaine",
        "xKey": "day",
        "series": [
            {"key": "revenue", "label": "Chiffre d'affaires (€)", "color": "#A8C090"},
            {"key": "order_count", "label": "Commandes", "color": "#5A6B4A"},
        ],
        "data": [
            {
                "day": r.get("day", ""),
                "revenue": float(r.get("revenue", 0)),
                "order_count": int(r.get("order_count", 0)),
            }
            for r in rows
        ],
        "unit": "€",
    }
    return answer, chart


async def _format_cross_producer(
    question: str, result: QueryResult
) -> tuple[str, dict[str, Any] | None]:
    rows = result.as_dicts()
    if not rows:
        return "Aucun producteur actif sur la période.", None
    total_orders = sum(int(r.get("order_count", 0)) for r in rows)
    top_two = sum(int(r.get("order_count", 0)) for r in rows[:2])
    top_pct = int((top_two / total_orders * 100)) if total_orders > 0 else 0
    lines: list[str] = []
    chart_data = []
    for i, row in enumerate(rows, start=1):
        name = row.get("producer_name", "?")
        n = int(row.get("order_count", 0))
        rev = float(row.get("revenue_eur", 0))
        lines.append(f"{i}. **{name}** — {n} commandes · {_format_eur(rev)}")
        chart_data.append({"producer_name": name, "order_count": n, "revenue_eur": rev})
    answer = (
        "**Classement des producteurs** par nombre de commandes ce mois-ci :\n\n"
        + "\n".join(lines)
        + f"\n\nLes deux premiers représentent **{top_pct} %** du volume mensuel."
    )
    chart = {
        "type": "bar",
        "title": "Classement producteurs — commandes ce mois-ci",
        "xKey": "producer_name",
        "series": [
            {"key": "order_count", "label": "Commandes", "color": "#A8C090"},
        ],
        "data": chart_data,
        "unit": "commandes",
    }
    return answer, chart


async def format_answer(
    question: str,
    intent: str,
    result: QueryResult,
    producer_id: int | None,
    role: str,
) -> tuple[str, dict[str, Any] | None]:
    """Dispatch to the right formatter based on the intent classification."""
    if intent == "top_products":
        return await _format_top_products(question, result, producer_id)
    if intent == "stock_shortfall":
        return await _format_stock_shortfall(question, result, producer_id)
    if intent == "net_revenue":
        return await _format_net_revenue(question, result, producer_id)
    if intent == "weekly_sales":
        return await _format_weekly_sales(question, result, producer_id)
    if intent == "cross_producer":
        return await _format_cross_producer(question, result)
    return "Voici les résultats de votre requête.", None


# ─────────────────────────────────────────────────────────────────────────────
# Documentary RAG formatter — turns FTS5 chunks into a cited French answer
# ─────────────────────────────────────────────────────────────────────────────


def _truncate_chunk(content: str, max_chars: int = 480) -> str:
    """Trim a chunk to ``max_chars`` on a word boundary for the answer body."""
    if len(content) <= max_chars:
        return content
    cut = content.rfind(" ", 0, max_chars)
    if cut == -1:
        cut = max_chars
    return content[:cut].rstrip() + "…"


def format_documentary_answer(
    question: str,
    rag_result: RagResult,
) -> tuple[str, list[dict[str, Any]]]:
    """Build a cited French answer from the RAG chunks.

    Returns ``(answer, sources)`` where ``sources`` is the list of
    ``{type: "document", title, chunk_index, document_id}`` dicts that
    populate ``AgentResponse.sources``.

    If no chunks were retrieved, returns a polite "not found" message and
    an empty sources list.
    """
    if not rag_result.chunks:
        return (
            "Je n'ai pas trouvé d'information à ce sujet dans la base documentaire. "
            "Pouvez-vous reformuler ou contacter l'équipe Ops ?",
            [],
        )

    # Build the answer body: intro + each chunk quoted + sources footer.
    chunks = rag_result.chunks
    parts: list[str] = [
        "D'après la base documentaire Drive Producteur :",
        "",
    ]
    sources: list[dict[str, Any]] = []
    seen_doc_ids: set[int] = set()
    for i, chunk in enumerate(chunks, start=1):
        body = _truncate_chunk(chunk.content, max_chars=480)
        parts.append(
            f"{i}. {body}\n   — *source : {chunk.document_title}* "
            f"(chunk {chunk.chunk_index})"
        )
        if chunk.document_id not in seen_doc_ids:
            sources.append({
                "type": "document",
                "title": chunk.document_title,
                "chunk_index": chunk.chunk_index,
                "document_id": chunk.document_id,
            })
            seen_doc_ids.add(chunk.document_id)
    parts.append("")
    parts.append(
        f"*{len(sources)} document(s) cité(s) · {len(chunks)} passage(s) "
        "récupéré(s) via recherche FTS5 BM25.*"
    )
    return "\n".join(parts), sources


# ─────────────────────────────────────────────────────────────────────────────
# Refusal formatter
# ─────────────────────────────────────────────────────────────────────────────


def format_refusal(producer_id: int | None, reason: str = "cross_producer") -> str:
    """Polite French refusal for a scope-violating question."""
    if reason == "cross_producer":
        scope_text = f"producer_id = {producer_id}" if producer_id is not None else "votre scope producteur"
        return (
            "En tant que producteur, vous ne pouvez voir que vos propres données. "
            "Cette question demande une agrégation sur l'ensemble des producteurs du tenant "
            "Drive Producteur. Votre scope actuel est limité à "
            f"{scope_text}. Si vous avez besoin de cette information, contactez l'équipe "
            "Ops Drive Producteur qui dispose d'un accès admin."
        )
    if reason == "security_incident":
        return (
            "Votre question a déclenché une alerte de sécurité (tentative de contournement "
            "du scoping producteur). L'incident a été journalisé pour audit. Veuillez "
            "reformuler votre question — l'agent ne peut accéder qu'à vos propres données."
        )
    return "Votre question n'a pas pu être traitée."


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────


class AgentOrchestrator:
    """Phase 1 orchestrator — no LLM, rule-based + deterministic.

    Construction::

        orchestrator = AgentOrchestrator(
            sql_tool=tool, role="producer", producer_id=42,
        )
        response = await orchestrator.run(message)

    The orchestrator produces the full audit trail (steps + security_checks)
    regardless of success/refusal, so the inspector UI always has something
    to display.
    """

    def __init__(
        self,
        sql_tool: SqlReadTool,
        role: str = "producer",
        producer_id: int | None = None,
        *,
        identity_id: str | None = None,
        tracer: Tracer | None = None,
        rag_tool: RagSearchTool | None = None,
        forecast_tool: ForecastTool | None = None,
    ) -> None:
        self.sql_tool = sql_tool
        self.role = role
        self.producer_id = producer_id
        self.identity_id = identity_id
        # Phase 2 tracing — ``None`` falls back to a no-op tracer so the
        # orchestrator stays usable in scripts/tests without the chat API.
        self.tracer: Tracer = tracer if tracer is not None else _NoopTracer()
        # Phase 3 RAG — ``None`` falls back to building a default
        # ``RagSearchTool`` on demand (so a script that doesn't pass one
        # still gets documentary answers). The chat API always passes a
        # real one so tenant scoping is enforced.
        self.rag_tool: RagSearchTool | None = rag_tool
        # Phase 5 ML forecast — ``None`` falls back to building a default
        # ``ForecastTool`` on demand (so a script that doesn't pass one
        # still gets ML-based stock predictions when the model is trained).
        # The chat API always passes a real one so the producer scoping is
        # enforced at request time.
        self.forecast_tool: ForecastTool | None = forecast_tool

    async def run(self, user_message: str) -> AgentResponse:
        """Execute the (rule-based) agent loop and return a structured response.

        Tracing is additive: this method opens a trace, wraps each step in a
        span, and calls ``tracer.end_trace`` with the full result dict before
        returning. The returned ``AgentResponse`` carries the ``trace_id``
        so the API layer can include it in the JSON response.
        """
        ctx = self.tracer.start_trace(
            user_message,
            {
                "identity_id": self.identity_id,
                "producer_id": self.producer_id,
                "role": self.role,
                "tenant_id": "dp",
            },
        )
        try:
            response = await self._run_inner(user_message, ctx)
        except Exception as exc:  # noqa: BLE001 — never crash the caller
            # Record the error in the trace, then re-raise so the API layer
            # can return its own 200-with-error envelope.
            await self.tracer.end_trace(
                ctx,
                {
                    "answer": "",
                    "error": str(exc),
                    "refused": True,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "latency_ms": int((time.monotonic() - ctx.started_at) * 1000),
                },
            )
            raise
        # Persist the trace (async — writes to SQLite + optionally Langfuse).
        trace_result = self._build_trace_result(user_message, response, ctx)
        trace_id = await self.tracer.end_trace(ctx, trace_result)
        response.trace_id = trace_id
        return response

    def _build_trace_result(
        self,
        user_message: str,
        response: AgentResponse,
        ctx: TraceContext,
    ) -> dict[str, Any]:
        """Project an ``AgentResponse`` into the trace-row dict.

        The ``intent`` field is filled from the first step's detail ("Intention
        détectée : <intent>.") — the orchestrator records it there but not
        as a top-level field on the response. ``sql_valid`` is True iff SQL
        was generated AND sqlglot accepted it (``response.sql is not None``).
        """
        intent = None
        for step in response.steps:
            detail = step.get("detail") or ""
            if "Intention détectée" in detail:
                intent = detail.split("Intention détectée :", 1)[-1].strip().rstrip(".")
                break
        # Build a richer tool_calls list for the trace ({name, latency_ms,
        # success}) — the API response keeps tool_calls as list[str].
        tool_calls_detail: list[dict[str, Any]] = []
        if response.tool_calls:
            # Look up the execution span ("Exécution read-only") for latency.
            exec_ms = 0
            for span in ctx.spans:
                if span.name == "sql_execution":
                    exec_ms = span.duration_ms
                    break
            for name in response.tool_calls:
                tool_calls_detail.append(
                    {"name": name, "latency_ms": exec_ms, "success": not response.refused}
                )
        # ``scope_applied`` is True iff a non-null scope_clause was injected
        # (i.e. the producer's row-level filter is in effect). Admin requests
        # have ``scope_clause=None`` so scope_applied=False there.
        scope_applied = response.scope_clause is not None
        return {
            "answer": response.answer,
            "sql": response.sql,
            "intent": intent,
            "sql_valid": response.sql is not None and not response.refused,
            "scope_applied": scope_applied,
            "security_incident": any(
                sc.get("label") == "Scope appliqué" and sc.get("status") == "warning"
                for sc in response.security_checks
            ),
            "refused": response.refused,
            "tool_calls": tool_calls_detail,
            "steps": response.steps,
            "tokens_in": response.tokens_in,
            "tokens_out": response.tokens_out,
            "latency_ms": response.latency_ms,
            "error": None,
        }

    async def _run_inner(self, user_message: str, ctx: TraceContext) -> AgentResponse:
        """Original agent loop body, instrumented with tracing spans.

        Returns the ``AgentResponse`` — the public ``run()`` wraps this to
        call ``end_trace``.
        """
        started_at = time.monotonic()
        steps: list[StepTrace] = []
        security_checks: list[SecurityCheck] = []

        # ── Step 1 — comprehend the question ──
        span = self.tracer.start_span(ctx, "comprehension")
        t = time.monotonic()
        intent = classify_question(user_message, self.role)
        steps.append(
            StepTrace(
                index=1,
                title="Compréhension de la question",
                detail=f"Intention détectée : {intent}.",
                status="ok",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(ctx, span, status="ok", intent=intent)

        # ── Step 2 — tool selection ──
        span = self.tracer.start_span(ctx, "tool_selection")
        t = time.monotonic()
        # Pre-refuse cross-producer questions for producers.
        if intent == "cross_producer" and self.role != "admin":
            steps.append(
                StepTrace(
                    index=2,
                    title="Sélection de l'outil",
                    detail="Aucun — refus préventif",
                    status="blocked",
                    duration_ms=int((time.monotonic() - t) * 1000),
                )
            )
            self.tracer.end_span(ctx, span, status="blocked", reason="cross_producer_refusal")
            span_val = self.tracer.start_span(ctx, "sqlglot_validation")
            security_checks = [
                SecurityCheck("Read-only", "ok", "N/A — requête non exécutée"),
                SecurityCheck("Scope appliqué", "blocked", "Violation : agrégation cross-producteur"),
                SecurityCheck("Tables autorisées", "ok", "N/A"),
                SecurityCheck("LIMIT 1000", "ok", "N/A"),
            ]
            for next_idx, (title, detail, status) in enumerate(
                [
                    ("Validation sqlglot", "Scoping violation : la requête nécessite un accès admin.", "blocked"),
                    ("Exécution read-only", "Action refusée — scoping violation", "blocked"),
                    ("Synthèse", "Refus formaté.", "blocked"),
                ],
                start=3,
            ):
                tt = time.monotonic()
                steps.append(
                    StepTrace(
                        index=next_idx,
                        title=title,
                        detail=detail,
                        status=status,
                        duration_ms=int((time.monotonic() - tt) * 1000),
                    )
                )
            self.tracer.end_span(ctx, span_val, status="blocked", reason="cross_producer")
            answer = format_refusal(self.producer_id, reason="cross_producer")
            return AgentResponse(
                answer=answer,
                sql=None,
                scope_clause=None,
                chart=None,
                tokens_in=480,
                tokens_out=120,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                tool_calls=[],
                steps=[s.__dict__ for s in steps],
                security_checks=[s.__dict__ for s in security_checks],
                refused=True,
                tables_touched=[],
            )

        # Step 2 — tool selection (sql_read_tool for analytical intents,
        # rag_search for documentary, ops_copilot for ops_analysis,
        # forecast_tool for producer-side stock_shortfall when the ML model
        # is trained). The documentary branch routes to ``_run_documentary``
        # right after; the ops_analysis branch routes to ``_run_ops_copilot``;
        # the stock_shortfall branch (producer + model exists) routes to
        # ``_run_stock_forecast``; the analytical branch keeps the existing
        # SQL generation/validation/execution pipeline.
        can_forecast = (
            intent == "stock_shortfall"
            and self.role != "admin"
            and self.producer_id is not None
            and self._is_forecast_available()
        )
        if intent == "ops_analysis":
            selected_tool = "ops_copilot"
        elif intent == "documentary":
            selected_tool = "rag_search"
        elif can_forecast:
            selected_tool = "forecast_tool"
        else:
            selected_tool = "sql_read_tool"
        steps.append(
            StepTrace(
                index=2,
                title="Sélection de l'outil",
                detail=selected_tool,
                status="ok",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(ctx, span, status="ok", tool=selected_tool)

        # ── Phase 4 — ops_analysis intent: route to OpsCopilotAgent ──
        # Admin-only: producers asking for an onboarding pre-analysis are
        # refused with the same shape as the cross_producer refusal
        # (security_checks + steps + polite French message).
        if intent == "ops_analysis":
            if self.role != "admin":
                return self._build_ops_refusal(steps, started_at)
            return await self._run_ops_copilot(user_message, ctx, started_at, steps)

        # ── Phase 3 — documentary intent: route to RagSearchTool ──
        # We intercept BEFORE SQL generation because documentary questions
        # never need SQL. The RAG tool enforces tenant + producer scoping
        # internally (mirrors the SqlReadTool row-level security).
        if intent == "documentary":
            return await self._run_documentary(user_message, ctx, started_at, steps)

        # ── Phase 5 — stock_shortfall intent (producer + ML model trained):
        # route to ForecastTool. We intercept BEFORE SQL generation because
        # the ML path doesn't need SQL — the forecast_tool builds features
        # from stock_history + stocks + products directly. When the model
        # .pkl is missing OR the caller is admin (no producer scope), we
        # fall through to the SQL heuristic below (existing eval-011 admin
        # case stays on the SQL path).
        if can_forecast:
            return await self._run_stock_forecast(user_message, ctx, started_at, steps)

        # ── Step 3 — SQL generation ──
        span = self.tracer.start_span(ctx, "sql_generation")
        t = time.monotonic()
        try:
            raw_sql = await self.sql_tool.generate_sql(user_message)
        except Exception as exc:  # noqa: BLE001
            steps.append(
                StepTrace(
                    index=3,
                    title="Génération SQL",
                    detail=f"Échec : {exc}",
                    status="blocked",
                    duration_ms=int((time.monotonic() - t) * 1000),
                )
            )
            self.tracer.end_span(ctx, span, status="error", error=str(exc))
            return AgentResponse(
                answer=(
                    "Je n'ai pas pu générer de requête SQL pour cette question. "
                    "Pouvez-vous la reformuler en utilisant les mots-clés attendus "
                    "(ventes, stock, juin, …) ?"
                ),
                tokens_in=400,
                tokens_out=80,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                tool_calls=[],
                steps=[s.__dict__ for s in steps],
                security_checks=[
                    SecurityCheck("Read-only", "ok", "N/A — requête non exécutée").__dict__,
                    SecurityCheck("Scope appliqué", "ok", "N/A").__dict__,
                    SecurityCheck("Tables autorisées", "ok", "N/A").__dict__,
                    SecurityCheck("LIMIT 1000", "ok", "N/A").__dict__,
                ],
                refused=True,
            )
        refused_by_generator = raw_sql == REFUSE_MARKER
        gen_detail = (
            "Refusé — question cross-producteur" if refused_by_generator
            else "Rule-based generator (Phase 1)"
        )
        steps.append(
            StepTrace(
                index=3,
                title="Génération SQL",
                detail=gen_detail,
                status="blocked" if refused_by_generator else "ok",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(
            ctx, span,
            status="blocked" if refused_by_generator else "ok",
            raw_sql=raw_sql if not refused_by_generator else None,
        )

        # ── Step 4 — sqlglot validation + scoping ──
        span = self.tracer.start_span(ctx, "sqlglot_validation")
        t = time.monotonic()
        if refused_by_generator:
            steps.append(
                StepTrace(
                    index=4,
                    title="Validation sqlglot",
                    detail="Scoping violation : la requête nécessite un accès admin.",
                    status="blocked",
                    duration_ms=int((time.monotonic() - t) * 1000),
                )
            )
            self.tracer.end_span(ctx, span, status="blocked", reason="cross_producer")
            security_checks = [
                SecurityCheck("Read-only", "ok", "N/A — requête non exécutée"),
                SecurityCheck("Scope appliqué", "blocked", "Violation : agrégation cross-producteur"),
                SecurityCheck("Tables autorisées", "ok", "N/A"),
                SecurityCheck("LIMIT 1000", "ok", "N/A"),
            ]
            span_exec = self.tracer.start_span(ctx, "sql_execution")
            steps.append(
                StepTrace(
                    index=5,
                    title="Exécution read-only",
                    detail="Action refusée — scoping violation",
                    status="blocked",
                    duration_ms=0,
                )
            )
            self.tracer.end_span(ctx, span_exec, status="blocked", reason="refused")
            span_synth = self.tracer.start_span(ctx, "synthesis")
            steps.append(
                StepTrace(
                    index=6,
                    title="Synthèse",
                    detail="Refus formaté.",
                    status="blocked",
                    duration_ms=0,
                )
            )
            self.tracer.end_span(ctx, span_synth, status="blocked", reason="refusal")
            return AgentResponse(
                answer=format_refusal(self.producer_id, reason="cross_producer"),
                sql=None,
                scope_clause=None,
                chart=None,
                tokens_in=480,
                tokens_out=120,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                tool_calls=[],
                steps=[s.__dict__ for s in steps],
                security_checks=[s.__dict__ for s in security_checks],
                refused=True,
                tables_touched=[],
            )

        # Run the rewriter.
        try:
            safe_sql = self.sql_tool.validate_and_rewrite(raw_sql)
        except Exception as exc:  # noqa: BLE001
            steps.append(
                StepTrace(
                    index=4,
                    title="Validation sqlglot",
                    detail=f"Rejetée : {exc}",
                    status="blocked",
                    duration_ms=int((time.monotonic() - t) * 1000),
                )
            )
            self.tracer.end_span(ctx, span, status="error", error=str(exc))
            return AgentResponse(
                answer=(
                    "Votre question a été bloquée par la couche de sécurité. "
                    "L'agent ne peut pas exécuter cette requête."
                ),
                tokens_in=450,
                tokens_out=90,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                tool_calls=[],
                steps=[s.__dict__ for s in steps],
                security_checks=[
                    SecurityCheck("Read-only", "blocked", str(exc)).__dict__,
                ],
                refused=True,
            )

        scope_clause = self.sql_tool._last_scope_clause  # noqa: SLF001
        scope_detail = (
            scope_clause.replace("WHERE ", "") if scope_clause else "Full access (admin)"
        )
        steps.append(
            StepTrace(
                index=4,
                title="Validation sqlglot",
                detail=f"Scoping injecté : {scope_detail}"
                if scope_clause
                else "Aucun scope (admin)",
                status="warning" if self.sql_tool._last_security_incident else "ok",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(
            ctx, span,
            status="warning" if self.sql_tool._last_security_incident else "ok",
            safe_sql=safe_sql,
            scope_clause=scope_clause,
            security_incident=self.sql_tool._last_security_incident,
        )

        # ── Step 5 — execution ──
        span = self.tracer.start_span(ctx, "sql_execution")
        t = time.monotonic()
        try:
            result = await self.sql_tool.execute(safe_sql)
        except Exception as exc:  # noqa: BLE001
            steps.append(
                StepTrace(
                    index=5,
                    title="Exécution read-only",
                    detail=f"Erreur DB : {exc}",
                    status="blocked",
                    duration_ms=int((time.monotonic() - t) * 1000),
                )
            )
            self.tracer.end_span(ctx, span, status="error", error=str(exc))
            return AgentResponse(
                answer=(
                    "Une erreur est survenue lors de l'exécution de la requête sur la base "
                    "de données. Réessayez dans un instant."
                ),
                sql=safe_sql,
                scope_clause=scope_clause,
                tokens_in=500,
                tokens_out=100,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                tool_calls=["sql_read_tool"],
                steps=[s.__dict__ for s in steps],
                security_checks=[
                    SecurityCheck("Read-only", "ok", "SELECT uniquement").__dict__,
                    SecurityCheck("Scope appliqué", "ok", scope_detail).__dict__,
                ],
                refused=False,
                tables_touched=self.sql_tool._extract_tables(safe_sql),  # noqa: SLF001
            )

        steps.append(
            StepTrace(
                index=5,
                title="Exécution read-only",
                detail=f"{result.rowcount} lignes retournées",
                status="ok",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(
            ctx, span, status="ok", rowcount=result.rowcount
        )

        # ── Step 6 — synthesise the answer ──
        span = self.tracer.start_span(ctx, "synthesis")
        t = time.monotonic()
        answer, chart = await format_answer(
            user_message, intent, result, self.producer_id, self.role
        )
        steps.append(
            StepTrace(
                index=6,
                title="Synthèse de la réponse",
                detail="Formatage FR + chart",
                status="ok",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(ctx, span, status="ok", has_chart=chart is not None)

        # Build the security checklist.
        tables_touched = self.sql_tool._extract_tables(safe_sql)  # noqa: SLF001
        security_checks = [
            SecurityCheck("Read-only", "ok", "SELECT uniquement"),
            SecurityCheck(
                "Scope appliqué",
                "ok" if not self.sql_tool._last_security_incident else "warning",
                scope_detail,
            ),
            SecurityCheck(
                "Tables autorisées", "ok", ", ".join(tables_touched) or "N/A"
            ),
            SecurityCheck("LIMIT 1000", "ok", "Présente"),
        ]

        tokens_in = 850
        tokens_out = 412 if chart else 280

        return AgentResponse(
            answer=answer,
            sql=safe_sql,
            scope_clause=scope_clause,
            chart=chart,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            tool_calls=["sql_read_tool"],
            steps=[s.__dict__ for s in steps],
            security_checks=[s.__dict__ for s in security_checks],
            refused=False,
            tables_touched=tables_touched,
            sources=[{"type": "sql", "tables": tables_touched}],
        )

    # ───────────────────────────────────────────────────────────────────────
    # Phase 3 — documentary intent (RAG path)
    # ───────────────────────────────────────────────────────────────────────
    async def _run_documentary(
        self,
        user_message: str,
        ctx: TraceContext,
        started_at: float,
        steps: list[StepTrace],
    ) -> AgentResponse:
        """Documentary intent: RagSearchTool.search() → cited FR answer.

        6-step trace mirroring the analytical path:
          3. Recherche FTS5 BM25 (rag_search)
          4. Ranking BM25 (already done by FTS5)
          5. Synthèse + citations
          6. Réponse finalisée

        Security checks for documentary:
          - Scope appliqué      (tenant + producer_id filter enforced)
          - Documents autorisés (tenant scope only)
          - Source citée        (bool — at least one source cited)
        """
        # Lazily build a RagSearchTool if the caller didn't provide one
        # (scripts/tests convenience). The chat API always passes one.
        rag_tool = self.rag_tool
        if rag_tool is None:
            from app.connectors.sqlite_connector import SqliteConnector
            from app.tools.rag_tool import RagSearchTool as _Rag

            rag_tool = _Rag(
                connector=SqliteConnector(),
                tenant_id="dp",
                producer_id=self.producer_id,
                role=self.role,
                tracer=self.tracer,
            )
            self.rag_tool = rag_tool

        # Build the scope description for the security check.
        if self.role == "admin":
            scope_detail_doc = "tenant=dp (admin — tous les docs du tenant)"
        else:
            scope_detail_doc = (
                f"tenant=dp + (producer_id IS NULL OR producer_id = {self.producer_id})"
            )

        # ── Step 3 — FTS5 BM25 search ──
        span = self.tracer.start_span(ctx, "rag_search")
        t = time.monotonic()
        try:
            rag_result = await rag_tool.search(user_message, top_k=4, ctx=ctx)
        except Exception as exc:  # noqa: BLE001 — never crash the chat
            steps.append(
                StepTrace(
                    index=3,
                    title="Recherche FTS5 BM25",
                    detail=f"Échec : {exc}",
                    status="blocked",
                    duration_ms=int((time.monotonic() - t) * 1000),
                )
            )
            self.tracer.end_span(ctx, span, status="error", error=str(exc))
            return AgentResponse(
                answer=(
                    "Une erreur est survenue lors de la recherche documentaire. "
                    "Réessayez dans un instant."
                ),
                tokens_in=300,
                tokens_out=80,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                tool_calls=["rag_search"],
                steps=[s.__dict__ for s in steps],
                security_checks=[
                    SecurityCheck("Scope appliqué", "ok", scope_detail_doc).__dict__,
                    SecurityCheck("Documents autorisés", "ok", "tenant=dp").__dict__,
                    SecurityCheck("Source citée", "blocked", "Recherche échouée").__dict__,
                ],
                refused=False,
                tables_touched=["document_chunks_fts"],
                sources=[],
            )
        steps.append(
            StepTrace(
                index=3,
                title="Recherche FTS5 BM25",
                detail=(
                    f"{len(rag_result.chunks)} passage(s) récupéré(s) "
                    f"en {rag_result.latency_ms} ms"
                ),
                status="ok",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(
            ctx, span, status="ok",
            chunks_found=len(rag_result.chunks),
            latency_ms=rag_result.latency_ms,
        )

        # ── Step 4 — Ranking BM25 ──
        span = self.tracer.start_span(ctx, "rag_ranking")
        t = time.monotonic()
        # BM25 ranking is done by FTS5 at query time (ORDER BY score ASC).
        # We just document it as a separate step so the inspector UI shows
        # the ranking as an explicit phase.
        steps.append(
            StepTrace(
                index=4,
                title="Ranking BM25",
                detail=(
                    f"Top-{rag_result.top_k} trié par score BM25 ascendant "
                    f"(meilleur = score le plus négatif)"
                ),
                status="ok",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(ctx, span, status="ok", top_k=rag_result.top_k)

        # ── Step 5 — Synthèse avec citations ──
        span = self.tracer.start_span(ctx, "synthesis")
        t = time.monotonic()
        answer, sources = format_documentary_answer(user_message, rag_result)
        steps.append(
            StepTrace(
                index=5,
                title="Synthèse avec citations",
                detail=(
                    f"{len(sources)} document(s) cité(s)"
                    if sources
                    else "Aucun document cité (base vide ou sans match)"
                ),
                status="ok" if sources else "warning",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(
            ctx, span, status="ok" if sources else "warning",
            sources_count=len(sources),
        )

        # ── Step 6 — Réponse finalisée ──
        span = self.tracer.start_span(ctx, "answer_citations")
        t = time.monotonic()
        cited = bool(sources)
        steps.append(
            StepTrace(
                index=6,
                title="Réponse finalisée",
                detail=(
                    "Réponse + sources citées"
                    if cited
                    else "Réponse « no hit » — reformulation suggérée"
                ),
                status="ok" if cited else "warning",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(ctx, span, status="ok", cited=cited)

        # Security checks for documentary.
        security_checks = [
            SecurityCheck("Scope appliqué", "ok", scope_detail_doc),
            SecurityCheck("Documents autorisés", "ok", "tenant=dp (FTS5 filter)"),
            SecurityCheck(
                "Source citée",
                "ok" if cited else "warning",
                f"{len(sources)} source(s)" if cited else "Aucune source — base vide",
            ),
        ]

        tokens_in = 600
        tokens_out = 320 if cited else 80

        return AgentResponse(
            answer=answer,
            sql=None,                       # documentary intent → no SQL
            scope_clause=None,              # scoping is internal to the RAG tool
            chart=None,                     # documentary → no chart
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            tool_calls=["rag_search"],
            steps=[s.__dict__ for s in steps],
            security_checks=[s.__dict__ for s in security_checks],
            refused=False,
            tables_touched=["document_chunks_fts", "document_chunks", "documents"],
            sources=sources,
        )

    # ───────────────────────────────────────────────────────────────────────
    # Phase 5 — stock_shortfall intent (ML forecast path)
    # ───────────────────────────────────────────────────────────────────────
    def _is_forecast_available(self) -> bool:
        """Return True iff we can serve the ML forecast for this request.

        Conditions:
          1. A ``ForecastTool`` is wired up (the chat API always passes one).
          2. The trained model bundle ``ml/models/stock_shortage_model.pkl``
             exists on disk. When it's missing (e.g. the model hasn't been
             trained yet), we fall back to the SQL heuristic so the demo
             still works.
        """
        if self.forecast_tool is None:
            return False
        # Import here to avoid a circular import at module load time
        # (forecast_tool imports db_seed which is heavy).
        from app.tools.forecast_tool import MODEL_PATH
        return MODEL_PATH.exists()

    async def _run_stock_forecast(
        self,
        user_message: str,
        ctx: TraceContext,
        started_at: float,
        steps: list[StepTrace],
    ) -> AgentResponse:
        """Stock-shortfall intent: ForecastTool.predict() → ML-based answer.

        Flow:
          3. Construction des features ML (stock_history + stocks + products)
          4. Inférence ML (RandomForest.predict_proba)
          5. Classement top-5 par probabilité
          6. Synthèse (réponse markdown FR + chart barres)

        Security checks:
          - Scope appliqué         : producer_id from request identity
          - Modèle ML valide       : .pkl loaded successfully
          - Features disponibles   : ≥1 product evaluated

        The forecast tool enforces producer scoping internally (it queries
        stock_history / stocks / products WHERE producer_id = :producer_id),
        so the agent never sees another producer's data even if the model
        had a bug. Tracing: every predict() call opens a Langfuse span
        ``forecast_predict`` so the dashboard shows forecast calls
        alongside SQL / RAG calls.
        """
        # Lazily build a ForecastTool if the caller didn't provide one
        # (scripts/tests convenience). The chat API always passes one.
        forecast_tool = self.forecast_tool
        if forecast_tool is None:
            from app.connectors.sqlite_connector import SqliteConnector
            from app.tools.forecast_tool import ForecastTool as _ForecastTool

            forecast_tool = _ForecastTool(
                connector=SqliteConnector(),
                tenant_id="dp",
                producer_id=self.producer_id,
                role=self.role,
                tracer=self.tracer,
            )
            self.forecast_tool = forecast_tool

        scope_detail = f"producer_id = {self.producer_id}"

        # ── Step 3 — feature engineering ──
        span = self.tracer.start_span(
            ctx, "forecast_feature_engineering",
            producer_id=self.producer_id,
        )
        t = time.monotonic()
        # The forecast_tool's predict() does feature engineering internally
        # (one SQL round-trip per aggregate). We record this as a separate
        # step in the inspector UI; the actual work happens inside the
        # predict() call below.
        steps.append(
            StepTrace(
                index=3,
                title="Construction des features ML",
                detail=(
                    f"stock_history + stocks + products (scope : {scope_detail})"
                ),
                status="ok",
                duration_ms=0,  # filled in after predict() returns
            )
        )
        self.tracer.end_span(ctx, span, status="ok", producer_id=self.producer_id)

        # ── Step 4 — ML prediction (RandomForest.predict_proba) ──
        span = self.tracer.start_span(
            ctx, "forecast_ml_predict",
            producer_id=self.producer_id,
            horizon_days=3,
        )
        t = time.monotonic()
        try:
            result = await forecast_tool.predict(
                producer_id=self.producer_id,
                horizon_days=3,
                ctx=ctx,
                top_k=5,
            )
        except Exception as exc:  # noqa: BLE001 — never crash the chat
            logger.exception("ForecastTool.predict crashed for producer=%s", self.producer_id)
            self.tracer.end_span(ctx, span, status="error", error=str(exc))
            steps.append(
                StepTrace(
                    index=4,
                    title="Inférence ML (RandomForest)",
                    detail=f"Échec : {exc}",
                    status="blocked",
                    duration_ms=int((time.monotonic() - t) * 1000),
                )
            )
            security_checks = [
                SecurityCheck("Scope appliqué", "ok", scope_detail),
                SecurityCheck("Modèle ML valide", "warning", f"Erreur : {exc}"),
                SecurityCheck("Features disponibles", "blocked", "N/A"),
            ]
            return AgentResponse(
                answer=(
                    "Le modèle ML de prévision de rupture n'a pas pu produire de "
                    "prédiction. Réessayez dans un instant, ou reformulez votre "
                    "question (le SQL de secours reste disponible si vous précisez "
                    "« état du stock »)."
                ),
                sql=None,
                scope_clause=None,
                chart=None,
                tokens_in=400,
                tokens_out=120,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                tool_calls=["forecast_tool"],
                steps=[s.__dict__ for s in steps],
                security_checks=[s.__dict__ for s in security_checks],
                refused=False,
                tables_touched=["stock_history", "stocks", "products"],
                forecast_predictions=[],
            )
        # Update step 3 duration now that feature engineering is done.
        steps[-1].duration_ms = int((time.monotonic() - t) * 1000)
        steps.append(
            StepTrace(
                index=4,
                title="Inférence ML (RandomForest)",
                detail=(
                    f"{result.n_products_evaluated} produits évalués, "
                    f"{len(result.predictions)} à risque "
                    f"(latence {result.latency_ms} ms)"
                ),
                status="ok" if result.model_loaded and not result.error else "warning",
                duration_ms=result.latency_ms,
            )
        )
        self.tracer.end_span(
            ctx, span,
            status="ok" if result.model_loaded else "warning",
            n_products=result.n_products_evaluated,
            n_predictions=len(result.predictions),
            latency_ms=result.latency_ms,
            model_loaded=result.model_loaded,
        )

        # ── Step 5 — ranking top-k by probability ──
        span = self.tracer.start_span(ctx, "forecast_ranking")
        t = time.monotonic()
        steps.append(
            StepTrace(
                index=5,
                title="Classement top-5 par probabilité",
                detail=(
                    f"Top-{len(result.predictions)} produit(s) à risque "
                    f"de rupture sur 3 jours"
                ),
                status="ok" if result.predictions else "warning",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(
            ctx, span,
            status="ok" if result.predictions else "warning",
            top_k=len(result.predictions),
        )

        # ── Step 6 — synthesis (FR markdown + chart) ──
        span = self.tracer.start_span(ctx, "synthesis")
        t = time.monotonic()
        # Pull the model metadata for the footer (n_rows + n_estimators).
        model_meta: dict[str, Any] | None = None
        try:
            from app.tools.forecast_tool import MODEL_PATH
            import joblib as _joblib
            if MODEL_PATH.exists():
                bundle = _joblib.load(MODEL_PATH)
                if isinstance(bundle, dict):
                    model_meta = bundle.get("metadata")
        except Exception:  # noqa: BLE001 — footer is best-effort
            model_meta = None
        answer = render_forecast_answer(result, model_meta=model_meta)
        chart = render_forecast_chart(result)
        steps.append(
            StepTrace(
                index=6,
                title="Synthèse de la réponse",
                detail=(
                    f"Réponse ML formatée ({'avec' if chart else 'sans'} graphique)"
                ),
                status="ok",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(
            ctx, span, status="ok", has_chart=chart is not None,
        )

        # Security checks for the ML forecast path.
        security_checks = [
            SecurityCheck("Scope appliqué", "ok", scope_detail),
            SecurityCheck(
                "Modèle ML valide",
                "ok" if result.model_loaded else "warning",
                (
                    "stock_shortage_model.pkl chargé"
                    if result.model_loaded
                    else "Modèle non chargé"
                ),
            ),
            SecurityCheck(
                "Features disponibles",
                "ok" if result.n_products_evaluated > 0 else "warning",
                f"{result.n_products_evaluated} produit(s) évalué(s)",
            ),
        ]

        # Build the forecast_predictions list for the API response.
        forecast_predictions: list[dict[str, Any]] = [
            {
                "product_id": p.product_id,
                "product_name": p.product_name,
                "category": p.category,
                "probability": round(p.probability, 4),
                "probability_pct": int(round(p.probability * 100)),
                "stock_available": round(p.stock_available, 2),
                "sales_7d": round(p.sales_7d, 2),
                "sales_3d": round(p.sales_3d, 2),
                "sales_1d": round(p.sales_1d, 2),
                "avg_sales_30d": round(p.avg_sales_30d, 2),
                "top_factor": p.top_factor,
                "is_perishable": p.is_perishable,
                "days_since_last_stockout": p.days_since_last_stockout,
            }
            for p in result.predictions
        ]

        tokens_out = 380 if chart else 280

        return AgentResponse(
            answer=answer,
            sql=None,                     # ML path → no SQL on the response
            scope_clause=None,            # scoping is internal to the forecast tool
            chart=chart,
            tokens_in=600,
            tokens_out=tokens_out,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            tool_calls=["forecast_tool"],
            steps=[s.__dict__ for s in steps],
            security_checks=[s.__dict__ for s in security_checks],
            refused=False,
            tables_touched=["stock_history", "stocks", "products"],
            sources=[{"type": "ml_model", "name": "stock_shortage_model.pkl"}],
            forecast_predictions=forecast_predictions,
        )

    # ───────────────────────────────────────────────────────────────────────
    # Phase 4 — ops_analysis intent (Ops Copilot HITL path)
    # ───────────────────────────────────────────────────────────────────────
    def _build_ops_refusal(
        self,
        steps: list[StepTrace],
        started_at: float,
    ) -> AgentResponse:
        """Build the refusal returned when a non-admin asks for an ops analysis.

        Same shape as the cross_producer refusal (steps 3-6 with status
        "blocked" + a polite French message) so the inspector UI renders a
        consistent refusal regardless of which guard fired.
        """
        security_checks = [
            SecurityCheck("Read-only", "ok", "N/A — requête non exécutée"),
            SecurityCheck(
                "Scope appliqué", "blocked",
                "Violation : ops analysis réservée à l'admin Ops",
            ),
            SecurityCheck("Tables autorisées", "ok", "N/A"),
            SecurityCheck("LIMIT 1000", "ok", "N/A"),
        ]
        for next_idx, (title, detail, status) in enumerate(
            [
                ("Validation sqlglot", "Ops Copilot : accès admin requis.", "blocked"),
                ("Exécution read-only", "Action refusée — ops analysis est admin-only", "blocked"),
                ("Synthèse", "Refus formaté.", "blocked"),
            ],
            start=3,
        ):
            tt = time.monotonic()
            steps.append(
                StepTrace(
                    index=next_idx,
                    title=title,
                    detail=detail,
                    status=status,
                    duration_ms=int((time.monotonic() - tt) * 1000),
                )
            )
        return AgentResponse(
            answer=(
                "L'analyse préalable des dossiers d'onboarding est réservée à "
                "l'équipe Ops Drive Producteur (rôle admin). En tant que producteur, "
                "vous ne pouvez pas demander cette analyse. Si vous avez une question "
                "sur votre propre dossier, contactez l'équipe Ops qui dispose d'un "
                "accès admin."
            ),
            sql=None,
            scope_clause=None,
            chart=None,
            tokens_in=480,
            tokens_out=120,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            tool_calls=[],
            steps=[s.__dict__ for s in steps],
            security_checks=[s.__dict__ for s in security_checks],
            refused=True,
            tables_touched=[],
        )

    async def _run_ops_copilot(
        self,
        user_message: str,
        ctx: TraceContext,
        started_at: float,
        steps: list[StepTrace],
    ) -> AgentResponse:
        """Ops Copilot intent: resolve the dossier by name → analyze → respond.

        Flow:
          3. Résolution du dossier (name → onboarding_id, SQL SELECT)
          4. Pré-analyse OpsCopilotAgent (5 checks + recommendation)
          5. Synthèse avec décision proposée (FR)
          6. Réponse finalisée + ops_analysis dict attached

        Security checks:
          - Scope appliqué     : admin-only intent (already gated upstream)
          - Dossier résolu     : ok | warning (dossier introuvable)
          - Décision proposée  : approve | reject | request_info

        If the dossier name cannot be resolved from the message, returns a
        polite "dossier introuvable" answer with the list of known names
        (so the user can retry with an exact match).
        """
        # Lazy import to avoid circular dependency at module load time.
        from app.agents.ops_copilot import OpsCopilotAgent
        from sqlalchemy import select as _select

        from app.db_seed import get_engine, producer_onboardings

        # ── Step 3 — dossier resolution ──
        span = self.tracer.start_span(ctx, "ops_dossier_resolution")
        t = time.monotonic()
        onboarding_dict, resolution_detail = await self._resolve_onboarding(
            user_message
        )
        steps.append(
            StepTrace(
                index=3,
                title="Résolution du dossier",
                detail=resolution_detail,
                status="ok" if onboarding_dict else "blocked",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(
            ctx, span,
            status="ok" if onboarding_dict else "blocked",
            onboarding_id=(onboarding_dict or {}).get("id"),
        )

        if onboarding_dict is None:
            # Dossier not found — return a polite message + the known names.
            known = await self._known_onboarding_names()
            known_str = ", ".join(known) if known else "(aucun dossier en base)"
            answer = (
                "Je n'ai pas pu identifier le dossier d'onboarding visé par votre "
                "demande. Veuillez préciser le nom exact (raison sociale) du "
                "producteur. Dossiers actuellement en base : " + known_str + "."
            )
            security_checks = [
                SecurityCheck("Scope appliqué", "ok", "admin — accès tous dossiers"),
                SecurityCheck("Dossier résolu", "warning", "Nom non reconnu"),
                SecurityCheck("Décision proposée", "blocked", "N/A — dossier introuvable"),
            ]
            return AgentResponse(
                answer=answer,
                sql=None,
                scope_clause=None,
                chart=None,
                tokens_in=350,
                tokens_out=120,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                tool_calls=["ops_copilot"],
                steps=[s.__dict__ for s in steps],
                security_checks=[s.__dict__ for s in security_checks],
                refused=False,
                tables_touched=["producer_onboardings"],
                ops_analysis=None,
            )

        # ── Step 4 — OpsCopilotAgent pre-analysis ──
        span = self.tracer.start_span(ctx, "ops_pre_analysis")
        t = time.monotonic()
        agent = OpsCopilotAgent(tracer=self.tracer)
        analysis = await agent.analyze_onboarding(onboarding_dict)
        analysis_dict = analysis.to_dict()
        steps.append(
            StepTrace(
                index=4,
                title="Pré-analyse Ops Copilot",
                detail=(
                    f"Décision proposée : {analysis.proposed_decision} "
                    f"(confiance {analysis.confidence} %, "
                    f"{len(analysis.issues)} issue(s) détectée(s))."
                ),
                status="ok",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(
            ctx, span, status="ok",
            proposed_decision=analysis.proposed_decision,
            confidence=analysis.confidence,
            issues_count=len(analysis.issues),
            trace_id=analysis.trace_id,
        )

        # ── Step 5 — synthèse (FR human-readable answer) ──
        span = self.tracer.start_span(ctx, "ops_synthesis")
        t = time.monotonic()
        answer = self._format_ops_answer(analysis)
        steps.append(
            StepTrace(
                index=5,
                title="Synthèse avec décision proposée",
                detail=(
                    f"Recommandation : {analysis.proposed_decision} — "
                    f"{len(analysis.issues)} issue(s)."
                ),
                status="ok",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(
            ctx, span, status="ok",
            proposed_decision=analysis.proposed_decision,
        )

        # ── Step 6 — réponse finalisée ──
        span = self.tracer.start_span(ctx, "ops_response")
        t = time.monotonic()
        steps.append(
            StepTrace(
                index=6,
                title="Réponse finalisée",
                detail=(
                    f"Analyse prête — en attente de validation humaine "
                    f"(trace_id={analysis.trace_id})."
                ),
                status="ok",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(ctx, span, status="ok", trace_id=analysis.trace_id)

        # Security checks for ops_analysis.
        security_checks = [
            SecurityCheck("Scope appliqué", "ok", "admin — accès tous dossiers"),
            SecurityCheck(
                "Dossier résolu", "ok",
                f"id={onboarding_dict['id']} legal_name={onboarding_dict['legal_name']!r}",
            ),
            SecurityCheck(
                "Décision proposée",
                "ok" if analysis.proposed_decision == "approve" else "warning",
                f"{analysis.proposed_decision} (confiance {analysis.confidence} %) — "
                f"en attente de validation humaine",
            ),
        ]

        return AgentResponse(
            answer=answer,
            sql=None,                       # ops_analysis → no SQL on the response
            scope_clause=None,              # admin-only intent (no producer scoping)
            chart=None,                     # ops_analysis → no chart
            tokens_in=600,
            tokens_out=320,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            tool_calls=["ops_copilot"],
            steps=[s.__dict__ for s in steps],
            security_checks=[s.__dict__ for s in security_checks],
            refused=False,
            tables_touched=["producer_onboardings"],
            ops_analysis=analysis_dict,
        )

    @staticmethod
    def _format_ops_answer(analysis: Any) -> str:
        """Build a French markdown answer that wraps the agent's
        ``proposed_reason`` + a one-line summary table of the checks.

        The answer is intentionally short — the full structured analysis
        lives in the ``ops_analysis`` field of the AgentResponse (which the
        chat endpoint serialises alongside the answer). The admin UI is
        expected to render both.
        """
        decision_label = {
            "approve": "✅ APPROUVER",
            "reject": "❌ REJETER",
            "request_info": "ℹ️ COMPLÉTER LE DOSSIER",
        }.get(analysis.proposed_decision, analysis.proposed_decision.upper())
        lines = [
            f"**Pré-analyse du dossier « {analysis.legal_name} »**",
            "",
            f"- **Décision proposée** : {decision_label}",
            f"- **Confiance** : {analysis.confidence} %",
            f"- **SIRET** : `{analysis.siret}`",
            f"- **Issues détectées** : {len(analysis.issues)}",
            "",
            "**Motivation** :",
            "",
            analysis.proposed_reason,
            "",
            "**Checks** :",
            "",
            "| Check | Statut | Détail |",
            "|---|---|---|",
        ]
        for c in analysis.checks:
            status_emoji = {
                "ok": "✅", "warning": "⚠️", "blocked": "🚫",
            }.get(c.status, c.status)
            lines.append(
                f"| {c.name} | {status_emoji} {c.status} | {c.detail} |"
            )
        lines.append("")
        lines.append(
            "*L'agent ne valide jamais le dossier seul — la décision finale "
            "revient à un administrateur Ops via `/api/approvals/{id}/decide`.*"
        )
        return "\n".join(lines)

    async def _resolve_onboarding(
        self, user_message: str
    ) -> tuple[dict[str, Any] | None, str]:
        """Find the onboarding dossier whose ``legal_name`` appears in the message.

        Returns ``(dossier_dict, detail_string)``. ``dossier_dict`` is None
        when no match is found (the detail string then lists the known names
        so the caller can render a helpful message).
        """
        from sqlalchemy import select as _select

        from app.db_seed import get_engine, producer_onboardings

        global _OPS_ONBOARDING_NAMES
        engine = get_engine()
        # Always re-read the onboarding rows — there may be new ones since
        # the last call (uploads via the API). The cost is one SELECT
        # per ops_analysis chat request; fine for the demo.
        try:
            async with engine.connect() as conn:
                r = await conn.execute(
                    _select(
                        producer_onboardings.c.id,
                        producer_onboardings.c.legal_name,
                        producer_onboardings.c.siret,
                        producer_onboardings.c.siret_valid,
                        producer_onboardings.c.email,
                        producer_onboardings.c.phone,
                        producer_onboardings.c.declared_address,
                        producer_onboardings.c.document_address,
                        producer_onboardings.c.rib_document_present,
                        producer_onboardings.c.id_document_present,
                        producer_onboardings.c.professional_certificate_present,
                        producer_onboardings.c.professional_certificate_expiry,
                        producer_onboardings.c.tenant_id,
                    )
                )
                rows = r.fetchall()
        except Exception:  # noqa: BLE001
            rows = []
        _OPS_ONBOARDING_NAMES = [(row.id, row.legal_name) for row in rows]

        if not rows:
            return None, "Aucun dossier d'onboarding en base"

        msg_lower = user_message.lower()
        # Score each dossier by how many of its significant tokens appear
        # in the message. Pick the highest-scoring one (with a tie-break
        # on shorter name = more specific match).
        best: tuple[float, Any] | None = None  # (score, row)
        for row in rows:
            name = row.legal_name or ""
            # Tokenise the name (drop French stopwords + 1-char tokens).
            tokens = [
                t for t in name.lower().split()
                if len(t) > 2 and t not in {"les", "des", "du", "de", "la", "le", "et"}
            ]
            if not tokens:
                continue
            hits = sum(1 for t in tokens if t in msg_lower)
            # Exact name substring → instant win.
            if name.lower() in msg_lower:
                return (
                    dict(row._mapping),
                    f"Dossier « {name} » (id={row.id}) — match exact",
                )
            score = hits / len(tokens)
            if best is None or score > best[0] or (score == best[0] and len(name) < len(best[1].legal_name or "")):
                best = (score, row)

        if best is not None and best[0] >= 0.5:
            row = best[1]
            return (
                dict(row._mapping),
                f"Dossier « {row.legal_name} » (id={row.id}) — match {int(best[0] * 100)} %",
            )
        known = ", ".join(r.legal_name for r in rows)
        return None, f"Dossier non reconnu. Dossiers connus : {known}."

    async def _known_onboarding_names(self) -> list[str]:
        """Return the list of known onboarding legal_names (for the not-found message)."""
        global _OPS_ONBOARDING_NAMES
        if _OPS_ONBOARDING_NAMES is None:
            try:
                from sqlalchemy import select as _select

                from app.db_seed import get_engine, producer_onboardings

                engine = get_engine()
                async with engine.connect() as conn:
                    r = await conn.execute(
                        _select(
                            producer_onboardings.c.id, producer_onboardings.c.legal_name
                        )
                    )
                    _OPS_ONBOARDING_NAMES = [
                        (row.id, row.legal_name) for row in r.fetchall()
                    ]
            except Exception:  # noqa: BLE001
                _OPS_ONBOARDING_NAMES = []
        return [name for _id, name in _OPS_ONBOARDING_NAMES]
