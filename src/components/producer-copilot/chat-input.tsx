"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import { useCopilotStore } from "@/lib/store";
import { ArrowUp } from "@/components/ui/feather-icons";

export function ChatInput() {
  const sendMessage = useCopilotStore((s) => s.sendMessage);
  const isStreaming = useCopilotStore((s) => s.isStreaming);
  const [value, setValue] = React.useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!value.trim() || isStreaming) return;
    sendMessage(value);
    setValue("");
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="mx-auto flex w-full max-w-3xl items-end gap-2 rounded-md border border-border bg-background p-2 transition-colors focus-within:border-accent/50 focus-within:ring-1 focus-within:ring-ring"
    >
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSubmit(e);
          }
        }}
        rows={1}
        placeholder="Posez votre question à l'agent Tevet-7…"
        className="max-h-40 min-h-[40px] flex-1 resize-none bg-transparent px-2 py-2 font-body text-sm text-foreground outline-none placeholder:text-muted-foreground"
      />
      <button
        type="submit"
        disabled={!value.trim() || isStreaming}
        aria-label={isStreaming ? "Génération en cours" : "Envoyer"}
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded-md bg-primary text-foreground transition-colors",
          "hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-40",
        )}
      >
        <ArrowUp size={18} />
      </button>
    </form>
  );
}
