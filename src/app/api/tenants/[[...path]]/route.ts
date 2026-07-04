import { NextRequest, NextResponse } from "next/server";

/**
 * Tevet-7 tenants proxy.
 *
 * Forwards every `/api/tenants/*` request from the Next.js frontend to the
 * FastAPI tenants service at `http://localhost:8001/api/tenants/*`. Used by
 * the frontend to list the user's tenants (`GET /api/tenants/mine`) and to
 * switch the active tenant (`POST /api/tenants/{id}/activate`).
 *
 * The browser frontend always uses relative paths (`/api/tenants/...`); this
 * route handler performs the cross-origin hop to localhost:8001.
 */

const BACKEND_BASE = "http://localhost:8001";

function buildTargetUrl(req: NextRequest, segments: string[] | undefined): string {
  const path = segments && segments.length > 0 ? segments.join("/") : "";
  const qs = req.nextUrl.search ?? "";
  return `${BACKEND_BASE}/api/tenants/${path}${qs}`;
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
      err instanceof Error ? err.message : "Tenants backend unreachable";
    return NextResponse.json(
      {
        error: "tenants_backend_unreachable",
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
