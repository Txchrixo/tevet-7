"""LLM-powered orchestrator using function calling (tool use).

This is the REAL AI agent: the LLM is the brain. It receives the user's
question, the available tools, and the conversation history. It decides
which tool to call (or responds directly for greetings/conversation).

Architecture:
    User question + history
        ↓
    LLM (the brain) — function calling
        ↓
    LLM decides: SQL? RAG? Forecast? Direct response?
        ↓
    If SQL: LLM generates SQL → sqlglot validates → execute → result back to LLM
    If RAG: search docs → chunks back to LLM
    If Forecast: ML predict → predictions back to LLM
    If greeting: LLM responds directly (no tool)
        ↓
    LLM synthesizes final answer in natural language
        ↓
    AgentResponse (same shape as rule-based)

Security: sqlglot validates ALL SQL before execution. The LLM NEVER
touches the database — it generates text. sqlglot is the gardener.

Token efficiency:
    - System prompt: ~350 tokens (compact schema + rules)
    - History: last 6 messages (compact)
    - Tool results: max 300 tokens each (compact JSON, 20 rows max)
    - Final answer: max 500 tokens
    - Total per turn: ~1500-2000 tokens

Fallback: if the LLM is unavailable or fails, the caller falls back to
AgentOrchestrator (rule-based).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.agents.orchestrator import (
    AgentResponse,
    StepTrace,
    SecurityCheck,
    _producer_name,
)
from app.tools.sql_tool import SqlReadTool, SqlSecurityError
from app.tools.rag_tool import RagSearchTool
from app.tools.forecast_tool import ForecastTool
from app.tracing.base import Tracer

logger = logging.getLogger("tevet7.llm_orchestrator")


# ─────────────────────────────────────────────────────────────────────────────
# Tool definitions (OpenAI function calling format)
# ─────────────────────────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "execute_sql_query",
            "description": (
                "Execute a SQL SELECT query on the tenant's database. "
                "The system validates the query for security (read-only, "
                "allowed tables, row-level scoping) before execution. "
                "Use this for questions about sales, products, stock, "
                "orders, revenue, statistics, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": (
                            "The SQL SELECT query in SQLite syntax. "
                            "Do NOT include WHERE producer_id = X — "
                            "the system injects it automatically. "
                            "Use date('now', '-7 days') for date filters."
                        ),
                    }
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": (
                "Search the tenant's document base (FAQ, CGV, procedures, "
                "policies). Returns relevant passages with source citations. "
                "Use this for questions about rules, procedures, how things work."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query (natural language).",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "predict_stock_shortage",
            "description": (
                "Predict which products are at risk of stock shortage in "
                "the next 3 days using a trained ML model (RandomForest). "
                "Returns products with risk probability. Use this for "
                "questions about stock shortages, ruptures, what will run out."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# LLM Orchestrator
# ─────────────────────────────────────────────────────────────────────────────


class LLMOrchestrator:
    """LLM-powered orchestrator using function calling.

    The LLM is the brain. It decides which tool to use (or responds
    directly). The security layer (sqlglot) is NEVER bypassed.

    Construction::

        orchestrator = LLMOrchestrator(
            sql_tool=sql_tool,
            rag_tool=rag_tool,
            forecast_tool=forecast_tool,
            role="producer",
            producer_id=42,
            identity_id="marie@tevet7.dev",
            tracer=get_tracer(),
            schema=schema,
            llm_client=async_openai_client,
            model="deepseek-chat",
        )
        response = await orchestrator.run("Quels sont mes top produits ?", history)
    """

    def __init__(
        self,
        sql_tool: SqlReadTool,
        rag_tool: RagSearchTool | None = None,
        forecast_tool: ForecastTool | None = None,
        role: str = "producer",
        producer_id: int | None = None,
        identity_id: str = "",
        tracer: Tracer | None = None,
        schema: dict | None = None,
        router: Any = None,
    ) -> None:
        self.sql_tool = sql_tool
        self.rag_tool = rag_tool
        self.forecast_tool = forecast_tool
        self.role = role
        self.producer_id = producer_id
        self.identity_id = identity_id
        self.tracer = tracer
        self._schema = schema or {}
        self._router = router

    # ── Schema rendering (compact, ~200 tokens) ──────────────────────────

    def _render_compact_schema(self) -> str:
        """Render the schema as compact text for the system prompt.

        Format: table_name(col1, col2, col3)
        ~150-200 tokens for a typical 8-table schema.
        """
        tables = self._schema.get("tables", [])
        lines = []
        for t in tables:
            name = t.get("name", "?")
            cols = t.get("columns", [])
            col_str = ", ".join(c.get("name", "?") for c in cols)
            lines.append(f"- {name}({col_str})")
        return "\n".join(lines)

    # ── System prompt ────────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        """Build the system prompt (~350 tokens).

        Compact but complete: role, schema, rules, tool descriptions.
        """
        schema_text = self._render_compact_schema()
        scope_col = self.sql_tool.scope_column or "producer_id"
        scope_val = self.sql_tool.scope_value or "admin"
        scope_info = (
            f"User scope: {scope_col} = {scope_val}"
            if self.sql_tool.scope_column and self.sql_tool.scope_value
            else "User scope: admin (full access)"
        )
        return (
            f"You are Tevet-7, an AI agent for business analytics.\n"
            f"Help the user analyze their data, search documents, and predict stock.\n\n"
            f"DATABASE SCHEMA (SQLite):\n{schema_text}\n\n"
            f"USER: {self.role}\n{scope_info}\n\n"
            f"RULES:\n"
            f"1. Respond in French. Be concise and professional.\n"
            f"2. For data questions: call execute_sql_query with SQLite SQL.\n"
            f"3. For document questions: call search_documents.\n"
            f"4. For stock shortage: call predict_stock_shortage.\n"
            f"5. For greetings/small talk: respond directly (no tool call).\n"
            f"6. Do NOT include {scope_col} in your WHERE clause — the system injects it.\n"
            f"7. Use SQLite dates: date('now', '-7 days'), date('now', 'start of month').\n"
            f"8. Do NOT use date_trunc, INTERVAL, CURRENT_DATE (PostgreSQL only).\n"
            f"9. Cite document sources by title when using search_documents.\n"
            f"10. Format numbers with French conventions (virgule, espace).\n"
            f"11. Do NOT add semicolons at the end of SQL.\n"
            f"12. CONVERSATION MEMORY: the user may ask follow-up questions that reference "
            f"previous turns ('et le mois dernier ?', 'pareil pour les producteurs', 'compare avec juin'). "
            f"Use the conversation history to resolve these references. If the previous question "
            f"was about revenue in June, 'et le mois dernier ?' means 'revenue in May'.\n"
        )

    # ── Tool execution ───────────────────────────────────────────────────

    async def _execute_sql(self, sql: str) -> tuple[str, str | None, str | None, dict | None, list[dict]]:
        """Validate + execute SQL. Returns (result_text, sql_used, scope_clause, chart, security_checks).

        The LLM generates SQL → sqlglot validates + rewrites → execute read-only.
        The LLM NEVER touches the database.
        """
        try:
            safe_sql = self.sql_tool.validate_and_rewrite(sql)
            result = await self.sql_tool.execute(safe_sql)
            rows = result.as_dicts()

            # Compact result for LLM (max 20 rows, JSON).
            tool_result = json.dumps(
                {"columns": result.columns, "rows": rows[:20], "rowcount": len(rows)},
                ensure_ascii=False,
                default=str,
            )

            scope_clause = getattr(self.sql_tool, "_last_scope_clause", None)

            # Auto-detect chart (name column + numeric column).
            chart = None
            if len(rows) >= 2 and len(result.columns) >= 2:
                name_key = next(
                    (k for k in result.columns
                     if any(w in k.lower() for w in ("name", "label", "category", "type", "status"))),
                    None,
                )
                numeric_key = next(
                    (k for k in result.columns
                     if k != name_key and isinstance(rows[0].get(k), (int, float))),
                    None,
                )
                if name_key and numeric_key:
                    chart = {
                        "type": "bar",
                        "title": f"{numeric_key} par {name_key}",
                        "xKey": "name",
                        "series": [{"key": "value", "label": numeric_key, "color": "#A8C090"}],
                        "data": [
                            {"name": str(r.get(name_key, "?")), "value": float(r.get(numeric_key, 0))}
                            for r in rows[:10]
                        ],
                        "unit": "",
                    }

            security_checks = [
                {"label": "Read-only", "status": "ok", "detail": "SELECT uniquement"},
                {"label": "Scope appliqué", "status": "ok", "detail": str(scope_clause or "admin")},
                {"label": "Tables autorisées", "status": "ok", "detail": "Validées par sqlglot"},
                {"label": "LIMIT 1000", "status": "ok", "detail": "Présente"},
            ]

            return tool_result, safe_sql, scope_clause, chart, security_checks

        except SqlSecurityError as exc:
            error_msg = f"SQL rejected by security: {exc}. Use only SELECT, allowed tables, SQLite syntax."
            security_checks = [
                {"label": "Read-only", "status": "blocked", "detail": str(exc)},
                {"label": "Scope appliqué", "status": "blocked", "detail": "Rejetée"},
                {"label": "Tables autorisées", "status": "blocked", "detail": "Rejetée"},
                {"label": "LIMIT 1000", "status": "ok", "detail": "N/A"},
            ]
            return error_msg, None, None, None, security_checks

        except Exception as exc:
            error_msg = f"SQL execution failed: {exc}. Use SQLite syntax (date('now', '-7 days') not INTERVAL)."
            return error_msg, None, None, None, []

    async def _search_documents(self, query: str) -> tuple[str, list[dict]]:
        """Search documents via FTS5. Returns (result_text, sources)."""
        if not self.rag_tool:
            return "No document search available for this tenant.", []
        try:
            result = await self.rag_tool.search(query)
            chunks = result.chunks[:3]
            tool_result = json.dumps(
                [{"title": c.document_title, "content": c.content[:300]} for c in chunks],
                ensure_ascii=False,
            )
            sources = [{"type": "document", "title": c.document_title} for c in chunks]
            return tool_result, sources
        except Exception as exc:
            return f"Search failed: {exc}", []

    async def _predict_stock(self) -> tuple[str, list[dict] | None]:
        """Run ML prediction. Returns (result_text, predictions)."""
        if not self.forecast_tool:
            return "Stock prediction not available for this tenant.", None
        try:
            result = await self.forecast_tool.predict(self.producer_id)
            preds = result.predictions[:5]
            tool_result = json.dumps(
                [{"product": p.product_name, "probability": round(p.probability, 2),
                  "stock": p.stock_available} for p in preds],
                ensure_ascii=False,
            )
            predictions = [
                {"product_name": p.product_name, "probability": p.probability,
                 "stock_available": p.stock_available, "sales_7d": 0, "top_factor": ""}
                for p in preds
            ]
            return tool_result, predictions
        except Exception as exc:
            return f"Prediction failed: {exc}", None

    # ── Main loop ────────────────────────────────────────────────────────

    async def run(self, user_message: str, history: list | None = None) -> AgentResponse:
        """Run the LLM orchestrator loop.

        1. Build system prompt + messages (with history).
        2. Call LLM with tools (function calling).
        3. If tool call: execute tool, send result back to LLM.
        4. LLM synthesizes final answer.
        5. Return AgentResponse (same shape as rule-based).
        """
        started_at = time.monotonic()
        steps: list[StepTrace] = []
        tool_calls: list[str] = []
        sql_used: str | None = None
        scope_clause: str | None = None
        chart: dict | None = None
        sources: list[dict] = []
        forecast_predictions: list[dict] | None = None
        security_checks: list[dict] = [
            {"label": "Read-only", "status": "ok", "detail": "N/A"},
            {"label": "Scope appliqué", "status": "ok", "detail": "N/A"},
            {"label": "Tables autorisées", "status": "ok", "detail": "N/A"},
            {"label": "LIMIT 1000", "status": "ok", "detail": "N/A"},
        ]
        total_tokens_in = 0
        total_tokens_out = 0

        # ── Guardrails (Phase A4) — run BEFORE the LLM is called ──
        from app.agents.guardrails import check_message, redact_pii
        guardrail_result = check_message(user_message)
        if guardrail_result.blocked:
            latency_ms = int((time.monotonic() - started_at) * 1000)
            steps.append(StepTrace(
                index=1, title="Garde-fou — blocage",
                detail=guardrail_result.reason,
                status="blocked", duration_ms=latency_ms,
            ))
            return AgentResponse(
                answer=guardrail_result.reason,
                sql=None, scope_clause=None, chart=None,
                tokens_in=0, tokens_out=0, latency_ms=latency_ms,
                tool_calls=[], steps=steps,
                security_checks=[
                    {"label": "Garde-fou", "status": "blocked", "detail": guardrail_result.category},
                    {"label": "Read-only", "status": "ok", "detail": "N/A"},
                    {"label": "Scope appliqué", "status": "ok", "detail": "N/A"},
                    {"label": "LIMIT 1000", "status": "ok", "detail": "N/A"},
                ],
                refused=True, tables_touched=[], sources=[],
                ops_analysis=None, forecast_predictions=None, trace_id=None,
            )
        # PII redaction — replace PII before sending to the LLM.
        safe_message = redact_pii(user_message)

        # ── Build messages ──
        system_prompt = self._build_system_prompt()
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        # Add history (last 10 messages = 5 turns, for conversation memory).
        # Phase A3: the LLM uses this to resolve follow-up references
        # ("et le mois dernier ?" after a question about June revenue).
        if history:
            for h in history[-10:]:
                messages.append({
                    "role": h.get("role", "user"),
                    "content": h.get("content", ""),
                })

        messages.append({"role": "user", "content": safe_message})

        # ── Step 1: LLM analysis (function calling) ──
        t = time.monotonic()
        try:
            result = await self._router.chat(
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.0,
                max_tokens=800,
            )
            model_used = result.model
            total_tokens_in += result.usage.prompt_tokens
            total_tokens_out += result.usage.completion_tokens
        except Exception as exc:
            logger.warning("LLM orchestrator: first call failed: %s", exc)
            raise

        steps.append(StepTrace(
            index=1, title="Analyse de la question",
            detail=f"LLM ({model_used}) — {result.usage.completion_tokens} tokens",
            status="ok", duration_ms=int((time.monotonic() - t) * 1000),
        ))

        # ── No tool calls → direct response (greetings, conversation) ──
        if not result.tool_calls:
            latency_ms = int((time.monotonic() - started_at) * 1000)
            steps.append(StepTrace(
                index=2, title="Réponse directe",
                detail="Pas d'outil nécessaire — réponse conversationnelle.",
                status="ok", duration_ms=0,
            ))
            return AgentResponse(
                answer=result.content or "",
                sql=None, scope_clause=None, chart=None,
                tokens_in=total_tokens_in, tokens_out=total_tokens_out,
                latency_ms=latency_ms,
                tool_calls=[], steps=steps,
                security_checks=security_checks,
                refused=False, tables_touched=[], sources=[],
                ops_analysis=None, forecast_predictions=None,
                trace_id=None,
            )

        # ── Execute tool calls ──
        # Reconstruct the assistant message in OpenAI dict shape for the next LLM call.
        from app.agents.llm_adapters import tool_calls_to_openai_dict
        messages.append({
            "role": "assistant",
            "content": result.content or "",
            "tool_calls": tool_calls_to_openai_dict(result.tool_calls),
        })

        for tc in result.tool_calls:
            fn_name = tc.name
            fn_args = tc.arguments  # already parsed dict
            tool_calls.append(fn_name)

            t = time.monotonic()
            steps.append(StepTrace(
                index=2, title=f"Exécution: {fn_name}",
                detail=json.dumps(fn_args, ensure_ascii=False)[:100],
                status="ok", duration_ms=0,
            ))

            if fn_name == "execute_sql_query":
                sql_raw = fn_args.get("sql", "")
                tool_result, sql_used, scope_clause, chart, security_checks = \
                    await self._execute_sql(sql_raw)

            elif fn_name == "search_documents":
                query = fn_args.get("query", "")
                tool_result, sources = await self._search_documents(query)

            elif fn_name == "predict_stock_shortage":
                tool_result, forecast_predictions = await self._predict_stock()

            else:
                tool_result = f"Unknown tool: {fn_name}"

            # Send tool result back to LLM.
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result,
            })

        # ── Step 3: LLM synthesis (generate final answer from tool results) ──
        t = time.monotonic()
        synth_model = "unknown"
        synth_tokens = 0
        try:
            synth_result = await self._router.chat(
                messages=messages,
                temperature=0.3,
                max_tokens=500,
            )
            synth_model = synth_result.model
            total_tokens_in += synth_result.usage.prompt_tokens
            total_tokens_out += synth_result.usage.completion_tokens
            synth_tokens = synth_result.usage.completion_tokens
            final_answer = synth_result.content or ""
        except Exception as exc:
            logger.warning("LLM orchestrator: synthesis failed: %s", exc)
            final_answer = (
                "Une erreur est survenue lors de la synthèse de la réponse. "
                "Les données ont été récupérées mais n'ont pas pu être formatées."
            )

        steps.append(StepTrace(
            index=3, title="Synthèse de la réponse",
            detail=f"LLM ({synth_model}) — {synth_tokens} tokens",
            status="ok", duration_ms=int((time.monotonic() - t) * 1000),
        ))

        latency_ms = int((time.monotonic() - started_at) * 1000)

        return AgentResponse(
            answer=final_answer,
            sql=sql_used,
            scope_clause=scope_clause,
            chart=chart,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            latency_ms=latency_ms,
            tool_calls=tool_calls,
            steps=steps,
            security_checks=security_checks,
            refused=False,
            tables_touched=[],
            sources=sources,
            ops_analysis=None,
            forecast_predictions=forecast_predictions,
            trace_id=None,
        )
