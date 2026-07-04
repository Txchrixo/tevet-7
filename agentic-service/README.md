# OpsPilot AI — Agentic Service

> Configurable enterprise AI agent platform. First tenant: **Drive Producteur**.

OpsPilot AI is a multi-tenant platform for building, deploying, and observing
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
| Database         | **PostgreSQL 16 + pgvector**                       | One store for relational data + embeddings (RAG later) |
| ORM              | **SQLAlchemy 2.x (async)** + **asyncpg**           | Mature, async-first, dialect-aware |
| LLM              | **OpenAI** (gpt-4o / gpt-4o-mini)                  | Default provider; pluggable later |
| Observability    | **Langfuse** (self-hosted)                         | Traces, prompts, evals, cost tracking per tenant |
| SQL rewriting    | **sqlglot**                                        | Parse + validate + rewrite LLM-generated SQL (security) |
| Frontend         | Next.js prototype (separate repo / folder)         | Owned by the frontend agent |

---

## Architecture summary

```
User (browser)
   │  HTTPS
   ▼
Next.js prototype ── POST /chat ──►  FastAPI agentic-service
                                          │
                                          ▼
                                  Agent Orchestrator
                                  (system prompt + loop)
                                          │
                            ┌─────────────┼──────────────┐
                            ▼             ▼              ▼
                      sql_read_tool  doc_search_tool  (future tools)
                            │
                            ▼
                       Connector
                   (Postgres / REST / Shopify)
                            │
                            ▼
                   Tenant database (read-only user)

            ┌──────────────────────────────────────┐
            │  Langfuse — traces every LLM + tool   │
            │  pgvector — RAG embeddings store      │
            └──────────────────────────────────────┘
```

Key concepts (detailed in `docs/architecture.md`):

1. **Connectors** — the only path between an agent and tenant data.
2. **Tools** — thin, audited functions the agent can call (read-only first).
3. **Agents** — a prompt + a set of tools + an orchestrator loop.
4. **Permissions** — role-based table allowlist + row-level scoping enforced by `sqlglot` rewriting.
5. **Human-in-the-loop** — write actions are proposed, not executed; a human approves them (Phase 4).

---

## How to run

> The service is **not yet runnable end-to-end** (Phase 0 skeleton). The
> instructions below describe the intended workflow once Phase 1 lands.

### 1. Start the infrastructure

```bash
cd agentic-service
docker compose up -d   # postgres (pgvector) + langfuse
```

### 2. Configure environment

```bash
cp .env.example .env
# fill in OPENAI_API_KEY, JWT_SECRET, Langfuse keys, DP connector credentials
```

### 3. Run the API (dev mode)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 4. Health check

```bash
curl http://localhost:8000/health
# {"status":"ok","service":"opspilot-ai","version":"0.1.0"}
```

### Key environment variables

See `.env.example` for the full list. The most important:

- `DATABASE_URL` — asyncpg URL for the **control plane** DB (tenants, users, configs).
- `OPENAI_API_KEY` — LLM provider key.
- `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` — tracing.
- `JWT_SECRET` — token verification for `/chat`.
- `DP_API_BASE_URL` / `DP_API_TOKEN` — future Drive Producteur REST connector.
- `TOKEN_QUOTA_PER_TENANT_PER_DAY` — fair-use cap.

---

## Project layout

```
agentic-service/
├── app/
│   ├── main.py              # FastAPI entrypoint
│   ├── config.py            # Pydantic Settings (env)
│   ├── database.py          # async engine + session
│   ├── schema.yaml          # THE DP business schema (8 tables)
│   ├── prompts/             # Agent system prompts (markdown)
│   ├── connectors/          # Tenant data abstraction
│   ├── tools/               # sql_tool, (later) doc_search_tool...
│   ├── agents/              # Agent loop orchestrator
│   └── api/                 # HTTP routers (/chat)
├── docs/
│   └── architecture.md      # Long-form architecture + Mermaid diagram
├── tests/
│   └── test_sql_security.py # THE interview argument (security tests)
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md  (this file)
```

---

## Current status: **Phase 0 — skeleton only**

| Phase | Goal                                       | Status |
|-------|--------------------------------------------|--------|
| 0     | Skeleton + reference architecture          | ✅ this PR |
| 1     | Real `/chat` endpoint + sql_read_tool end-to-end | ⏳ |
| 2     | Langfuse tracing, multi-turn memory        | ⏳ |
| 3     | RAG: pgvector + document_search_tool       | ⏳ |
| 4     | Human-in-the-loop queue for write actions  | ⏳ |
| 5     | Multi-tenant onboarding + connector SDK    | ⏳ |
| 6     | LangGraph migration (complex agent graphs) | ⏳ |
| 7     | Eval harness + golden datasets             | ⏳ |
| 8     | Production hardening, SSO, billing         | ⏳ |

---

## Further reading

- **Architecture deep-dive**: [`docs/architecture.md`](docs/architecture.md)
- **DP schema (the data contract)**: [`app/schema.yaml`](app/schema.yaml)
- **Producer Copilot prompt**: [`app/prompts/producer_copilot.md`](app/prompts/producer_copilot.md)
- **SQL security tests**: [`tests/test_sql_security.py`](tests/test_sql_security.py)
