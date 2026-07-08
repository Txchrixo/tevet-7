/**
 * Tevet-7 onboarding API client.
 *
 * All onboarding endpoints are proxied through the Next.js catch-all route at
 * `/api/tenants/{id}/onboarding/*` (see
 * `src/app/api/tenants/[id]/onboarding/[[...step]]/route.ts`). The proxy
 * forwards the Authorization header (JWT) to the FastAPI onboarding service at
 * `http://localhost:8001/api/tenants/{id}/onboarding/*`.
 *
 * The frontend never talks to localhost:8001 directly - only relative paths
 * so the request goes through Next.js (and Caddy in production).
 *
 * Why a separate client (vs. reusing admin-api.ts):
 *   - onboarding has its own error envelope (`{ok, error, tables_count}`)
 *   - the connect endpoint accepts multipart/form-data for CSV uploads
 *   - the schema/roles endpoints take large nested payloads that don't fit
 *     the admin client's flat `body` shape
 */

import type {
  OnboardingConnectResult,
  OnboardingRole,
  OnboardingSaveResult,
  OnboardingSchemaTable,
  OnboardingStatus,
} from "./types";

/** Where the JWT is persisted client-side (set by the login flow). */


/**
 * Thrown by the onboarding client for any non-2xx response OR when the backend
 * is unreachable (502 from the Next.js proxy).
 */
export class OnboardingApiError extends Error {
  status: number;
  detail: unknown;
  unreachable: boolean;
  constructor(
    message: string,
    status: number,
    detail?: unknown,
    unreachable = false,
  ) {
    super(message);
    this.name = "OnboardingApiError";
    this.status = status;
    this.detail = detail;
    this.unreachable = unreachable;
  }
}

/**
 * Parses a backend response body. Handles JSON + plain text. Returns
 * `{ parsed, rawText }` so the caller can fall back to raw text when JSON
 * parsing fails.
 */
async function parseBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (text.length === 0) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/** Extracts a human-readable error message from a parsed backend response. */
function describeError(parsed: unknown, fallback: string): string {
  if (typeof parsed === "object" && parsed && "detail" in parsed) {
    const detail = (parsed as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0];
      if (first && typeof first === "object" && "msg" in first) {
        return String((first as { msg: unknown }).msg);
      }
    }
    return JSON.stringify(detail);
  }
  if (typeof parsed === "object" && parsed && "message" in parsed) {
    return String((parsed as { message: unknown }).message);
  }
  if (typeof parsed === "object" && parsed && "error" in parsed) {
    return String((parsed as { error: unknown }).error);
  }
  if (typeof parsed === "string" && parsed.length > 0) return parsed;
  return fallback;
}

// ---------------------------------------------------------------------------
// Step 1 - Connect data source
// ---------------------------------------------------------------------------

/**
 * `POST /api/tenants/{id}/onboarding/connect` with JSON `{connector_type:
 * "postgres", connection_url}`. Tests the connection and persists the
 * connector config on the backend.
 */
export async function connectPostgres(
  tenantId: string,
  connectionUrl: string,
): Promise<OnboardingConnectResult> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };

  let res: Response;
  try {
    res = await fetch(
      `/api/tenants/${encodeURIComponent(tenantId)}/onboarding/connect`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({
          connector_type: "postgres",
          connection_url: connectionUrl,
        }),
      },
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : "Network error";
    throw new OnboardingApiError(message, 0, undefined, true);
  }

  const parsed = await parseBody(res);

  if (res.status === 502) {
    throw new OnboardingApiError(
      "Backend Tevet-7 injoignable",
      502,
      parsed,
      true,
    );
  }

  if (!res.ok) {
    throw new OnboardingApiError(
      describeError(parsed, `Onboarding connect ${res.status} ${res.statusText}`),
      res.status,
      parsed,
    );
  }

  const r =
    (typeof parsed === "object" && parsed !== null ? parsed : {}) as Record<
      string,
      unknown
    >;
  return {
    ok: Boolean(r.ok ?? res.ok),
    error: typeof r.error === "string" ? r.error : null,
    tables_count: typeof r.tables_count === "number" ? r.tables_count : 0,
  };
}

/**
 * `POST /api/tenants/{id}/onboarding/connect` with `multipart/form-data`
 * (`connector_type=csv` + `file=<csv_file>`). Uploads the CSV and persists
 * the connector config on the backend.
 */
