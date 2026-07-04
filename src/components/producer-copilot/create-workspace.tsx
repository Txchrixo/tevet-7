"use client";

import * as React from "react";
import { motion } from "framer-motion";

import { cn } from "@/lib/utils";
import { useCopilotStore } from "@/lib/store";
import { ArrowRight, Layers } from "@/components/ui/feather-icons";
import { BrandMark } from "./brand-mark";

/**
 * Shown when an authenticated user has NO tenants. The user just signed up
 * and needs to create their first workspace before they can use the agent.
 *
 * Simple form: workspace name + slug → POST /api/tenants → the backend makes
 * the caller the admin of the new tenant → JWT refreshed → chat loads.
 *
 * For the demo, users can also click "Utiliser la démo" to login as
 * marie@tevet7.dev (which already has a tenant).
 */
export function CreateWorkspace() {
  const createTenant = useCopilotStore((s) => s.createTenant);
  const logout = useCopilotStore((s) => s.logout);
  const [name, setName] = React.useState("");
  const [slug, setSlug] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Auto-generate slug from name.
  React.useEffect(() => {
    if (name && !slug) {
      setSlug(
        name
          .toLowerCase()
          .trim()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-+|-+$/g, ""),
      );
    }
  }, [name, slug]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) return;
    setError(null);
    if (!name.trim() || !slug.trim()) {
      setError("Nom et slug requis.");
      return;
    }
    setLoading(true);
    const result = await createTenant(name.trim(), slug.trim());
    setLoading(false);
    if (!result.ok) setError(result.error);
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
          {/* Brand */}
          <div className="flex flex-col items-center text-center">
            <div className="flex size-16 items-center justify-center rounded-md border border-border bg-background text-accent">
              <BrandMark size={36} />
            </div>
            <h1 className="mt-5 font-heading text-3xl tracking-tight text-foreground">
              Créer votre workspace
            </h1>
            <p className="mt-2 max-w-sm font-body text-sm leading-relaxed text-muted-foreground">
              Vous n&apos;avez pas encore de workspace. Créez-en un pour
              configurer votre agent et connecter vos données.
            </p>
          </div>

          {/* Form */}
          <form
            onSubmit={handleSubmit}
            className="mt-7 space-y-3 rounded-md border border-border bg-background p-5"
          >
            <div className="space-y-1.5">
              <label className="text-[11px] font-body font-medium uppercase tracking-wide text-muted-foreground">
                Nom du workspace
              </label>
              <div className="flex items-center gap-2 rounded-md border border-border bg-background px-2.5">
                <Layers size={14} className="text-muted-foreground" />
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Ma Société"
                  className="w-full bg-transparent px-1 py-2 font-body text-sm text-foreground outline-none placeholder:text-muted-foreground"
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-[11px] font-body font-medium uppercase tracking-wide text-muted-foreground">
                Slug (identifiant unique)
              </label>
              <div className="flex items-center gap-2 rounded-md border border-border bg-background px-2.5">
                <span className="font-mono text-xs text-muted-foreground">/</span>
                <input
                  type="text"
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                  placeholder="ma-societe"
                  className="w-full bg-transparent px-1 py-2 font-body text-sm text-foreground outline-none placeholder:text-muted-foreground"
                />
              </div>
              <p className="text-[10px] text-muted-foreground">
                Le slug identifie votre workspace (lettres, chiffres, tirets).
              </p>
            </div>

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
              disabled={loading}
              className={cn(
                "flex w-full items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5 font-body text-sm font-medium text-foreground transition-colors",
                "hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50",
              )}
            >
              {loading ? "Création…" : "Créer le workspace"}
              {!loading && <ArrowRight size={15} />}
            </button>
          </form>

          {/* Logout */}
          <button
            type="button"
            onClick={logout}
            className="mt-3 w-full text-center text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            Se déconnecter
          </button>
        </motion.div>
      </main>
    </div>
  );
}
