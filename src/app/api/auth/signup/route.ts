/**
 * Signup proxy - the single non-NextAuth auth endpoint.
 *
 * Creates the account on the FastAPI backend. It deliberately does NOT
 * return the backend JWT to the browser: after a 200 the client calls
 * signIn("credentials") with the same email/password so the session is
 * established through NextAuth (httpOnly cookie), exactly like a login.
 */

import { NextRequest, NextResponse } from "next/server";

import { backendJson } from "@/lib/server/backend";

interface SignupBody {
  email?: string;
  password?: string;
  name?: string;
}

export async function POST(req: NextRequest) {
  let body: SignupBody;
  try {
    body = (await req.json()) as SignupBody;
  } catch {
    return NextResponse.json({ detail: "invalid JSON body" }, { status: 400 });
  }
  if (!body.email || !body.password || !body.name) {
    return NextResponse.json(
      { detail: "email, password and name are required" },
      { status: 400 },
    );
  }
  try {
    const { status, body: upstream } = await backendJson<{
      user?: unknown;
      detail?: unknown;
    }>("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify({
        email: body.email,
        password: body.password,
        name: body.name,
      }),
    });
    // Strip the token fields - the browser must never see backend JWTs.
    if (status === 200 && upstream && typeof upstream === "object") {
      return NextResponse.json({ user: upstream.user }, { status: 200 });
    }
    return NextResponse.json(upstream ?? { detail: "signup failed" }, { status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return NextResponse.json(
      { error: "auth_backend_unreachable", message },
      { status: 502 },
    );
  }
}
