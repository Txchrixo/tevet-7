/**
 * NextAuth configuration - the session backbone of the Tevet-7 frontend.
 *
 * Security model
 * --------------
 * The FastAPI backend issues short-lived access JWTs (2h) and long-lived
 * refresh tokens (30d). Neither EVER reaches browser JavaScript:
 *
 * - Both are stored inside the NextAuth session token, a JWE (encrypted
 *   with NEXTAUTH_SECRET) held in an httpOnly, SameSite=Lax cookie
 *   (Secure in production). XSS cannot read it; CSRF is covered by
 *   NextAuth's built-in csrf token on every state-changing auth route.
 * - API proxies (route handlers under src/app/api/*) decrypt the cookie
 *   server-side with getToken() and attach `Authorization: Bearer` when
 *   forwarding to FastAPI. The browser only ever sends the cookie.
 * - The session callback exposes user identity + tenant context to the
 *   client, NEVER the backend tokens.
 *
 * Lifecycle
 * ---------
 * - signIn("credentials")  -> authorize() delegates to FastAPI /auth/login.
 * - token refresh          -> jwt() rotates the access token via
 *                             /auth/refresh when it is within 5 minutes of
 *                             expiry. A failed refresh marks the session
 *                             with error="RefreshFailed" so the UI can
 *                             force a re-login.
 * - tenant switch          -> update({activateTenantId}) triggers jwt()
 *                             to call /tenants/{id}/activate with the
 *                             CURRENT access token and swap in the newly
 *                             scoped backend JWT. The client never touches
 *                             either token.
 */

import type { NextAuthOptions } from "next-auth";
import type { JWT } from "next-auth/jwt";
import CredentialsProvider from "next-auth/providers/credentials";

import { backendJson } from "./backend";

// ── Backend JWT claims ───────────────────────────────────────────────────────

interface BackendClaims {
  sub?: string;
  email?: string;
  tenant_id?: string | null;
  role?: string | null;
  producer_id?: number | null;
  is_demo?: boolean;
  exp?: number;
}

/** Decode the backend JWT payload WITHOUT verifying the signature.
 *
 * Safe here: the token was received server-to-server from the backend we
 * are about to send it back to - FastAPI verifies the signature on every
 * request. We only read claims for display/session purposes. */
function decodeBackendJwt(token: string): BackendClaims {
  try {
    const payload = token.split(".")[1];
    return JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
  } catch {
    return {};
  }
}

interface BackendLoginResponse {
  user: {
    id: number;
    email: string;
    name: string;
    is_platform_owner?: boolean;
  };
  token: string;
  refresh_token?: string;
}

/** Copy backend token + claims into the NextAuth JWT. */
function applyBackendToken(token: JWT, backendToken: string): JWT {
  const claims = decodeBackendJwt(backendToken);
  token.backendAccessToken = backendToken;
  token.backendAccessExp = claims.exp ?? 0;
  token.tenant = {
    tenant_id: claims.tenant_id ?? null,
    role: claims.role ?? null,
    producer_id: claims.producer_id ?? null,
    is_demo: claims.is_demo ?? false,
  };
  return token;
}

// ── Token refresh ────────────────────────────────────────────────────────────

const REFRESH_MARGIN_S = 5 * 60;

async function refreshBackendToken(token: JWT): Promise<JWT> {
  if (!token.backendRefreshToken) {
    return { ...token, error: "RefreshFailed" as const };
  }
  const { status, body } = await backendJson<{ access_token?: string }>(
    "/api/auth/refresh",
    {
      method: "POST",
      body: JSON.stringify({ refresh_token: token.backendRefreshToken }),
    },
  );
  if (status !== 200 || !body?.access_token) {
    return { ...token, error: "RefreshFailed" as const };
  }
  const next = applyBackendToken({ ...token }, body.access_token);
  delete next.error;
  return next;
}

// ── Tenant activation (update() trigger) ────────────────────────────────────

async function activateTenantInToken(token: JWT, tenantId: string): Promise<JWT> {
  const { status, body } = await backendJson<{ token?: string }>(
    `/api/tenants/${encodeURIComponent(tenantId)}/activate`,
    {
      method: "POST",
      headers: { authorization: `Bearer ${token.backendAccessToken}` },
    },
  );
  if (status !== 200 || !body?.token) {
    // Keep the previous (still valid) token - the UI surfaces the failure
    // through the proxy call it makes right after.
    return token;
  }
  return applyBackendToken({ ...token }, body.token);
}

// ── Options ──────────────────────────────────────────────────────────────────

export const authOptions: NextAuthOptions = {
  session: {
    strategy: "jwt",
    // Matches the backend refresh token lifetime: after 30 days without
    // a valid refresh, the user re-authenticates.
    maxAge: 30 * 24 * 60 * 60,
  },
  pages: {
    // The app renders its own auth screen at the root route.
    signIn: "/",
    error: "/",
  },
  providers: [
    CredentialsProvider({
      id: "credentials",
      name: "Email et mot de passe",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Mot de passe", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials.password) return null;
        const { status, body } = await backendJson<BackendLoginResponse>(
          "/api/auth/login",
          {
            method: "POST",
            body: JSON.stringify({
              email: credentials.email,
              password: credentials.password,
            }),
          },
        );
        if (status !== 200 || !body?.token) return null;
        return {
          id: String(body.user.id),
          email: body.user.email,
          name: body.user.name,
          isPlatformOwner: body.user.is_platform_owner ?? false,
          backendAccessToken: body.token,
          backendRefreshToken: body.refresh_token ?? null,
        };
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user, trigger, session }) {
      // Initial sign-in: copy the backend tokens + user into the JWT.
      if (user) {
        const u = user as typeof user & {
          backendAccessToken: string;
          backendRefreshToken: string | null;
          isPlatformOwner: boolean;
        };
        token.user = {
          id: Number(u.id),
          email: u.email ?? "",
          name: u.name ?? "",
          is_platform_owner: u.isPlatformOwner,
        };
        token.backendRefreshToken = u.backendRefreshToken;
        return applyBackendToken(token, u.backendAccessToken);
      }

      // Tenant switch requested via update({activateTenantId}).
      if (trigger === "update" && session && typeof session === "object") {
        const tenantId = (session as { activateTenantId?: string }).activateTenantId;
        if (tenantId) {
          return activateTenantInToken(token, tenantId);
        }
      }

      // Proactive access-token rotation.
      const exp = (token.backendAccessExp as number | undefined) ?? 0;
      const now = Math.floor(Date.now() / 1000);
      if (exp > 0 && now >= exp - REFRESH_MARGIN_S) {
        return refreshBackendToken(token);
      }
      return token;
    },
    async session({ session, token }) {
      session.user = token.user as typeof session.user;
      session.tenant = token.tenant as typeof session.tenant;
      if (token.error) session.error = token.error as "RefreshFailed";
      return session;
    },
  },
};
