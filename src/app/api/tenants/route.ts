import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side proxy to the Tevet-7 FastAPI backend's tenants API.
 *
 * POST /api/tenants → create a new tenant (Phase 6b will wire the form).
 * Forwards the Authorization header (creating a tenant requires an
 * authenticated user — the new tenant's first membership goes to them).
 *
 * Mirrors the pattern of `src/app/api/auth/signup/route.ts`.
 */

const BACKEND_ORIGIN = "http://localhost:8001";
const BACKEND_TIMEOUT_MS = 12_000;

export async function POST(req: NextRequest) {
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

    const backendRes = await fetch(`${BACKEND_ORIGIN}/api/tenants`, {
      method: "POST",
      headers,
      body,
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
