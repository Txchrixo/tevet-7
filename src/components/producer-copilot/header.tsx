"use client";

import * as React from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { useCopilotStore } from "@/lib/store";
import { Sparkles } from "@/components/ui/feather-icons";
import {
  ChevronDown,
  Eye,
  Globe,
  LogOut,
  Menu,
  Settings,
  Shield,
  User,
} from "@/components/ui/feather-icons";

import { BrandLogo } from "./brand-mark";
import { ViewToggle } from "./view-toggle";
import { APP_PHASE } from "@/lib/constants";

interface HeaderProps {
  onOpenSidebar: () => void;
  onOpenInspector: () => void;
}

export function Header({ onOpenSidebar, onOpenInspector }: HeaderProps) {
  const identity = useCopilotStore((s) => s.identity);
  const messages = useCopilotStore((s) => s.messages);
  const inspectorOpen = useCopilotStore((s) => s.inspectorOpen);
  const toggleInspector = useCopilotStore((s) => s.toggleInspector);
  const activeTenant = useCopilotStore((s) => s.activeTenant);
  const authMode = useCopilotStore((s) => s.authMode);
  const isDemoSession = useCopilotStore((s) => s.isDemoSession);

  const isAdmin = identity.kind === "admin";

  // Tenant display name - real tenant name when authenticated, fallback to
  // "Drive Producteur" (the demo tenant) when in demo mode.
  const tenantName = activeTenant?.name ?? "Drive Producteur";

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

      {/* App identity - Tevet-7 brand */}
      <BrandLogo size={26} />

      <Separator orientation="vertical" className="hidden h-5 md:block" />

      {/* Tenant badge - dynamic, muted context indicator (NOT the app name) */}
      <Badge
        variant="outline"
        className="hidden gap-1 border-border text-[10px] font-body uppercase tracking-wide text-muted-foreground md:inline-flex"
        title={`Tenant actif : ${tenantName}`}
      >
        <span className="size-1.5 rounded-full bg-accent" aria-hidden="true" />
        {tenantName}
      </Badge>

      {/* DÉMO PUBLIQUE badge - shown when in demo session */}
      {isDemoSession && (
        <Badge
          variant="outline"
          className="gap-1 border-dashed border-border bg-secondary/30 text-[9px] font-body uppercase tracking-wide text-muted-foreground"
        >
          <Sparkles size={9} className="text-accent" />
          Démo publique
        </Badge>
      )}

      {/* Scope breadcrumb (hidden on small) - shows the active scope */}
      <div className="ml-1 hidden items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted-foreground lg:flex">
        <Separator orientation="vertical" className="h-4" />
        <span className="text-muted-foreground/60">Scope</span>
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

        {/* Phase badge */}
        <Badge
          variant="outline"
          className="hidden border-border text-[10px] font-body uppercase tracking-wide text-muted-foreground sm:inline-flex"
        >
          {APP_PHASE}
        </Badge>

        {/* Surface toggle - Agent ↔ Ops Console */}
        <ViewToggle />

        {/*
         * Inspector toggle - view control, grouped with the surface toggle
         * (also a view control) BEFORE the user menu (which is an account
         * action, not a view action). Mobile + desktop variants both render
         * here so the layout doesn't reflow when crossing the md breakpoint.
         */}
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
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          onClick={onOpenInspector}
          aria-label="Ouvrir l'inspecteur"
        >
          <Eye size={20} />
        </Button>

        <Separator orientation="vertical" className="hidden h-4 md:block" />

        {/* User dropdown - carries admin/platform entries when admin + logout */}
        <UserDropdown
          isAdmin={isAdmin}
          canLogout={authMode === "authenticated" || authMode === "demo"}
          activeTenant={activeTenant}
        />
      </div>
    </header>
  );
}

/**
 * Compact user dropdown in the main header. Shows the active identity and,
 * for admins, the "Console admin" / "Console platform" entries. When the user
 * is authenticated (or in demo mode), adds a "Se déconnecter" entry.
 */
function UserDropdown({
  isAdmin,
  canLogout,
  activeTenant,
}: {
  isAdmin: boolean;
  canLogout: boolean;
  activeTenant: { name: string } | null;
}) {
  const identity = useCopilotStore((s) => s.identity);
  const setAdminView = useCopilotStore((s) => s.setAdminView);
  const logout = useCopilotStore((s) => s.logout);
  const user = useCopilotStore((s) => s.user);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex items-center gap-2 rounded-md border border-border bg-background px-2 py-1.5 transition-colors hover:border-accent/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          aria-label="Menu utilisateur"
        >
          <span
            className={cn(
              "flex size-6 shrink-0 items-center justify-center rounded-full border",
              identity.kind === "admin"
                ? "border-border bg-secondary text-foreground"
                : "border-border bg-primary text-foreground",
            )}
          >
            <span className="font-heading text-[10px] font-medium">
              {identity.initials}
            </span>
          </span>
          <span className="hidden text-[12px] font-medium text-foreground sm:inline">
            {identity.name}
          </span>
          <ChevronDown size={14} className="text-muted-foreground" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[240px]">
        <DropdownMenuLabel className="text-[11px] font-body uppercase tracking-wide text-muted-foreground">
          {identity.kind === "admin" ? (
            <span className="inline-flex items-center gap-1">
              <Shield size={11} /> {identity.role}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1">
              <User size={11} /> {identity.role}
            </span>
          )}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <div className="px-2 py-1.5">
          <div className="text-sm font-medium text-foreground">
            {identity.name}
          </div>
          <div className="text-[11px] text-muted-foreground">
            {user?.email ?? identity.name}
          </div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">
            {identity.kind === "admin"
              ? "Accès admin (full tenant)"
              : identity.farmName
                ? `${identity.farmName} · ${identity.producerNumber ?? (identity.producerId != null ? `#${identity.producerId}` : "")}`
                : `${activeTenant?.name ?? "Drive Producteur"}${identity.producerId != null ? ` · #${identity.producerId}` : ""}`}
          </div>
        </div>
        {isAdmin && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={() => setAdminView("tenant")}
              className="gap-2 p-2"
            >
              <Settings size={14} className="shrink-0 text-muted-foreground" />
              <div className="flex-1">
                <div className="text-sm font-medium text-foreground">
                  Console admin
                </div>
                <div className="text-[11px] text-muted-foreground">
                  Utilisateurs · config · traces
                </div>
              </div>
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => setAdminView("platform")}
              className="gap-2 p-2"
            >
              <Globe size={14} className="shrink-0 text-muted-foreground" />
              <div className="flex-1">
                <div className="text-sm font-medium text-foreground">
                  Console platform
                </div>
                <div className="text-[11px] text-muted-foreground">
                  Tenants · stats globales · reset démo
                </div>
              </div>
            </DropdownMenuItem>
          </>
        )}
        {!isAdmin && (
          <div className="px-2 py-1.5 text-[11px] text-muted-foreground">
            Console admin réservée aux administrateurs du tenant.
          </div>
        )}
        {canLogout && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={() => logout()}
              className="gap-2 p-2 text-muted-foreground"
            >
              <LogOut size={14} className="shrink-0" />
              <span className="text-sm">Se déconnecter</span>
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
