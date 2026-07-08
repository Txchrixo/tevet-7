/**
 * Tevet-7 generic API helpers.
 *
 * Frontend client functions that don't fit neatly into the auth-api or
 * admin-api buckets live here. Currently hosts the example-questions
 * fetcher used by the Producer Copilot sidebar (Phase 6d - dynamic
 * example questions).
 *
 * All requests go through the Next.js proxies (relative paths only) so
 * the browser never talks to localhost:8001 directly - same convention
 * as `src/lib/auth-api.ts` and `src/lib/admin-api.ts`.
 */

import type { ExampleQuestion } from "./types";

/**
 * Auth headers are no longer built client-side: the NextAuth session
 * cookie flows automatically with same-origin fetches, and the Next.js
 * proxy routes attach the backend Bearer token server-side
 * (src/lib/server/backend-auth.ts). Kept for call-site compatibility.
 */
export function authHeaders(): Record<string, string> {
  return {};
}

/**
 * `GET /api/tenants/{tenantId}/example-questions` - returns up to 5
 * schema-driven example questions for the active tenant. Returns an
 * empty list on any error so the caller can fall back to the hardcoded
 * Drive Producteur questions (`FALLBACK_QUESTIONS` in `mock-data.ts`).
 *
 * The empty-list-on-error contract is intentional: the sidebar shows
 * dynamic questions when available, and falls back to the hardcoded
 * ones silently when the backend is unreachable or returns an error.
 */
export async function fetchExampleQuestions(
  tenantId: string,
): Promise<ExampleQuestion[]> {
  try {
    const res = await fetch(
      `/api/tenants/${encodeURIComponent(tenantId)}/example-questions`,
      {
        headers: authHeaders(),
      },
    );
    if (!res.ok) return [];
    const data = await res.json();
    const questions = (data?.questions ?? []) as ExampleQuestion[];
    return Array.isArray(questions) ? questions : [];
  } catch {
    return [];
  }
}
