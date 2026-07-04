"use client";

import * as React from "react";
import { motion } from "framer-motion";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  AlertCircle,
  ArrowRight,
  Check,
  Lock,
  LogIn,
  Mail,
  Plus,
  User,
  Zap,
} from "@/components/ui/feather-icons";
import { useCopilotStore } from "@/lib/store";
import { BrandLogo, BrandMark } from "./brand-mark";

/**
 * Full-screen auth gate.
 *
 * Shown by `src/app/page.tsx` when the user is NOT authenticated and has not
 * yet entered demo mode. Three modes:
 *   - Login  → email + password (POST /api/auth/login)
 *   - Signup → name + email + password (POST /api/auth/signup)
 *   - Create workspace → name + slug for the FIRST tenant of a freshly
 *     signed-up user with zero memberships (Phase 6b onboarding entry point).
 *
 * A prominent "Essayer la démo" button tries the real auth path
 * (login as marie@tevet7.dev / tevet7demo) and falls back to mock identities
 * if the backend is unreachable — the prototype must remain demoable even
 * when the FastAPI service is offline.
 *
 * After a successful signup with zero tenants, the AuthScreen switches to
 * "create workspace" mode so the user can create their first tenant + start
 * the onboarding wizard.
 */

type Mode = "login" | "signup" | "create-workspace";

const DEMO_EMAIL = "marie@tevet7.dev";
const DEMO_PASSWORD = "tevet7demo";

