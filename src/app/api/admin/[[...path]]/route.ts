import { NextRequest, NextResponse } from "next/server";

import { getBackendAccessToken } from "@/lib/server/backend-auth";

/**
 * Tevet-7 admin proxy.
 *
 * Forwards every `/api/admin/*` request from the Next.js frontend to the
 * FastAPI admin service at `http://localhost:8001/api/admin/*`. The backend
 * handles authentication (JWT in Authorization header) + tenant scoping.
 *
 * We forward:
 *   - the HTTP method (GET / POST)
 *   - the trailing path segments (the catch-all `path` param)
 *   - the query string
 *   - the Authorization header (JWT)
 *   - the JSON body for POST requests
 *
 * The browser frontend always uses relative paths (`/api/admin/...`), and
 * this route handler performs the cross-origin hop to localhost:8001.
 */

const BACKEND_BASE = "http://localhost:8001";

function buildTargetUrl(req: NextRequest, segments: string[] | undefined): string {
  const path = segments && segments.length > 0 ? segments.join("/") : "";
  const qs = req.nextUrl.search ?? "";
  return `${BACKEND_BASE}/api/admin/${path}${qs}`;
}

async function forward(req: NextRequest, segments: string[] | undefined) {
  const target = buildTargetUrl(req, segments);

  // Forward only safe headers - Authorization carries the JWT.
  const headers = new Headers();
  // Session-derived token: the browser never holds the backend JWT, so
  // any client-sent Authorization header is ignored on purpose.
  const access = await getBackendAccessToken(req);
  if (access) headers.set("authorization", `Bearer ${access}`);
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);

  const init: RequestInit = {
    method: req.method,
    headers,
  };

  // Forward body for POST/PUT/PATCH.
  if (req.method !== "GET" && req.method !== "HEAD") {
    const body = await req.text();
    if (body.length > 0) init.body = body;
  }

  try {
    const upstream = await fetch(target, init);
    const text = await upstream.text();
    const respHeaders = new Headers();
    // Pass through content-type so JSON is parsed correctly by the client.
    const upCt = upstream.headers.get("content-type");
    if (upCt) respHeaders.set("content-type", upCt);
    return new NextResponse(text, {
      status: upstream.status,
      headers: respHeaders,
    });
  } catch (err) {
    // Backend not reachable - return a structured 502 so the admin UI can
    // surface a meaningful empty state instead of crashing.
    const message =
      err instanceof Error ? err.message : "Admin backend unreachable";
    return NextResponse.json(
      {
        error: "admin_backend_unreachable",
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

export async function PUT(
  req: NextRequest,
  ctx: { params: Promise<{ path?: string[] }> },
) {
  const { path } = await ctx.params;
  return forward(req, path);
}

export async function DELETE(
  req: NextRequest,
  ctx: { params: Promise<{ path?: string[] }> },
) {
  const { path } = await ctx.params;
  return forward(req, path);
}