export async function connectCsv(
  tenantId: string,
  file: File,
): Promise<OnboardingConnectResult> {
  const headers: Record<string, string> = {};
  // NOTE: do NOT set content-type - the browser sets it automatically with
  // the correct multipart boundary when we pass a FormData body.

  const form = new FormData();
  form.append("connector_type", "csv");
  form.append("file", file);

  let res: Response;
  try {
    res = await fetch(
      `/api/tenants/${encodeURIComponent(tenantId)}/onboarding/connect`,
      {
        method: "POST",
        headers,
        body: form,
      },
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : "Network error";
    throw new OnboardingApiError(message, 0, undefined, true);
  }

  const parsed = await parseBody(res);

  if (res.status === 502) {
    throw new OnboardingApiError(
      "Backend Tevet-7 injoignable",
      502,
      parsed,
      true,
    );
  }

  if (!res.ok) {
    throw new OnboardingApiError(
      describeError(parsed, `Onboarding connect ${res.status} ${res.statusText}`),
      res.status,
      parsed,
    );
  }

  const r =
    (typeof parsed === "object" && parsed !== null ? parsed : {}) as Record<
      string,
      unknown
    >;
  return {
    ok: Boolean(r.ok ?? res.ok),
    error: typeof r.error === "string" ? r.error : null,
    tables_count: typeof r.tables_count === "number" ? r.tables_count : 0,
  };
}

// ---------------------------------------------------------------------------
// Step 2 - Detect schema
// ---------------------------------------------------------------------------

/** Raw column shape returned by the backend `detect-schema` endpoint. */
interface RawColumn {
  name: string;
  type: string;
  description?: string;
}

/** Raw table shape returned by the backend `detect-schema` endpoint. */
interface RawTable {
  name: string;
  description?: string;
  columns: RawColumn[];
}

/**
 * `POST /api/tenants/{id}/onboarding/detect-schema`. Returns the detected
 * tables + columns, normalized to the frontend's `OnboardingSchemaTable`
 * shape (with `selected: true` and `scope_column: null` defaults so the
 * wizard starts with everything selected).
 */
export async function detectSchema(
  tenantId: string,
): Promise<{ tables: OnboardingSchemaTable[] }> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };

  let res: Response;
  try {
    res = await fetch(
      `/api/tenants/${encodeURIComponent(tenantId)}/onboarding/detect-schema`,
      {
        method: "POST",
        headers,
      },
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : "Network error";
    throw new OnboardingApiError(message, 0, undefined, true);
  }

  const parsed = await parseBody(res);

  if (res.status === 502) {
    throw new OnboardingApiError(
      "Backend Tevet-7 injoignable",
      502,
      parsed,
      true,
    );
  }

  if (!res.ok) {
    throw new OnboardingApiError(
      describeError(parsed, `Detect schema ${res.status} ${res.statusText}`),
      res.status,
      parsed,
    );
  }

  const r =
    (typeof parsed === "object" && parsed !== null ? parsed : {}) as Record<
      string,
      unknown
    >;
  const rawTables = Array.isArray(r.tables)
    ? (r.tables as RawTable[])
    : Array.isArray((r as any).schema?.tables)
      ? ((r as any).schema.tables as RawTable[])
      : [];
  const tables: OnboardingSchemaTable[] = rawTables.map((t) => ({
    name: t.name,
    description: t.description,
    selected: true,
    scope_column: null,
    columns: (Array.isArray(t.columns) ? t.columns : []).map((c) => ({
      name: c.name,
      type: c.type,
      description: c.description,
      selected: true,
    })),
  }));
  return { tables };
}

// ---------------------------------------------------------------------------
// Step 2 (save) - Save schema
// ---------------------------------------------------------------------------

/**
 * `POST /api/tenants/{id}/onboarding/save-schema`. Persists the wizard's
 * schema draft (selected tables + columns + scope columns) as the tenant's
 * `schema_config`.
 */
export async function saveSchema(
  tenantId: string,
  schemaConfig: {
    tables: OnboardingSchemaTable[];
    forbidden_tables?: string[];
    metadata?: Record<string, unknown>;
  },
): Promise<OnboardingSaveResult> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };

  // Strip the wizard-only `selected` flag before sending - the backend stores
  // the schema without it. Deselected tables/columns are dropped entirely.
  const payload = {
    schema_config: {
      tables: schemaConfig.tables
        .filter((t) => t.selected)
        .map((t) => ({
          name: t.name,
          description: t.description,
          scope_column: t.scope_column,
          columns: t.columns.filter((c) => c.selected).map((c) => ({
            name: c.name,
            type: c.type,
            description: c.description,
          })),
        })),
      forbidden_tables: schemaConfig.forbidden_tables ?? [],
      metadata: schemaConfig.metadata ?? {},
    },
  };

  let res: Response;
  try {
    res = await fetch(
      `/api/tenants/${encodeURIComponent(tenantId)}/onboarding/save-schema`,
      {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
      },
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : "Network error";
    throw new OnboardingApiError(message, 0, undefined, true);
  }

  const parsed = await parseBody(res);

  if (res.status === 502) {
    throw new OnboardingApiError(
      "Backend Tevet-7 injoignable",
      502,
      parsed,
      true,
    );
  }

  if (!res.ok) {
    throw new OnboardingApiError(
      describeError(parsed, `Save schema ${res.status} ${res.statusText}`),
      res.status,
      parsed,
    );
  }

  const r =
    (typeof parsed === "object" && parsed !== null ? parsed : {}) as Record<
      string,
      unknown
    >;
  return { ok: Boolean(r.ok ?? res.ok) };
}

