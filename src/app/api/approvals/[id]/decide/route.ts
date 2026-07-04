import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side proxy — POST the admin's human-in-the-loop decision.
 *
 * Body shape: `{ decision: "approve"|"reject"|"override", reason: string,
 * decided_by: string }`. The browser calls the relative
 * `/api/approvals/{id}/decide` and Next.js forwards the request server-side
 * to `http://localhost:8001/api/approvals/{id}/decide`.
 *
 * The backend persists the decision, the reason, the actor id and the
 * timestamp, then returns the updated approval + onboarding row.
 */

const BACKEND_ORIGIN = "http://localhost:8001";
const BACKEND_TIMEOUT_MS = 15_000;

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const body = await req.text();
  // Forward the query string (e.g. ?admin=true) — the backend requires admin=true.
  const search = req.nextUrl.search;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);

  try {
    const backendRes = await fetch(
      `${BACKEND_ORIGIN}/api/approvals/${encodeURIComponent(id)}/decide${search}`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
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
