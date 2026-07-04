"use client";

import { Shield } from "@/components/ui/feather-icons";
import { useCopilotStore } from "@/lib/store";
import type { BackendStatus } from "@/lib/store";

interface StatusConfig {
  label: string;
  /** Tailwind background utility for the 8px status dot. */
  dot: string;
}

function statusConfig(status: BackendStatus): StatusConfig {
  switch (status) {
    case "connected":
      return {
        label: "Backend connecté",
        // On-brand accent green — matches the Scoping actif shield.
        dot: "bg-accent",
      };
    case "demo":
      return {
        label: "Mode démo",
        // Muted dot — NOT a warning color, stays in the Tevet-7 palette.
        dot: "bg-muted-foreground/60",
      };
    case "unknown":
    default:
      return {
        label: "Backend en attente",
        dot: "bg-muted-foreground/30",
      };
  }
}

export function Footer() {
  const backendStatus = useCopilotStore((s) => s.backendStatus);
  const user = useCopilotStore((s) => s.user);
  const token = useCopilotStore((s) => s.token);
  const demoFallback = useCopilotStore((s) => s.demoFallback);
  const { label, dot } = statusConfig(backendStatus);

  // Auth status label — drives the left-side text in the footer.
  //   - Authenticated → "Connecté en tant que {email}"
  //   - Demo fallback (backend unreachable) → "Mode démo (backend hors ligne)"
  //   - Pure demo (not authenticated, no fallback yet) → "Mode démo"
  let authStatus = "Mode démo";
  if (user && token) {
    authStatus = `Connecté en tant que ${user.email}`;
  } else if (demoFallback) {
    authStatus = "Mode démo (backend hors ligne)";
  }

  return (
    <footer className="mt-auto border-t border-border bg-background">
      <div className="flex h-9 items-center justify-between gap-2 px-3 text-[11px] text-muted-foreground sm:px-4">
        <span className="truncate font-body uppercase tracking-wide">
          Tevet-7 <span className="text-muted-foreground/50">·</span> {authStatus}
        </span>
        <span className="hidden truncate text-center font-body uppercase tracking-wide sm:inline">
          Drive Producteur tenant
        </span>
        <span className="flex shrink-0 items-center gap-2.5 font-body uppercase tracking-wide sm:gap-3">
          <span
            className="flex items-center gap-1.5"
            title={label}
            aria-label={label}
          >
            <span
              className={`size-2 rounded-full ${dot}`}
              aria-hidden
            />
            <span className="hidden sm:inline">{label}</span>
          </span>
          <span className="flex items-center gap-1.5">
            <Shield size={12} className="text-accent" />
            Scoping actif
          </span>
        </span>
      </div>
    </footer>
  );
}
