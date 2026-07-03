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
import { cn } from "@/lib/utils";
import { IDENTITIES } from "@/lib/mock-data";
import { useCopilotStore } from "@/lib/store";
import { Check, ChevronDown, Shield, User } from "@/components/ui/feather-icons";

export function IdentitySwitcher() {
  const identity = useCopilotStore((s) => s.identity);
  const setIdentity = useCopilotStore((s) => s.setIdentity);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center justify-between gap-2 rounded-md border border-border bg-background px-2.5 py-2 text-left transition-colors hover:border-accent/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <div className="flex min-w-0 items-center gap-2">
            <span
              className={cn(
                "flex size-8 shrink-0 items-center justify-center rounded-full border",
                identity.kind === "admin"
                  ? "border-border bg-secondary text-foreground"
                  : "border-border bg-primary text-primary-foreground",
              )}
            >
              <span className="font-heading text-[11px] font-medium">
                {identity.initials}
              </span>
            </span>
            <div className="min-w-0">
              <div className="truncate text-sm font-medium leading-tight text-foreground">
                {identity.name}
              </div>
              <div className="truncate text-[11px] leading-tight text-muted-foreground">
                {identity.kind === "admin" ? (
                  <span className="inline-flex items-center gap-1">
                    <Shield size={10} /> {identity.role}
                  </span>
                ) : (
                  <span>
                    {identity.role}{" "}
                    <span className="font-heading text-muted-foreground">
                      {identity.producerNumber}
                    </span>{" "}
                    · {identity.farmName}
                  </span>
                )}
              </div>
            </div>
          </div>
          <ChevronDown
            size={16}
            className="shrink-0 text-muted-foreground"
          />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-[260px]">
        <DropdownMenuLabel className="text-[11px] font-body uppercase tracking-wide text-muted-foreground">
          Changer d&apos;identité
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {IDENTITIES.map((id) => {
          const active = id.id === identity.id;
          return (
            <DropdownMenuItem
              key={id.id}
              onSelect={() => !active && setIdentity(id.id)}
              className="gap-2 p-2"
            >
              <span
                className={cn(
                  "flex size-7 shrink-0 items-center justify-center rounded-full border",
                  id.kind === "admin"
                    ? "border-border bg-secondary text-foreground"
                    : "border-border bg-primary text-primary-foreground",
                )}
              >
                <span className="font-heading text-[10px] font-medium">
                  {id.initials}
                </span>
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-sm font-medium text-foreground">
                    {id.name}
                  </span>
                  {id.kind === "admin" ? (
                    <Shield size={12} className="shrink-0 text-muted-foreground" />
                  ) : (
                    <User size={12} className="shrink-0 text-muted-foreground" />
                  )}
                </div>
                <div className="truncate text-[11px] text-muted-foreground">
                  {id.kind === "admin" ? (
                    id.role
                  ) : (
                    <span>
                      {id.role}{" "}
                      <span className="font-heading">{id.producerNumber}</span> ·{" "}
                      {id.farmName}
                    </span>
                  )}
                </div>
              </div>
              {active && (
                <Check size={14} className="shrink-0 text-accent" />
              )}
            </DropdownMenuItem>
          );
        })}
        <DropdownMenuSeparator />
        <div className="px-2 py-1.5">
          <span className="inline-flex items-center rounded-md border border-border px-2 py-0.5 text-[10px] font-body uppercase tracking-wide text-muted-foreground">
            Tenant · Drive Producteur
          </span>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
