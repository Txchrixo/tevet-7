import { NextRequest, NextResponse } from "next/server";

/**
 * Tevet-7 auth proxy.
 *
 * Forwards every `/api/auth/*` request from the Next.js frontend to the
 * FastAPI auth service at `http://localhost:8001/api/auth/*`. The backend
 * owns the user table, password hashing, and JWT issuance.
 *
 * We forward:
 *   - the HTTP method (GET / POST)
 *   - the trailing path segments (the catch-all `path` param)
 *   - the query string
 *   - the Authorization header (JWT) when present
 *   - the JSON body for POST requests
 *
 * The browser frontend always uses relative paths (`/api/auth/...`); this
 * route handler performs the cross-origin hop to localhost:8001 so the
 * browser never talks to the FastAPI service directly.
 */

const BACKEND_BASE = "http://localhost:8001";

function buildTargetUrl(req: NextRequest, segments: string[] | undefined): string {
  const path = segments && segments.length > 0 ? segments.join("/") : "";
  const qs = req.nextUrl.search ?? "";
  return `${BACKEND_BASE}/api/auth/${path}${qs}`;
}

async function forward(req: NextRequest, segments: string[] | undefined) {
  const target = buildTargetUrl(req, segments);

  const headers = new Headers();
  const auth = req.headers.get("authorization");
  if (auth) headers.set("authorization", auth);
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);

  const init: RequestInit = {
    method: req.method,
    headers,
  };

  if (req.method !== "GET" && req.method !== "HEAD") {
    const body = await req.text();
    if (body.length > 0) init.body = body;
  }

  try {
    const upstream = await fetch(target, init);
    const text = await upstream.text();
    const respHeaders = new Headers();
    const upCt = upstream.headers.get("content-type");
    if (upCt) respHeaders.set("content-type", upCt);
    return new NextResponse(text, {
      status: upstream.status,
      headers: respHeaders,
    });
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "Auth backend unreachable";
    return NextResponse.json(
      {
        error: "auth_backend_unreachable",
        message,
        backend: target,
      },
      { status: 502 },
    );
  }
}

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ path?: string[] }> },
) {
  const { path } = await ctx.params;
  return forward(req, path);
}

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ path?: string[] }> },
) {
  const { path } = await ctx.params;
  return forward(req, path);
}
