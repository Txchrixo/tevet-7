"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";

import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-mobile";
import { Zap } from "@/components/ui/feather-icons";

import { FALLBACK_QUESTIONS } from "@/lib/mock-data";
import { useCopilotStore } from "@/lib/store";
import { APP_NAME, APP_PHASE } from "@/lib/constants";

import { AdminConsole } from "@/components/producer-copilot/admin-console";
import { AuthScreen } from "@/components/producer-copilot/auth-screen";
import { ChatInput } from "@/components/producer-copilot/chat-input";
import { ChatMessage, TypingIndicator } from "@/components/producer-copilot/chat-message";
import { Footer } from "@/components/producer-copilot/footer";
import { Header } from "@/components/producer-copilot/header";
import { Inspector } from "@/components/producer-copilot/inspector";
import { OnboardingWizard } from "@/components/producer-copilot/onboarding-wizard";
import { Sidebar } from "@/components/producer-copilot/sidebar";
import { BrandMark } from "@/components/producer-copilot/brand-mark";
import { CreateWorkspace } from "@/components/producer-copilot/create-workspace";

export default function Home() {
  const adminView = useCopilotStore((s) => s.adminView);
  const authMode = useCopilotStore((s) => s.authMode);
  const bootstrap = useCopilotStore((s) => s.bootstrap);
  const tenants = useCopilotStore((s) => s.tenants);
  const activeTenant = useCopilotStore((s) => s.activeTenant);

  // Validate the stored JWT (if any) on first mount. Sets `authMode` to
  // "authenticated" / "anonymous" / "demo" depending on the outcome.
  React.useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  // While we're checking the stored JWT, render a minimal placeholder so the
  // AuthScreen doesn't flash before we know whether the user is logged in.
  // Uses pure CSS animation (no framer-motion) for instant render — the
  // loading state can be very brief (<100ms) and framer-motion's init delay
  // sometimes means the loader never even appears before the page swaps.
  if (authMode === "loading") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-background">
        <div
          className="animate-pulse"
          style={{ animationDuration: "1.5s" }}
        >
          <BrandMark size={48} />
        </div>
        <p className="mt-5 text-[11px] uppercase tracking-wide text-muted-foreground">
          {APP_NAME} · chargement
        </p>
      </div>
    );
  }

  // Anonymous → AuthScreen (no header / sidebar / inspector).
  if (authMode === "anonymous") {
    return <AuthScreen />;
  }

  // Authenticated but no tenants → CreateWorkspace (onboarding gate).
  if (authMode === "authenticated" && tenants.length === 0) {
    return <CreateWorkspace />;
  }

  // Authenticated with tenants but not onboarded → Onboarding Wizard.
  // The wizard handles connect-data → detect-schema → select-tables →
  // define-roles → complete. After `completeOnboarding()` the active
  // tenant's `onboarded` flag flips to true and the gate lets the user
  // through to the chat surface.
  if (
    authMode === "authenticated" &&
    tenants.length > 0 &&
    activeTenant &&
    !activeTenant.onboarded
  ) {
    return <OnboardingWizard tenantId={activeTenant.tenant_id} />;
  }

  // Admin / platform surfaces replace the chat layout entirely.
  if (adminView === "tenant") {
    return (
      <div className="flex min-h-screen flex-col bg-background">
        <AdminConsole mode="tenant" />
        <Footer />
      </div>
    );
  }
  if (adminView === "platform") {
    return (
      <div className="flex min-h-screen flex-col bg-background">
        <AdminConsole mode="platform" />
        <Footer />
      </div>
    );
  }

  return <CopilotHome />;
}

