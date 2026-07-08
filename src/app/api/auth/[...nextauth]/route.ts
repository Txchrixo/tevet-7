/**
 * NextAuth route handler - owns /api/auth/* (session, csrf, signin,
 * signout, callback). The one custom auth endpoint that is NOT NextAuth's
 * is /api/auth/signup (explicit route, takes precedence over this
 * catch-all).
 */

import NextAuth from "next-auth";

import { authOptions } from "@/lib/server/auth-options";

const handler = NextAuth(authOptions);

export { handler as GET, handler as POST };
