"use client";

import * as React from "react";
import { motion } from "framer-motion";

import { cn } from "@/lib/utils";
import { useCopilotStore } from "@/lib/store";
import { ArrowRight, Lock, Mail, User, Zap } from "@/components/ui/feather-icons";

import { BrandMark } from "./brand-mark";
import { APP_PHASE } from "@/lib/constants";

/**
 * Tevet-7 authentication screen.
 *
 * Two paths:
 *   1. Real backend login (email + password) → calls `POST /api/auth/login`
 *      via the Next.js proxy, stores the JWT, loads `/api/auth/me` +
 *      `/api/tenants/mine`, switches to the chat with real backend data.
 *   2. "Essayer la démo" → calls `login("marie@tevet7.dev", "tevet7demo")`
 *      and falls back to `enterDemoMode()` if the backend is unreachable
 *      (toast: "Mode démo (backend hors ligne)").
 *
 * Renders the Tevet-7 design system: dark green background, Caudex headings,
 * Manrope body, Feather icons, no indigo/blue, no lucide-react.
 */
export function AuthScreen() {
  const login = useCopilotStore((s) => s.login);
  const signup = useCopilotStore((s) => s.signup);
  const tryDemoLogin = useCopilotStore((s) => s.tryDemoLogin);
  const enterDemoMode = useCopilotStore((s) => s.enterDemoMode);
  const authLoading = useCopilotStore((s) => s.authLoading);

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [name, setName] = React.useState("");
  const [isSignup, setIsSignup] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (authLoading) return;
    setError(null);
    if (!email.trim() || !password) {
      setError("Email et mot de passe requis.");
      return;
    }
    if (isSignup && !name.trim()) {
      setError("Nom requis pour l'inscription.");
      return;
    }
    const result = isSignup
      ? await signup(email.trim(), password, name.trim())
      : await login(email.trim(), password);
    if (!result.ok) setError(result.error);
  };

  const handleDemo = async () => {
    if (authLoading) return;
    setError(null);
    await tryDemoLogin();
  };

  const handleMockDemo = () => {
    setError(null);
    enterDemoMode();
  };

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: "easeOut" }}
          className="w-full max-w-md"
        >
          {/* Brand + heading */}
          <div className="flex flex-col items-center text-center">
            <div className="flex size-16 items-center justify-center rounded-md border border-border bg-background text-accent">
              <BrandMark size={36} />
            </div>
            <h1 className="mt-5 font-heading text-3xl tracking-tight text-foreground">
              Tevet-7
            </h1>
            <p className="mt-2 max-w-sm font-body text-sm leading-relaxed text-muted-foreground">
              Plateforme d&apos;agents IA configurable. Connectez-vous pour
              accéder à votre agent — chaque question est sécurisée par un
              scope tenant.
            </p>
          </div>

          {/* Login form */}
          <form
            onSubmit={handleSubmit}
            className="mt-7 space-y-3 rounded-md border border-border bg-background p-5"
          >
            {isSignup && (
              <Field
                label="Nom"
                icon={<User size={14} className="text-muted-foreground" />}
              >
                <input
                  type="text"
                  autoComplete="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Jean Dupont"
                  className="w-full bg-transparent px-2 py-2 font-body text-sm text-foreground outline-none placeholder:text-muted-foreground"
                />
              </Field>
            )}
            <Field
              label="Email"
              icon={<Mail size={14} className="text-muted-foreground" />}
            >
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="marie@tevet7.dev"
                className="w-full bg-transparent px-2 py-2 font-body text-sm text-foreground outline-none placeholder:text-muted-foreground"
              />
            </Field>
            <Field
              label="Mot de passe"
              icon={<Lock size={14} className="text-muted-foreground" />}
            >
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full bg-transparent px-2 py-2 font-body text-sm text-foreground outline-none placeholder:text-muted-foreground"
              />
            </Field>

            {error && (
              <div
                role="alert"
                className="rounded-md border border-dashed border-border bg-secondary/40 px-3 py-2 text-xs text-muted-foreground"
              >
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={authLoading}
              className={cn(
                "flex w-full items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5 font-body text-sm font-medium text-primary-foreground transition-colors",
                "hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50",
              )}
            >
              {authLoading ? "Connexion…" : isSignup ? "Créer mon compte" : "Se connecter"}
              {!authLoading && <ArrowRight size={15} />}
            </button>
          </form>

          {/* Toggle login / signup */}
          <button
            type="button"
            onClick={() => { setError(null); setIsSignup(!isSignup); }}
            className="mt-3 w-full text-center text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            {isSignup
              ? "Déjà un compte ? Se connecter"
              : "Pas de compte ? Créer un compte"}
          </button>
          <div className="mt-3 space-y-2">
            <button
              type="button"
              onClick={handleDemo}
              disabled={authLoading}
              className={cn(
                "flex w-full items-center justify-center gap-2 rounded-md border border-border bg-background px-4 py-2.5 font-body text-sm text-foreground transition-colors",
                "hover:border-accent/50 hover:bg-secondary/30 disabled:cursor-not-allowed disabled:opacity-50",
              )}
            >
              <Zap size={14} className="text-accent" />
              {authLoading ? "Connexion…" : "Essayer la démo"}
            </button>
            <p className="text-center text-[11px] uppercase tracking-wide text-muted-foreground">
              Marie Dubois · producer #42 · tenant Drive Producteur
            </p>
          </div>

          {/* Skip to mock demo */}
          <div className="mt-6 text-center">
            <button
              type="button"
              onClick={handleMockDemo}
              disabled={authLoading}
              className="text-[11px] uppercase tracking-wide text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline disabled:cursor-not-allowed disabled:opacity-50"
            >
              Continuer sans backend (mock data)
            </button>
          </div>
        </motion.div>
      </main>

      <Footer />
    </div>
  );
}

function Field({
  label,
  icon,
  children,
}: {
  label: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-body uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <div className="flex items-center gap-2 rounded-md border border-border bg-background px-2.5 transition-colors focus-within:border-accent/50 focus-within:ring-1 focus-within:ring-ring">
        <span className="shrink-0">{icon}</span>
        {children}
      </div>
    </label>
  );
}

function Footer() {
  return (
    <footer className="mt-auto border-t border-border bg-background">
      <div className="flex h-9 items-center justify-between gap-2 px-3 text-[11px] text-muted-foreground sm:px-4">
        <span className="truncate font-body uppercase tracking-wide">
          Tevet-7 <span className="text-muted-foreground/50">·</span> Plateforme
          d&apos;agents IA
        </span>
        <span className="hidden truncate text-center font-body uppercase tracking-wide sm:inline">
          Premier tenant : Drive Producteur
        </span>
        <span className="shrink-0 font-body uppercase tracking-wide">
          {APP_PHASE}
        </span>
      </div>
    </footer>
  );
}
