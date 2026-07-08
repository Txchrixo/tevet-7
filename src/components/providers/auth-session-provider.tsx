"use client";

/**
 * Mounts NextAuth's SessionProvider and wires its `update` function into
 * the session bridge so zustand store actions can rotate the tenant
 * context (see src/lib/session-bridge.ts).
 */

import * as React from "react";
import { SessionProvider, useSession } from "next-auth/react";

import { registerSessionUpdate } from "@/lib/session-bridge";

function SessionBridge() {
  const { update } = useSession();
  React.useEffect(() => {
    registerSessionUpdate(update);
    return () => registerSessionUpdate(null);
  }, [update]);
  return null;
}

export function AuthSessionProvider({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider refetchOnWindowFocus={false}>
      <SessionBridge />
      {children}
    </SessionProvider>
  );
}
