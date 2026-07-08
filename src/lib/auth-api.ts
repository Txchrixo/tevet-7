/**
 * Tevet-7 auth + tenant API client (NextAuth edition).
 *
 * Security model
 * --------------
 * The browser NEVER holds a backend JWT. Authentication lives in a
 * NextAuth session: an encrypted (JWE), httpOnly, SameSite=Lax cookie.
 * Login goes through `signIn("credentials")`; every subsequent API call
 * is a plain fetch to a Next.js proxy route, which decrypts the cookie
 * server-side and attaches the backend token itself
 * (see `src/lib/server/backend-auth.ts`).
 *
 * There is therefore NO token storage in this module - no localStorage,
 * no Authorization headers. XSS cannot exfiltrate what the JS runtime
 * never sees.
 *
 * Tenant switching rotates the backend JWT inside the session cookie via
 * `updateSession({activateTenantId})` (see `src/lib/session-bridge.ts`
 * and the `jwt` callback in `src/lib/server/auth-options.ts`).
 */

import { getSession, signIn, signOut } from "next-auth/react";
import type { Session } from "next-auth";

import { updateSession } from "./session-bridge";
import type { AuthUser, TenantMembership } from "./types";

/** Email + password of the demo producer, used by the "Essayer la démo"
 * button on the public landing page. These accounts only exist when the
 * backend runs with ENABLE_DEMO_SEED=true (never in production). */
export const DEMO_EMAIL = "marie@tevet7.dev";
export const DEMO_PASSWORD = "tevet7demo";

/**
 * Thrown for any non-2xx response OR when the backend is unreachable
 * (502 from the Next.js proxy). Callers use `instanceof` to distinguish
 * auth errors from generic JS errors.
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

// ---------------------------------------------------------------------------
// Low-level fetch helper (proxy routes; session cookie flows automatically)
// ---------------------------------------------------------------------------

interface ApiFetchOptions {
  method?: "GET" | "POST";
  body?: unknown;
}

async function apiFetch<T>(
  pathPrefix: "auth" | "tenants",
  path: string,
  opts: ApiFetchOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };
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
    // 10-second timeout - the backend can take 1-2s per request (DB + LLM).
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    res = await fetch(url, { ...init, signal: controller.signal });
    clearTimeout(timeout);
  } catch (err) {
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
    throw new AuthApiError("Backend Tevet-7 injoignable", 502, detail, true);
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
    let message = `Auth API ${res.status} ${res.statusText}`;
    if (typeof parsed === "object" && parsed && "detail" in parsed) {
      const detail = (parsed as { detail: unknown }).detail;
      if (Array.isArray(detail)) {
        message = detail.map((e: { msg?: string }) => e.msg || String(e)).join("; ");
      } else {
        message = String(detail);
      }
    } else if (typeof parsed === "object" && parsed && "message" in parsed) {
      message = String((parsed as { message: unknown }).message);
    }
    throw new AuthApiError(message, res.status, parsed);
  }

  return parsed as T;
}

// ---------------------------------------------------------------------------
// Session lifecycle (NextAuth)
// ---------------------------------------------------------------------------

/** Maps a NextAuth session to the app's AuthUser shape. */
function userFromSession(session: Session): AuthUser {
  return {
    id: session.user.id,
    email: session.user.email,
    name: session.user.name,
    is_platform_owner: session.user.is_platform_owner,
  } as AuthUser;
}

export interface LoginResult {
  user: AuthUser;
  session: Session;
}

/**
 * Authenticates through NextAuth (credentials provider -> FastAPI login).
 * On success the session cookie is set; no token is returned to JS.
 * Throws AuthApiError(401) on bad credentials.
 */
export async function login(email: string, password: string): Promise<LoginResult> {
  const result = await signIn("credentials", {
    redirect: false,
    email,
    password,
  });
  if (!result || result.error) {
    // NextAuth surfaces every authorize() failure as "CredentialsSignin";
    // network-level failures inside authorize() also land here.
    throw new AuthApiError(
      "Email ou mot de passe invalide.",
      401,
      result?.error ?? null,
    );
  }
  const session = await getSession();
  if (!session) {
    throw new AuthApiError("Session introuvable après connexion.", 500);
  }
  return { user: userFromSession(session), session };
}

/**
 * Creates the account on the backend (via the signup proxy - the backend
 * JWT never reaches the browser), then signs in through NextAuth.
 */
export async function signup(
  email: string,
  password: string,
  name: string,
): Promise<LoginResult> {
  await apiFetch<{ user: AuthUser }>("auth", "signup", {
    method: "POST",
    body: { email, password, name },
  });
  return login(email, password);
}

/** Ends the NextAuth session (clears the httpOnly cookie). */
export async function logoutSession(): Promise<void> {
  await signOut({ redirect: false });
}

/** Returns the current session, or null when unauthenticated. */
export async function getCurrentSession(): Promise<Session | null> {
  return getSession();
}

// ---------------------------------------------------------------------------
// Tenant endpoints (proxied; token attached server-side)
// ---------------------------------------------------------------------------

export interface ListTenantsResponse {
  count: number;
  tenants: TenantMembership[];
}

/** `GET /api/tenants/mine` - list the user's memberships. */
export async function listMyTenants(): Promise<ListTenantsResponse> {
  return apiFetch<ListTenantsResponse>("tenants", "mine");
}

/**
 * Switches the active tenant. The backend activation happens INSIDE the
 * NextAuth `jwt` callback (server-side) so the newly scoped backend JWT
 * lands directly in the session cookie. Returns the refreshed session
 * (whose `tenant` reflects the new scope) or throws on failure.
 */
export async function activateTenant(tenantId: string): Promise<Session> {
  const session = await updateSession({ activateTenantId: tenantId });
  if (!session || session.tenant?.tenant_id !== tenantId) {
    throw new AuthApiError(
      `Impossible d'activer le tenant ${tenantId}.`,
      409,
      session?.tenant ?? null,
    );
  }
  return session;
}

export interface CreateTenantResponse {
  tenant: TenantMembership;
}

/**
 * `POST /api/tenants` - create a new tenant (the caller becomes admin),
 * then rotate the session onto it. The token returned by the backend is
 * discarded by the proxy path - the session rotation goes through
 * `activateTenant` so the cookie stays the single source of truth.
 */
export async function createTenant(
  name: string,
  slug: string,
): Promise<{ tenant: TenantMembership; session: Session }> {
  const resp = await apiFetch<{ tenant: TenantMembership }>("tenants", "", {
    method: "POST",
    body: { name, slug },
  });
  const tenantId =
    (resp.tenant as unknown as { id?: string }).id ??
    (resp.tenant as unknown as { tenant_id?: string }).tenant_id ??
    slug;
  const session = await activateTenant(tenantId);
  return { tenant: resp.tenant, session };
}
