import { NextRequest, NextResponse } from "next/server";

/**
 * Tevet-7 chat proxy.
 *
 * Forwards `POST /api/chat` from the Next.js frontend to the FastAPI chat
 * endpoint at `http://localhost:8001/api/chat`. The backend reads the
 * caller identity from the JWT (Authorization: Bearer) and returns the
 * full agent envelope (answer, sql, scope_clause, chart, steps,
 * security_checks, tokens, latency, refused, …).
 *
 * The browser frontend always uses the relative path `/api/chat`; this
 * route handler performs the cross-origin hop to localhost:8001.
 */

const BACKEND_TARGET = "http://localhost:8001/api/chat";

export async function POST(req: NextRequest) {
  const headers = new Headers();
  const auth = req.headers.get("authorization");
  if (auth) headers.set("authorization", auth);
  headers.set("content-type", "application/json");

  const body = await req.text();

  try {
    const upstream = await fetch(BACKEND_TARGET, {
      method: "POST",
      headers,
      body: body.length > 0 ? body : undefined,
    });
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
      err instanceof Error ? err.message : "Chat backend unreachable";
    return NextResponse.json(
      {
        error: "chat_backend_unreachable",
        message,
        backend: BACKEND_TARGET,
      },
      { status: 502 },
    );
  }
}
