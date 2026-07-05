"use client";

import * as React from "react";
import { motion } from "framer-motion";

import { cn } from "@/lib/utils";
import type { ChatMessage as ChatMessageT } from "@/lib/types";
import {
  Check,
  Clock,
  Database,
  ShieldOff,
  User,
} from "@/components/ui/feather-icons";

import { ChartDisplay } from "./chart-display";
import { Markdown } from "./markdown";
import { SqlBlock } from "./sql-block";
import { BrandMark } from "./brand-mark";

interface ChatMessageProps {
  message: ChatMessageT;
  selected: boolean;
  onSelect: (id: string) => void;
  isLast: boolean;
}

export function ChatMessage({ message, selected, onSelect, isLast }: ChatMessageProps) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.22, ease: "easeOut" }}
        className="flex justify-end"
      >
        <div className="flex max-w-[85%] items-start gap-2.5 sm:max-w-[75%]">
          <div className="rounded-md bg-secondary px-3.5 py-2.5 text-sm text-foreground">
            <p className="whitespace-pre-wrap break-words font-body">
              {message.content}
            </p>
          </div>
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full border border-border bg-secondary text-muted-foreground">
            <User size={16} />
          </span>
        </div>
      </motion.div>
    );
  }

  const response = message.response;
  const isStreaming = message.streaming;
  const totalTokens = response ? response.tokensIn + response.tokensOut : 0;
  const latencyS = response
    ? (response.latencyMs / 1000)
        .toFixed(1)
        .replace(".", ",")
        .replace(/\s/g, "\u00A0")
    : "—";
  const tokensDisplay = totalTokens.toLocaleString("fr-FR").replace(/\s/g, "\u00A0");

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: "easeOut" }}
      className="flex justify-start"
    >
      <div className="flex max-w-[92%] items-start gap-2.5 sm:max-w-[85%]">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-background text-accent">
          <BrandMark size={18} />
        </span>

        <div className="min-w-0 flex-1">
          <div
            role="button"
            tabIndex={0}
            onClick={() => onSelect(message.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(message.id);
              }
            }}
            className={cn(
              "group cursor-pointer rounded-lg border bg-background p-4 transition-colors",
              response?.refused
                ? "border-dashed border-border"
                : "border-border",
              selected
                ? "border-accent/60 ring-1 ring-accent/30"
                : "hover:border-accent/40",
            )}
          >
            {response?.refused && (
              <div className="mb-3 flex items-center gap-2 border-b border-dashed border-border pb-2 text-sm text-muted-foreground">
                <ShieldOff size={14} className="shrink-0" />
                <span className="font-body font-medium">Action refusée</span>
              </div>
            )}

            {/* While streaming with no content yet, show typing dots inside the card */}
            {isStreaming && !message.content ? (
              <div className="flex items-center gap-1.5 py-1">
                <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:0ms]" />
                <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:150ms]" />
                <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:300ms]" />
              </div>
            ) : (
              <Markdown content={message.content} />
            )}

            {response?.refused ? null : (
              !isStreaming && response?.sql && (
                <div className="mt-3">
                  <SqlBlock
                    sql={response.sql}
                    scopeClause={response.scopeClause}
                    defaultOpen={isLast}
                  />
                </div>
              )
            )}

            {response?.chart && !response.refused && !isStreaming && (
              <div className="mt-3">
                <ChartDisplay spec={response.chart} />
              </div>
            )}

            {/* Footer line — hidden while streaming (Phase A2) */}
            {!isStreaming && (
            <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-2 text-[11px] uppercase tracking-wide text-muted-foreground">
              {response?.refused ? (
                <span className="inline-flex items-center gap-1 text-muted-foreground">
                  <ShieldOff size={12} />
                  Action refusée
                  <span className="text-muted-foreground/50">·</span>
                  scoping violation
                </span>
              ) : (
                <span className="inline-flex items-center gap-1">
                  <Check size={12} className="text-accent" />
                  Scope vérifié
                </span>
              )}
              <span className="inline-flex items-center gap-1">
                <span className="font-heading text-foreground tabular-nums">
                  {tokensDisplay}
                </span>
                tokens
              </span>
              <span className="inline-flex items-center gap-1">
                <Clock size={12} />
                <span className="font-heading text-foreground tabular-nums">
                  {latencyS}
                </span>
                s
              </span>
              {response && response.toolCalls.length > 0 && (
                <span className="inline-flex items-center gap-1 rounded-md border border-border bg-secondary px-1.5 py-0 text-[10px] text-muted-foreground">
                  <Database size={10} />
                  {response.toolCalls[0]}
                </span>
              )}
              <span className="ml-auto hidden text-[10px] text-muted-foreground/70 sm:inline">
                cliquez pour voir la trace →
              </span>
            </div>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
}

/** Three bouncing dots shown while the assistant "thinks". */
export function TypingIndicator() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex justify-start"
    >
      <div className="flex items-start gap-2.5">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-background text-accent">
          <BrandMark size={18} />
        </span>
        <div className="rounded-lg border border-border bg-background px-4 py-3">
          <div className="flex items-center gap-1">
            {[0, 1, 2].map((i) => (
              <motion.span
                key={i}
                className="size-2 rounded-full bg-muted-foreground"
                animate={{ y: [0, -4, 0], opacity: [0.4, 1, 0.4] }}
                transition={{
                  duration: 0.9,
                  repeat: Infinity,
                  delay: i * 0.15,
                  ease: "easeInOut",
                }}
              />
            ))}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
