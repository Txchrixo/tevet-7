import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side proxy to the Tevet-7 FastAPI backend's tenants API.
 *
 * POST /api/tenants/{tenant_id}/activate → swap the active tenant context.
 * The backend issues a new JWT with the updated `tenant_id` / `role` /
 * `producer_id` claims; the store replaces the persisted token + re-derives
 * the chat identity from the new claims.
 *
 * The Authorization header is ALWAYS forwarded — the call is authed.
 *
 * Mirrors the pattern of `src/app/api/approvals/[id]/decide/route.ts`.
 */

const BACKEND_ORIGIN = "http://localhost:8001";
const BACKEND_TIMEOUT_MS = 12_000;

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const body = await req.text();
  const auth = req.headers.get("authorization");

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);

  try {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json",
    };
    if (auth) headers["Authorization"] = auth;

    const backendRes = await fetch(
      `${BACKEND_ORIGIN}/api/tenants/${encodeURIComponent(id)}/activate`,
      {
        method: "POST",
        headers,
        body,
        signal: controller.signal,
      },
    );

    const text = await backendRes.text();

    if (!backendRes.ok) {
      return new NextResponse(text, {
        status: backendRes.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    return new NextResponse(text, {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch (err) {
    const message =
      err instanceof DOMException && err.name === "AbortError"
        ? `Backend timed out after ${BACKEND_TIMEOUT_MS} ms`
        : err instanceof Error
          ? err.message
          : "Unknown proxy error";

    return NextResponse.json(
      { error: "backend_unreachable", detail: message },
      { status: 502 },
    );
  } finally {
    clearTimeout(timeout);
  }
}
