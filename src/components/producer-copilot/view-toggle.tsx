"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import { useCopilotStore, isTenantAdmin } from "@/lib/store";
import { Sliders, Terminal } from "@/components/ui/feather-icons";

/**
 * Compact two-segment toggle: "Agent" (chat surface) ↔ "Ops Console" (admin
 * surface). Reflects + drives `adminView` in the store:
 *   - `adminView === "none"`     → "Agent" is active.
 *   - `adminView === "tenant"`   → "Ops Console" is active (tenant admin).
 *   - `adminView === "platform"` → "Ops Console" is active (platform owner).
 *
 * For non-admin identities, "Ops Console" is disabled with a tooltip explaining
 * why. Renders the Tevet-7 design system (bordered pill, no shadows, Feather
 * icons only).
 */
export function ViewToggle() {
  const identity = useCopilotStore((s) => s.identity);
  const adminView = useCopilotStore((s) => s.adminView);
  const setAdminView = useCopilotStore((s) => s.setAdminView);

  const isAdmin = isTenantAdmin(identity);
  const onAgent = adminView === "none";

  return (
    <div
      role="tablist"
      aria-label="Surface"
      className="hidden items-center rounded-md border border-border bg-background p-0.5 md:inline-flex"
    >
      <ToggleButton
        active={onAgent}
        onClick={() => setAdminView("none")}
        icon={<Terminal size={13} />}
        label="Agent"
      />
      <ToggleButton
        active={!onAgent}
        disabled={!isAdmin}
        onClick={() => setAdminView("tenant")}
        icon={<Sliders size={13} />}
        label="Ops Console"
        title={
          isAdmin
            ? "Ouvrir la console ops"
            : "Console ops réservée aux administrateurs du tenant"
        }
      />
    </div>
  );
}

function ToggleButton({
  active,
  disabled,
  onClick,
  icon,
  label,
  title,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  title?: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      disabled={disabled}
      onClick={onClick}
      title={title}
      className={cn(
        "flex items-center gap-1.5 rounded-[5px] px-2.5 py-1 font-body text-[12px] font-medium transition-colors",
        active
          ? "bg-secondary text-foreground"
          : "text-muted-foreground hover:text-foreground",
        disabled && "cursor-not-allowed opacity-50 hover:text-muted-foreground",
      )}
    >
      <span className="shrink-0">{icon}</span>
      {label}
    </button>
  );
}
