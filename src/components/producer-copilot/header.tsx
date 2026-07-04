"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Separator } from "@/components/ui/separator";
import {
  Check,
  ChevronDown,
  Eye,
  LogOut,
  Menu,
  Settings,
  Shield,
  User as UserIcon,
} from "@/components/ui/feather-icons";
import { useCopilotStore } from "@/lib/store";

import { BrandLogo } from "./brand-mark";
import { ViewToggle } from "./view-toggle";

interface HeaderProps {
  onOpenSidebar: () => void;
  onOpenInspector: () => void;
}

export function Header({ onOpenSidebar, onOpenInspector }: HeaderProps) {
  const identity = useCopilotStore((s) => s.identity);
  const messages = useCopilotStore((s) => s.messages);
  const inspectorOpen = useCopilotStore((s) => s.inspectorOpen);
  const toggleInspector = useCopilotStore((s) => s.toggleInspector);

  // Auth state — when authenticated we render the user menu + tenant
  // switcher. When NOT authenticated (demo mode), the user menu stays
  // hidden and the IdentitySwitcher in the sidebar handles scope changes.
  const user = useCopilotStore((s) => s.user);
  const token = useCopilotStore((s) => s.token);
  const tenants = useCopilotStore((s) => s.tenants);
  const activeTenant = useCopilotStore((s) => s.activeTenant);
  const logout = useCopilotStore((s) => s.logout);
  const setActiveTenant = useCopilotStore((s) => s.setActiveTenant);
  const demoFallback = useCopilotStore((s) => s.demoFallback);

  const isAuthenticated = !!user && !!token;

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-background px-3 sm:px-4">
      {/* Mobile: open sidebar */}
      <Button
        variant="ghost"
        size="icon"
        className="md:hidden"
        onClick={onOpenSidebar}
        aria-label="Ouvrir le menu"
      >
        <Menu size={18} />
      </Button>

      {/* Brand logo */}
      <BrandLogo size={26} />

      <Separator orientation="vertical" className="hidden h-5 md:block" />

      <Badge
        variant="outline"
        className="hidden uppercase tracking-wide text-[11px] font-body sm:inline-flex"
      >
        Drive Producteur
      </Badge>

      {/* Admin-only view toggle — switches between Producer Copilot and Ops Console.
          Returns null for producers so the header layout is identical to before.
          On mobile the labels collapse to icon-only. */}
      <ViewToggle />

      {/* Scope breadcrumb (hidden on small) */}
      <div className="ml-2 hidden items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted-foreground lg:flex">
        <Separator orientation="vertical" className="h-4" />
        <span>Tenant</span>
        <span className="text-muted-foreground/50">/</span>
        <span className="font-medium text-foreground">
          {isAuthenticated && activeTenant
            ? activeTenant.name
            : "Drive Producteur"}
        </span>
        <span className="text-muted-foreground/50">/</span>
        <span className="font-medium text-foreground">
          {identity.kind === "admin" ? (
            "Admin (full access)"
          ) : (
            <>
              Producer{" "}
              <span className="font-heading text-accent">
                {identity.producerNumber}
              </span>
            </>
          )}
        </span>
      </div>

      <div className="ml-auto flex items-center gap-1.5">
        {/* Conversation status pill (hidden on mobile) */}
        {messages.length > 0 && (
          <span className="hidden items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted-foreground md:inline-flex">
            <span className="font-heading text-foreground tabular-nums">
              {messages.length}
            </span>
            message{messages.length > 1 ? "s" : ""}
          </span>
        )}
        <Badge
          variant="outline"
          className="hidden uppercase tracking-wide text-[11px] font-body sm:inline-flex"
        >
          {isAuthenticated ? "Phase 6a" : demoFallback ? "Démo" : "Phase 0"}
        </Badge>

        <Button
          variant="ghost"
          size="icon"
          className="hidden sm:inline-flex"
          aria-label="Paramètres"
        >
          <Settings size={18} />
        </Button>

        <Separator orientation="vertical" className="hidden h-4 md:block" />

        {/* Desktop inspector toggle */}
        <Button
          variant="ghost"
          size="icon"
          className="hidden md:inline-flex"
          onClick={() => toggleInspector()}
          aria-label="Basculer l'inspecteur"
          data-state={inspectorOpen ? "on" : "off"}
        >
          <Eye size={18} />
        </Button>

        {/* Mobile inspector toggle */}
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          onClick={onOpenInspector}
          aria-label="Ouvrir l'inspecteur"
        >
          <Eye size={20} />
        </Button>

        {/* Auth: user dropdown (login + tenant switcher + logout) */}
        {isAuthenticated && user && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label="Menu utilisateur"
                className="flex items-center gap-1.5 rounded-md border border-border bg-background px-2 py-1 text-left transition-colors hover:border-accent/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-border bg-primary text-primary-foreground">
                  <span className="font-heading text-[10px] font-medium">
                    {user.name
                      .split(/[\s@.]+/)
                      .filter(Boolean)
                      .map((s) => s[0])
                      .join("")
                      .toUpperCase()
                      .slice(0, 2) || "?"}
                  </span>
                </span>
                <span className="hidden max-w-[120px] truncate text-xs font-medium text-foreground sm:inline">
                  {user.name || user.email}
                </span>
                <ChevronDown
                  size={14}
                  className="shrink-0 text-muted-foreground"
                />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-[280px]">
              <DropdownMenuLabel className="flex flex-col gap-0.5 text-[11px] font-body uppercase tracking-wide text-muted-foreground">
                <span className="text-foreground">{user.name || user.email}</span>
                <span className="truncate text-[10px] font-normal normal-case tracking-normal text-muted-foreground">
                  {user.email}
                </span>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />

              {/* Tenant switcher — only rendered when the user has at least
                  one membership. The active tenant is highlighted with a
                  check; clicking another tenant calls /api/tenants/{id}/activate. */}
              {tenants.length > 0 && (
                <>
                  <DropdownMenuLabel className="text-[11px] font-body uppercase tracking-wide text-muted-foreground">
                    Tenants
                  </DropdownMenuLabel>
                  {tenants.map((t) => {
                    const isActive =
                      activeTenant?.tenant_id === t.tenant_id;
                    return (
                      <DropdownMenuItem
                        key={t.tenant_id}
                        className="gap-2 p-2"
                        disabled={isActive}
                        onSelect={() => {
                          if (!isActive) void setActiveTenant(t.tenant_id);
                        }}
                      >
                        <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-secondary text-foreground">
                          {t.role === "admin" ? (
                            <Shield size={13} />
                          ) : (
                            <UserIcon size={13} />
                          )}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className="truncate text-sm font-medium text-foreground">
                              {t.name}
                            </span>
                            {t.is_demo && (
                              <span className="rounded border border-border px-1 py-0 text-[9px] uppercase tracking-wide text-muted-foreground">
                                démo
                              </span>
                            )}
                          </div>
                          <div className="truncate text-[11px] text-muted-foreground">
                            {t.role} · {t.slug}
                          </div>
                        </div>
                        {isActive && (
                          <Check size={14} className="shrink-0 text-accent" />
                        )}
                      </DropdownMenuItem>
                    );
                  })}
                  <DropdownMenuSeparator />
                </>
              )}

              {/* Logout */}
              <DropdownMenuItem
                className="gap-2 p-2 text-foreground"
                onSelect={() => logout()}
              >
                <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-secondary text-foreground">
                  <LogOut size={13} />
                </span>
                <span className="flex-1 text-sm font-medium">Déconnexion</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </header>
  );
}
