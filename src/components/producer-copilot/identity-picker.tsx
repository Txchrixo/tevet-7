"use client";

import * as React from "react";
import { motion } from "framer-motion";

import { cn } from "@/lib/utils";
import { useCopilotStore } from "@/lib/store";
import { ArrowLeft, ArrowRight, Shield, User } from "@/components/ui/feather-icons";
import { BrandMark } from "./brand-mark";

/**
 * Identity selection screen — shown when the user clicks "Essayer la démo".
 *
 * Best practice for demo flows: let the user pick their role BEFORE entering
 * the product, not after. This sets expectations and makes the scoping demo
 * more impactful (the user chose to be a producer, so they understand why
 * they can't see other producers' data).
 *
 * Three cards:
 *   - Marie Dubois — Producer #42 (Ferme du Vallon) — vegetables
 *   - Pierre Martin — Producer #99 (Verger de la Côte) — apples/cider
 *   - DP Admin — Ops team — full tenant access
 *
 * Each card logs in as the corresponding demo user via the real backend.
 */

interface DemoIdentity {
  email: string;
  name: string;
  role: string;
  description: string;
  icon: typeof User;
  accent: string;
}

const DEMO_IDENTITIES: DemoIdentity[] = [
  {
    email: "marie@tevet7.dev",
    name: "Marie Dubois",
    role: "Productrice #42",
    description: "Ferme du Vallon — légumes, tomates, courgettes. Voyez vos ventes, votre stock, vos revenus.",
    icon: User,
    accent: "accent",
  },
  {
    email: "pierre@tevet7.dev",
    name: "Pierre Martin",
    role: "Producteur #99",
    description: "Verger de la Côte — pommes, poires, cidre. Mêmes questions, données différentes.",
    icon: User,
    accent: "primary",
  },
  {
    email: "admin@tevet7.dev",
    name: "DP Admin",
    role: "Équipe Ops",
    description: "Accès complet au tenant : classement cross-producteur, Ops Console, admin console.",
    icon: Shield,
    accent: "accent",
  },
];

interface IdentityPickerProps {
  onBack: () => void;
}

export function IdentityPicker({ onBack }: IdentityPickerProps) {
  const tryDemoLogin = useCopilotStore((s) => s.tryDemoLogin);
  const authLoading = useCopilotStore((s) => s.authLoading);

  const [selected, setSelected] = React.useState<string | null>(null);

  const handlePick = async (email: string) => {
    if (authLoading) return;
    setSelected(email);
    await tryDemoLogin(email);
  };

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: "easeOut" }}
          className="w-full max-w-2xl"
        >
          {/* Brand + heading */}
          <div className="flex flex-col items-center text-center">
            <div className="flex size-14 items-center justify-center rounded-md border border-border bg-background text-accent">
              <BrandMark size={32} />
            </div>
            <h1 className="mt-4 font-heading text-2xl tracking-tight text-foreground sm:text-3xl">
              Choisissez votre identité
            </h1>
            <p className="mt-2 max-w-md font-body text-sm leading-relaxed text-muted-foreground">
              Vous explorez la démo publique de Tevet-7 sur le tenant Drive
              Producteur. Chaque identité voit des données différentes — le
              scoping est appliqué serveur.
            </p>
          </div>

          {/* Identity cards */}
          <div className="mt-8 grid gap-3 sm:grid-cols-3">
            {DEMO_IDENTITIES.map((ident) => {
              const Icon = ident.icon;
              const isSelected = selected === ident.email;
              return (
                <button
                  key={ident.email}
                  type="button"
                  disabled={authLoading}
                  onClick={() => handlePick(ident.email)}
                  className={cn(
                    "group flex flex-col items-start gap-3 rounded-md border border-border bg-background p-4 text-left transition-all hover:border-accent/60 hover:bg-secondary/30 disabled:cursor-not-allowed disabled:opacity-50",
                    isSelected && "border-accent/50 bg-secondary/30",
                  )}
                >
                  <div className="flex w-full items-center justify-between">
                    <div
                      className={cn(
                        "flex size-10 items-center justify-center rounded-full border border-border",
                        isSelected ? "bg-primary text-foreground" : "bg-secondary text-muted-foreground",
                      )}
                    >
                      <Icon size={18} />
                    </div>
                    {isSelected && authLoading && (
                      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                        Connexion…
                      </span>
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="font-heading text-sm font-medium text-foreground">
                      {ident.name}
                    </div>
                    <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                      {ident.role}
                    </div>
                  </div>
                  <p className="font-body text-xs leading-relaxed text-muted-foreground">
                    {ident.description}
                  </p>
                </button>
              );
            })}
          </div>

          {/* Back button */}
          <div className="mt-6 flex justify-center">
            <button
              type="button"
              onClick={onBack}
              disabled={authLoading}
              className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
            >
              <ArrowLeft size={13} />
              Retour à la connexion
            </button>
          </div>
        </motion.div>
      </main>
    </div>
  );
}
