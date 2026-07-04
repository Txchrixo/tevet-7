/**
 * Tevet-7 auth + tenant API client.
 *
 * All endpoints are proxied through Next.js:
 *   - `/api/auth/*`     → see `src/app/api/auth/[[...path]]/route.ts`
 *   - `/api/tenants/*`  → see `src/app/api/tenants/[[...path]]/route.ts`
 *
 * The browser frontend never talks to localhost:8001 directly — only relative
 * paths so the request goes through Next.js (and Caddy in production).
 *
 * JWT persistence lives in `localStorage` under `tevet7.jwt` (shared with the
 * admin API client — `src/lib/admin-api.ts` reads the same key).
 */

import type { AuthUser, TenantMembership } from "./types";

/** localStorage key shared with `admin-api.ts`. */
const TOKEN_STORAGE_KEY = "tevet7.jwt";

/** localStorage key for the cached active tenant id (so reloads remember it). */
const ACTIVE_TENANT_KEY = "tevet7.activeTenantId";

/** Email + password of the demo producer, used by the "Essayer la démo" button. */
export const DEMO_EMAIL = "marie@tevet7.dev";
export const DEMO_PASSWORD = "tevet7demo";

/** Reads the JWT from localStorage. Returns null on the server or when unset. */
export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setAuthToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
    else window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

export function getActiveTenantId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(ACTIVE_TENANT_KEY);
  } catch {
    return null;
  }
}

export function setActiveTenantId(tenantId: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (tenantId) window.localStorage.setItem(ACTIVE_TENANT_KEY, tenantId);
    else window.localStorage.removeItem(ACTIVE_TENANT_KEY);
  } catch {
    /* ignore */
  }
}

/**
 * Thrown by the auth client for any non-2xx response OR when the backend is
 * unreachable (502 from the Next.js proxy). Callers can use `instanceof` to
 * distinguish auth errors from generic JS errors.
 */
export class AuthApiError extends Error {
  status: number;
  detail: unknown;
  /** True when the underlying failure was the backend being unreachable. */
  unreachable: boolean;
  constructor(
    message: string,
    status: number,
    detail?: unknown,
    unreachable = false,
  ) {
    super(message);
    this.name = "AuthApiError";
    this.status = status;
    this.detail = detail;
    this.unreachable = unreachable;
  }
}

interface AuthFetchOptions {
  method?: "GET" | "POST";
  body?: unknown;
  /** When true, send the stored JWT (default true). */
  withToken?: boolean;
}

/**
 * Low-level auth/tenant fetch helper. Uses relative paths only.
 *
 * `pathPrefix` is `"auth"` or `"tenants"` — selects which Next.js proxy to hit.
 */
async function apiFetch<T>(
  pathPrefix: "auth" | "tenants",
  path: string,
  opts: AuthFetchOptions = {},
): Promise<T> {
  const withToken = opts.withToken ?? true;
  const token = withToken ? getAuthToken() : null;
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };
  if (token) headers["authorization"] = `Bearer ${token}`;

  const init: RequestInit = {
    method: opts.method ?? "GET",
    headers,
  };
  if (opts.body !== undefined) init.body = JSON.stringify(opts.body);

  const url = path.startsWith("/")
    ? `/api/${pathPrefix}${path}`
    : `/api/${pathPrefix}/${path}`;

  let res: Response;
  try {
    // 3-second timeout — prevents the loading screen from hanging when the
    // backend is slow or unreachable.
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    res = await fetch(url, { ...init, signal: controller.signal });
    clearTimeout(timeout);
  } catch (err) {
    // Network-level failure (backend offline, DNS error, CORS, timeout, …).
    // Treat as unreachable so the caller can fall back to demo mode.
    const message = err instanceof Error ? err.message : "Network error";
    throw new AuthApiError(message, 0, undefined, true);
  }

  // 502 is what the Next.js proxy returns when the backend is unreachable.
  if (res.status === 502) {
    const text = await res.text().catch(() => "");
    let detail: unknown = text;
    try {
      detail = text.length > 0 ? JSON.parse(text) : null;
    } catch {
      /* keep raw text */
    }
    throw new AuthApiError(
      "Backend Tevet-7 injoignable",
      502,
      detail,
      true,
    );
  }

  const text = await res.text();
  let parsed: unknown = null;
  if (text.length > 0) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }

  if (!res.ok) {
    const message =
      typeof parsed === "object" && parsed && "detail" in parsed
        ? String((parsed as { detail: unknown }).detail)
        : typeof parsed === "object" && parsed && "message" in parsed
          ? String((parsed as { message: unknown }).message)
          : `Auth API ${res.status} ${res.statusText}`;
    throw new AuthApiError(message, res.status, parsed);
  }

  return parsed as T;
}

// ---------------------------------------------------------------------------
// Auth endpoints
// ---------------------------------------------------------------------------

export interface LoginResponse {
  user: AuthUser;
  token: string;
}

/** `POST /api/auth/login` with `{email, password}`. Throws 401 on bad creds. */
export async function login(
  email: string,
  password: string,
): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("auth", "login", {
    method: "POST",
    body: { email, password },
    withToken: false,
  });
}

export async function signup(
  email: string,
  password: string,
  name: string,
): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("auth", "signup", {
    method: "POST",
    body: { email, password, name },
    withToken: false,
  });
}

export interface MeResponse {
  user: AuthUser;
  memberships: TenantMembership[];
}

/** `GET /api/auth/me` — validates the stored JWT and returns the user + memberships. */
export async function getMe(): Promise<MeResponse> {
  return apiFetch<MeResponse>("auth", "me");
}

// ---------------------------------------------------------------------------
// Tenant endpoints
// ---------------------------------------------------------------------------

export interface ListTenantsResponse {
  count: number;
  tenants: TenantMembership[];
}

/** `GET /api/tenants/mine` — list the user's memberships. */
export async function listMyTenants(): Promise<ListTenantsResponse> {
  return apiFetch<ListTenantsResponse>("tenants", "mine");
}

export interface ActivateTenantResponse {
  membership: TenantMembership;
  token: string;
}

/** `POST /api/tenants/{tenantId}/activate` — switch active tenant, get a fresh JWT. */
export async function activateTenant(
  tenantId: string,
): Promise<ActivateTenantResponse> {
  return apiFetch<ActivateTenantResponse>(
    "tenants",
    `${encodeURIComponent(tenantId)}/activate`,
    { method: "POST" },
  );
}

export interface CreateTenantResponse {
  tenant: TenantMembership;
  token: string;
}

/** `POST /api/tenants` — create a new tenant (the caller becomes admin). */
export async function createTenant(
  name: string,
  slug: string,
): Promise<CreateTenantResponse> {
  return apiFetch<CreateTenantResponse>("tenants", "", {
    method: "POST",
    body: { name, slug },
  });
}
