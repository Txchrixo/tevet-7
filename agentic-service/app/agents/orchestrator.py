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
from app.tools.sql_tool import REFUSE_MARKER, SqlReadTool, ToolResult
from app.tracing.base import Span, TraceContext, Tracer

logger = logging.getLogger("tevet7.orchestrator")


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
    # Phase 2 tracing — id of the row written to the ``traces`` table (and
    # optionally to Langfuse). ``None`` means tracing was disabled.
    trace_id: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Intent classification (mirrors the rule-based generator's branching)
# ─────────────────────────────────────────────────────────────────────────────


def classify_question(question: str, role: str) -> str:
    """Return one of: top_products | stock_shortfall | net_revenue |
    weekly_sales | cross_producer | unknown.

    Used by the formatter to pick the right answer template. The
    RuleBasedSQLGenerator mirrors this branching — keep them in sync.
    """
    q = question.lower()
    if "producteur" in q and ("commande" in q or "vente" in q):
        return "cross_producer"
    if ("produit" in q or "vendu" in q or "vente" in q) and (
        "top" in q or "plus" in q or "best" in q or "meilleur" in q
    ):
        return "top_products"
    if any(k in q for k in ("stock", "manqu", "rupture", "samedi", "épuis")):
        return "stock_shortfall"
    if any(k in q for k in ("gagné", "gagne", "net", "commission", "chiffre", "ca ", "revenu", "recette")):
        return "net_revenue"
    if any(k in q for k in ("résumé", "resume", "semaine", "synthèse", "synthese")):
        return "weekly_sales"
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
    """Top-products answer + bar chart spec (markdown-formatted)."""
    rows = result.as_dicts()
    if not rows:
        return (
            "Aucune vente enregistrée ce mois-ci pour votre exploitation.",
            None,
        )
    total_revenue = sum(float(r.get("revenue", 0)) for r in rows)
    top_row = rows[0]
    top_name = top_row.get("name", "?")
    top_revenue = float(top_row.get("revenue", 0))
    top_pct = int((top_revenue / total_revenue * 100)) if total_revenue > 0 else 0
    if producer_id is not None:
        prod_name = await _producer_name(producer_id)
        intro = f"Vos **5 produits les plus vendus ce mois-ci** ({prod_name}) :\n\n"
    else:
        intro = "**Top 5 des produits les plus vendus ce mois-ci** :\n\n"
    lines: list[str] = []
    chart_data: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        name = row.get("name", "?")
        units = int(float(row.get("units_sold", 0)))
        revenue = float(row.get("revenue", 0))
        lines.append(f"{i}. **{name}** — {units} unités · {_format_eur(revenue)}")
        chart_data.append({"name": name, "units_sold": float(units), "revenue": revenue})
    insight = (
        f"\n\nLes {top_name.lower()} représentent **{top_pct} %** de votre "
        "chiffre d'affaires du mois. Pensez à anticiper le réassort pour le week-end."
    )
    answer = intro + "\n".join(lines) + insight
    chart = {
        "type": "bar",
        "title": "Top 5 produits — ce mois-ci",
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
    ) -> None:
        self.sql_tool = sql_tool
        self.role = role
        self.producer_id = producer_id
        self.identity_id = identity_id
        # Phase 2 tracing — ``None`` falls back to a no-op tracer so the
        # orchestrator stays usable in scripts/tests without the chat API.
        self.tracer: Tracer = tracer if tracer is not None else _NoopTracer()

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

        steps.append(
            StepTrace(
                index=2,
                title="Sélection de l'outil",
                detail="sql_read_tool",
                status="ok",
                duration_ms=int((time.monotonic() - t) * 1000),
            )
        )
        self.tracer.end_span(ctx, span, status="ok", tool="sql_read_tool")

        # ── Step 3 — SQL generation ──
        span = self.tracer.start_span(ctx, "sql_generation")
        t = time.monotonic()
        try:
            raw_sql = self.sql_tool.generate_sql(user_message)
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