// ---------------------------------------------------------------------------
// Step 3 - Save roles
// ---------------------------------------------------------------------------

/**
 * `POST /api/tenants/{id}/onboarding/save-roles`. Persists the wizard's roles
 * draft as the tenant's `roles_config`.
 */
export async function saveRoles(
  tenantId: string,
  rolesConfig: OnboardingRole[],
): Promise<OnboardingSaveResult> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };

  let res: Response;
  try {
    res = await fetch(
      `/api/tenants/${encodeURIComponent(tenantId)}/onboarding/save-roles`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({
        roles_config: Object.fromEntries(
          rolesConfig.map((r) => [
            r.name,
            { scope_column: r.scope_column, allowed_tables: r.allowed_tables },
          ]),
        ),
      }),
      },
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : "Network error";
    throw new OnboardingApiError(message, 0, undefined, true);
  }

  const parsed = await parseBody(res);

  if (res.status === 502) {
    throw new OnboardingApiError(
      "Backend Tevet-7 injoignable",
      502,
      parsed,
      true,
    );
  }

  if (!res.ok) {
    throw new OnboardingApiError(
      describeError(parsed, `Save roles ${res.status} ${res.statusText}`),
      res.status,
      parsed,
    );
  }

  const r =
    (typeof parsed === "object" && parsed !== null ? parsed : {}) as Record<
      string,
      unknown
    >;
  return { ok: Boolean(r.ok ?? res.ok) };
}

// ---------------------------------------------------------------------------
// Step 4 - Complete onboarding
// ---------------------------------------------------------------------------

/**
 * `POST /api/tenants/{id}/onboarding/complete`. Marks the tenant as onboarded
 * on the backend (flips `tenant_configs.onboarded = true`). After this call,
 * `GET /api/auth/me` returns memberships with `onboarded: true` and the
 * frontend gate lets the user through to the chat surface.
 */
export async function completeOnboarding(
  tenantId: string,
): Promise<OnboardingSaveResult> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };

  let res: Response;
  try {
    res = await fetch(
      `/api/tenants/${encodeURIComponent(tenantId)}/onboarding/complete`,
      {
        method: "POST",
        headers,
      },
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : "Network error";
    throw new OnboardingApiError(message, 0, undefined, true);
  }

  const parsed = await parseBody(res);

  if (res.status === 502) {
    throw new OnboardingApiError(
      "Backend Tevet-7 injoignable",
      502,
      parsed,
      true,
    );
  }

  if (!res.ok) {
    throw new OnboardingApiError(
      describeError(parsed, `Complete onboarding ${res.status} ${res.statusText}`),
      res.status,
      parsed,
    );
  }

  const r =
    (typeof parsed === "object" && parsed !== null ? parsed : {}) as Record<
      string,
      unknown
    >;
  return { ok: Boolean(r.ok ?? res.ok) };
}

// ---------------------------------------------------------------------------
// Status (used by the store to refresh memberships)
// ---------------------------------------------------------------------------

/**
 * `GET /api/tenants/{id}/onboarding/status`. Returns whether the tenant is
 * onboarded, the connector type, the schema table count, and the roles count.
 */
export async function getOnboardingStatus(
  tenantId: string,
): Promise<OnboardingStatus> {
  const headers: Record<string, string> = {};

  let res: Response;
  try {
    res = await fetch(
      `/api/tenants/${encodeURIComponent(tenantId)}/onboarding/status`,
      { headers },
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : "Network error";
    throw new OnboardingApiError(message, 0, undefined, true);
  }

  const parsed = await parseBody(res);

  if (res.status === 502) {
    throw new OnboardingApiError(
      "Backend Tevet-7 injoignable",
      502,
      parsed,
      true,
    );
  }

  if (!res.ok) {
    throw new OnboardingApiError(
      describeError(parsed, `Onboarding status ${res.status} ${res.statusText}`),
      res.status,
      parsed,
    );
  }

  const r =
    (typeof parsed === "object" && parsed !== null ? parsed : {}) as Record<
      string,
      unknown
    >;
  return {
    onboarded: Boolean(r.onboarded),
    connector_type:
      typeof r.connector_type === "string" ? r.connector_type : null,
    schema_tables_count:
      typeof r.schema_tables_count === "number" ? r.schema_tables_count : 0,
    roles_count: typeof r.roles_count === "number" ? r.roles_count : 0,
  };
}
