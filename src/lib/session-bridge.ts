/**
 * Bridge between NextAuth's React hooks and the zustand store.
 *
 * `useSession().update()` only exists inside React. The store's async
 * actions (switchTenant, createTenant) need it to swap the backend JWT
 * held in the session cookie. The <AuthSessionProvider> mounts a tiny
 * component that registers the live `update` function here; store actions
 * call `updateSession(...)` without knowing about React.
 */

import type { Session } from "next-auth";

type UpdateFn = (data?: unknown) => Promise<Session | null>;

let _update: UpdateFn | null = null;

export function registerSessionUpdate(fn: UpdateFn | null): void {
  _update = fn;
}

/** Trigger the NextAuth jwt() callback with `trigger="update"`.
 *
 * Returns the refreshed Session (or null when no provider is mounted or
 * the session is gone). */
export async function updateSession(data?: unknown): Promise<Session | null> {
  if (!_update) return null;
  return _update(data);
}
