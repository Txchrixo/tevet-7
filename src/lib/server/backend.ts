/**
 * Server-side backend access (Node runtime only - never ship to the client).
 *
 * Single source of truth for the FastAPI base URL. Every Next.js route
 * handler (proxy) and the NextAuth callbacks go through here so the
 * backend origin is configured in exactly one place (`BACKEND_URL`).
 */

export const BACKEND_BASE =
  process.env.BACKEND_URL?.replace(/\/$/, "") ?? "http://localhost:8001";

/** POST JSON to the backend. Returns the parsed body + status. */
export async function backendJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<{ status: number; body: T | null }> {
  const res = await fetch(`${BACKEND_BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init.headers ?? {}),
    },
    // The backend is a sibling service - never cache auth exchanges.
    cache: "no-store",
  });
  const text = await res.text();
  let body: T | null = null;
  if (text.length > 0) {
    try {
      body = JSON.parse(text) as T;
    } catch {
      body = null;
    }
  }
  return { status: res.status, body };
}
