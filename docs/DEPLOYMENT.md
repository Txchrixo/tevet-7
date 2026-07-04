# Deployment Guide — Tevet-7

This guide walks through deploying the full Tevet-7 stack (FastAPI backend + Next.js frontend + PostgreSQL + Langfuse) on Railway. The same Dockerfiles work on any container host (Fly.io, Render, AWS App Runner, GCP Cloud Run), but Railway is the recommended path because it handles Postgres, custom domains, and secrets in a single workflow.

> **TL;DR** — Push the repo, create 3 Railway services (backend, frontend, postgres), set the env vars from the table below, attach a custom domain, done.

---

## 1. Architecture recap

```
                    ┌──────────────────────────────┐
                    │       Railway Project         │
                    │                              │
   HTTPS  ─────────►│  tevet7-frontend  (Next.js)  │
                    │       │  /api/* proxies       │
                    │       ▼                      │
                    │  tevet7-backend  (FastAPI)   │
                    │       │                      │
                    │       ├──► Postgres (managed)│
                    │       └──► Langfuse Cloud    │
                    └──────────────────────────────┘
```

The Next.js frontend proxies every `/api/*` request to the FastAPI backend — the browser only ever talks to one origin. This means CORS is trivially scoped to a single domain (the frontend's) and JWTs never leak to third-party origins.

---

## 2. Prerequisites

- A GitHub account with push access to `Txchrixo/tevet-7`.
- A [Railway](https://railway.app) account (the Hobby plan covers the dev/staging footprint).
- An OpenAI API key with `gpt-4o-mini` access.
- A [Langfuse Cloud](https://cloud.langfuse.com) account (free tier is enough).
- (Optional) A custom domain pointing at Railway's nameservers.

---

## 3. Provisioning the Railway project

### 3.1 Create the project + Postgres

1. Go to **railway.app → New Project → Deploy from GitHub repo**.
2. Pick `Txchrixo/tevet-7`.
3. Add a **PostgreSQL** database via **+ New → Database → PostgreSQL**. Railway provisions a managed Postgres 16 instance and exposes `DATABASE_URL` (and friends) as service variables.
4. (Optional but recommended) Run this once in the Postgres shell to enable `pgvector`:

   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

### 3.2 Deploy the backend

1. **+ New → GitHub Repo → tevet-7**.
2. Set the **Root Directory** to `agentic-service` (Railway auto-detects the Dockerfile).
3. Set the env vars from the [backend table](#5-environment-variables) below.
4. Railway builds and deploys. Confirm the health check passes:

   ```bash
   curl https://<backend-domain>.railway.app/health
   # {"status":"ok","service":"tevet-7","version":"0.1.0"}
   ```

### 3.3 Deploy the frontend

1. **+ New → GitHub Repo → tevet-7** (same repo, different root).
2. Set the **Root Directory** to `.` (project root — where the Next.js `Dockerfile` lives).
3. Set the env vars from the [frontend table](#5-environment-variables) below.
4. Railway builds and deploys. Visit the generated domain — you should land on the auth screen.

### 3.4 Wire the services together

In the backend service's variables, set:

```
CORS_ORIGINS=https://<frontend-domain>.railway.app
```

In the frontend service's variables, set:

```
AGENTIC_SERVICE_URL=https://<backend-domain>.railway.app
NEXT_PUBLIC_AGENTIC_SERVICE_URL=https://<backend-domain>.railway.app
```

---

## 4. Migrating from SQLite to PostgreSQL

The dev environment runs on an in-process SQLite database (`dev.db`) that is created and seeded on startup (`app/db_seed.py`). Production uses Postgres — the only change required is the `DATABASE_URL` environment variable.

### 4.1 Update the connection string

In Railway's backend service, set:

```
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/<db>
```

The `app/config.py` `_coerce_sqlite_default` validator accepts `postgresql+asyncpg://` URLs as-is — no code change needed.

### 4.2 Seed the production database

The FastAPI lifespan calls `init_db()` on startup, which:

1. Creates the 8 business tables + `users` / `tenants` / `tenant_memberships` / `tenant_configs` / `traces` / `documents` / `approval_requests` / `producer_onboardings` tables.
2. Seeds the Drive Producteur demo data (products, producers, orders, order items, stock movements).
3. Creates the 3 demo users (marie / pierre / admin) + their memberships.
4. Trains the ML stock-shortage model if `stock_shortage_model.pkl` is missing.

On first deploy, the backend logs should show:

```
Tevet-7 starting — version=0.1.0 env=production llm_model=gpt-4o-mini
SQLite database ready at postgresql+asyncpg://...
ML model: stock_shortage_model.pkl ready (forecast_tool active)
Tracer active: LangfuseTracer
```

### 4.3 (Optional) Run alembic migrations

Currently the schema is created idempotently on startup (drop + recreate for SQLite, `CREATE TABLE IF NOT EXISTS` for Postgres). For production with persistent data, wrap the schema in Alembic migrations so future column additions don't drop existing rows. This is left as an exercise for the operator — the current codebase works fine on a fresh Postgres instance.

---

## 5. Environment variables

### Backend (`tevet7-backend`)

| Variable | Required | Example | Notes |
|---|---|---|---|
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://user:pwd@host:5432/tevet7` | Async SQLAlchemy URL. SQLite for dev, Postgres for prod. |
| `JWT_SECRET` | ✅ | `openssl rand -base64 32` | HS256 signing secret. Rotate quarterly. |
| `JWT_ALGORITHM` | — | `HS256` | Default `HS256`. |
| `OPENAI_API_KEY` | ✅ | `sk-...` | Used by the orchestrator + forecast tool. |
| `LLM_MODEL` | — | `gpt-4o-mini` | Default `gpt-4o-mini`. |
| `EMBEDDING_MODEL` | — | `text-embedding-3-small` | Used for RAG embeddings. |
| `LANGFUSE_PUBLIC_KEY` | — | `pk-lf-...` | Set both keys to enable LangfuseTracer. |
| `LANGFUSE_SECRET_KEY` | — | `sk-lf-...` | Set both keys to enable LangfuseTracer. |
| `LANGFUSE_HOST` | — | `https://cloud.langfuse.com` | Default is Langfuse Cloud. |
| `CORS_ORIGINS` | ✅ | `https://app.tevet7.dev` | Comma-separated; `*` only for dev. |
| `ENV` | — | `production` | `development` \| `staging` \| `production`. |
| `LOG_LEVEL` | — | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR`. |
| `TOKEN_QUOTA_PER_TENANT_PER_DAY` | — | `200000` | Hard cap on tokens per tenant per UTC day. |
| `DEMO_RESET_ENABLED` | — | `true` | Resets the `dp` demo tenant every 24h. |

### Frontend (`tevet7-frontend`)

| Variable | Required | Example | Notes |
|---|---|---|---|
| `AGENTIC_SERVICE_URL` | ✅ | `https://tevet7-backend.up.railway.app` | Backend base URL (server-side). |
| `NEXT_PUBLIC_AGENTIC_SERVICE_URL` | ✅ | `https://tevet7-backend.up.railway.app` | Backend base URL (browser-side, for any client-side calls). |
| `NODE_ENV` | — | `production` | Always `production` in deploy. |
| `PORT` | — | `3000` | Railway injects `$PORT` automatically. |

---

## 6. Langfuse setup

Langfuse is the LLM observability layer — every `/api/chat` request emits a trace with spans for the orchestrator loop, the LLM call, and each tool execution.

### 6.1 Create a Langfuse project

1. Sign up at [cloud.langfuse.com](https://cloud.langfuse.com).
2. **+ New Project → Tevet-7 Production**.
3. Go to **Settings → API Keys → + Create new API keys**.
4. Copy the **Public** and **Secret** keys.

### 6.2 Wire the keys to the backend

In Railway's backend service, set:

```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
```

Restart the service. The startup log should now show `Tracer active: LangfuseTracer` instead of `Tracer active: LocalTracer`.

### 6.3 Verify traces

1. Log in as `marie@tevet7.dev / tevet7demo`.
2. Ask "Quels sont mes 5 produits les plus vendus ce mois-ci ?"
3. Open Langfuse → **Traces**. You should see a single trace with:
   - A generation span for the orchestrator's first LLM call.
   - Tool spans for `sql_read_tool` (with the rewritten SQL).
   - Cost + latency + token counts.

### 6.4 (Optional) Self-host Langfuse

For tenants with data-residency requirements, self-host Langfuse via `agentic-service/docker-compose.yml` (Postgres + Langfuse). Set `LANGFUSE_HOST` to your self-hosted URL and point it at the same Postgres instance used by the backend.

---

## 7. Custom domain

### 7.1 Frontend (the user-facing app)

1. In Railway's frontend service → **Settings → Networking → Generate Domain** (gives you `*.up.railway.app`) or **Custom Domain → Add**.
2. For a custom domain like `app.tevet7.dev`:
   - Add a `CNAME` record in your DNS provider pointing at the Railway-generated domain.
   - Railway issues the TLS certificate automatically via Let's Encrypt.
3. Wait for the certificate to provision (usually under 60 seconds).
4. Update `CORS_ORIGINS` on the backend to include the new domain.

### 7.2 Backend (no public access needed)

The backend should NOT be exposed on a custom domain — only the frontend talks to it, via the `AGENTIC_SERVICE_URL` env var. If you want to lock it down further:

- In Railway's backend service → **Settings → Networking → Private Networking**. The backend becomes reachable only from within the Railway project (`tevet7-backend.railway.internal`).
- Update `AGENTIC_SERVICE_URL` to `http://tevet7-backend.railway.internal:8001`.

### 7.3 API documentation

The FastAPI auto-docs (`/docs` and `/redoc`) are exposed by default. For production, restrict them by setting `OPENAPI_URL=None` in `app/main.py` or by gating them behind an admin JWT check.

---

## 8. Post-deploy verification checklist

- [ ] `curl https://<backend>/health` returns `{"status":"ok",...}`.
- [ ] `curl https://<frontend>/` returns the auth screen HTML.
- [ ] Login as `marie@tevet7.dev / tevet7demo` succeeds (JWT issued).
- [ ] A "Quels sont mes 5 produits les plus vendus ce mois-ci ?" question returns 5 products with `producer_id = 42` in the SQL (visible in the inspector).
- [ ] Login as `pierre@tevet7.dev` returns producer 99's data — NOT producer 42's.
- [ ] Login as `admin@tevet7.dev` shows the admin console with tenant stats.
- [ ] Langfuse shows a trace for each chat request.
- [ ] The 8 security tests pass: `cd agentic-service && pytest tests/test_sql_security.py -v`.
- [ ] The 39-case eval passes: `cd agentic-service && python3 -m eval.eval`.

---

## 9. Rollback

Railway keeps every deploy as an immutable image. To roll back:

1. Open the failing service in Railway.
2. Go to **Deployments**.
3. Click **Promote to latest** on the previous good deploy.

The rollback is instant (container swap) — no database migration is reversed. If a migration broke the schema, restore the Postgres snapshot from Railway's **Postgres → Backups** tab.

---

## 10. Cost optimization

- **Backend**: the FastAPI service is I/O-bound (LLM + DB calls). A single 1-vCPU / 512MB container handles ~50 concurrent chats. Scale horizontally by raising the replica count.
- **Frontend**: Next.js is mostly static. A 256MB container is plenty.
- **Postgres**: Railway's `$5/mo` developer tier covers the demo workload. Switch to a managed RDS/CloudSQL instance once you exceed 1GB of data.
- **LLM**: `gpt-4o-mini` is ~$0.15/M input tokens. The 200K/day quota caps a tenant at ~$30/day worst case. Tune `TOKEN_QUOTA_PER_TENANT_PER_DAY` per-tier.
- **Langfuse**: the cloud free tier covers 10K observations/month — enough for staging + low-traffic prod. Above that, self-host.

---

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/health` returns 502 | Container crashed on startup | Check logs: usually a missing env var or DB connection refused. |
| Login returns 401 | `JWT_SECRET` mismatch between frontend and backend | Both services MUST share the same `JWT_SECRET`. |
| Chat returns `Tracer active: LocalTracer` despite Langfuse keys set | One of the Langfuse env vars is missing or still has the `pk-lf-replace-me` placeholder | Verify all three (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`) are set. |
| CORS error in browser console | `CORS_ORIGINS` on backend doesn't include the frontend domain | Set `CORS_ORIGINS=https://app.tevet7.dev` (no trailing slash). |
| SQL tool returns `SqlSecurityError` on every query | The schema.yaml's `tenant_scope_column` doesn't match the database column name | Check `app/schema.yaml` vs. the actual DB schema. |
| ML forecast tool returns "model not trained" | `stock_shortage_model.pkl` is missing AND the training script failed | Check the startup log for `ensure_model_trained() failed`. Re-run `python3 -m ml.train_stock_model`. |

For anything else, consult the [worklog](../worklog.md) — every phase has a "Stage Summary" section that explains the design trade-offs.
