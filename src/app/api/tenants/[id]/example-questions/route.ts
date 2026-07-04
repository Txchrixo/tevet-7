import { NextRequest, NextResponse } from "next/server";

/**
 * Tevet-7 example-questions proxy (Phase 6d).
 *
 * Forwards `GET /api/tenants/{id}/example-questions` from the Next.js
 * frontend to the FastAPI tenants service at
 * `http://localhost:8001/api/tenants/{id}/example-questions`. Forwards
 * the Authorization header so the backend can verify the caller's
 * membership on the tenant.
 *
 * The browser frontend always uses relative paths; this route handler
 * performs the cross-origin hop to localhost:8001.
 *
 * NOTE: this dedicated route takes precedence over the catch-all proxy
 * at `src/app/api/tenants/[[...path]]/route.ts` (Next.js prefers more
 * specific dynamic segments over catch-alls), so the example-questions
 * path is handled here while every other `/api/tenants/*` path keeps
 * flowing through the catch-all.
 */

const BACKEND_BASE = "http://localhost:8001";

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const qs = req.nextUrl.search ?? "";
  const target = `${BACKEND_BASE}/api/tenants/${encodeURIComponent(
    id,
  )}/example-questions${qs}`;

  const headers = new Headers();
  const auth = req.headers.get("authorization");
  if (auth) headers.set("authorization", auth);

  try {
    const upstream = await fetch(target, { method: "GET", headers });
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
