"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import { useCopilotStore } from "@/lib/store";
import { MessageSquare, ShieldCheck } from "@/components/ui/feather-icons";

/**
 * Segmented control — switches the admin between the Producer Copilot (chat)
 * and the Ops Console (approval queue). Admin-only: returns `null` for any
 * other identity so producers never see the toggle.
 *
 * The active segment uses the primary surface (filled), the inactive one
 * uses a ghost style. Both buttons keep the same height/width for a stable
 * transition. On narrow viewports the labels truncate to icons-only.
 */
export function ViewToggle() {
  const identity = useCopilotStore((s) => s.identity);
  const view = useCopilotStore((s) => s.view);
  const setView = useCopilotStore((s) => s.setView);

  // Hidden for producers — the Ops Console is admin-only.
  if (identity.kind !== "admin") return null;

  return (
    <div
      role="tablist"
      aria-label="Sélection de la vue"
      className="inline-flex items-center gap-0.5 rounded-md border border-border bg-secondary/40 p-0.5"
    >
      <ToggleSegment
        active={view === "copilot"}
        label="Producer Copilot"
        icon={<MessageSquare size={14} />}
        onClick={() => setView("copilot")}
      />
      <ToggleSegment
        active={view === "ops"}
        label="Ops Console"
        icon={<ShieldCheck size={14} />}
        onClick={() => setView("ops")}
      />
    </div>
  );
}

interface ToggleSegmentProps {
  active: boolean;
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
}

function ToggleSegment({ active, label, icon, onClick }: ToggleSegmentProps) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-[calc(0.375rem-2px)] px-2.5 py-1 text-[11px] font-body uppercase tracking-wide transition-colors",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        active
          ? "bg-primary text-primary-foreground"
          : "text-muted-foreground hover:text-foreground hover:bg-secondary",
      )}
    >
      <span className={cn(active ? "text-primary-foreground" : "text-muted-foreground")}>
        {icon}
      </span>
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}
