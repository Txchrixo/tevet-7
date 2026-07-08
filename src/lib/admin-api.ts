/**
 * Tevet-7 admin API client.
 *
 * All admin endpoints are proxied through the Next.js catch-all route at
 * `/api/admin/*` (see `src/app/api/admin/[[...path]]/route.ts`). The proxy
 * forwards the Authorization header (JWT) to the FastAPI admin service at
 * `http://localhost:8001/api/admin/*`.
 *
 * The frontend never talks to localhost:8001 directly - only relative paths
 * so the request goes through Next.js (and Caddy in production).
 */

import type {
  Conversation,
  PlatformStats,
  PlatformTenant,
  ResetResult,
  TenantConfig,
  TenantStats,
  TenantUser,
} from "./types";

/** Where the JWT is persisted client-side (set by the login flow). */

/** The default tenant slug - Drive Producteur. */
export const DEFAULT_TENANT_ID = "dp";


interface FetchOptions {
  method?: "GET" | "POST";
  body?: unknown;
}

/**
 * Low-level admin fetch helper. Throws an `AdminApiError` for non-2xx
 * responses so the caller can render a meaningful toast.
 */
export class AdminApiError extends Error {
  status: number;
  detail: unknown;
  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = "AdminApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function adminFetch<T>(path: string, opts: FetchOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };

  const init: RequestInit = {
    method: opts.method ?? "GET",
    headers,
  };
  if (opts.body !== undefined) init.body = JSON.stringify(opts.body);

  const res = await fetch(`/api/admin/${path}`, init);
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
      typeof parsed === "object" && parsed && "message" in parsed
        ? String((parsed as { message: unknown }).message)
        : `Admin API ${res.status} ${res.statusText}`;
    throw new AdminApiError(message, res.status, parsed);
  }

  return parsed as T;
}

// ---------------------------------------------------------------------------
// Tenant admin endpoints
// ---------------------------------------------------------------------------

export async function getTenantUsers(
  tenantId: string,
): Promise<TenantUser[]> {
  const r = await adminFetch<{ users: TenantUser[] }>(
    `tenants/${encodeURIComponent(tenantId)}/users`,
  );
  return Array.isArray(r) ? r : (r.users ?? []);
}

export async function getTenantConfig(
  tenantId: string,
): Promise<TenantConfig> {
  const r = await adminFetch<{ config: TenantConfig }>(
    `tenants/${encodeURIComponent(tenantId)}/config`,
  );
  return r.config ?? r;
}

export async function getTenantConversations(
  tenantId: string,
  limit = 50,
): Promise<Conversation[]> {
  const r = await adminFetch<{ conversations: Conversation[] }>(
    `tenants/${encodeURIComponent(tenantId)}/conversations?limit=${limit}`,
  );
  return Array.isArray(r) ? r : (r.conversations ?? []);
}

export async function getTenantStats(
  tenantId: string,
): Promise<TenantStats> {
  const r = await adminFetch<{ stats: TenantStats }>(
    `tenants/${encodeURIComponent(tenantId)}/stats`,
  );
  return r.stats ?? r;
}

// ---------------------------------------------------------------------------
// Platform owner endpoints
// ---------------------------------------------------------------------------

export async function listAllTenants(): Promise<PlatformTenant[]> {
  const r = await adminFetch<{ tenants: PlatformTenant[] }>(`platform/tenants`);
  return Array.isArray(r) ? r : (r.tenants ?? []);
}

export async function getPlatformStats(): Promise<PlatformStats> {
  const r = await adminFetch<{ stats: PlatformStats }>(`platform/stats`);
  return r.stats ?? r;
}

export async function resetDemoTenant(): Promise<ResetResult> {
  return adminFetch<ResetResult>(`platform/reset-demo`, { method: "POST" });
}
