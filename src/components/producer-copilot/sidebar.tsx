"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { useCopilotStore } from "@/lib/store";
import type { TenantMembership } from "@/lib/types";
import {
  Check,
  ChevronDown,
  Hash,
  Layers,
  Plus,
  RefreshCw,
  ShieldOff,
  X,
} from "@/components/ui/feather-icons";

import { IdentitySwitcher } from "./identity-switcher";
import { DocumentsPanel } from "./documents-panel";

interface SidebarProps {
  /** Called when an example or action is triggered (used to close the mobile sheet). */
  onNavigate?: () => void;
}

export function Sidebar({ onNavigate }: SidebarProps) {
  const identity = useCopilotStore((s) => s.identity);
  const sendExample = useCopilotStore((s) => s.sendExample);
  const reset = useCopilotStore((s) => s.resetConversation);
  const isStreaming = useCopilotStore((s) => s.isStreaming);
  const authMode = useCopilotStore((s) => s.authMode);
  const user = useCopilotStore((s) => s.user);
  const tenants = useCopilotStore((s) => s.tenants);
  const activeTenant = useCopilotStore((s) => s.activeTenant);
  const switchTenant = useCopilotStore((s) => s.switchTenant);
  // Phase 6d — example questions are now dynamic, fetched per-tenant from
  // `/api/tenants/{id}/example-questions` (see `loadExampleQuestions` in
  // the store). The store initialises this to the hardcoded
  // `FALLBACK_QUESTIONS` so the sidebar always has something to render
  // before the first fetch resolves AND when the fetch fails / the
  // tenant is in demo mode.
  const exampleQuestions = useCopilotStore((s) => s.exampleQuestions);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/*
       * Top bar: identity/tenant panel + close button (mobile only).
       * The close button is a feather X icon that calls onNavigate (which
       * closes the mobile Sheet). On desktop it's hidden — the sidebar is
       * always visible.
       */}
      <div className="shrink-0 p-3">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            {authMode === "authenticated" && user ? (
              <TenantUserPanel
                user={user}
                tenants={tenants}
                activeTenant={activeTenant}
                onSwitchTenant={(id) => {
                  void switchTenant(id);
                  onNavigate?.();
                }}
              />
            ) : (
              <IdentitySwitcher />
            )}
          </div>
          {onNavigate && (
            <button
              type="button"
              onClick={onNavigate}
              className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground md:hidden"
              aria-label="Fermer le menu"
            >
              <X size={16} />
            </button>
          )}
        </div>
      </div>

      {/*
       * ScrollArea fills ALL the remaining vertical space (min-h-0 lets it
       * shrink below content height so the viewport becomes scrollable).
       * Order inside: Quick actions → Examples → Demo identity switcher.
       * This is the only scrollable region — the user panel above is fixed.
       */}
      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-4 px-3 pb-4">
          {/* Quick actions */}
          <div className="space-y-2">
            <Button
              variant="outline"
              size="sm"
              className="w-full justify-start gap-2 text-xs"
              onClick={() => {
                reset();
                onNavigate?.();
              }}
            >
              <Plus size={14} />
              Nouvelle conv.
            </Button>
            <button
              type="button"
              onClick={() => {
                reset();
                onNavigate?.();
              }}
              className="flex w-full items-center gap-1.5 px-1 text-[11px] uppercase tracking-wide text-muted-foreground transition-colors hover:text-foreground"
            >
              <RefreshCw size={11} />
              Réinitialiser
            </button>
          </div>

          <SectionSeparator />

          {/* Example questions */}
          <section>
            <SectionLabel icon={<Hash size={12} />}>Exemples</SectionLabel>
            <div className="mt-2 space-y-1.5">
              {exampleQuestions.map((q) => {
                // The "top-producers" id is the only hardcoded admin-only
                // question (lives in FALLBACK_QUESTIONS, surfaces the
                // "Sera refusé · scoping producer" hint when a producer
                // is signed in). Dynamic questions don't carry this id
                // so the check is a no-op for them.
                const adminOnly = q.id === "top-producers";
                const disabledForProducer =
                  adminOnly && identity.kind === "producer";
                return (
                  <button
                    key={q.id}
                    type="button"
                    disabled={isStreaming}
                    onClick={() => {
                      sendExample(q.id, q.label);
                      onNavigate?.();
                    }}
                    className={cn(
                      "group flex w-full items-start gap-2 rounded-md border border-border bg-background px-2.5 py-2 text-left text-xs transition-colors hover:border-accent/60 hover:bg-secondary/40 disabled:cursor-not-allowed disabled:opacity-50",
                      disabledForProducer && "border-dashed",
                    )}
                  >
                    {disabledForProducer ? (
                      <ShieldOff
                        size={13}
                        className="mt-0.5 shrink-0 text-muted-foreground"
                      />
                    ) : (
                      <Hash
                        size={13}
                        className="mt-0.5 shrink-0 text-muted-foreground group-hover:text-accent"
                      />
                    )}
                    <div className="min-w-0 flex-1">
                      <span className="block font-body text-foreground">
                        {q.label}
                      </span>
                      {adminOnly && disabledForProducer && (
                        <span className="mt-1 block text-[10px] uppercase tracking-wide text-muted-foreground">
                          Sera refusé · scoping producer
                        </span>
                      )}
                      {q.hint && !disabledForProducer && (
                        <span className="mt-1 block text-[10px] uppercase tracking-wide text-muted-foreground">
                          {q.hint}
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          <SectionSeparator />

          {/* Documents panel — upload + list (Phase 6b / Priority 4) */}
          <DocumentsPanel />
        </div>
      </ScrollArea>
    </div>
  );
}

/**
 * Thin separator between sidebar sections. Uses `border-border` so it matches
 * the rest of the design system (no shadows, no accent).
 */
function SectionSeparator() {
  return <Separator className="bg-border" />;
}

function SectionLabel({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-1.5 text-[11px] font-body font-medium uppercase tracking-wide text-muted-foreground">
      <span className="text-muted-foreground">{icon}</span>
      {children}
    </div>
  );
}

/**
 * Authenticated-mode sidebar panel — shows the logged-in user + a tenant
 * switcher (if the user has multiple memberships). Replaces the demo
 * IdentitySwitcher when the user is logged in via the real backend.
 */
function TenantUserPanel({
  user,
  tenants,
  activeTenant,
  onSwitchTenant,
}: {
  user: { name: string; email: string };
  tenants: TenantMembership[];
  activeTenant: TenantMembership | null;
  onSwitchTenant: (tenantId: string) => void;
}) {
  const initials = React.useMemo(() => {
    const parts = user.name.trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return "?";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }, [user.name]);

  const canSwitch = tenants.length > 1;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center justify-between gap-2 rounded-md border border-border bg-background px-2.5 py-2 text-left transition-colors hover:border-accent/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <div className="flex min-w-0 items-center gap-2">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full border border-border bg-primary text-foreground">
              <span className="font-heading text-[11px] font-medium">
                {initials}
              </span>
            </span>
            <div className="min-w-0">
              <div className="truncate text-sm font-medium leading-tight text-foreground">
                {user.name}
              </div>
              <div className="flex items-center gap-1 truncate text-[11px] leading-tight text-muted-foreground">
                <Layers size={10} />
                <span className="truncate">{activeTenant?.name ?? "—"}</span>
              </div>
            </div>
          </div>
          {canSwitch && (
            <ChevronDown
              size={16}
              className="shrink-0 text-muted-foreground"
            />
          )}
        </button>
      </DropdownMenuTrigger>
      {canSwitch && (
        <DropdownMenuContent align="start" className="w-[260px]">
          <DropdownMenuLabel className="text-[11px] font-body uppercase tracking-wide text-muted-foreground">
            Changer de tenant
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          {tenants.map((t) => {
            const active = activeTenant?.tenant_id === t.tenant_id;
            return (
              <DropdownMenuItem
                key={t.tenant_id}
                onSelect={() => !active && onSwitchTenant(t.tenant_id)}
                className="gap-2 p-2"
              >
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full border border-border bg-secondary text-foreground">
                  <Layers size={12} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-sm font-medium text-foreground">
                      {t.name}
                    </span>
                  </div>
                  <div className="truncate text-[11px] text-muted-foreground">
                    {t.role}
                    {t.producer_id != null ? ` · #${t.producer_id}` : ""}
                  </div>
                </div>
                {active && <Check size={14} className="shrink-0 text-accent" />}
              </DropdownMenuItem>
            );
          })}
        </DropdownMenuContent>
      )}
    </DropdownMenu>
  );
}

