"""RagSearchTool - documentary retrieval over the FTS5 ``document_chunks_fts``.

Phase 3 - RAG layer for the Producer Copilot.

SECURITY NOTES
==============

The RAG tool enforces the **same row-level scoping** as ``SqlReadTool``:

1. ``tenant_id`` filter - always applied (a producer from tenant "dp" only
   sees chunks where ``tenant_id = 'dp'``).
2. ``producer_id`` filter - for producers: chunks where
   ``producer_id IS NULL`` (tenant-wide docs like the CGV) OR
   ``producer_id = <caller_producer_id>``. For admins: no producer filter
   (admin sees all chunks in the tenant).

The filter is applied **inside the FTS5 query** (not in Python), so a
 SQLite optimisation miss cannot leak another producer's private docs.

DESIGN
======

* The class follows the same Protocol as ``SqlReadTool`` (constructor takes
  ``connector``/``tenant_id``/``producer_id``/``role``/``tracer``; main
  method is ``search``). This makes the eventual swap to a vector-search
  tool a drop-in replacement in the orchestrator.

* BM25 ranking via the ``bm25(document_chunks_fts)`` FTS5 helper. The
  scores are negative (smaller = better match); we surface them as-is
  in the ``RagResult``.

* Tracing: ``RagSearchTool.search()`` wraps the FTS5 query in a Langfuse
  span ``rag_search`` (mirrors the ``sql_execution`` span of
  ``SqlReadTool``) so the Langfuse dashboard shows RAG and SQL calls
  side by side.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from app.db_seed import get_engine
from app.tracing.base import Span, TraceContext, Tracer

logger = logging.getLogger("tevet7.rag_tool")


# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class RagChunk:
    """One retrieved chunk with its provenance + BM25 score."""

    content: str
    document_id: int
    document_title: str
    chunk_index: int
    score: float  # bm25() - negative, smaller = better
    producer_id: int | None


@dataclass
class RagResult:
    """Structured result returned by ``RagSearchTool.search()``."""

    chunks: list[RagChunk] = field(default_factory=list)
    query: str = ""
    top_k: int = 4
    latency_ms: int = 0


@dataclass
class RagToolResult:
    """Structured result returned by ``RagSearchTool.run()``.

    Mirrors ``SqlReadTool.ToolResult`` so the orchestrator can treat both
    tools uniformly (``success``, ``error``, ``question``, ``security_incident``).
    """

    success: bool
    rag_result: RagResult | None = None
    error: str | None = None
    question: str | None = None
    tables_touched: list[str] = field(default_factory=list)
    security_incident: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# FTS5 query building
# ─────────────────────────────────────────────────────────────────────────────


def _build_fts_match(question: str) -> str:
    """Turn a French natural-language question into an FTS5 MATCH expression.

    Strategy:
      1. Lowercase + strip accents (the FTS5 ``unicode61`` tokenizer already
         strips accents at index time, so we mirror that here).
      2. Strip common French stop-words + punctuation.
      3. Keep at most 6 tokens (FTS5 LIMIT works on rows, not tokens, but a
         long MATCH expression degrades precision).
      4. Wrap each token in double quotes so FTS5 treats them as phrases
         (otherwise ``-`` and other chars break the parser). Join with
         `` OR `` so a chunk matching ANY token surfaces.

    The expression is what we feed to the FTS5 MATCH operator. ``?``-bound
    parameters cannot be used for the MATCH expression itself (it's not a
    value, it's a query-language string), so we sanitise carefully and
    pass it inline. We still bind ``tenant_id`` and ``producer_id`` as
    named parameters - those are real values.
    """
    import unicodedata

    # 1. lowercase + strip accents.
    q = question.lower()
    q = "".join(
        c for c in unicodedata.normalize("NFKD", q)
        if not unicodedata.combining(c)
    )
    # 2. drop punctuation (keep alphanumerics + spaces).
    cleaned_chars: list[str] = []
    for ch in q:
        if ch.isalnum() or ch.isspace():
            cleaned_chars.append(ch)
        else:
            cleaned_chars.append(" ")
    q = "".join(cleaned_chars)
    # 3. drop stop words.
    stop_words = {
        "le", "la", "les", "un", "une", "des", "du", "de", "d", "l",
        "et", "ou", "mais", "donc", "or", "ni", "car",
        "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles",
        "me", "te", "se", "lui", "leur", "y", "en",
        "mon", "ton", "son", "ma", "ta", "sa", "mes", "tes", "ses",
        "notre", "votre", "leur", "nos", "vos", "leurs",
        "ce", "cet", "cette", "ces", "ca", "cela", "c",
        "que", "qui", "quoi", "ou", "quand", "comment", "pourquoi",
        "est", "sont", "etre", "ai", "as", "a", "ont", "avait",
        "pour", "par", "sur", "sous", "avec", "sans", "dans", "en",
        "ne", "pas", "plus", "tres", "trop", "peu",
        "the", "a", "an", "of", "to", "in", "on", "is", "are", "and", "or",
    }
    tokens = [t for t in q.split() if t and t not in stop_words]
    # 4. Keep the 6 first tokens (enough signal for a small corpus).
    tokens = tokens[:6]
    if not tokens:
        return ""
    # Wrap each token in double quotes and join with OR.
    return " OR ".join(f'"{t}"' for t in tokens)


# ─────────────────────────────────────────────────────────────────────────────
# The tool
# ─────────────────────────────────────────────────────────────────────────────


class RagSearchTool:
    """Documentary RAG tool backed by SQLite FTS5 (BM25).

    Construction (per request, mirrors ``SqlReadTool``)::

        rag_tool = RagSearchTool(
            connector=connector,            # SqliteConnector (for engine access)
            tenant_id="dp",
            producer_id=42,                  # None for admin
            role="producer",
            tracer=get_tracer(),
        )
        result = await rag_tool.search("Quand suis-je payé ?")

    Scope semantics
    ---------------

    * ``role="producer"`` + ``producer_id=N``:
        matches chunks where ``tenant_id = 'dp'`` AND
        (``producer_id IS NULL`` OR ``producer_id = N``).
      → tenant-wide docs (CGV, FAQ, ...) + the producer's own private docs.
    * ``role="admin"``:
        matches chunks where ``tenant_id = 'dp'`` (any producer_id).
      → all tenant docs.
    """

    def __init__(
        self,
        connector: Any,  # SqliteConnector (only used for engine access)
        tenant_id: str,
        producer_id: int | None,
        role: str,
        tracer: Tracer | None = None,
    ) -> None:
        self.connector = connector
        self.tenant_id = tenant_id
        self.producer_id = producer_id
        self.role = role
        self.tracer = tracer

    # ───────────────────────────────────────────────────────────────────────
    # search()
    # ───────────────────────────────────────────────────────────────────────
    async def search(
        self,
        question: str,
        top_k: int = 4,
        ctx: TraceContext | None = None,
    ) -> RagResult:
        """Run a BM25 search and return the top-k chunks.

        Tracing: if a ``Tracer`` and ``ctx`` are provided, wraps the FTS5
        query in a span ``rag_search`` so Langfuse shows it alongside the
        SQL spans.
        """
        started = time.monotonic()
        match_expr = _build_fts_match(question)
        if not match_expr:
            # No usable tokens after stop-word removal → return empty result.
            return RagResult(chunks=[], query=question, top_k=top_k, latency_ms=0)

        # Build the WHERE clause for scoping.
        # We use named parameters for tenant_id + producer_id (real values).
        # The MATCH expression is sanitised (only quoted tokens + OR) and
        # passed inline.
        #
        # IMPORTANT: both ``document_chunks_fts`` and ``document_chunks``
        # have ``tenant_id`` / ``producer_id`` columns, so the WHERE clause
        # MUST qualify them with ``fts.`` to avoid SQLite's "ambiguous
        # column name" error.
        if self.role == "admin":
            scope_clause = "fts.tenant_id = :tenant_id"
            params: dict[str, Any] = {"tenant_id": self.tenant_id}
        else:
            # Producer: tenant-wide (producer_id IS NULL) OR own docs.
            scope_clause = (
                "fts.tenant_id = :tenant_id AND "
                "(fts.producer_id IS NULL OR fts.producer_id = :producer_id)"
            )
            params = {
                "tenant_id": self.tenant_id,
                "producer_id": self.producer_id,
            }

        sql = (
            "SELECT fts.content AS content, "
            "fts.document_id AS document_id, "
            "fts.producer_id AS producer_id, "
            "bm25(document_chunks_fts) AS score, "
            "dc.chunk_index AS chunk_index, "
            "d.title AS document_title "
            "FROM document_chunks_fts fts "
            "JOIN document_chunks dc "
            "  ON dc.document_id = fts.document_id "
            "  AND dc.chunk_index = ("
            "    SELECT MIN(dc2.chunk_index) "
            "    FROM document_chunks dc2 "
            "    WHERE dc2.document_id = fts.document_id "
            "      AND dc2.content = fts.content"
            "  ) "
            "JOIN documents d ON d.id = fts.document_id "
            "WHERE document_chunks_fts MATCH :match_expr "
            f"AND {scope_clause} "
            "ORDER BY score ASC "
            "LIMIT :top_k"
        )
        params["match_expr"] = match_expr
        params["top_k"] = top_k

        # ── Tracing span ──
        span: Span | None = None
        if self.tracer is not None and ctx is not None:
            span = self.tracer.start_span(
                ctx, "rag_search",
                question=question,
                top_k=top_k,
                match_expr=match_expr,
            )

        chunks: list[RagChunk] = []
        try:
            engine = get_engine()
            async with engine.connect() as conn:
                result = await conn.execute(text(sql), params)
                for row in result.fetchall():
                    chunks.append(
                        RagChunk(
                            content=row.content,
                            document_id=int(row.document_id),
                            document_title=row.document_title,
                            chunk_index=int(row.chunk_index) if row.chunk_index is not None else 0,
                            score=float(row.score) if row.score is not None else 0.0,
                            producer_id=row.producer_id,
                        )
                    )

            # ── Semantic reranking (Phase A5) ──
            # FTS5 gives keyword matches; the reranker improves precision for
            # synonyms/paraphrases ("payé" → "règlement").
            if len(chunks) > 1:
                try:
                    from app.tools.semantic_reranker import rerank
                    chunk_dicts = [
                        {"content": c.content, "document_id": c.document_id,
                         "document_title": c.document_title, "chunk_index": c.chunk_index,
                         "score": c.score, "producer_id": c.producer_id}
                        for c in chunks
                    ]
                    reranked = rerank(question, chunk_dicts, top_k=len(chunks))
                    chunks = [
                        RagChunk(
                            content=r["content"], document_id=r["document_id"],
                            document_title=r["document_title"], chunk_index=r["chunk_index"],
                            score=r["score"], producer_id=r["producer_id"],
                        )
                        for r in reranked
                    ]
                except Exception:  # noqa: BLE001
                    logger.debug("Semantic reranker failed, using FTS5 order")

            latency_ms = int((time.monotonic() - started) * 1000)
            if span is not None and self.tracer is not None:
                self.tracer.end_span(
                    ctx, span, status="ok",
                    chunks_found=len(chunks),
                    latency_ms=latency_ms,
                )
            return RagResult(
                chunks=chunks, query=question, top_k=top_k, latency_ms=latency_ms,
            )
        except Exception as exc:  # noqa: BLE001 - never crash the chat flow
            logger.exception("RagSearchTool.search failed for question=%r", question)
            latency_ms = int((time.monotonic() - started) * 1000)
            if span is not None and self.tracer is not None:
                self.tracer.end_span(
                    ctx, span, status="error", error=str(exc),
                )
            return RagResult(chunks=[], query=question, top_k=top_k, latency_ms=latency_ms)

    # ───────────────────────────────────────────────────────────────────────
    # run() - Tool-protocol entry point (mirrors SqlReadTool.run)
    # ───────────────────────────────────────────────────────────────────────
    async def run(self, question: str) -> RagToolResult:
        """End-to-end entry point used by callers that don't need to pass a
        trace context (e.g. scripts/tests). The orchestrator calls
        ``search()`` directly so it can pass its trace context.
        """
        try:
            result = await self.search(question)
            return RagToolResult(
                success=True,
                rag_result=result,
                question=question,
                tables_touched=["document_chunks_fts", "document_chunks", "documents"],
            )
        except Exception as exc:  # noqa: BLE001
            return RagToolResult(
                success=False,
                error=str(exc),
                question=question,
            )
