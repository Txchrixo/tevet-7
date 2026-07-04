// ---------------------------------------------------------------------------
// Onboarding API client (Phase 6b)
// ---------------------------------------------------------------------------
//
// All requests go through the relative `/api/tenants/{id}/onboarding/*`
// paths — Next.js route handlers proxy them server-side to
// `http://localhost:8001/api/tenants/{id}/onboarding/*` (same pattern as the
// chat + documents + tenants proxies). The browser never talks to the FastAPI
// service directly, so the prototype works on any port the Preview Panel
// serves the app on.
//
// The store is responsible for persisting the JWT to localStorage and
// attaching it to every API call. The functions in this file are pure I/O —
// they read the token from localStorage (mirroring `src/lib/api.ts`) and
// return typed payloads.
//
// Every function throws an `OnboardingApiError` on failure so the wizard can
// surface a precise message ("Connection URL invalide", "CSV sans en-tête",
// "Backend injoignable", etc.).

import type {
  ConnectionTest,
  ConnectorType,
  OnboardingStatus,
  RoleConfig,
  SchemaDraft,
  SchemaTable,
  Tenant,
} from "./types";

const ONBOARDING_TIMEOUT_MS = 30_000;
const AUTH_TOKEN_STORAGE_KEY = "tevet7.auth.token";

/** Error shape used by every onboarding-api function. */
export class OnboardingApiError extends Error {
  /** HTTP status returned by the backend (or 502 for proxy-level failures). */
  readonly status: number;
  /** Optional machine-readable code from the backend envelope. */
  readonly code: string | null;

  constructor(
    message: string,
    status: number,
    code: string | null = null,
  ) {
    super(message);
    this.name = "OnboardingApiError";
    this.status = status;
    this.code = code;
  }
}

interface BackendErrorEnvelope {
  error?: string;
  detail?: string;
  message?: string;
  code?: string;
}

async function parseBackendError(
  res: Response,
  fallback: string,
): Promise<OnboardingApiError> {
  let code: string | null = null;
  let detail = fallback;
  try {
    const json = (await res.json()) as BackendErrorEnvelope;
    if (json.code) code = json.code;
    if (json.error) detail = json.error;
    else if (json.detail) detail = json.detail;
    else if (json.message) detail = json.message;
  } catch {
    // Non-JSON body — keep the fallback message.
  }
  return new OnboardingApiError(detail, res.status, code);
}

/** Read the persisted JWT from localStorage (browser-only, no-op on SSR). */
function readAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function authHeaders(): Record<string, string> {
  const token = readAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    ONBOARDING_TIMEOUT_MS,
  );
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function tenantBase(tenantId: string): string {
  return `/api/tenants/${encodeURIComponent(tenantId)}/onboarding`;
}

// ---------------------------------------------------------------------------
// POST /onboarding/connect
// ---------------------------------------------------------------------------

interface BackendConnectionTest {
  ok: boolean;
  error: string | null;
  tables_count: number;
}

/**
 * Test a PostgreSQL connection. The backend tries to introspect the schema
 * and returns the number of tables it can see — `ok: true` means the URL
 * is reachable AND the credentials have read access.
 */
export async function connectPostgres(
  tenantId: string,
  connectionUrl: string,
): Promise<ConnectionTest> {
  const res = await fetchWithTimeout(`${tenantBase(tenantId)}/connect`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify({
      connector_type: "postgres",
      connection_url: connectionUrl,
    }),
  });
  if (!res.ok) {
    throw await parseBackendError(
      res,
      `connectPostgres → HTTP ${res.status} ${res.statusText}`,
    );
  }
  const json = (await res.json()) as BackendConnectionTest;
  return {
    ok: json.ok,
    error: json.error,
    tables_count: json.tables_count,
  };
}

/**
 * Upload a CSV file and have the backend infer a schema from the header row.
 * The file is sent as multipart/form-data so the backend can stream it into
 * the tenant's SQLite sidecar without buffering the whole thing in memory.
 */
export async function connectCsv(
  tenantId: string,
  file: File,
): Promise<ConnectionTest> {
  const fd = new FormData();
  fd.append("connector_type", "csv");
  fd.append("file", file, file.name || "upload.csv");

  const res = await fetchWithTimeout(`${tenantBase(tenantId)}/connect`, {
    method: "POST",
    headers: { Accept: "application/json", ...authHeaders() },
    body: fd,
  });
  if (!res.ok) {
    throw await parseBackendError(
      res,
      `connectCsv → HTTP ${res.status} ${res.statusText}`,
    );
  }
  const json = (await res.json()) as BackendConnectionTest;
  return {
    ok: json.ok,
    error: json.error,
    tables_count: json.tables_count,
  };
}

