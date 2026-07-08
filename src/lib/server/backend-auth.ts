/**
 * Server-side extraction of the backend access token from the NextAuth
 * session cookie.
 *
 * Every API proxy calls this instead of trusting an Authorization header
 * from the browser: the browser never holds the backend JWT, so a
 * client-sent header is either absent or an attack - both are ignored.
 */

import type { NextRequest } from "next/server";
import { getToken } from "next-auth/jwt";

/** Returns the backend access token for the request's session, or null. */
export async function getBackendAccessToken(
  req: NextRequest,
): Promise<string | null> {
  const token = await getToken({ req, secret: process.env.NEXTAUTH_SECRET });
  const access = token?.backendAccessToken;
  return typeof access === "string" && access.length > 0 ? access : null;
}

/** Builds the forward headers for a proxy hop: content-type + session token. */
export async function buildProxyHeaders(
  req: NextRequest,
  extra: Record<string, string> = {},
): Promise<Headers> {
  const headers = new Headers(extra);
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const access = await getBackendAccessToken(req);
  if (access) headers.set("authorization", `Bearer ${access}`);
  return headers;
}
