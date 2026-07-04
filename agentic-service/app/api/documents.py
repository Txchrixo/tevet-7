"""``/api/documents`` — documentary RAG management endpoints.

Phase 3 — RAG layer for the Producer Copilot.

Endpoints
=========

- ``POST /api/documents``          — upload a document (PDF or text).
- ``GET  /api/documents``          — list documents for the tenant.
- ``GET  /api/documents/{id}``     — document detail + its chunks.
- ``DELETE /api/documents/{id}``   — delete a document + its chunks + FTS rows.

All endpoints trace via the active tracer (LocalTracer or LangfuseTracer)
so the operator can see uploads / deletions in the same Langfuse dashboard
as the chat traces.

Security model
==============

Phase 6a — dual auth mode (same pattern as ``app/api/chat.py``):

1. **JWT path (new, for the frontend)** — the caller sends
   ``Authorization: Bearer <jwt>``. The ``tenant_id`` and
   ``producer_id`` are extracted from the verified JWT (the form/query
   params are IGNORED).
2. **Form/query path (legacy, for the eval + the old frontend)** — no
   ``Authorization`` header. The ``tenant_id`` is read from the form
   (POST) or query string (GET) and defaults to ``"dp"``. The
   ``producer_id`` is read from the form/query string too.

Phase 3 kept the model intentionally simple (no JWT) — the dual mode
preserves that for the eval while letting the frontend authenticate
via JWT.

PDF extraction uses ``pypdf`` (already in requirements.txt). If the
extraction yields no text (e.g. scanned PDF), the endpoint returns 400.
"""

from __future__ import annotations

import io
import logging
import time
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select

from app.auth.dependencies import TenantContext, try_get_tenant_context
from app.db_seed import (
    delete_document,
    document_chunks,
    documents,
    get_engine,
    ingest_document,
)
from app.tracing import get_tracer
from app.tracing.base import TraceContext

logger = logging.getLogger("tevet7.api.documents")

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _resolve_doc_context(
    request: Request,
    fallback_tenant_id: str,
    fallback_producer_id: int | None,
) -> tuple[str, int | None]:
    """Return ``(tenant_id, producer_id)`` for a documents endpoint call.

    Phase 6a dual mode:
      - If an ``Authorization: Bearer <jwt>`` header is present and
        valid, the tenant_id + producer_id are extracted from the JWT
        (the form/query fallbacks are IGNORED).
      - Otherwise the fallback values (from the form/query params) are
        used — this is the legacy path the eval relies on.
    """
    jwt_ctx: TenantContext | None = try_get_tenant_context(request)
    if jwt_ctx is not None and jwt_ctx.tenant_id:
        # For producer role → scope to their producer_id; for admin role
        # → producer_id stays None (tenant-wide).
        pid = jwt_ctx.producer_id if jwt_ctx.role == "producer" else None
        return jwt_ctx.tenant_id, pid
    return fallback_tenant_id, fallback_producer_id


