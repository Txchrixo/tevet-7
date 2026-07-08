/**
 * NextAuth module augmentation - the Tevet-7 session/JWT shape.
 *
 * The backend tokens live ONLY in the JWT (server-side, encrypted cookie).
 * The Session (what the client sees) carries user identity + tenant
 * context, never a token.
 */

import type { DefaultSession } from "next-auth";

export interface SessionTenant {
  tenant_id: string | null;
  role: string | null;
  producer_id: number | null;
  is_demo: boolean;
}

export interface SessionUser {
  id: number;
  email: string;
  name: string;
  is_platform_owner: boolean;
}

declare module "next-auth" {
  interface Session extends DefaultSession {
    user: SessionUser;
    tenant: SessionTenant;
    error?: "RefreshFailed";
  }

  interface User {
    isPlatformOwner?: boolean;
    backendAccessToken?: string;
    backendRefreshToken?: string | null;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    user?: SessionUser;
    tenant?: SessionTenant;
    backendAccessToken?: string;
    backendAccessExp?: number;
    backendRefreshToken?: string | null;
    error?: "RefreshFailed";
  }
}
