// ---------------------------------------------------------------------------
// Auth & tenant API client (Phase 6a)
// ---------------------------------------------------------------------------
//
// All requests go through the relative `/api/auth/*` and `/api/tenants/*`
// paths — Next.js route handlers proxy them server-side to
// `http://localhost:8001/api/auth/*` and `http://localhost:8001/api/tenants/*`
// (same pattern as the chat + documents proxies). The browser never talks to
// the FastAPI service directly, so the prototype works on any port the
// Preview Panel serves the app on.
//
// The store is responsible for persisting the JWT to localStorage and
// attaching it to every other API call (chat, documents, approvals). The
// functions in this file are pure I/O — they take an explicit `token`
// argument when auth is required and return typed payloads.

import type { AuthResult, MeResult, Tenant } from "./types";

const AUTH_TIMEOUT_MS = 12_000;

/** Error shape used by every auth-api function. */
export class AuthApiError extends Error {
  /** HTTP status returned by the backend (or 502 for proxy-level failures). */
  readonly status: number;
  /** Optional machine-readable code from the backend envelope. */
  readonly code: string | null;

  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = "AuthApiError";
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
): Promise<AuthApiError> {
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
  return new AuthApiError(detail, res.status, code);
}

/** Build the Authorization header for the given token, or return an empty object. */
export function authHeader(token: string | null): Record<string, string> {
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

/** Run a fetch with a timeout, aborting after `AUTH_TIMEOUT_MS`. */
async function fetchWithTimeout(
  url: string,
  init: RequestInit,
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    AUTH_TIMEOUT_MS,
  );
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    window.clearTimeout(timeoutId);
  }
}

// ---------------------------------------------------------------------------
// POST /api/auth/signup
// ---------------------------------------------------------------------------

interface BackendAuthResult {
  user: { id: number; email: string; name: string };
  token: string;
}

/**
 * Create a new account. The backend creates the user + (optionally) seeds a
 * demo tenant membership. The newly issued JWT is returned so the store can
 * persist it and immediately consider the user authenticated.
 *
 * NOTE: a freshly created user may have zero tenant memberships — the UI
 * surfaces a "Créez un tenant (Phase 6b)" prompt in that case.
 */
export async function signup(
  email: string,
  password: string,
  name: string,
): Promise<AuthResult> {
  const res = await fetchWithTimeout("/api/auth/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ email, password, name }),
  });
  if (!res.ok) {
    throw await parseBackendError(
      res,
      `signup → HTTP ${res.status} ${res.statusText}`,
    );
  }
  const json = (await res.json()) as BackendAuthResult;
  return { user: json.user, token: json.token };
}

// ---------------------------------------------------------------------------
// POST /api/auth/login
// ---------------------------------------------------------------------------

/**
 * Log a user in with email + password. Returns the JWT — the caller is
 * responsible for storing it (the store puts it in localStorage).
 */
export async function login(
  email: string,
  password: string,
): Promise<AuthResult> {
  const res = await fetchWithTimeout("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    throw await parseBackendError(
      res,
      `login → HTTP ${res.status} ${res.statusText}`,
    );
  }
  const json = (await res.json()) as BackendAuthResult;
  return { user: json.user, token: json.token };
}

// ---------------------------------------------------------------------------
// GET /api/auth/me
// ---------------------------------------------------------------------------

interface BackendMeResult {
  user: { id: number; email: string; name: string };
  memberships: Array<{
    tenant_id: string;
    name: string;
    slug: string;
    role: string;
    is_demo: boolean;
  }>;
}

/**
 * Validate the JWT and fetch the user's profile + tenant memberships.
 *
 * Used on app mount (`loadAuthFromStorage`) to recover an authenticated
 * session across reloads. Throws on a 401 (token expired / invalid) — the
 * caller should clear localStorage + revert to demo mode.
 */
export async function getMe(token: string): Promise<MeResult> {
  const res = await fetchWithTimeout("/api/auth/me", {
    method: "GET",
    headers: { Accept: "application/json", ...authHeader(token) },
  });
  if (!res.ok) {
    throw await parseBackendError(
      res,
      `getMe → HTTP ${res.status} ${res.statusText}`,
    );
  }
  const json = (await res.json()) as BackendMeResult;
  return {
    user: json.user,
    memberships: (json.memberships ?? []).map(mapTenant),
  };
}

function mapTenant(t: BackendMeResult["memberships"][number]): Tenant {
  return {
    tenant_id: t.tenant_id,
    name: t.name,
    slug: t.slug,
    role: t.role,
    is_demo: t.is_demo,
  };
}

// ---------------------------------------------------------------------------
// GET /api/tenants/mine
// ---------------------------------------------------------------------------

interface BackendTenantsResult {
  tenants: BackendMeResult["memberships"];
}

/** List the tenant memberships available to the authenticated user. */
export async function listMyTenants(token: string): Promise<Tenant[]> {
  const res = await fetchWithTimeout("/api/tenants/mine", {
    method: "GET",
    headers: { Accept: "application/json", ...authHeader(token) },
  });
  if (!res.ok) {
    throw await parseBackendError(
      res,
      `listMyTenants → HTTP ${res.status} ${res.statusText}`,
    );
  }
  const json = (await res.json()) as BackendTenantsResult;
  return (json.tenants ?? []).map(mapTenant);
}

// ---------------------------------------------------------------------------
// POST /api/tenants/{tenant_id}/activate
// ---------------------------------------------------------------------------

interface BackendActivateResult {
  token: string;
}

/**
 * Activate a different tenant context. The backend issues a new JWT with the
 * updated `tenant_id` / `role` / `producer_id` claims; the store replaces
 * the persisted token and re-derives the chat identity from the new claims.
 */
export async function activateTenant(
  tenantId: string,
  token: string,
): Promise<{ token: string }> {
  const res = await fetchWithTimeout(
    `/api/tenants/${encodeURIComponent(tenantId)}/activate`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...authHeader(token),
      },
      body: JSON.stringify({}),
    },
  );
  if (!res.ok) {
    throw await parseBackendError(
      res,
      `activateTenant → HTTP ${res.status} ${res.statusText}`,
    );
  }
  const json = (await res.json()) as BackendActivateResult;
  return { token: json.token };
}