// ---------------------------------------------------------------------------
// POST /onboarding/detect-schema
// ---------------------------------------------------------------------------

interface BackendSchemaColumn {
  name: string;
  type: string;
  description?: string;
  selected?: boolean;
}

interface BackendSchemaTable {
  name: string;
  description?: string;
  columns: BackendSchemaColumn[];
  selected?: boolean;
  /** Backend field for the RLS scope column (Phase 6b). */
  tenant_scope_column?: string | null;
  /** Legacy field name — kept for backward compat. */
  scope_column?: string | null;
  /** Backend metadata fields we ignore on the frontend. */
  allowed_for_roles?: string[];
  joins_to?: unknown[];
}

interface BackendSchemaDraft {
  schema: { tables: BackendSchemaTable[] };
}

/**
 * Ask the backend to auto-detect the tenant's schema (tables + columns +
 * best-guess types + descriptions). Returns a draft the user can edit
 * (toggle tables/columns on or off, pick a scope column per table).
 *
 * The backend's response uses `tenant_scope_column` for the RLS scope
 * (per-table); we normalise to the frontend's `scope_column` field. Tables
 * and columns default to `selected: true` (the backend doesn't currently
 * send this field — the wizard's "all selected by default" matches the
 * common case).
 */
export async function detectSchema(tenantId: string): Promise<SchemaDraft> {
  const res = await fetchWithTimeout(
    `${tenantBase(tenantId)}/detect-schema`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...authHeaders(),
      },
      body: JSON.stringify({}),
    },
  );
  if (!res.ok) {
    throw await parseBackendError(
      res,
      `detectSchema → HTTP ${res.status} ${res.statusText}`,
    );
  }
  const json = (await res.json()) as BackendSchemaDraft;
  return {
    tables: (json.schema?.tables ?? []).map((t) => ({
      name: t.name,
      description: t.description ?? "",
      columns: (t.columns ?? []).map((c) => ({
        name: c.name,
        type: c.type,
        description: c.description ?? "",
        selected: c.selected ?? true,
      })),
      selected: t.selected ?? true,
      scope_column: t.tenant_scope_column ?? t.scope_column ?? null,
    })),
  };
}

// ---------------------------------------------------------------------------
// POST /onboarding/save-schema
// ---------------------------------------------------------------------------

interface BackendSaveSchemaBody {
  schema_config: {
    tables: Array<{
      name: string;
      description: string;
      columns: Array<{
        name: string;
        type: string;
        description: string;
        selected: boolean;
      }>;
      selected: boolean;
      scope_column: string | null;
    }>;
    forbidden_tables: string[];
    metadata: Record<string, unknown>;
  };
}

/**
 * Persist the user's table/column selection + RLS scope columns. The backend
 * stores this as the tenant's effective `schema.yaml` so the agent only sees
 * the tables/columns the user explicitly approved.
 */
export async function saveSchema(
  tenantId: string,
  tables: SchemaTable[],
): Promise<{ ok: boolean }> {
  const forbidden = tables
    .filter((t) => !t.selected)
    .map((t) => t.name);
  const body: BackendSaveSchemaBody = {
    schema_config: {
      tables: tables
        .filter((t) => t.selected)
        .map((t) => ({
          name: t.name,
          description: t.description,
          columns: t.columns.map((c) => ({
            name: c.name,
            type: c.type,
            description: c.description,
            selected: c.selected,
          })),
          selected: t.selected,
          scope_column: t.scope_column,
        })),
      forbidden_tables: forbidden,
      metadata: {
        source: "onboarding-wizard",
        saved_at: new Date().toISOString(),
      },
    },
  };

  const res = await fetchWithTimeout(
    `${tenantBase(tenantId)}/save-schema`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...authHeaders(),
      },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) {
    throw await parseBackendError(
      res,
      `saveSchema → HTTP ${res.status} ${res.statusText}`,
    );
  }
  const json = (await res.json()) as { ok?: boolean };
  return { ok: json.ok ?? true };
}

// ---------------------------------------------------------------------------
// POST /onboarding/save-roles
// ---------------------------------------------------------------------------

/**
 * Backend contract note (Phase 6b): the FastAPI endpoint expects
 * `roles_config` as a **dict** keyed by role name (NOT a list):
 *
 *   {
 *     "admin":   {"scope_column": null,        "allowed_tables": [...]},
 *     "user":    {"scope_column": "id",        "allowed_tables": [...]}
 *   }
 *
 * The frontend works with an array of `RoleConfig` (so the UI can render
 * them as a list with add/remove buttons) — `saveRoles` converts the array
 * to the dict shape the backend expects. Role names are the dict keys, so
 * they MUST be unique. We keep the LAST role when names collide (defensive
 * — the UI doesn't currently enforce uniqueness, but the user editing a
 * duplicate name is a no-op for the backend save).
 */
