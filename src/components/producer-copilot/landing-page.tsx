"use client";

/**
 * LandingPage — public-facing landing page for Tevet-7.
 *
 * Phase C1: converts visitors into signups. Shows what Tevet-7 does, key
 * features, pricing tiers, and a CTA to sign up. Only shown to anonymous
 * users (authMode === "anonymous" or "loading").
 *
 * Design: Tevet-7 dark green palette, Caudex headings + Manrope body,
 * Feather icons, no indigo/blue, sticky footer, responsive.
 */

import { motion } from "framer-motion";
import { Shield, Zap, Database, BarChart3, Users, Lock, ArrowRight, Check } from "lucide-react";
import { APP_NAME, APP_TAGLINE } from "@/lib/constants";

interface LandingPageProps {
  onSignup: () => void;
  onDemo: () => void;
}

const FEATURES = [
  {
    icon: Database,
    title: "Agent SQL intelligent",
    desc: "Posez vos questions en langage naturel. L'IA génère et exécute le SQL automatiquement, avec validation sqlglot.",
  },
  {
    icon: Shield,
    title: "Row-level security",
    desc: "Chaque producteur ne voit que ses données. sqlglot injecte le scope au niveau AST — impossible à contourner.",
  },
  {
    icon: BarChart3,
    title: "Analytics en temps réel",
    desc: "Ventes, stock, revenus, prévisions de rupture. Graphiques générés automatiquement depuis vos données.",
  },
  {
    icon: Zap,
    title: "Streaming temps réel",
    desc: "La réponse se construit sous vos yeux. Pas de spinner, pas d'attente — l'IA stream en SSE.",
  },
  {
    icon: Lock,
    title: "Guardrails IA",
    desc: "Protection contre le prompt injection, détection PII, modération de contenu. Sécurité by design.",
  },
  {
    icon: Users,
    title: "Multi-tenant",
    desc: "Chaque workspace a son schéma, ses rôles, son agent. Onboarding en 4 étapes, prêt en 5 minutes.",
  },
];

const PRICING = [
  {
    name: "Découverte",
    price: "Gratuit",
    period: "",
    features: [
      "1 workspace",
      "100 questions / mois",
      "Agent SQL + RAG",
      "Row-level security",
    ],
    cta: "Commencer gratuitement",
    highlight: false,
  },
  {
    name: "Pro",
    price: "49€",
    period: "/mois",
    features: [
      "Workspaces illimités",
      "10 000 questions / mois",
      "Streaming temps réel",
      "Prévisions ML (stock)",
      "Guardrails avancés",
      "Support prioritaire",
    ],
    cta: "Essayer 14 jours",
    highlight: true,
  },
  {
    name: "Enterprise",
    price: "Sur devis",
    period: "",
    features: [
      "Questions illimitées",
      "SSO (SAML/OIDC)",
      "On-premise / private cloud",
      "Audit log persistant",
      "SLA 99.9%",
      "Account manager dédié",
    ],
    cta: "Nous contacter",
    highlight: false,
  },
];

export function LandingPage({ onSignup, onDemo }: LandingPageProps) {
  return (
    <div className="min-h-screen flex flex-col bg-background">
      {/* ── Hero ── */}
      <section className="flex-1 flex flex-col items-center justify-center px-4 py-20 max-w-5xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="text-center"
        >
          <h1 className="font-heading text-5xl md:text-6xl text-foreground mb-4">
            {APP_NAME}
          </h1>
          <p className="text-xl md:text-2xl text-muted-foreground mb-2 font-body">
            {APP_TAGLINE}
          </p>
          <p className="text-sm text-muted-foreground/70 mb-8 max-w-2xl mx-auto">
            La plateforme d'agents IA configurable pour marketplaces B2B.
            Sécurité multi-tenant by design, LLM orchestrator avec function
            calling, guardrails IA. Déployé en production chez Drive Producteur.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <button
              onClick={onSignup}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-8 py-3 text-base font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
            >
              Créer un compte
              <ArrowRight className="h-4 w-4" />
            </button>
            <button
              onClick={onDemo}
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-8 py-3 text-base font-medium text-foreground transition-colors hover:bg-secondary/40"
            >
              Essayer la démo
            </button>
          </div>
        </motion.div>
      </section>

      {/* ── Features ── */}
      <section className="px-4 py-16 border-t border-border">
        <div className="max-w-5xl mx-auto">
          <h2 className="font-heading text-3xl text-foreground text-center mb-12">
            Pourquoi {APP_NAME} ?
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {FEATURES.map((f, i) => (
              <motion.div
                key={f.title}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: i * 0.1 }}
                className="rounded-lg border border-border bg-card p-6"
              >
                <f.icon className="h-8 w-8 text-accent mb-4" />
                <h3 className="font-heading text-lg text-foreground mb-2">{f.title}</h3>
                <p className="text-sm text-muted-foreground">{f.desc}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Pricing ── */}
      <section className="px-4 py-16 border-t border-border">
        <div className="max-w-5xl mx-auto">
          <h2 className="font-heading text-3xl text-foreground text-center mb-12">
            Tarifs
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {PRICING.map((tier) => (
              <div
                key={tier.name}
                className={`rounded-lg border p-6 ${
                  tier.highlight
                    ? "border-accent bg-accent/5"
                    : "border-border bg-card"
                }`}
              >
                {tier.highlight && (
                  <span className="mb-3 inline-block rounded-full bg-accent/20 px-3 py-1 text-xs font-medium text-accent-foreground">
                    Recommandé
                  </span>
                )}
                <h3 className="font-heading text-xl text-foreground mb-2">{tier.name}</h3>
                <div className="mb-4">
                  <span className="font-heading text-3xl text-foreground">{tier.price}</span>
                  <span className="text-sm text-muted-foreground">{tier.period}</span>
                </div>
                <ul className="space-y-2 mb-6">
                  {tier.features.map((feat) => (
                    <li key={feat} className="flex items-start gap-2 text-sm text-muted-foreground">
                      <Check className="h-4 w-4 text-accent shrink-0 mt-0.5" />
                      {feat}
                    </li>
                  ))}
                </ul>
                <button
                  onClick={onSignup}
                  className={`w-full rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                    tier.highlight
                      ? "bg-primary text-foreground hover:bg-accent hover:text-accent-foreground"
                      : "border border-border text-foreground hover:bg-secondary/40"
                  }`}
                >
                  {tier.cta}
                </button>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="mt-auto border-t border-border px-4 py-8">
        <div className="max-w-5xl mx-auto text-center">
          <p className="text-sm text-muted-foreground">
            {APP_NAME} · {APP_TAGLINE}
          </p>
          <p className="mt-2 text-xs text-muted-foreground/60">
            Sécurisé par sqlglot AST rewriting · LLM orchestrator avec function calling ·
            Guardrails IA · Multi-tenant by design
          </p>
        </div>
      </footer>
    </div>
  );
}
