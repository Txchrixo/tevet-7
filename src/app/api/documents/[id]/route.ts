import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side proxy — DELETE a single document by id.
 *
 * The browser calls the relative `/api/documents/{id}` and Next.js forwards
 * the request server-side to `http://localhost:8001/api/documents/{id}`.
 */

const BACKEND_ORIGIN = "http://localhost:8001";
const BACKEND_TIMEOUT_MS = 30_000;

// `params` is a Promise in Next.js 15+/16 — we await it before reading `id`.
export async function DELETE(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  // Forward the Authorization header (Phase 6a dual mode — JWT context).
  const auth = req.headers.get("authorization");

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);

  try {
    const headers: Record<string, string> = {};
    if (auth) headers["Authorization"] = auth;

    const backendRes = await fetch(
      `${BACKEND_ORIGIN}/api/documents/${encodeURIComponent(id)}`,
      {
        method: "DELETE",
        headers,
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

    // Some backends return an empty body on DELETE — fall back to a small
    // JSON envelope so the client always gets parseable JSON.
    const body =
      text.trim().length === 0
        ? JSON.stringify({ deleted: true, id })
        : text;

    return new NextResponse(body, {
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
