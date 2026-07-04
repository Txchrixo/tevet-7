"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";

import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-mobile";
import { Zap } from "@/components/ui/feather-icons";

import { EXAMPLE_QUESTIONS } from "@/lib/mock-data";
import { useCopilotStore } from "@/lib/store";

import { ChatInput } from "@/components/producer-copilot/chat-input";
import { ChatMessage, TypingIndicator } from "@/components/producer-copilot/chat-message";
import { Footer } from "@/components/producer-copilot/footer";
import { Header } from "@/components/producer-copilot/header";
import { Inspector } from "@/components/producer-copilot/inspector";
import { OpsConsole } from "@/components/producer-copilot/ops-console";
import { Sidebar } from "@/components/producer-copilot/sidebar";
import { BrandMark } from "@/components/producer-copilot/brand-mark";

export default function Home() {
  const messages = useCopilotStore((s) => s.messages);
  const isStreaming = useCopilotStore((s) => s.isStreaming);
  const selectedMessageId = useCopilotStore((s) => s.selectedMessageId);
  const selectMessage = useCopilotStore((s) => s.selectMessage);
  const inspectorOpen = useCopilotStore((s) => s.inspectorOpen);
  const setInspectorOpen = useCopilotStore((s) => s.setInspectorOpen);
  const sendExample = useCopilotStore((s) => s.sendExample);
  const identity = useCopilotStore((s) => s.identity);
  const loadDocuments = useCopilotStore((s) => s.loadDocuments);
  const view = useCopilotStore((s) => s.view);

  const [sidebarSheet, setSidebarSheet] = React.useState(false);
  const [inspectorSheet, setInspectorSheet] = React.useState(false);
  const isMobile = useIsMobile();

  const selectedMessage = React.useMemo(
    () => messages.find((m) => m.id === selectedMessageId) ?? null,
    [messages, selectedMessageId],
  );

  const scrollRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, isStreaming]);

  // Load the RAG document corpus on mount AND whenever the identity changes
  // (producers are scoped by `producer_id`, admin sees everything). The store
  // also re-fetches inside `setIdentity`, but this effect is the source of
  // truth — it guarantees the panel is populated even on a hard refresh with
  // the default identity, and survives any future change to the store.
  React.useEffect(() => {
    void loadDocuments();
  }, [identity.id, loadDocuments]);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <Header
        onOpenSidebar={() => setSidebarSheet(true)}
        onOpenInspector={() => setInspectorSheet(true)}
      />

      <div className="flex min-h-0 flex-1">
        {/* Desktop sidebar */}
        <aside className="hidden w-[280px] shrink-0 border-r border-border bg-background md:block">
          <Sidebar />
        </aside>

        {/* Center: chat thread OR Ops Console (admin only) */}
        <main className="flex min-w-0 flex-1 flex-col">
          {identity.kind === "admin" && view === "ops" ? (
            <OpsConsole />
          ) : (
            <>
              <div ref={scrollRef} className="flex-1 overflow-y-auto">
                <div className="mx-auto w-full max-w-3xl px-3 py-5 sm:px-4">
                  {messages.length === 0 ? (
                    <WelcomeState
                      onPick={(id, label) => sendExample(id, label)}
                    />
                  ) : (
                    <div className="space-y-5">
                      <AnimatePresence initial={false}>
                        {messages.map((m, i) => (
                          <ChatMessage
                            key={m.id}
                            message={m}
                            selected={m.id === selectedMessageId}
                            onSelect={(id) => {
                              selectMessage(id);
                              if (isMobile) setInspectorSheet(true);
                            }}
                            isLast={i === messages.length - 1 && m.role === "assistant"}
                          />
                        ))}
                      </AnimatePresence>
                      {isStreaming && <TypingIndicator />}
                    </div>
                  )}
                </div>
              </div>

              {/* Chat input docked at bottom of main */}
              <div className="border-t border-border bg-background px-3 py-3 sm:px-4">
                <ChatInput />
                <p className="mt-1.5 text-center text-[10px] uppercase tracking-wide text-muted-foreground">
                  Prototype Phase 0 — réponses simulées
                </p>
              </div>
            </>
          )}
        </main>

        {/* Desktop inspector */}
        <AnimatePresence initial={false}>
          {inspectorOpen && (
            <motion.aside
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 336, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.25, ease: "easeInOut" }}
              className="hidden shrink-0 overflow-hidden border-l border-border bg-background md:block"
            >
              <div className="h-full w-[336px]">
                <Inspector
                  message={selectedMessage}
                  onClose={() => {
                    setInspectorOpen(false);
                    selectMessage(null);
                  }}
                />
              </div>
            </motion.aside>
          )}
        </AnimatePresence>
      </div>

      <Footer />

      {/* Mobile sidebar sheet */}
      <Sheet open={sidebarSheet} onOpenChange={setSidebarSheet}>
        <SheetContent side="left" className="w-[300px] p-0">
          <SheetTitle className="sr-only">Menu</SheetTitle>
          <Sidebar onNavigate={() => setSidebarSheet(false)} />
        </SheetContent>
      </Sheet>

      {/* Mobile inspector sheet */}
      <Sheet open={inspectorSheet} onOpenChange={setInspectorSheet}>
        <SheetContent side="right" className="w-full p-0 sm:max-w-md">
          <SheetTitle className="sr-only">Trace de l&apos;agent</SheetTitle>
          <Inspector
            message={selectedMessage}
            onClose={() => setInspectorSheet(false)}
          />
        </SheetContent>
      </Sheet>
    </div>
  );
}

