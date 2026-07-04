import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side proxy to the Tevet-7 FastAPI backend's document corpus API.
 *
 * Mirrors the pattern of `src/app/api/chat/route.ts`: the browser calls the
 * relative `/api/documents` (same origin, always reachable), and Next.js
 * forwards the request server-side to `http://localhost:8001/api/documents`.
 * Works on any port the Preview Panel uses — no Caddy gateway or
 * `XTransformPort` query needed.
 *
 *   - GET  → list documents (query string forwarded as-is)
 *   - POST → upload a document (multipart/form-data forwarded verbatim)
 *
 * DELETE lives in `src/app/api/documents/[id]/route.ts`.
 */

const BACKEND_ORIGIN = "http://localhost:8001";
const BACKEND_TIMEOUT_MS = 30_000;

export async function GET(req: NextRequest) {
  const search = req.nextUrl.search; // includes the leading "?"
  // Forward the Authorization header (Phase 6a dual mode — JWT context).
  const auth = req.headers.get("authorization");

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);

  try {
    const headers: Record<string, string> = {
      Accept: "application/json",
    };
    if (auth) headers["Authorization"] = auth;

    const backendRes = await fetch(
      `${BACKEND_ORIGIN}/api/documents${search}`,
      {
        method: "GET",
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

export async function POST(req: NextRequest) {
  // Forward the multipart/form-data body verbatim — fetch reconstructs the
  // Content-Type header (with the boundary) when the body is a FormData.
  // Forward the Authorization header (Phase 6a dual mode — JWT context).
  const auth = req.headers.get("authorization");
  let form: FormData;
  try {
    form = await req.formData();
  } catch (err) {
    return NextResponse.json(
      {
        error: "invalid_form",
        detail: err instanceof Error ? err.message : "formData parse failed",
      },
      { status: 400 },
    );
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);

  try {
    const headers: Record<string, string> = {};
    if (auth) headers["Authorization"] = auth;

    const backendRes = await fetch(`${BACKEND_ORIGIN}/api/documents`, {
      method: "POST",
      headers,
      body: form,
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
