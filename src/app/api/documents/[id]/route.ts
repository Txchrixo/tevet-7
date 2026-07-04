import { NextRequest, NextResponse } from "next/server";

const BACKEND_BASE = "http://localhost:8001";

export async function DELETE(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const auth = req.headers.get("authorization");
  const headers: Record<string, string> = {};
  if (auth) headers["authorization"] = auth;

  try {
    const res = await fetch(`${BACKEND_BASE}/api/documents/${id}`, {
      method: "DELETE",
      headers,
    });
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return NextResponse.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
