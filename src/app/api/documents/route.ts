import { NextRequest, NextResponse } from "next/server";

import { getBackendAccessToken } from "@/lib/server/backend-auth";

const BACKEND_BASE = "http://localhost:8001";

export async function GET(req: NextRequest) {
  const headers: Record<string, string> = {};
  const access = await getBackendAccessToken(req);
  if (access) headers["authorization"] = `Bearer ${access}`;

  try {
    const res = await fetch(`${BACKEND_BASE}/api/documents`, { headers });
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return NextResponse.json({ documents: [] }, { status: 502 });
  }
}

export async function POST(req: NextRequest) {
  const headers = new Headers();
  const access = await getBackendAccessToken(req);
  if (access) headers.set("authorization", `Bearer ${access}`);
  const ct = req.headers.get("content-type");
  if (ct) headers.set("content-type", ct);

  const body = await req.arrayBuffer();
  try {
    const res = await fetch(`${BACKEND_BASE}/api/documents`, {
      method: "POST",
      headers,
      body,
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
