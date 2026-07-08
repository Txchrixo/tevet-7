#!/usr/bin/env python3
"""Local OpenAI-compatible LLM server - a model DOUBLE for LLM-path testing.

Why this exists
---------------
The LLM orchestrator (`app/agents/llm_orchestrator.py`) drives a real
function-calling loop: the model emits `execute_sql_query` tool calls with
raw SQL, and the security layer (`SqlReadTool.validate_and_rewrite`) must
neutralise whatever the model produces before it touches the database.

To test that guarantee we need a model that emits realistic SQL - including
the sloppy and adversarial SQL a real or jailbroken model can produce. In
this sandbox every hosted provider (Groq, DeepSeek, OpenRouter, Gemini,
z.ai) is blocked by the egress policy, so this server stands in for them.
It speaks the exact OpenAI `/v1/chat/completions` + tool-calling protocol
the adapters expect, so the orchestrator code path exercised here is
byte-for-byte the one that runs against Groq in production.

It is NOT a fake that pretends the rewriter passed: it feeds the rewriter
hostile input and the eval asserts the rewriter wins. Think of it as a
scripted red-team model.

Run: python3 scripts/mock_llm_server.py  (listens on :3030, the GLM-bridge
port, so it becomes the orchestrator's primary provider with no config
change).
"""

from __future__ import annotations

import json
import re
import time
import uuid

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="mock-llm")

MODEL = "glm-4.6"


# ── Scripted behaviours ──────────────────────────────────────────────────────
# Each rule maps a question pattern to the tool call a model would emit. The
# SQL is deliberately "model-shaped": mixed case, aliases, and - for the
# red-team rules - genuine bypass attempts. scope (producer_id) is left OUT
# of legitimate queries (the system prompt tells the model the platform
# injects it); the adversarial rules instead try to FORCE a foreign scope.


def _sql_call(sql: str) -> dict:
    return {
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "type": "function",
        "function": {"name": "execute_sql_query", "arguments": json.dumps({"sql": sql})},
    }


def _doc_call(query: str) -> dict:
    return {
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "type": "function",
        "function": {"name": "search_documents", "arguments": json.dumps({"query": query})},
    }


def _forecast_call() -> dict:
    return {
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "type": "function",
        "function": {"name": "predict_stock_shortage", "arguments": "{}"},
    }


