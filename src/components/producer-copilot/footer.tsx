"use client";

import { Shield } from "@/components/ui/feather-icons";

export function Footer() {
  return (
    <footer className="mt-auto border-t border-border bg-background">
      <div className="flex h-9 items-center justify-between gap-2 px-3 text-[11px] text-muted-foreground sm:px-4">
        <span className="truncate font-body uppercase tracking-wide">
          Tevet-7 <span className="text-muted-foreground/50">·</span> Phase 0 Prototype
        </span>
        <span className="hidden truncate text-center font-body uppercase tracking-wide sm:inline">
          Drive Producteur tenant
        </span>
        <span className="flex shrink-0 items-center gap-1.5 font-body uppercase tracking-wide">
          <Shield size={12} className="text-accent" />
          Scoping actif
        </span>
      </div>
    </footer>
  );
}
