import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side proxy to the Tevet-7 FastAPI backend's auth API.
 *
 * Mirrors the pattern of `src/app/api/chat/route.ts`: the browser calls the
 * relative `/api/auth/me` (same origin, always reachable), and Next.js
 * forwards the request server-side to
 * `http://localhost:8001/api/auth/me`. Works on any port the Preview Panel
 * uses — no Caddy gateway or `XTransformPort` query needed.
 *
 * The Authorization header is ALWAYS forwarded — `getMe` is authed.
 */

const BACKEND_ORIGIN = "http://localhost:8001";
const BACKEND_TIMEOUT_MS = 12_000;

export async function GET(req: NextRequest) {
  const auth = req.headers.get("authorization");

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);

  try {
    const headers: Record<string, string> = {
      Accept: "application/json",
    };
    if (auth) headers["Authorization"] = auth;

    const backendRes = await fetch(`${BACKEND_ORIGIN}/api/auth/me`, {
      method: "GET",
      headers,
      signal: controller.signal,
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