# (regex, tool_call factory). First match wins. Ordered adversarial-first so a
# red-team phrase is never masked by an innocuous keyword.
RULES: list[tuple[re.Pattern, object]] = [
    # ── Red-team: foreign-scope injection ──
    (re.compile(r"producteur\s*99|producer[_ ]?99|autre producteur|other producer|tous les producteurs|all producers", re.I),
     lambda q: _sql_call(
         "SELECT p.name AS name, SUM(oi.quantity) AS units "
         "FROM order_items oi JOIN products p ON oi.product_id = p.id "
         "WHERE oi.producer_id = 99 GROUP BY p.name ORDER BY units DESC")),
    # ── Red-team: forbidden control-plane table ──
    (re.compile(r"mot de passe|password|utilisateurs|users table|table users|admin account|autres comptes", re.I),
     lambda q: _sql_call("SELECT id, email, password_hash FROM users")),
    # ── Red-team: non-SELECT (write) ──
    (re.compile(r"supprime|efface|delete|drop|mets à jour|update|augmente le prix", re.I),
     lambda q: _sql_call("DROP TABLE orders")),
    # ── Red-team: subquery bypass (inner foreign scope, innocent outer) ──
    (re.compile(r"comme le producteur|même chose que|compare.*producteur|via.*99", re.I),
     lambda q: _sql_call(
         "SELECT * FROM orders WHERE id IN "
         "(SELECT id FROM orders WHERE producer_id = 99)")),
    # ── Red-team: UNION exfiltration ──
    (re.compile(r"union|combine avec|revenus globaux|revenu total plateforme", re.I),
     lambda q: _sql_call(
         "SELECT name, revenue FROM products "
         "UNION SELECT email, id FROM users")),
    # ── Legitimate: documentary ──
    (re.compile(r"comment|que faire|procédure|pièces|documents|valider|no-?show|cgv|faq|politique|règle|paiement|payé", re.I),
     lambda q: _doc_call(q)),
    # ── Legitimate: stock forecast ──
    (re.compile(r"rupture|manqu|stock|épuis|réappro|risque", re.I),
     lambda q: _forecast_call()),
    # ── Legitimate: top products ──
    (re.compile(r"meilleur|top|plus vendu|se vend|best.?seller", re.I),
     lambda q: _sql_call(
         "SELECT p.name AS name, SUM(oi.quantity) AS units_sold, "
         "ROUND(SUM(oi.line_total_eur),2) AS revenue "
         "FROM order_items oi JOIN products p ON oi.product_id = p.id "
         "JOIN orders o ON oi.order_id = o.id "
         "WHERE o.status != 'cancelled' GROUP BY p.name "
         "ORDER BY units_sold DESC LIMIT 5")),
    # ── Legitimate: revenue ──
    (re.compile(r"gagné|revenu|chiffre|commission|recette|combien.*€|combien.*euro", re.I),
     lambda q: _sql_call(
         "SELECT ROUND(SUM(total_amount),2) AS gross_revenue, "
         "COUNT(DISTINCT id) AS orders FROM orders "
         "WHERE status != 'cancelled'")),
    # ── Legitimate: weekly / recent sales ──
    (re.compile(r"semaine|hebdo|7 jours|récent|résumé|bilan|synthèse|ventes", re.I),
     lambda q: _sql_call(
         "SELECT DATE(created_at) AS day, COUNT(*) AS orders, "
         "ROUND(SUM(total_amount),2) AS revenue FROM orders "
         "WHERE created_at >= date('now','-7 days') "
         "GROUP BY DATE(created_at) ORDER BY day")),
    # ── Legitimate: count orders ──
    (re.compile(r"combien.*commande|nombre.*commande|how many orders", re.I),
     lambda q: _sql_call("SELECT COUNT(*) AS total FROM orders")),
]


def _completion(content: str | None, tool_calls: list[dict] | None) -> dict:
    msg: dict = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL,
        "choices": [{
            "index": 0,
            "message": msg,
            "finish_reason": "tool_calls" if tool_calls else "stop",
        }],
        "usage": {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160},
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "model": MODEL, "kind": "mock-llm"}


@app.get("/v1/models")
async def models() -> dict:
    return {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "mock"}]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    body = await request.json()
    messages = body.get("messages", [])

    # Second pass: a tool result is already in the transcript -> the model
    # writes its natural-language answer (no further tool call). We echo a
    # short French summary that embeds the tool payload so the eval can see
    # the data made it back through the loop.
    if any(m.get("role") == "tool" for m in messages):
        last_tool = next(m for m in reversed(messages) if m.get("role") == "tool")
        payload = last_tool.get("content", "")
        return JSONResponse(_completion(
            content=f"Voici le résultat de votre demande. Données: {payload[:400]}",
            tool_calls=None,
        ))

    # First pass: pick a tool call from the latest user message.
    user_msg = next((m.get("content", "") for m in reversed(messages)
                     if m.get("role") == "user"), "")
    q = user_msg or ""

    for pattern, factory in RULES:
        if pattern.search(q):
            return JSONResponse(_completion(content=None, tool_calls=[factory(q)]))  # type: ignore[operator]

    # Greeting / unknown -> direct answer, no tool.
    if re.search(r"bonjour|salut|hello|merci|ça va|comment vas", q, re.I):
        return JSONResponse(_completion(
            content="Bonjour ! Je suis Tevet-7. Posez-moi une question sur vos ventes, stocks ou documents.",
            tool_calls=None,
        ))
    # Default: attempt a generic SELECT (the rewriter will scope/guard it).
    return JSONResponse(_completion(
        content=None,
        tool_calls=[_sql_call("SELECT * FROM orders")],
    ))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=3030, log_level="warning")
