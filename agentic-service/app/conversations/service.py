"""Conversation persistence service — DB operations."""
from __future__ import annotations
import logging, uuid
from datetime import datetime
from typing import Any
from sqlalchemy import desc, select, update
from app.db_seed import conversations, get_engine, messages

logger = logging.getLogger("tevet7.conversations")


async def create_conversation(tenant_id: str, user_id: int | None = None, title: str | None = None) -> str:
    conv_id = uuid.uuid4().hex
    engine = get_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(conversations.insert().values(
                id=conv_id, tenant_id=tenant_id, user_id=user_id, title=title,
                created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
            ))
    except Exception:
        logger.exception("create_conversation failed")
    return conv_id


async def load_history(conversation_id: str, limit: int = 10) -> list[dict[str, str]]:
    if not conversation_id:
        return []
    try:
        engine = get_engine()
        async with engine.begin() as conn:
            rows = await conn.execute(
                select(messages.c.role, messages.c.content)
                .where(messages.c.conversation_id == conversation_id)
                .order_by(messages.c.id)
                .limit(limit)
            ).all() if False else (await conn.execute(
                select(messages.c.role, messages.c.content)
                .where(messages.c.conversation_id == conversation_id)
                .order_by(messages.c.id)
                .limit(limit)
            )).all()
            return [{"role": r.role, "content": r.content} for r in rows]
    except Exception:
        logger.exception("load_history failed")
        return []


async def append_message(conversation_id: str, role: str, content: str,
                         sql: str | None = None, tokens_in: int = 0, tokens_out: int = 0) -> int:
    try:
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(messages.insert().values(
                conversation_id=conversation_id, role=role, content=content,
                sql=sql, tokens_in=tokens_in, tokens_out=tokens_out,
                created_at=datetime.utcnow(),
            ))
            # Touch the parent conversation's updated_at.
            await conn.execute(
                update(conversations).where(conversations.c.id == conversation_id)
                .values(updated_at=datetime.utcnow())
            )
            return int(result.inserted_primary_key[0]) if result.inserted_primary_key else 0
    except Exception:
        logger.exception("append_message failed")
        return 0