def _extract_pdf_text(file_bytes: bytes) -> str:
    """Extract text from a PDF using pypdf. Returns '' on failure or empty."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover — pypdf is in requirements
        raise HTTPException(
            status_code=500,
            detail=f"pypdf is not installed on the server: {exc}",
        ) from exc
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        parts: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text:
                parts.append(text)
        return "\n\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail=f"PDF text extraction failed: {exc}",
        ) from exc


def _start_doc_span(name: str, **metadata: Any) -> tuple[Any, TraceContext | None, Any]:
    """Start a trace + span for a documents endpoint call.

    Returns ``(tracer, ctx, span)`` so the endpoint can ``end_span`` /
    ``end_trace`` when done. Falls back gracefully if the tracer is the
    noop one (no real persistence).
    """
    tracer = get_tracer()
    ctx = tracer.start_trace(name, metadata)
    span = tracer.start_span(ctx, name, **metadata)
    return tracer, ctx, span


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/documents — upload
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/documents")
async def upload_document(
    request: Request,
    title: str = Form(..., description="Document title (e.g. 'CGV Drive Producteur')."),
    source_type: str = Form("text", description="'pdf' or 'text'."),
    file: UploadFile | None = File(None, description="PDF file (required if source_type=pdf)."),
    content: str | None = Form(None, description="Manual text content (required if source_type=text)."),
    producer_id: int | None = Form(None, description="Producer id for producer-private docs. NULL = tenant-wide."),
    tenant_id: str = Form("dp", description="Tenant id (default 'dp'). IGNORED when Authorization: Bearer is present."),
) -> dict[str, Any]:
    """Upload a document, chunk it, sync the FTS5 table.

    Returns ``{document_id, title, chunks_count}``.

    Phase 6a — dual auth mode: when an ``Authorization: Bearer <jwt>``
    header is present, the tenant_id and producer_id are extracted from
    the JWT and the form fields are ignored.
    """
    tenant_id, producer_id = _resolve_doc_context(request, tenant_id, producer_id)
    tracer, ctx, span = _start_doc_span(
        "document_upload",
        title=title,
        source_type=source_type,
        tenant_id=tenant_id,
        producer_id=producer_id,
    )
    t0 = time.monotonic()
    try:
        # ── Resolve content ──
        if source_type == "pdf":
            if file is None:
                raise HTTPException(
                    status_code=400,
                    detail="source_type=pdf requires a 'file' upload field.",
                )
            file_bytes = await file.read()
            if not file_bytes:
                raise HTTPException(status_code=400, detail="Uploaded PDF is empty.")
            extracted = _extract_pdf_text(file_bytes)
            if not extracted.strip():
                raise HTTPException(
                    status_code=400,
                    detail="PDF text extraction yielded no text (scanned PDF?).",
                )
            raw_content = extracted
            source_filename = file.filename
        elif source_type == "text":
            if not content or not content.strip():
                raise HTTPException(
                    status_code=400,
                    detail="source_type=text requires a non-empty 'content' form field.",
                )
            raw_content = content
            source_filename = None
        else:
            raise HTTPException(
                status_code=400,
                detail=f"source_type must be 'pdf' or 'text', got {source_type!r}.",
            )

        # ── Ingest ──
        doc_id = await ingest_document(
            tenant_id=tenant_id,
            title=title,
            source_type=source_type,
            content=raw_content,
            producer_id=producer_id,
            source_filename=source_filename,
        )

        # ── Count chunks for the response ──
        engine = get_engine()
        async with engine.connect() as conn:
            r = await conn.execute(
                select(func.count())
                .select_from(document_chunks)
                .where(document_chunks.c.document_id == doc_id)
            )
            chunks_count = int(r.scalar_one())

        latency_ms = int((time.monotonic() - t0) * 1000)
        tracer.end_span(
            ctx, span, status="ok",
            document_id=doc_id,
            chunks_count=chunks_count,
            latency_ms=latency_ms,
        )
        await tracer.end_trace(
            ctx,
            {
                "answer": f"document uploaded: {title}",
                "sql": None,
                "intent": "document_upload",
                "refused": False,
                "tokens_in": 0,
                "tokens_out": 0,
                "latency_ms": latency_ms,
                "tool_calls": [{"name": "ingest_document", "latency_ms": latency_ms, "success": True}],
                "steps": [],
            },
        )
        return {
            "document_id": doc_id,
            "title": title,
            "chunks_count": chunks_count,
            "source_type": source_type,
            "producer_id": producer_id,
            "tenant_id": tenant_id,
        }
    except HTTPException as exc:
        tracer.end_span(ctx, span, status="error", error=str(exc.detail))
        await tracer.end_trace(
            ctx,
            {
                "answer": "",
                "error": str(exc.detail),
                "refused": True,
                "tokens_in": 0,
                "tokens_out": 0,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            },
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("upload_document failed")
        tracer.end_span(ctx, span, status="error", error=str(exc))
        await tracer.end_trace(
            ctx,
            {
                "answer": "",
                "error": str(exc),
                "refused": True,
                "tokens_in": 0,
                "tokens_out": 0,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            },
        )
        raise HTTPException(status_code=500, detail=f"upload failed: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/documents — list
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/documents")
async def list_documents(
    request: Request,
    producer_id: int | None = Query(None, description="Scope the list to a producer (NULL = all tenant docs). IGNORED when Authorization: Bearer is present and role=producer."),
    tenant_id: str = Query("dp", description="Tenant id (default 'dp'). IGNORED when Authorization: Bearer is present."),
) -> dict[str, Any]:
    """List documents for the tenant, optionally scoped to a producer.

    Phase 6a — dual auth mode: when an ``Authorization: Bearer <jwt>``
    header is present, the tenant_id and producer_id are extracted from
    the JWT and the query params are ignored.
    """
    tenant_id, producer_id = _resolve_doc_context(request, tenant_id, producer_id)
    tracer, ctx, span = _start_doc_span(
        "document_list",
        tenant_id=tenant_id,
        producer_id=producer_id,
    )
    t0 = time.monotonic()
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            stmt = (
                select(
                    documents.c.id,
                    documents.c.title,
                    documents.c.source_type,
                    documents.c.source_filename,
                    documents.c.producer_id,
                    documents.c.created_at,
                    func.count(document_chunks.c.id).label("chunks_count"),
                )
                .select_from(documents.outerjoin(document_chunks, document_chunks.c.document_id == documents.c.id))
                .where(documents.c.tenant_id == tenant_id)
                .group_by(documents.c.id)
                .order_by(documents.c.created_at.desc())
            )
            if producer_id is not None:
                # When producer_id is set, show tenant-wide docs (NULL) + this
                # producer's docs. (Same scoping rule as the RAG tool.)
                stmt = stmt.where(
                    (documents.c.producer_id.is_(None))
                    | (documents.c.producer_id == producer_id)
                )
            r = await conn.execute(stmt)
            items = []
            for row in r.fetchall():
                ca = row.created_at
                items.append({
                    "id": row.id,
                    "title": row.title,
                    "source_type": row.source_type,
                    "source_filename": row.source_filename,
                    "producer_id": row.producer_id,
                    "created_at": ca.isoformat() if ca is not None else None,
                    "chunks_count": int(row.chunks_count or 0),
                })
        latency_ms = int((time.monotonic() - t0) * 1000)
        tracer.end_span(ctx, span, status="ok", count=len(items), latency_ms=latency_ms)
        await tracer.end_trace(
            ctx,
            {
                "answer": f"document list: {len(items)} items",
                "sql": None,
                "intent": "document_list",
                "refused": False,
                "tokens_in": 0,
                "tokens_out": 0,
                "latency_ms": latency_ms,
                "tool_calls": [{"name": "list_documents", "latency_ms": latency_ms, "success": True}],
                "steps": [],
            },
        )
        return {"count": len(items), "documents": jsonable_encoder(items)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("list_documents failed")
        tracer.end_span(ctx, span, status="error", error=str(exc))
        await tracer.end_trace(
            ctx,
            {
                "answer": "",
                "error": str(exc),
                "refused": True,
                "tokens_in": 0,
                "tokens_out": 0,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            },
        )
        raise HTTPException(status_code=500, detail=f"list failed: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/documents/{id} — detail
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/documents/{doc_id}")
async def get_document(doc_id: int) -> dict[str, Any]:
    """Return one document + its chunks."""
    tracer, ctx, span = _start_doc_span("document_detail", doc_id=doc_id)
    t0 = time.monotonic()
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            r = await conn.execute(
                select(documents).where(documents.c.id == doc_id)
            )
            doc_row = r.fetchone()
            if doc_row is None:
                raise HTTPException(status_code=404, detail=f"document {doc_id} not found")
            r2 = await conn.execute(
                select(
                    document_chunks.c.id,
                    document_chunks.c.chunk_index,
                    document_chunks.c.content,
                    document_chunks.c.created_at,
                )
                .where(document_chunks.c.document_id == doc_id)
                .order_by(document_chunks.c.chunk_index.asc())
            )
            chunks = []
            for row in r2.fetchall():
                ca = row.created_at
                chunks.append({
                    "id": row.id,
                    "chunk_index": row.chunk_index,
                    "content": row.content,
                    "created_at": ca.isoformat() if ca is not None else None,
                })
        ca = doc_row.created_at
        latency_ms = int((time.monotonic() - t0) * 1000)
        tracer.end_span(ctx, span, status="ok", chunks_count=len(chunks), latency_ms=latency_ms)
        await tracer.end_trace(
            ctx,
            {
                "answer": f"document detail: {doc_row.title}",
                "sql": None,
                "intent": "document_detail",
                "refused": False,
                "tokens_in": 0,
                "tokens_out": 0,
                "latency_ms": latency_ms,
                "tool_calls": [{"name": "get_document", "latency_ms": latency_ms, "success": True}],
                "steps": [],
            },
        )
        return {
            "id": doc_row.id,
            "tenant_id": doc_row.tenant_id,
            "title": doc_row.title,
            "source_type": doc_row.source_type,
            "source_filename": doc_row.source_filename,
            "producer_id": doc_row.producer_id,
            "created_at": ca.isoformat() if ca is not None else None,
            "content_raw": doc_row.content_raw,
            "chunks": chunks,
        }
    except HTTPException as exc:
        tracer.end_span(ctx, span, status="error", error=str(exc.detail))
        await tracer.end_trace(
            ctx,
            {
                "answer": "",
                "error": str(exc.detail),
                "refused": True,
                "tokens_in": 0,
                "tokens_out": 0,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            },
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("get_document failed")
        tracer.end_span(ctx, span, status="error", error=str(exc))
        await tracer.end_trace(
            ctx,
            {
                "answer": "",
                "error": str(exc),
                "refused": True,
                "tokens_in": 0,
                "tokens_out": 0,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            },
        )
        raise HTTPException(status_code=500, detail=f"get failed: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /api/documents/{id}
# ─────────────────────────────────────────────────────────────────────────────


@router.delete("/documents/{doc_id}")
async def remove_document(doc_id: int) -> dict[str, Any]:
    """Delete a document, its chunks, and its FTS rows."""
    tracer, ctx, span = _start_doc_span("document_delete", doc_id=doc_id)
    t0 = time.monotonic()
    try:
        deleted = await delete_document(doc_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"document {doc_id} not found")
        latency_ms = int((time.monotonic() - t0) * 1000)
        tracer.end_span(ctx, span, status="ok", deleted=True, latency_ms=latency_ms)
        await tracer.end_trace(
            ctx,
            {
                "answer": f"document {doc_id} deleted",
                "sql": None,
                "intent": "document_delete",
                "refused": False,
                "tokens_in": 0,
                "tokens_out": 0,
                "latency_ms": latency_ms,
                "tool_calls": [{"name": "delete_document", "latency_ms": latency_ms, "success": True}],
                "steps": [],
            },
        )
        return {"deleted": True, "document_id": doc_id}
    except HTTPException as exc:
        tracer.end_span(ctx, span, status="error", error=str(exc.detail))
        await tracer.end_trace(
            ctx,
            {
                "answer": "",
                "error": str(exc.detail),
                "refused": True,
                "tokens_in": 0,
                "tokens_out": 0,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            },
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("remove_document failed")
        tracer.end_span(ctx, span, status="error", error=str(exc))
        await tracer.end_trace(
            ctx,
            {
                "answer": "",
                "error": str(exc),
                "refused": True,
                "tokens_in": 0,
                "tokens_out": 0,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            },
        )
        raise HTTPException(status_code=500, detail=f"delete failed: {exc}") from exc


@router.get("/documents/health", include_in_schema=False)
async def documents_health() -> dict[str, Any]:
    """Lightweight health probe scoped to the documents router."""
    return {"status": "ok", "router": "documents"}