export function AuthScreen() {
  const login = useCopilotStore((s) => s.login);
  const signup = useCopilotStore((s) => s.signup);
  const enterDemoMode = useCopilotStore((s) => s.enterDemoMode);
  const authLoading = useCopilotStore((s) => s.authLoading);
  const authError = useCopilotStore((s) => s.authError);
  const clearAuthError = useCopilotStore((s) => s.clearAuthError);

  // Auth state — after a successful signup with zero tenants we transition
  // to the "create workspace" mode so the user can name their first tenant.
  const user = useCopilotStore((s) => s.user);
  const token = useCopilotStore((s) => s.token);
  const tenants = useCopilotStore((s) => s.tenants);
  const activeTenant = useCopilotStore((s) => s.activeTenant);
  const createTenant = useCopilotStore((s) => s.createTenant);
  const startOnboarding = useCopilotStore((s) => s.startOnboarding);

  const [mode, setMode] = React.useState<Mode>("login");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [name, setName] = React.useState("");
  const [wsName, setWsName] = React.useState("");
  const [wsSlug, setWsSlug] = React.useState("");
  const [createInFlight, setCreateInFlight] = React.useState(false);
  const [demoInFlight, setDemoInFlight] = React.useState(false);
  const [demoFallbackNote, setDemoFallbackNote] = React.useState(false);
  // Background BrandMark size — computed AFTER mount to avoid hydration
  // mismatch (server can't read window.innerWidth). Default 480 matches the
  // server-rendered value; the client updates it once mounted.
  const [bgMarkSize, setBgMarkSize] = React.useState(480);
  React.useEffect(() => {
    const update = () => setBgMarkSize(Math.min(640, window.innerWidth * 0.8));
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  // If the user is authenticated but has no tenants, switch to the
  // "create workspace" mode so they can name their first tenant. This is
  // the Phase 6b onboarding entry point — creating a tenant triggers the
  // onboarding wizard.
  React.useEffect(() => {
    if (user && token && tenants.length === 0 && !activeTenant) {
      setMode("create-workspace");
    }
  }, [user, token, tenants, activeTenant]);

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
      } else if (mode === "signup") {
        await signup(email.trim(), password, name.trim() || email.trim());
      }
    } catch {
      // The error is already in `authError` (set by the store) — surfaced
      // in the form's alert block. No additional handling needed here.
    }
  };

  const handleCreateWorkspace = async (e: React.FormEvent) => {
    e.preventDefault();
    if (createInFlight || authLoading) return;
    if (!wsName.trim()) return;
    setCreateInFlight(true);
    try {
      const newTenant = await createTenant(wsName.trim(), wsSlug.trim());
      // Kick off the onboarding wizard for the freshly created tenant.
      startOnboarding(newTenant.tenant_id);
    } catch {
      // Error is already in `authError` — surfaced in the form's alert block.
    } finally {
      setCreateInFlight(false);
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

  const busy = authLoading || demoInFlight || createInFlight;

  // -- "Create your first workspace" view ----------------------------------
  //
  // Rendered after a successful signup with 0 tenants. The form creates a
  // tenant via POST /api/tenants → on success the store starts the
  // onboarding wizard and page.tsx swaps the AuthScreen for the wizard.
  if (mode === "create-workspace" && user) {
    return (
      <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-background px-4 py-10">
        <div
          className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-[0.04]"
          aria-hidden
        >
          <BrandMark size={bgMarkSize} />
        </div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: "easeOut" }}
          className="relative z-10 w-full max-w-[460px]"
        >
          <div className="flex flex-col items-center text-center">
            <div className="flex size-14 items-center justify-center rounded-md border border-border bg-background text-accent">
              <BrandMark size={32} />
            </div>
            <div className="mt-4">
              <BrandLogo size={26} />
            </div>
            <h1 className="mt-4 text-2xl">Créez votre workspace</h1>
            <p className="mt-1.5 max-w-xs text-sm text-muted-foreground">
              Bienvenue {user.name || user.email}. Créez votre premier
              workspace — vous pourrez ensuite connecter votre donnée et
              configurer les rôles.
            </p>
          </div>

          <div className="mt-6 rounded-md border border-border bg-background p-5 shadow-sm sm:p-6">
            <form onSubmit={handleCreateWorkspace} className="space-y-3.5">
              <div className="space-y-1.5">
                <Label
                  htmlFor="ws-name"
                  className="text-[11px] uppercase tracking-wide text-muted-foreground"
                >
                  Nom du workspace
                </Label>
                <Input
                  id="ws-name"
                  type="text"
                  autoComplete="organization"
                  placeholder="Drive Producteur"
                  value={wsName}
                  onChange={(e) => setWsName(e.target.value)}
                  className="h-9"
                  required
                  autoFocus
                />
              </div>

              <div className="space-y-1.5">
                <Label
                  htmlFor="ws-slug"
                  className="text-[11px] uppercase tracking-wide text-muted-foreground"
                >
                  Slug (optionnel)
                </Label>
                <Input
                  id="ws-slug"
                  type="text"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="drive-producteur"
                  value={wsSlug}
                  onChange={(e) =>
                    setWsSlug(
                      e.target.value
                        .toLowerCase()
                        .replace(/[^a-z0-9-]/g, "-")
                        .replace(/-+/g, "-")
                        .slice(0, 40),
                    )
                  }
                  className="h-9 font-mono text-[12px]"
                />
                <p className="text-[11px] text-muted-foreground">
                  Laissez vide pour générer depuis le nom. Le slug est
                  l'identifiant URL-safe du workspace.
                </p>
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
                    Création…
                  </>
                ) : (
                  <>
                    <Plus size={15} />
                    Créer et configurer
                  </>
                )}
              </Button>
            </form>

            <div className="mt-4 flex items-center gap-2 rounded-md border border-border bg-secondary/40 px-3 py-2 text-[11px] text-muted-foreground">
              <Check size={13} className="shrink-0 text-accent" />
              <span>
                Connecté en tant que{" "}
                <span className="font-medium text-foreground">{user.email}</span>
                . La création du workspace lancera l'assistant de configuration.
              </span>
            </div>

            <button
              type="button"
              onClick={() => {
                clearAuthError();
                setMode("login");
              }}
              className="mt-3 flex w-full items-center justify-center gap-1.5 text-[11px] uppercase tracking-wide text-muted-foreground transition-colors hover:text-foreground"
            >
              <ArrowRight size={12} className="rotate-180" />
              Retour à la connexion
            </button>
          </div>

          <p className="mt-5 text-center text-[10px] uppercase tracking-wide text-muted-foreground">
            Tevet-7 <span className="text-muted-foreground/50">·</span> Phase 6b
            · Onboarding
          </p>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-background px-4 py-10">
      {/* Subtle background brand mark */}
      <div
        className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-[0.04]"
        aria-hidden
      >
        <BrandMark size={bgMarkSize} />
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
          <h1 className="mt-4 text-2xl">Tevet-7</h1>
          <p className="mt-1.5 max-w-xs text-sm text-muted-foreground">
            Plateforme d'agents IA configurable. Connectez-vous pour
            accéder à votre agent — chaque question est sécurisée par un
            scope tenant.
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
            La démo vous connecte sur le tenant{" "}
            <span className="font-medium text-foreground">Drive Producteur</span>{" "}
            en tant que Marie Dubois (Producer #42 · Ferme du Vallon).
          </p>
        </div>

        <p className="mt-5 text-center text-[10px] uppercase tracking-wide text-muted-foreground">
          Tevet-7 <span className="text-muted-foreground/50">·</span> Phase 6b · Onboarding
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
