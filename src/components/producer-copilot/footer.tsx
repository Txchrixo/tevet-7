"use client";

import * as React from "react";

import { useCopilotStore } from "@/lib/store";
import { Shield } from "@/components/ui/feather-icons";

/**
 * Tevet-7 sticky footer.
 *
 * Left   : "Tevet-7 · Plateforme d'agents IA" + auth status
 *          ("Connecté en tant que {email}" when logged in,
 *           "Mode démo" when in demo mode,
 *           nothing when anonymous - but the AuthScreen renders its own
 *           footer so this branch is rarely hit).
 * Center : "Tenant : {tenantName}" (dynamic).
 * Right  : security status (Scoping actif).
 *
 * Layout: `mt-auto` on a `min-h-screen flex flex-col` parent keeps the footer
 * pinned to the bottom when the page content is shorter than the viewport,
 * and pushes it down naturally when content overflows.
 */
export function Footer() {
  const authMode = useCopilotStore((s) => s.authMode);
  const user = useCopilotStore((s) => s.user);
  const activeTenant = useCopilotStore((s) => s.activeTenant);

  const tenantName = activeTenant?.name ?? "Drive Producteur";

  let authLabel: string;
  if (authMode === "authenticated" && user) {
    authLabel = `Connecté en tant que ${user.email}`;
  } else if (authMode === "demo") {
    authLabel = "Mode démo";
  } else {
    authLabel = "Non connecté";
  }

  return (
    <footer className="mt-auto border-t border-border bg-background">
      <div className="flex h-9 items-center justify-between gap-2 px-3 text-[11px] text-muted-foreground sm:px-4">
        <span className="flex min-w-0 items-center gap-1.5 truncate font-body uppercase tracking-wide">
          <span className="shrink-0">
            Tevet-7 <span className="text-muted-foreground/50">·</span>{" "}
            Plateforme d&apos;agents IA
          </span>
          <span className="hidden text-muted-foreground/50 sm:inline">·</span>
          <span className="hidden truncate text-muted-foreground sm:inline">
            {authLabel}
          </span>
        </span>
        <span className="hidden truncate text-center font-body uppercase tracking-wide md:inline">
          Tenant : {tenantName}
        </span>
        <span className="flex shrink-0 items-center gap-1.5 font-body uppercase tracking-wide">
          <Shield size={12} className="text-accent" />
          Scoping actif
        </span>
      </div>
    </footer>
  );
}
