"use client";

import * as React from "react";
import { motion } from "framer-motion";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  AlertCircle,
  Lock,
  LogIn,
  Mail,
  User,
  Zap,
} from "@/components/ui/feather-icons";
import { useCopilotStore } from "@/lib/store";
import { BrandLogo, BrandMark } from "./brand-mark";

/**
 * Full-screen auth gate.
 *
 * Shown by `src/app/page.tsx` when the user is NOT authenticated and has not
 * yet entered demo mode. Two modes:
 *   - Login  → email + password (POST /api/auth/login)
 *   - Signup → name + email + password (POST /api/auth/signup)
 *
 * A prominent "Essayer la démo" button tries the real auth path
 * (login as marie@tevet7.dev / tevet7demo) and falls back to mock identities
 * if the backend is unreachable — the prototype must remain demoable even
 * when the FastAPI service is offline.
 */

type Mode = "login" | "signup";

const DEMO_EMAIL = "marie@tevet7.dev";
const DEMO_PASSWORD = "tevet7demo";

export function AuthScreen() {
  const login = useCopilotStore((s) => s.login);
  const signup = useCopilotStore((s) => s.signup);
  const enterDemoMode = useCopilotStore((s) => s.enterDemoMode);
  const authLoading = useCopilotStore((s) => s.authLoading);
  const authError = useCopilotStore((s) => s.authError);
  const clearAuthError = useCopilotStore((s) => s.clearAuthError);

  const [mode, setMode] = React.useState<Mode>("login");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [name, setName] = React.useState("");
  const [demoInFlight, setDemoInFlight] = React.useState(false);
  const [demoFallbackNote, setDemoFallbackNote] = React.useState(false);

  // Reset the error when switching modes.
  React.useEffect(() => {
    clearAuthError();
    setDemoFallbackNote(false);
  }, [mode, clearAuthError]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (authLoading) return;
    setDemoFallbackNote(false);
    try {
      if (mode === "login") {
        await login(email.trim(), password);
      } else {
        await signup(email.trim(), password, name.trim() || email.trim());
      }
    } catch {
      // The error is already in `authError` (set by the store) — surfaced
      // in the form's alert block. No additional handling needed here.
    }
  };

  const handleDemo = async () => {
    if (authLoading || demoInFlight) return;
    setDemoFallbackNote(false);
    setDemoInFlight(true);
    try {
      // Try the real auth path first — Marie is seeded in the backend as a
      // demo producer (#42, Ferme du Vallon). When the backend's auth API
      // is wired up, this succeeds and we proceed through the JWT path.
      await login(DEMO_EMAIL, DEMO_PASSWORD);
    } catch {
      // The demo button should NEVER block the user. If the backend auth
      // API isn't ready yet (404 — endpoint missing, 502 — proxy can't
      // reach the backend, network error, or even 401 — seeded user not
      // present), fall back to the mock identities so the demo still
      // works. The "Mode démo (backend hors ligne)" note is surfaced.
      setDemoFallbackNote(true);
      enterDemoMode();
    } finally {
      setDemoInFlight(false);
    }
  };

  const busy = authLoading || demoInFlight;

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-background px-4 py-10">
      {/* Subtle background brand mark */}
      <div
        className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-[0.04]"
        aria-hidden
      >
        <BrandMark size={Math.min(640, typeof window !== "undefined" ? window.innerWidth * 0.8 : 480)} />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: "easeOut" }}
        className="relative z-10 w-full max-w-[420px]"
      >
        {/* Brand header */}
        <div className="flex flex-col items-center text-center">
          <div className="flex size-14 items-center justify-center rounded-md border border-border bg-background text-accent">
            <BrandMark size={32} />
          </div>
          <div className="mt-4">
            <BrandLogo size={26} />
          </div>
          <h1 className="mt-4 text-2xl">Producer Copilot</h1>
          <p className="mt-1.5 max-w-xs text-sm text-muted-foreground">
            Connectez-vous pour accéder à votre copilot Drive Producteur.
            Chaque question est sécurisée par un scope producteur.
          </p>
        </div>

        {/* Card */}
        <div className="mt-6 rounded-md border border-border bg-background p-5 shadow-sm sm:p-6">
          {/* Mode toggle */}
          <div
            role="tablist"
            aria-label="Mode d'authentification"
            className="mb-5 grid grid-cols-2 gap-1 rounded-md border border-border bg-secondary/40 p-1"
          >
            <ModeTab
              active={mode === "login"}
              onClick={() => setMode("login")}
              label="Connexion"
            />
            <ModeTab
              active={mode === "signup"}
              onClick={() => setMode("signup")}
              label="Créer un compte"
            />
          </div>

          <form onSubmit={handleSubmit} className="space-y-3.5">
            {mode === "signup" && (
              <div className="space-y-1.5">
                <Label htmlFor="auth-name" className="text-[11px] uppercase tracking-wide text-muted-foreground">
                  Nom
                </Label>
                <div className="relative">
                  <User
                    size={14}
                    className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
                  />
                  <Input
                    id="auth-name"
                    type="text"
                    autoComplete="name"
                    placeholder="Marie Dubois"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="h-9 pl-8"
                    required
                  />
                </div>
              </div>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="auth-email" className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Email
              </Label>
              <div className="relative">
                <Mail
                  size={14}
                  className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
                />
                <Input
                  id="auth-email"
                  type="email"
                  autoComplete="email"
                  placeholder="marie@tevet7.dev"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="h-9 pl-8"
                  required
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="auth-password" className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Mot de passe
              </Label>
              <div className="relative">
                <Lock
                  size={14}
                  className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
                />
                <Input
                  id="auth-password"
                  type="password"
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="h-9 pl-8"
                  required
                  minLength={4}
                />
              </div>
            </div>

            {authError && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-md border border-border bg-secondary/60 px-3 py-2 text-xs text-foreground"
              >
                <AlertCircle
                  size={14}
                  className="mt-0.5 shrink-0 text-muted-foreground"
                />
                <span className="font-body leading-snug">{authError}</span>
              </div>
            )}

            <Button
              type="submit"
              disabled={busy}
              className="h-9 w-full gap-2 font-body text-sm"
            >
              {busy ? (
                <>
                  <span className="size-3 animate-spin rounded-full border-2 border-primary-foreground/40 border-t-primary-foreground" />
                  {mode === "login" ? "Connexion…" : "Création…"}
                </>
              ) : (
                <>
                  <LogIn size={15} />
                  {mode === "login" ? "Se connecter" : "Créer un compte"}
                </>
              )}
            </Button>
          </form>

          <div className="my-4 flex items-center gap-2 text-[10px] uppercase tracking-wide text-muted-foreground">
            <Separator className="flex-1" />
            <span>ou</span>
            <Separator className="flex-1" />
          </div>

          <Button
            type="button"
            variant="outline"
            onClick={handleDemo}
            disabled={busy}
            className="h-9 w-full gap-2 border-accent/40 bg-accent/5 font-body text-sm text-accent hover:bg-accent/10"
          >
            <Zap size={15} />
            {demoInFlight ? "Essai…" : "Essayer la démo"}
          </Button>

          {demoFallbackNote && (
            <div
              role="status"
              className="mt-3 rounded-md border border-border bg-secondary/40 px-3 py-2 text-[11px] text-muted-foreground"
            >
              Mode démo (backend hors ligne) — réponses simulées depuis le mock local.
            </div>
          )}

          <p className="mt-4 text-center text-[11px] text-muted-foreground">
            La démo vous connecte en tant que{" "}
            <span className="font-medium text-foreground">Marie Dubois</span>{" "}
            (Producer #42 · Ferme du Vallon).
          </p>
        </div>

        <p className="mt-5 text-center text-[10px] uppercase tracking-wide text-muted-foreground">
          Tevet-7 <span className="text-muted-foreground/50">·</span> Phase 6a · Auth + multi-tenant
        </p>
      </motion.div>
    </div>
  );
}

interface ModeTabProps {
  active: boolean;
  onClick: () => void;
  label: string;
}

function ModeTab({ active, onClick, label }: ModeTabProps) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={
        "h-8 rounded-sm px-3 text-xs font-medium uppercase tracking-wide transition-colors " +
        (active
          ? "bg-background text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground")
      }
    >
      {label}
    </button>
  );
}
