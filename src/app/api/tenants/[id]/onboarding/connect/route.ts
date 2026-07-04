import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side proxy → FastAPI backend's onboarding connect endpoint.
 *
 * POST /api/tenants/{tenant_id}/onboarding/connect
 *
 * The body can be EITHER:
 *   - JSON `{connector_type: "postgres", connection_url: "postgresql://..."}` —
 *     forwarded verbatim with Content-Type application/json.
 *   - multipart/form-data with `connector_type=csv` + `file=<csv_file>` —
 *     forwarded verbatim (Next.js reconstructs the boundary on the backend
 *     fetch, mirroring the documents upload proxy).
 *
 * The Authorization header is ALWAYS forwarded — onboarding is authed.
 *
 * Mirrors the pattern of `src/app/api/tenants/[id]/activate/route.ts` +
 * `src/app/api/documents/route.ts` (multipart path).
 */

const BACKEND_ORIGIN = "http://localhost:8001";
const BACKEND_TIMEOUT_MS = 30_000;

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const auth = req.headers.get("authorization");
  const contentType = req.headers.get("content-type") ?? "";

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);

  try {
    const headers: Record<string, string> = {
      Accept: "application/json",
    };
    if (auth) headers["Authorization"] = auth;

    let body: BodyInit;

    if (contentType.toLowerCase().startsWith("multipart/form-data")) {
      // Forward the multipart body verbatim — fetch reconstructs the
      // Content-Type header (with the boundary) when the body is a FormData.
      let form: FormData;
      try {
        form = await req.formData();
      } catch (err) {
        return NextResponse.json(
          {
            error: "invalid_form",
            detail:
              err instanceof Error ? err.message : "formData parse failed",
          },
          { status: 400 },
        );
      }
      body = form;
    } else {
      // JSON body — forward as text and explicitly set Content-Type so the
      // backend's JSON parser picks it up.
      headers["Content-Type"] = "application/json";
      body = await req.text();
    }

    const backendRes = await fetch(
      `${BACKEND_ORIGIN}/api/tenants/${encodeURIComponent(
        id,
      )}/onboarding/connect`,
      {
        method: "POST",
        headers,
        body,
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
