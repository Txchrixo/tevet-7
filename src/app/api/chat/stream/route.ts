import { NextRequest } from "next/server";

/**
 * Tevet-7 chat SSE streaming proxy.
 *
 * Passes the SSE stream from FastAPI's /api/chat/stream through to the
 * browser without buffering. The browser reads the stream chunk by chunk
 * and updates the message progressively (Phase A2).
 */

const BACKEND_TARGET = "http://localhost:8001/api/chat/stream";

export async function POST(req: NextRequest) {
  const headers = new Headers();
  const auth = req.headers.get("authorization");
  if (auth) headers.set("authorization", auth);
  headers.set("content-type", "application/json");
  headers.set("accept", "text/event-stream");

  const body = await req.text();

  try {
    const upstream = await fetch(BACKEND_TARGET, {
      method: "POST",
      headers,
      body: body.length > 0 ? body : undefined,
    });

    if (!upstream.ok || !upstream.body) {
      const text = await upstream.text().catch(() => "");
      return new Response(text || "backend error", {
        status: upstream.status,
        headers: { "content-type": "application/json" },
      });
    }

    // Pass the SSE stream through without buffering.
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
        connection: "keep-alive",
      },
    });
  } catch {
    return new Response(
      JSON.stringify({ error: "chat_backend_unreachable" }),
      { status: 502, headers: { "content-type": "application/json" } },
    );
  }
}
