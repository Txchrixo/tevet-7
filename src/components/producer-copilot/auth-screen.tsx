"use client";

import * as React from "react";
import { motion } from "framer-motion";

import { cn } from "@/lib/utils";
import { ArrowRight, Lock, Mail, User, Zap } from "@/components/ui/feather-icons";

import { BrandMark } from "./brand-mark";
import { useCopilotStore } from "@/lib/store";
import { IdentityPicker } from "./identity-picker";

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

const AUTH_T = {
  en: {
    subtitle: "Configurable AI agent platform. Sign in to access your agent - every question is secured by tenant scoping.",
    name: "Name", namePlaceholder: "John Doe",
    email: "Email", password: "Password",
    signin: "Sign in", signup: "Create account", loading: "Loading...",
    hasAccount: "Already have an account? Sign in",
    noAccount: "No account? Create one",
    demo: "Try demo", demoLoading: "Loading...",
  },
  fr: {
    subtitle: "Plateforme d'agents IA configurable. Connectez-vous pour acceder a votre agent - chaque question est securisee par un scope tenant.",
    name: "Nom", namePlaceholder: "Jean Dupont",
    email: "Email", password: "Mot de passe",
    signin: "Se connecter", signup: "Creer mon compte", loading: "Connexion...",
    hasAccount: "Deja un compte ? Se connecter",
    noAccount: "Pas de compte ? Creer un compte",
    demo: "Essayer la demo", demoLoading: "Connexion...",
  },
};

interface AuthScreenProps {
  /**
   * Which form to show first when the screen opens. Defaults to "login".
   * The landing page passes "signup" when the user clicks "Try free" /
   * "Get started free", and "login" when they click "Log in".
   */
  initialMode?: "login" | "signup";
}

export function AuthScreen({ initialMode = "login" }: AuthScreenProps = {}) {
  const showIdentityPicker = useCopilotStore((s) => s.showIdentityPicker);
  const setShowIdentityPicker = useCopilotStore((s) => s.setShowIdentityPicker);

  // Phase 6d: identity picker - the user chooses their demo role BEFORE
  // entering the product, not after. Better UX, sets expectations.
  if (showIdentityPicker) {
    return <IdentityPicker onBack={() => setShowIdentityPicker(false)} />;
  }

  return <AuthForm initialMode={initialMode} />;
}

function AuthForm({ initialMode }: { initialMode: "login" | "signup" }) {
  const login = useCopilotStore((s) => s.login);
  const signup = useCopilotStore((s) => s.signup);
  const authLoading = useCopilotStore((s) => s.authLoading);
  const setShowIdentityPicker = useCopilotStore((s) => s.setShowIdentityPicker);

  const lang = useCopilotStore((s) => s.lang);
  const t = AUTH_T[lang];
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [name, setName] = React.useState("");
  const [isSignup, setIsSignup] = React.useState(initialMode === "signup");
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

  const handleDemo = () => {
    if (authLoading) return;
    setError(null);
    setShowIdentityPicker(true);
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
              accéder à votre agent - chaque question est sécurisée par un
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
                label={t.name}
                icon={<User size={14} className="text-muted-foreground" />}
              >
                <input
                  type="text"
                  autoComplete="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t.namePlaceholder}
                  className="w-full bg-transparent px-2 py-2 font-body text-sm text-foreground outline-none placeholder:text-muted-foreground"
                />
              </Field>
            )}
            <Field
              label={t.email}
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
              label={t.password}
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
                "flex w-full items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5 font-body text-sm font-medium text-foreground transition-colors",
                "hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50",
              )}
            >
              {authLoading ? t.loading : isSignup ? t.signup : t.signin}
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
              ? t.hasAccount
              : t.noAccount}
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
              {authLoading ? t.demoLoading : t.demo}
            </button>
            <p className="text-center text-[11px] uppercase tracking-wide text-muted-foreground">
              Marie Dubois · producer #42 · tenant Drive Producteur
            </p>
          </div>

        </motion.div>
      </main>
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
