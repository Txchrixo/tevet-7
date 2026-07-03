"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { EXAMPLE_QUESTIONS, SEED_HISTORY } from "@/lib/mock-data";
import { useCopilotStore } from "@/lib/store";
import {
  Hash,
  MessageSquare,
  Plus,
  RefreshCw,
  ShieldOff,
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

  return (
    <div className="flex h-full flex-col">
      <div className="p-3">
        <IdentitySwitcher />
      </div>

      <ScrollArea className="flex-1">
        <div className="space-y-5 px-3 pb-4">
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

          <Separator />

          {/* Example questions */}
          <section>
            <SectionLabel>Exemples</SectionLabel>
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
                      "group w-full rounded-md border bg-background px-2.5 py-2 text-left text-xs transition-colors hover:border-accent/60 hover:bg-secondary/40 disabled:cursor-not-allowed disabled:opacity-50",
                      disabledForProducer && "border-dashed",
                    )}
                  >
                    <div className="flex items-start gap-1.5">
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
                    </div>
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

          <Separator />

          {/* Conversation history (cosmetic, ledger-numbered) */}
          <section>
            <SectionLabel>Historique</SectionLabel>
            <div className="mt-2 space-y-1">
              {SEED_HISTORY.map((h, idx) => {
                const isOtherIdentity = h.identityId !== identity.id;
                const num = String(idx + 1).padStart(2, "0");
                return (
                  <button
                    key={h.id}
                    type="button"
                    className={cn(
                      "flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-secondary/40",
                      isOtherIdentity && "opacity-60",
                    )}
                  >
                    <span className="mt-0.5 shrink-0 font-heading text-[11px] text-accent tabular-nums">
                      {num}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-xs font-medium text-foreground">
                        {h.title}
                      </span>
                      <span className="block truncate text-[10px] text-muted-foreground">
                        {h.preview}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        </div>
      </ScrollArea>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 text-[11px] font-body font-medium uppercase tracking-wide text-muted-foreground">
      <MessageSquare size={12} className="text-muted-foreground" />
      {children}
    </div>
  );
}
