import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side proxy — GET detail for a single approval (approval row + full
 * onboarding dossier + parsed agent_analysis).
 *
 * The browser calls the relative `/api/approvals/{id}` and Next.js forwards
 * the request server-side to `http://localhost:8001/api/approvals/{id}`.
 */

const BACKEND_ORIGIN = "http://localhost:8001";
const BACKEND_TIMEOUT_MS = 15_000;

// `params` is a Promise in Next.js 15+/16 — we await it before reading `id`.
export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  // Forward the query string (e.g. ?admin=true) — the backend requires admin=true
  // on all approval endpoints. The browser-side store always sends it.
  const search = req.nextUrl.search;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);

  try {
    const backendRes = await fetch(
      `${BACKEND_ORIGIN}/api/approvals/${encodeURIComponent(id)}${search}`,
      {
        method: "GET",
        headers: { Accept: "application/json" },
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
