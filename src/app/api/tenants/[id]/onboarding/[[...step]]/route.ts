import { NextRequest, NextResponse } from "next/server";

/**
 * Tevet-7 onboarding proxy.
 *
 * Forwards every `/api/tenants/{id}/onboarding/*` request from the Next.js
 * frontend to the FastAPI onboarding service at
 * `http://localhost:8001/api/tenants/{id}/onboarding/{step}`.
 *
 * This catch-all takes precedence over the broader `/api/tenants/[[...path]]`
 * catch-all (Next.js picks the more specific route). It exists as a separate
 * handler because:
 *
 *   1. CSV uploads come in as `multipart/form-data` with a binary file part.
 *      The generic tenants proxy reads the body with `await req.text()` which
 *      corrupts non-text bytes. This handler reads `arrayBuffer()` so binary
 *      CSV files survive the round-trip.
 *
 *   2. The onboarding endpoints accept both JSON (`connect` for Postgres,
 *      `save-schema`, `save-roles`, `complete`) and multipart (`connect` for
 *      CSV). We forward `content-type` verbatim so the multipart boundary is
 *      preserved — without it, the backend's multipart parser would reject
 *      the upload.
 *
 * The browser frontend always uses relative paths (`/api/tenants/...`); this
 * route handler performs the cross-origin hop to localhost:8001.
 */

const BACKEND_BASE = "http://localhost:8001";

function buildTargetUrl(
  req: NextRequest,
  tenantId: string,
  step: string[] | undefined,
): string {
  const stepPath = step && step.length > 0 ? step.join("/") : "";
  const qs = req.nextUrl.search ?? "";
  const tail = stepPath.length > 0 ? `/${stepPath}` : "";
  return `${BACKEND_BASE}/api/tenants/${encodeURIComponent(tenantId)}/onboarding${tail}${qs}`;
}

async function forward(
  req: NextRequest,
  tenantId: string,
  step: string[] | undefined,
) {
  const target = buildTargetUrl(req, tenantId, step);

  // Forward only safe headers — Authorization carries the JWT, content-type
  // carries the multipart boundary for CSV uploads (must be preserved verbatim).
  const headers = new Headers();
  const auth = req.headers.get("authorization");
  if (auth) headers.set("authorization", auth);
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const accept = req.headers.get("accept");
  if (accept) headers.set("accept", accept);

  const init: RequestInit = {
    method: req.method,
    headers,
  };

  // Read the body as raw bytes so multipart/form-data binary payloads
  // (CSV uploads) survive the round-trip. JSON bodies also work since
  // arrayBuffer is just bytes.
  if (req.method !== "GET" && req.method !== "HEAD") {
    const buffer = await req.arrayBuffer();
    if (buffer.byteLength > 0) init.body = buffer;
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
      err instanceof Error ? err.message : "Onboarding backend unreachable";
    return NextResponse.json(
      {
        error: "onboarding_backend_unreachable",
        message,
        backend: target,
      },
      { status: 502 },
    );
  }
}

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ id: string; step?: string[] }> },
) {
  const { id, step } = await ctx.params;
  return forward(req, id, step);
}

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ id: string; step?: string[] }> },
) {
  const { id, step } = await ctx.params;
  return forward(req, id, step);
}

export async function PUT(
  req: NextRequest,
  ctx: { params: Promise<{ id: string; step?: string[] }> },
) {
  const { id, step } = await ctx.params;
  return forward(req, id, step);
}

export async function DELETE(
  req: NextRequest,
  ctx: { params: Promise<{ id: string; step?: string[] }> },
) {
  const { id, step } = await ctx.params;
  return forward(req, id, step);
}
