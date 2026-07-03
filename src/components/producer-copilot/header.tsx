"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Eye, Menu, Settings } from "@/components/ui/feather-icons";
import { useCopilotStore } from "@/lib/store";

import { BrandLogo } from "./brand-mark";

interface HeaderProps {
  onOpenSidebar: () => void;
  onOpenInspector: () => void;
}

export function Header({ onOpenSidebar, onOpenInspector }: HeaderProps) {
  const identity = useCopilotStore((s) => s.identity);
  const messages = useCopilotStore((s) => s.messages);
  const inspectorOpen = useCopilotStore((s) => s.inspectorOpen);
  const toggleInspector = useCopilotStore((s) => s.toggleInspector);

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

      {/* Scope breadcrumb (hidden on small) */}
      <div className="ml-2 hidden items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted-foreground lg:flex">
        <Separator orientation="vertical" className="h-4" />
        <span>Tenant</span>
        <span className="text-muted-foreground/50">/</span>
        <span className="font-medium text-foreground">Drive Producteur</span>
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
          Phase 0
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
      </div>
    </header>
  );
}
