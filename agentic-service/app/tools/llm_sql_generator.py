"""LLM-based SQL generator — uses OpenAI to translate natural language to SQL.

This is the "real" AI agent: instead of keyword matching (RuleBasedSQLGenerator),
the LLM receives the tenant's schema + the user's question and generates SQL.

Architecture:
    User question
        ↓
    LLMSQLGenerator.generate()
        ↓
    OpenAI chat completion (system prompt with schema + user question)
        ↓
    Raw SQL string (no scope clause — sqlglot injects it)
        ↓
    SqlReadTool.validate_and_rewrite() — sqlglot AST validation + scoping
        ↓
    Execute on read-only connection

Security: the LLM NEVER touches the database. It only generates text.
sqlglot validates + rewrites the SQL before execution. The LLM cannot
bypass the security layer.

Fallback: if OPENAI_API_KEY is not set, or the OpenAI call fails, the
generator falls back to RuleBasedSQLGenerator (DP-specific patterns +
generic schema-aware patterns).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from app.tools.sql_tool import RuleBasedSQLGenerator, REFUSE_MARKER

logger = logging.getLogger("tevet7.llm_sql_generator")


class LLMSQLGenerator:
    """LLM-powered SQL generator using OpenAI.

    Implements the same ``SQLGenerator`` protocol as ``RuleBasedSQLGenerator``.
    The orchestrator doesn't know which generator is active — it just calls
    ``generate()`` and gets back a SQL string (or None).

    Construction::

        generator = LLMSQLGenerator(
            schema=tenant_schema_config,
            api_key="sk-...",
            model="gpt-4o-mini",
        )

    Fallback: if no API key, delegates to ``RuleBasedSQLGenerator``.
    """

    def __init__(
        self,
        schema: dict | None = None,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> None:
        self._schema = schema or {}
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = base_url or ""
        self._fallback = RuleBasedSQLGenerator(schema=schema)
        self._client = None

        if self._api_key and self._api_key != "sk-replace-me":
            try:
                from openai import AsyncOpenAI
                kwargs: dict[str, Any] = {"api_key": self._api_key}
                if self._base_url:
                    kwargs["base_url"] = self._base_url
                self._client = AsyncOpenAI(**kwargs)
                provider = self._base_url or "OpenAI default"
                logger.info("LLMSQLGenerator: client ready (provider=%s model=%s)", provider, model)
            except Exception as exc:
                logger.warning("LLMSQLGenerator: failed to init LLM client: %s", exc)
                self._client = None
        else:
            logger.info("LLMSQLGenerator: no API key — will use rule-based fallback")

    # ── Schema rendering ──────────────────────────────────────────────────

    def _render_schema(self) -> str:
        """Render the tenant's schema as a compact text description for the LLM."""
        tables = self._schema.get("tables", [])
        if not tables:
            return "(no tables configured)"

        lines: list[str] = []
        for t in tables:
            name = t.get("name", "?")
            desc = t.get("description", "")
            cols = t.get("columns", [])
            col_lines = []
            for c in cols:
                col_lines.append(f"    {c['name']} ({c.get('type', 'text')}): {c.get('description', '')}")
            lines.append(f"Table: {name}")
            if desc:
                lines.append(f"  Description: {desc}")
            lines.append("  Columns:")
            lines.extend(col_lines)
            lines.append("")

        return "\n".join(lines)

    # ── System prompt ─────────────────────────────────────────────────────

    def _build_system_prompt(self, role: str, scope_column: str | None) -> str:
        """Build the system prompt for the LLM.

        The prompt explains:
        - The task (translate natural language to SQL SELECT)
        - The schema (tables, columns, types)
        - The constraints (SELECT only, no scope clause, use table names)
        - The user's role (for context — admin sees all, producer is scoped)
        """
        schema_text = self._render_schema()

        return f"""You are a SQL expert assistant for a business analytics platform.
Your job: translate the user's natural language question into a single SQL SELECT query.

DATABASE SCHEMA:
{schema_text}

RULES (CRITICAL — violations will be rejected):
1. Generate ONLY a SELECT statement. No INSERT, UPDATE, DELETE, DROP, or DDL.
2. Do NOT include a WHERE clause for row-level security (scope). The system
   injects it automatically. Just write the business logic.
3. Use the exact table and column names from the schema above.
4. Use SQLite-compatible SQL (the database is SQLite in development).
5. Keep the query simple and efficient. Avoid subqueries unless necessary.
6. If the question is about "top" or "best", use ORDER BY ... DESC LIMIT.
7. If the question is about a total/sum, use SUM() with ROUND(..., 2).
8. If the question is about a count, use COUNT(*).
9. If the question is about an average, use AVG() with ROUND(..., 2).
10. If the question asks for a breakdown by category, use GROUP BY.
11. If the question mentions a time period (e.g., "this month", "last week"),
    add a WHERE clause on the date column. Use '2024-07-01' as "current month start".
12. If the question is about another producer's data or a cross-tenant query,
    return "REFUSE" (the user is not authorized).
13. If you cannot generate SQL for the question, return "CANNOT_GENERATE".

USER CONTEXT:
- Role: {role}
- Scope column: {scope_column or "none (admin — full access)"}

Return ONLY the SQL query (no markdown, no explanation, no semicolons).
If you must refuse or cannot generate, return exactly "REFUSE" or "CANNOT_GENERATE"."""

    # ── Entry point ───────────────────────────────────────────────────────

    async def generate(
        self,
        question: str,
        role: str,
        scope_column: str | None,
        scope_value: int | str | None,
    ) -> str | None:
        """Translate a natural-language question into a SQL SELECT.

        Returns the SQL string, REFUSE_MARKER, or None.
        Falls back to RuleBasedSQLGenerator if OpenAI is not available.
        """
        # If no OpenAI client, use the rule-based generator.
        if self._client is None:
            return self._fallback.generate(question, role, scope_column, scope_value)

        try:
            system_prompt = self._build_system_prompt(role, scope_column)
            response = await self._client.chat.completions.create(
                model=self._model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
            )

            raw = response.choices[0].message.content or ""
            raw = raw.strip()

            # Check for refusal / cannot generate.
            if raw.upper() in ("REFUSE", "CANNOT_GENERATE", "REFUSE."):
                if "REFUSE" in raw.upper():
                    return REFUSE_MARKER
                return None

            # Strip markdown code fences if present.
            if raw.startswith("```"):
                lines = raw.split("\n")
                # Remove first line (```sql or ```) and last line (```).
                lines = [l for l in lines if not l.strip().startswith("```")]
                raw = "\n".join(lines).strip()

            # Strip trailing semicolons.
            raw = raw.rstrip(";").strip()

            if not raw:
                logger.warning("LLMSQLGenerator: empty response from LLM")
                return None

            logger.info("LLMSQLGenerator: generated SQL (%d chars) for question: %s", len(raw), question[:60])
            return raw

        except Exception as exc:
            logger.warning("LLMSQLGenerator: OpenAI call failed (%s) — falling back to rule-based", exc)
            return await self._fallback.generate(question, role, scope_column, scope_value)
