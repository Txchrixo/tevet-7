"""Export endpoints — CSV + PDF export of conversations + data (Phase C5).

Provides:
  - ``GET /api/export/conversations.csv`` — export the tenant's conversations as CSV.
  - ``GET /api/export/conversations.pdf`` — export as PDF (simple table layout).
  - ``GET /api/export/messages/{conversation_id}.csv`` — export a single conversation.

CSV uses Python's built-in ``csv`` module (no external dep).
PDF uses ``reportlab`` if installed, otherwise falls back to a simple
HTML-to-text format (no external dep required for dev).
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import try_get_tenant_context
from app.db_seed import get_engine, traces, messages, conversations

logger = logging.getLogger("tevet7.export")
router = APIRouter()


@router.get("/export/conversations.csv")
async def export_conversations_csv(request: Request) -> StreamingResponse:
    """Export the tenant's conversations as a CSV file."""
    jwt_ctx = try_get_tenant_context(request)
    if jwt_ctx is None:
        raise HTTPException(status_code=401, detail="auth required")

    engine = get_engine()
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(
                traces.c.id, traces.c.created_at, traces.c.identity_id,
                traces.c.user_message, traces.c.intent, traces.c.sql_generated,
                traces.c.tokens_in, traces.c.tokens_out, traces.c.latency_ms,
                traces.c.refused, traces.c.cost_usd,
            )
            .where(traces.c.tenant_id == jwt_ctx.tenant_id)
            .order_by(traces.c.created_at.desc())
            .limit(1000)
        )
        data = rows.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "created_at", "identity_id", "user_message", "intent",
        "sql_generated", "tokens_in", "tokens_out", "latency_ms",
        "refused", "cost_usd",
    ])
    for r in data:
        writer.writerow([
            str(r.id), str(r.created_at), r.identity_id or "",
            r.user_message or "", r.intent or "",
            r.sql_generated or "", r.tokens_in or 0, r.tokens_out or 0,
            r.latency_ms or 0, bool(r.refused), r.cost_usd or 0.0,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=tevet7_conversations_{jwt_ctx.tenant_id}.csv"},
    )


@router.get("/export/conversations.pdf")
async def export_conversations_pdf(request: Request) -> Response:
    """Export the tenant's conversations as a PDF file.

    Uses reportlab if installed, otherwise returns a simple text file.
    """
    jwt_ctx = try_get_tenant_context(request)
    if jwt_ctx is None:
        raise HTTPException(status_code=401, detail="auth required")

    engine = get_engine()
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(
                traces.c.created_at, traces.c.identity_id,
                traces.c.user_message, traces.c.intent,
                traces.c.tokens_in, traces.c.tokens_out, traces.c.refused,
            )
            .where(traces.c.tenant_id == jwt_ctx.tenant_id)
            .order_by(traces.c.created_at.desc())
            .limit(100),
        )
        data = rows.fetchall()

    # Try reportlab for PDF generation.
    try:
        from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
        from reportlab.lib import colors  # type: ignore[import-untyped]
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph  # type: ignore[import-untyped]
        from reportlab.lib.styles import getSampleStyleSheet  # type: ignore[import-untyped]

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()

        elements = [
            Paragraph(f"Tevet-7 — Conversations ({jwt_ctx.tenant_id})", styles["Title"]),
            Paragraph(f"Exporté le {__import__('datetime').datetime.utcnow().isoformat()}", styles["Normal"]),
        ]

        table_data = [["Date", "User", "Question", "Intent", "Tokens", "Refused"]]
        for r in data:
            table_data.append([
                str(r.created_at)[:19] if r.created_at else "",
                r.identity_id or "",
                (r.user_message or "")[:80],
                r.intent or "",
                str((r.tokens_in or 0) + (r.tokens_out or 0)),
                "Oui" if r.refused else "Non",
            ])

        table = Table(table_data, colWidths=[80, 60, 200, 60, 40, 40])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2D3A2F")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(table)
        doc.build(elements)

        return Response(
            content=buffer.getvalue(),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=tevet7_conversations_{jwt_ctx.tenant_id}.pdf"},
        )
    except ImportError:
        # Fallback: plain text export if reportlab not installed.
        output = io.StringIO()
        output.write(f"Tevet-7 — Conversations ({jwt_ctx.tenant_id})\n\n")
        for r in data:
            output.write(f"Date: {r.created_at}\n")
            output.write(f"User: {r.identity_id}\n")
            output.write(f"Question: {r.user_message}\n")
            output.write(f"Intent: {r.intent}\n")
            output.write(f"Tokens: {r.tokens_in}+{r.tokens_out}\n")
            output.write(f"Refused: {r.refused}\n\n---\n\n")
        return Response(
            content=output.getvalue(),
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename=tevet7_conversations_{jwt_ctx.tenant_id}.txt"},
        )


@router.get("/export/messages/{conversation_id}.csv")
async def export_messages_csv(conversation_id: str, request: Request) -> StreamingResponse:
    """Export a single conversation's messages as CSV."""
    jwt_ctx = try_get_tenant_context(request)
    if jwt_ctx is None:
        raise HTTPException(status_code=401, detail="auth required")

    engine = get_engine()
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(
                messages.c.id, messages.c.role, messages.c.content,
                messages.c.sql, messages.c.tokens_in, messages.c.tokens_out,
                messages.c.created_at,
            )
            .where(messages.c.conversation_id == conversation_id)
            .order_by(messages.c.id)
        )
        data = rows.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "role", "content", "sql", "tokens_in", "tokens_out", "created_at"])
    for r in data:
        writer.writerow([
            r.id, r.role, r.content or "", r.sql or "",
            r.tokens_in, r.tokens_out,
            str(r.created_at) if r.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=tevet7_messages_{conversation_id}.csv"},
    )