function WelcomeState({
  onPick,
}: {
  onPick: (questionId: string, label: string) => void;
}) {
  const identity = useCopilotStore((s) => s.identity);
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="mx-auto max-w-2xl py-6"
    >
      <div className="flex flex-col items-center text-center">
        <div className="flex size-14 items-center justify-center rounded-md border border-border bg-background text-accent">
          <BrandMark size={32} />
        </div>
        <h1 className="mt-4 text-2xl sm:text-3xl">
          Bonjour {identity.name.split(" ")[0]}
        </h1>
        <p className="mt-1.5 max-w-md text-sm text-muted-foreground">
          <span className="font-medium text-foreground">Tevet-7</span> · Producer
          Copilot. Posez-moi une question sur vos ventes, votre stock ou vos
          revenus — chaque réponse est sécurisée par un scope{" "}
          <code className="rounded bg-secondary px-1 py-0.5 font-mono text-[0.85em] text-accent">
            producer_id
          </code>
          .
        </p>
        <div className="mt-3 flex flex-wrap items-center justify-center gap-1.5">
          <span className="inline-flex items-center rounded-md border border-accent/30 bg-accent/5 px-2 py-0.5 text-[11px] uppercase tracking-wide text-accent">
            {identity.kind === "admin"
              ? "Accès admin (full tenant)"
              : `Scope : producer_id = ${identity.producerId}`}
          </span>
          <Badge
            variant="outline"
            className="gap-1 border-border text-[11px] uppercase tracking-wide text-muted-foreground"
          >
            <Zap size={12} className="text-muted-foreground" />
            sql_read_tool
          </Badge>
        </div>
      </div>

      <div className="mt-7 grid gap-2 sm:grid-cols-2">
        {EXAMPLE_QUESTIONS.map((q) => (
          <button
            key={q.id}
            type="button"
            onClick={() => onPick(q.id, q.label)}
            className="group rounded-md border border-border bg-background p-3 text-left transition-colors hover:border-accent/60 hover:bg-secondary/30"
          >
            <div className="flex items-start gap-2">
              <span className="mt-0.5 shrink-0 font-heading text-sm text-accent">
                ›
              </span>
              <span className="font-body text-sm text-foreground">{q.label}</span>
            </div>
          </button>
        ))}
      </div>

      <p className="mt-6 text-center text-[11px] uppercase tracking-wide text-muted-foreground">
        Astuce · essayez « Quels producteurs ont le plus de commandes ? » en
        producteur, puis basculez en Admin pour voir la différence de scope.
      </p>
    </motion.div>
  );
}