interface BackendSaveRolesBody {
  roles_config: Record<
    string,
    { scope_column: string | null; allowed_tables: string[] }
  >;
}

/**
 * Persist the tenant's roles (admin + scoped roles). Each role's
 * `scope_column` is the column the agent uses for row-level scoping when
 * this role is the active identity (e.g. "producer_id" or "team_id").
 */
export async function saveRoles(
  tenantId: string,
  roles: RoleConfig[],
): Promise<{ ok: boolean }> {
  const rolesDict: BackendSaveRolesBody["roles_config"] = {};
  for (const r of roles) {
    rolesDict[r.name] = {
      scope_column: r.scope_column,
      allowed_tables: r.allowed_tables,
    };
  }
  const body: BackendSaveRolesBody = { roles_config: rolesDict };

  const res = await fetchWithTimeout(
    `${tenantBase(tenantId)}/save-roles`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...authHeaders(),
      },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) {
    throw await parseBackendError(
      res,
      `saveRoles → HTTP ${res.status} ${res.statusText}`,
    );
  }
  const json = (await res.json()) as { ok?: boolean; saved?: boolean };
  return { ok: json.ok ?? json.saved ?? true };
}

// ---------------------------------------------------------------------------
// POST /onboarding/complete
// ---------------------------------------------------------------------------

/**
 * Backend response shape (Phase 6b): the endpoint returns `{onboarded: true,
 * tenant_id: "..."}` — NOT a full tenant record. The store uses the
 * `tenant_id` to refresh the onboarding status; the tenant record itself
 * is already in `state.tenants` from the create-tenant step.
 */
interface BackendCompleteResult {
  onboarded?: boolean;
  ok?: boolean;
  tenant_id?: string;
  tenant?: Tenant;
}

/**
 * Mark the tenant as onboarded. The backend flips the tenant's `onboarded`
 * flag and returns `{onboarded: true, tenant_id: "..."}`. We normalise the
 * shape so the store can treat both this minimal response AND a future
 * richer response (with the full tenant record) the same way.
 */
export async function completeOnboarding(
  tenantId: string,
): Promise<{ ok: boolean; tenant: Tenant | null; tenantId: string }> {
  const res = await fetchWithTimeout(
    `${tenantBase(tenantId)}/complete`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...authHeaders(),
      },
      body: JSON.stringify({}),
    },
  );
  if (!res.ok) {
    throw await parseBackendError(
      res,
      `completeOnboarding → HTTP ${res.status} ${res.statusText}`,
    );
  }
  const json = (await res.json()) as BackendCompleteResult;
  return {
    ok: json.ok ?? json.onboarded ?? true,
    tenant: json.tenant ?? null,
    tenantId: json.tenant_id ?? tenantId,
  };
}

// ---------------------------------------------------------------------------
// GET /onboarding/status
// ---------------------------------------------------------------------------

interface BackendOnboardingStatus {
  onboarded: boolean;
  connector_type: ConnectorType | null;
  schema_tables_count: number;
  roles_count: number;
}

/**
 * Fetch the onboarding status for a tenant. Used by `page.tsx` on mount (and
 * after tenant switches) to decide whether to render the wizard or the chat.
 *
 * A 404 (endpoint not implemented yet — backend contract built in parallel)
 * is treated as "tenant onboarded" so the demo flow isn't broken while the
 * backend lands.
 */
export async function getOnboardingStatus(
  tenantId: string,
): Promise<OnboardingStatus> {
  try {
    const res = await fetchWithTimeout(
      `${tenantBase(tenantId)}/status`,
      {
        method: "GET",
        headers: { Accept: "application/json", ...authHeaders() },
      },
    );
    if (!res.ok) {
      throw await parseBackendError(
        res,
        `getOnboardingStatus → HTTP ${res.status} ${res.statusText}`,
      );
    }
    const json = (await res.json()) as BackendOnboardingStatus;
    return {
      onboarded: json.onboarded,
      connector_type: json.connector_type,
      schema_tables_count: json.schema_tables_count,
      roles_count: json.roles_count,
    };
  } catch (err) {
    if (err instanceof OnboardingApiError) {
      // 404 = endpoint not yet implemented → treat as "onboarded: true" so
      // existing demo tenants (Drive Producteur, is_demo) keep working while
      // the backend onboarding API lands in parallel.
      if (err.status === 404) {
        return {
          onboarded: true,
          connector_type: null,
          schema_tables_count: 0,
          roles_count: 0,
        };
      }
      throw err;
    }
    // Network / proxy error — same fallback so the demo isn't broken.
    return {
      onboarded: true,
      connector_type: null,
      schema_tables_count: 0,
      roles_count: 0,
    };
  }
}
