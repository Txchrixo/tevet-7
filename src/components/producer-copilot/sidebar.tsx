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
import { EXAMPLE_QUESTIONS, IDENTITIES } from "@/lib/mock-data";
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
  Users,
} from "@/components/ui/feather-icons";

import { IdentitySwitcher } from "./identity-switcher";

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

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/*
       * Identity / tenant panel — fixed at the top of the sidebar. Does NOT
       * carry a close button: on mobile the wrapping Sheet already renders
       * its own X (top-right) and adding a second one here is what produced
       * the duplicate-close-button bug. On desktop there's nothing to close
       * (the sidebar is always visible).
       */}
      <div className="shrink-0 p-3">
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
              {EXAMPLE_QUESTIONS.map((q) => {
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
                    <span className="flex-1 font-body text-foreground">
                      {q.label}
                    </span>
                    {adminOnly && disabledForProducer && (
                      <div className="mt-1 flex items-center gap-1 pl-5 text-[10px] uppercase tracking-wide text-muted-foreground">
                        Sera refusé · scoping producer
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </section>

          {/* Demo identity quick-switch (only on demo tenant) */}
          {authMode === "authenticated" && activeTenant?.is_demo && (
            <DemoIdentitySwitcher />
          )}
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
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full border border-border bg-primary text-primary-foreground">
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

/**
 * Demo identity quick-switcher — shown only on the demo tenant ("dp").
 * Lets the user instantly switch between Marie (#42), Pierre (#99), and
 * DP Admin WITHOUT re-logging in. Uses a demo identity override that
 * sends body identity (no JWT) to the chat endpoint, so the backend's
 * dual-mode fallback handles the scoping.
 */
function DemoIdentitySwitcher() {
  const demoIdentityOverride = useCopilotStore((s) => s.demoIdentityOverride);
  const setDemoIdentityOverride = useCopilotStore(
    (s) => s.setDemoIdentityOverride,
  );
  const reset = useCopilotStore((s) => s.resetConversation);

  return (
    <section>
      <SectionLabel icon={<Users size={12} />}>
        Identité démo
      </SectionLabel>
      <div className="mt-2 space-y-1.5">
        {IDENTITIES.map((ident) => {
          const isActive =
            demoIdentityOverride?.id === ident.id ||
            (!demoIdentityOverride && ident.id === "producer-42");
          return (
            <button
              key={ident.id}
              type="button"
              onClick={() => {
                setDemoIdentityOverride(isActive ? null : ident.id);
                reset();
              }}
              className={cn(
                "flex w-full items-center gap-2 rounded-md border border-border bg-background px-2.5 py-2 text-left text-xs transition-colors hover:border-accent/60 hover:bg-secondary/40",
                isActive && "border-accent/50 bg-secondary/30",
              )}
            >
              <span
                className={cn(
                  "flex size-6 shrink-0 items-center justify-center rounded-full border border-border text-[10px] font-heading font-medium",
                  isActive
                    ? "bg-primary text-primary-foreground"
                    : "bg-secondary text-muted-foreground",
                )}
              >
                {ident.initials}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-foreground">
                  {ident.name}
                </div>
                <div className="truncate text-[10px] text-muted-foreground">
                  {ident.kind === "admin"
                    ? "Admin · full access"
                    : `Producer ${ident.producerNumber} · ${ident.farmName}`}
                </div>
              </div>
              {isActive && (
                <Check size={13} className="shrink-0 text-accent" />
              )}
            </button>
          );
        })}
      </div>
      <p className="mt-2 px-1 text-[10px] uppercase tracking-wide text-muted-foreground/70">
        Override démo — sans re-login
      </p>
    </section>
  );
}
