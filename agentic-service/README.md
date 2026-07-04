# Tevet-7 — Agentic Service

> Configurable enterprise AI agent platform. First tenant: **Drive Producteur**.

Tevet-7 is a multi-tenant platform for building, deploying, and observing
enterprise-grade LLM agents that can reason over tenant data **safely**.

Each tenant (an enterprise customer) gets:

- A dedicated **Connector** that exposes its data through a controlled abstraction.
- A configurable set of **tools** (read-only SQL, document search, business actions).
- One or more **agents** (e.g. Producer Copilot, Customer Copilot, Admin Copilot).
- A **permissions model** (roles + row-level scoping) enforced server-side, never trusted to the LLM.
- An optional **human-in-the-loop** queue for risky write actions.

The first tenant is **Drive Producteur (DP)**, a short-supply-chain marketplace
(click & collect) connecting local producers with end customers. The flagship
agent for DP is the **Producer Copilot**, which lets each producer ask natural
questions about their own sales, stock, and orders — and only their own.

---

## Tech stack

| Layer            | Choice                                             | Why |
|------------------|----------------------------------------------------|-----|
| Web framework    | **FastAPI** (async, typed, OpenAPI out of the box) | Native async, great DX, fits an event-driven agent loop |
| Database (dev)   | **SQLite** (aiosqlite)                             | Zero-config dev — service runs without external infra |
| Database (prod)  | **PostgreSQL 16 + pgvector**                       | One store for relational data + embeddings (RAG) |
| ORM              | **SQLAlchemy 2.x (async)**                         | Mature, async-first, dialect-aware |
| LLM              | **OpenAI** (gpt-4o / gpt-4o-mini)                  | Default provider; pluggable later |
| Observability    | **Langfuse** (cloud or self-hosted) + LocalTracer  | Traces, prompts, evals, cost tracking per tenant |
| SQL rewriting    | **sqlglot**                                        | Parse + validate + rewrite LLM-generated SQL (security) |
| Auth             | **python-jose + passlib/bcrypt**                   | JWT-issued identity, never trusted from the client |
| ML               | **scikit-learn RandomForest**                      | Stock shortage prediction (F1=0.83) |

---

## Architecture summary

```
User (browser)
   │  HTTPS
   ▼
Next.js frontend ── POST /api/chat ──►  FastAPI agentic-service
                                          │
                                          ▼
                                  Agent Orchestrator
                                  (system prompt + loop)
                                          │
                            ┌─────────────┼──────────────┐
                            ▼             ▼              ▼
                      sql_read_tool  rag_search_tool  forecast_tool
                            │
                            ▼
                       Connector
                   (SQLite / Postgres / CSV)
                            │
                            ▼
                   Tenant database (read-only)

            ┌──────────────────────────────────────┐
            │  Langfuse — traces every LLM + tool  │
            │  FTS5 — documentary RAG index        │
            └──────────────────────────────────────┘
```

Key concepts (detailed in `docs/architecture.md`):

1. **Connectors** — the only path between an agent and tenant data.
2. **Tools** — thin, audited functions the agent can call (read-only first).
3. **Agents** — a prompt + a set of tools + an orchestrator loop.
4. **Permissions** — role-based table allowlist + row-level scoping enforced by `sqlglot` rewriting.
5. **Human-in-the-loop** — write actions are proposed, not executed; a human approves them (Ops Copilot, Phase 4).

---

## How to run

### 1. Configure environment

```bash
cd agentic-service
cp .env.example .env
# fill in OPENAI_API_KEY, JWT_SECRET, Langfuse keys (optional — LocalTracer is the fallback)
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the API (dev mode)

```bash
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

The service creates and seeds an in-process SQLite database (`dev.db`) on startup — no external Postgres needed for development. The ML stock-shortage model is auto-trained on first run if `ml/models/stock_shortage_model.pkl` is missing.

### 4. Health check

```bash
curl http://localhost:8001/health
# {"status":"ok","service":"tevet-7","version":"0.1.0"}
```

### Key environment variables

See `.env.example` for the full list. The most important:

- `DATABASE_URL` — SQLAlchemy URL for the tenant business database (SQLite dev / Postgres prod).
- `OPENAI_API_KEY` — LLM provider key.
- `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` — tracing (optional; falls back to LocalTracer).
- `JWT_SECRET` — token verification for `/api/chat`.

---

## Project layout

```
agentic-service/
├── app/
│   ├── main.py              # FastAPI entrypoint + lifespan
│   ├── config.py            # Pydantic Settings (env)
│   ├── database.py          # async engine + session
│   ├── db_seed.py           # SQLite schema + DP demo data + auth seed
│   ├── schema.yaml          # THE DP business schema (8 tables)
│   ├── prompts/             # Agent system prompts (markdown)
│   ├── connectors/          # Tenant data abstraction (SQLite / Postgres / CSV)
│   ├── tools/               # sql_tool, rag_tool, forecast_tool
│   ├── agents/              # Agent loop orchestrator + Ops Copilot (HITL)
│   ├── tracing/             # LocalTracer + LangfuseTracer + factory
│   ├── auth/                # JWT issuance + verification (python-jose + bcrypt)
│   ├── tenants/             # Tenant CRUD + onboarding wizard
│   ├── admin/               # Admin console + demo reset cron
│   └── api/                 # HTTP routers (chat, documents, approvals)
├── eval/                    # 39-case evaluation suite + report.json
├── ml/                      # RandomForest training + stock_shortage_model.pkl
├── tests/                   # 8 sqlglot security tests (the interview argument)
├── docs/
│   └── architecture.md      # Long-form architecture + Mermaid diagram
├── docker-compose.yml       # Postgres + Langfuse (production-grade infra)
├── requirements.txt
├── .env.example
└── README.md  (this file)
```

---

## Current status

| Phase | Goal                                       | Status |
|-------|--------------------------------------------|--------|
| 0     | Skeleton + reference architecture          | ✅ |
| 1     | Real `/chat` endpoint + sql_read_tool end-to-end | ✅ |
| 2     | Langfuse tracing, multi-turn memory        | ✅ |
| 3     | Documentary RAG (SQLite FTS5 + BM25)       | ✅ |
| 4     | Human-in-the-loop queue (Ops Copilot)      | ✅ |
| 5     | Multi-tenant onboarding + connector SDK    | ✅ |
| 6a    | JWT auth + tenant memberships              | ✅ |
| 6b    | Onboarding backend + tenant_configs        | ✅ |
| 6c    | Demo reset cron                            | ✅ |
| 6d    | Admin console + platform owner view        | ✅ |
| 7     | Eval harness + 39-case golden dataset      | ✅ |
| 8     | Production hardening, README, deploy configs | ✅ |

---

## Further reading

- **Architecture deep-dive**: [`docs/architecture.md`](docs/architecture.md)
- **DP schema (the data contract)**: [`app/schema.yaml`](app/schema.yaml)
- **Producer Copilot prompt**: [`app/prompts/producer_copilot.md`](app/prompts/producer_copilot.md)
- **SQL security tests**: [`tests/test_sql_security.py`](tests/test_sql_security.py)
- **Eval suite + report**: [`eval/`](eval/)
- **ML training + model**: [`ml/`](ml/)
