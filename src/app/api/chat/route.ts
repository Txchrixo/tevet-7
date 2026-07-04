import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side proxy to the Tevet-7 FastAPI backend.
 *
 * Why this exists
 * ----------------
 * The browser cannot reach the FastAPI service (port 8001) directly:
 *   - The Caddy gateway (port 81) only forwards requests carrying
 *     `?XTransformPort=8001`, but the Preview Panel serves the app on
 *     port 3000 (Next.js direct), so gateway rewrites never happen.
 *   - Next.js receives `/api/chat?XTransformPort=8001` and returns 404,
 *     which the frontend interprets as "backend offline" and falls back
 *     to the mock layer.
 *
 * This route handler fixes that by proxying server-side. The browser
 * calls the relative `/api/chat` (same origin, always reachable), and
 * Next.js forwards the request to `http://localhost:8001/api/chat` from
 * the server — no CORS, no gateway dependency, works on any port the
 * Preview Panel uses.
 */

const BACKEND_ORIGIN = "http://localhost:8001";
const BACKEND_TIMEOUT_MS = 12_000;

export async function POST(req: NextRequest) {
  const body = await req.text();

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);

  try {
    const backendRes = await fetch(`${BACKEND_ORIGIN}/api/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body,
      signal: controller.signal,
      // Server-side fetch: no CORS, credentials, or browser origin.
    });

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

export async function GET() {
  // Health probe — the frontend can use this to check if the backend is up
  // without sending a chat message.
  try {
    const backendRes = await fetch(`${BACKEND_ORIGIN}/health`, {
      signal: AbortSignal.timeout(3_000),
    });
    if (backendRes.ok) {
      return NextResponse.json({ status: "ok", backend: "connected" });
    }
    return NextResponse.json(
      { status: "error", backend: "unhealthy" },
      { status: 502 },
    );
  } catch {
    return NextResponse.json(
      { status: "error", backend: "unreachable" },
      { status: 502 },
    );
  }
}