function CopilotHome() {
  const messages = useCopilotStore((s) => s.messages);
  const isStreaming = useCopilotStore((s) => s.isStreaming);
  const selectedMessageId = useCopilotStore((s) => s.selectedMessageId);
  const selectMessage = useCopilotStore((s) => s.selectMessage);
  const inspectorOpen = useCopilotStore((s) => s.inspectorOpen);
  const setInspectorOpen = useCopilotStore((s) => s.setInspectorOpen);
  const sendExample = useCopilotStore((s) => s.sendExample);

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

  return (
    <div className="flex h-screen flex-col bg-background">
      <Header
        onOpenSidebar={() => setSidebarSheet(true)}
        onOpenInspector={() => setInspectorSheet(true)}
      />

      <div className="flex min-h-0 flex-1">
        {/* Desktop sidebar */}
        <aside className="hidden w-[280px] shrink-0 border-r border-border bg-background md:block">
          <Sidebar />
        </aside>

        {/* Center: chat thread */}
        <main className="flex min-w-0 flex-1 flex-col">
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
                  {/* Phase A2: TypingIndicator removed — the streaming message
                      card now shows its own typing dots internally. */}
                </div>
              )}
            </div>
          </div>

          {/* Chat input docked at bottom of main */}
          <div className="border-t border-border bg-background px-3 py-3 sm:px-4">
            <ChatInput />
            <p className="mt-1.5 text-center text-[10px] uppercase tracking-wide text-muted-foreground">
              Prototype {APP_PHASE} — réponses de l&apos;agent Tevet-7
            </p>
          </div>
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

      {/*
        Mobile sidebar sheet — `gap-0` overrides the SheetContent default
        `gap-4` (which would leave a 16px gap above the Sidebar and push its
        bottom past the sheet viewport, breaking internal scroll). The
        Sidebar renders its own user panel + ScrollArea; we don't add a
        close button here because the Sheet already injects one at top-right
        and the Sidebar's user panel must NOT carry one (per design-system
        rule: only one close affordance per surface).
      */}
      <Sheet open={sidebarSheet} onOpenChange={setSidebarSheet}>
        <SheetContent side="left" className="w-[300px] gap-0 p-0" hideClose>
          <SheetTitle className="sr-only">Menu</SheetTitle>
          <Sidebar onNavigate={() => setSidebarSheet(false)} />
        </SheetContent>
      </Sheet>

      {/*
        Mobile inspector sheet — `hideClose` suppresses the Sheet's auto-X
        because the Inspector renders its own close button (X) in its header
        (top-right). Keeping both would create the duplicate close buttons
        the user reported. `gap-0` ensures the Inspector fills the sheet
        height (otherwise the default `gap-4` would offset it).
      */}
      <Sheet open={inspectorSheet} onOpenChange={setInspectorSheet}>
        <SheetContent
          side="right"
          className="w-full gap-0 p-0 sm:max-w-md"
          hideClose
        >
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
  const user = useCopilotStore((s) => s.user);
  const demoOverride = useCopilotStore((s) => s.demoIdentityOverride);
  const isDemoSession = useCopilotStore((s) => s.isDemoSession);
  const logout = useCopilotStore((s) => s.logout);

  // When a demo identity override is active, use the override's name (not the
  // authenticated user's name) so the welcome state reflects the switch.
  const greetingName = (demoOverride ?? identity).name.split(" ")[0];

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="mx-auto max-w-2xl py-6"
    >
      <div className="flex flex-col items-center text-center">
        <h1 className="text-2xl sm:text-3xl">
          Bonjour {greetingName}
        </h1>
        <p className="mt-1.5 max-w-md text-sm text-muted-foreground">
          <span className="font-medium text-foreground">Tevet-7</span> · Je suis
          votre agent. Posez-moi une question sur vos données — chaque réponse
          est sécurisée par un scope tenant.
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
        {FALLBACK_QUESTIONS.map((q) => (
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

      {/* CTA for demo users to create their own tenant */}
      {isDemoSession && (
        <div className="mt-6 flex flex-col items-center gap-2 rounded-md border border-dashed border-border bg-secondary/20 p-4 text-center">
          <p className="text-sm text-foreground">
            Vous explorez la démo publique Tevet-7.
          </p>
          <p className="text-xs text-muted-foreground">
            Créez votre propre workspace pour connecter vos données et
            configurer votre agent.
          </p>
          <button
            type="button"
            onClick={() => logout()}
            className="mt-1 rounded-md bg-primary px-4 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            Créer mon propre tenant →
          </button>
        </div>
      )}
    </motion.div>
  );
}
