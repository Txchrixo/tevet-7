"use client";

/**
 * LandingPage — production-grade SaaS landing page (Phase C1 v2).
 *
 * Design: minimalist, dark green palette, heptagon brand mark as background
 * pattern, interactive demo that looks like a real dashboard screenshot.
 *
 * Sections: Navbar → Hero → Social proof → Problem/Solution → Features →
 * How it works → Use cases → Pricing → FAQ → CTA → Footer
 */

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Shield, Database, Zap, BarChart3, Lock, Users,
  ArrowRight, Check, Menu, X, ChevronDown,
  MessageSquare, Sparkles, TrendingUp, AlertTriangle,
} from "lucide-react";
import { APP_NAME, APP_TAGLINE } from "@/lib/constants";
import { BrandMark, BrandLogo } from "@/components/producer-copilot/brand-mark";

// ─────────────────────────────────────────────────────────────────────────────
// Heptagon background pattern (subtle, used in hero + CTA sections)
// ─────────────────────────────────────────────────────────────────────────────

function HeptagonPattern({ opacity = 0.03 }: { opacity?: number }) {
  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden" style={{ opacity }}>
      <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <pattern id="heptagon-pattern" x="0" y="0" width="60" height="60" patternUnits="userSpaceOnUse">
            <path
              d="M 30 8 L 47.7 18.5 L 50.5 38.5 L 37.6 53 L 22.4 53 L 9.5 38.5 L 12.3 18.5 Z"
              fill="none"
              stroke="var(--accent, #A8C090)"
              strokeWidth="0.5"
            />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#heptagon-pattern)" />
      </svg>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Navbar
// ─────────────────────────────────────────────────────────────────────────────

function Navbar({ onSignup, onDemo }: { onSignup: () => void; onDemo: () => void }) {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const navLinks = [
    { label: "Fonctionnalités", href: "#features" },
    { label: "Comment ça marche", href: "#how" },
    { label: "Démo", href: "#demo" },
    { label: "Tarifs", href: "#pricing" },
    { label: "FAQ", href: "#faq" },
  ];

  return (
    <nav className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
      scrolled ? "bg-background/90 backdrop-blur-md border-b border-border" : "bg-transparent"
    }`}>
      <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
        <BrandLogo size={26} />

        <div className="hidden lg:flex items-center gap-6">
          {navLinks.map((l) => (
            <a key={l.href} href={l.href}
               className="text-sm text-muted-foreground hover:text-foreground transition-colors">
              {l.label}
            </a>
          ))}
        </div>

        <div className="hidden lg:flex items-center gap-3">
          <button onClick={onDemo}
            className="text-sm text-muted-foreground hover:text-foreground transition-colors">
            Se connecter
          </button>
          <button onClick={onSignup}
            className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground">
            Essayer gratuitement
          </button>
        </div>

        <button className="lg:hidden text-foreground" onClick={() => setMobileOpen(!mobileOpen)}>
          {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="lg:hidden bg-background border-b border-border overflow-hidden"
          >
            <div className="px-4 py-4 space-y-3">
              {navLinks.map((l) => (
                <a key={l.href} href={l.href} onClick={() => setMobileOpen(false)}
                   className="block text-sm text-muted-foreground hover:text-foreground">
                  {l.label}
                </a>
              ))}
              <button onClick={onSignup}
                className="block w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-foreground text-center">
                Essayer gratuitement
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </nav>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Hero
// ─────────────────────────────────────────────────────────────────────────────

function Hero({ onSignup, onDemo }: { onSignup: () => void; onDemo: () => void }) {
  return (
    <section className="relative pt-32 pb-20 px-4 overflow-hidden">
      <HeptagonPattern opacity={0.04} />
      <div className="absolute inset-0 bg-gradient-to-b from-primary/5 via-transparent to-transparent pointer-events-none" />

      <div className="relative max-w-4xl mx-auto text-center">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 mb-6">
            <Sparkles className="h-3 w-3 text-accent" />
            <span className="text-xs text-muted-foreground">Agent IA configurable pour vos données</span>
          </div>

          <h1 className="font-heading text-4xl md:text-6xl text-foreground leading-tight mb-4">
            Vos données parlent.
            <br />
            <span className="text-accent">Votre agent IA écoute.</span>
          </h1>

          <p className="text-lg text-muted-foreground max-w-2xl mx-auto mb-8">
            Posez vos questions en français. L'IA génère le SQL, valide la
            sécurité, et répond en temps réel. Sans code. Sans attendre.
          </p>

          <div className="flex flex-col sm:flex-row gap-3 justify-center mb-6">
            <button onClick={onSignup}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-7 py-3 text-base font-medium text-foreground transition-all hover:bg-accent hover:text-accent-foreground hover:scale-[1.02]">
              Commencer gratuitement
              <ArrowRight className="h-4 w-4" />
            </button>
            <button onClick={onDemo}
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-7 py-3 text-base font-medium text-foreground transition-all hover:bg-secondary/40">
              Voir la démo
            </button>
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="mt-12 relative"
        >
          <div className="rounded-xl border border-border bg-card overflow-hidden shadow-2xl">
            <InteractiveDemo />
          </div>
        </motion.div>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Interactive Demo — démo interactive façon Cursor
// ─────────────────────────────────────────────────────────────────────────────

type DemoRole = "producteur" | "admin" | "client";

interface DemoScenario {
  role: DemoRole;
  roleLabel: string;
  q: string;
  summary: string;
  table: { headers: string[]; rows: (string | number)[][] };
  sql: string | null;
  scope: string;
  tokens: string;
  latency: string;
  tagLabel: string;
  chartTitle: string;
  chartData: { name: string; value: number; display: string }[];
  chartColor: "accent" | "amber";
}

const DEMO_SCENARIOS: DemoScenario[] = [
  {
    role: "producteur",
    roleLabel: "Producteur",
    q: "Quels sont mes 5 produits les plus vendus ce mois-ci ?",
    summary: "Voici vos 5 produits les plus vendus ce mois-ci. Les tomates représentent 22% de votre chiffre d'affaires.",
    table: {
      headers: ["Produit", "Unités", "Chiffre d'affaires"],
      rows: [
        ["Tomates cœur de bœuf", "180", "807,36 €"],
        ["Courgettes", "102", "204,00 €"],
        ["Carottes en bottes", "95", "142,50 €"],
        ["Salade laitue", "88", "132,00 €"],
        ["Pommes Gala", "75", "150,00 €"],
      ],
    },
    sql: "SELECT p.name AS name, SUM(oi.quantity) AS units_sold, ROUND(SUM(oi.line_total_eur), 2) AS revenue FROM order_items AS oi JOIN products AS p ON oi.product_id = p.id JOIN orders AS o ON oi.order_id = o.id WHERE o.created_at >= date('2024-07-01', 'start of month') GROUP BY p.name ORDER BY units_sold DESC LIMIT 5",
    scope: "FULL ACCESS",
    tokens: "1 168",
    latency: "2,7",
    tagLabel: "SQL EXÉCUTÉ",
    chartTitle: "Unités vendues par produit",
    chartData: [
      { name: "Tomates", value: 180, display: "180" },
      { name: "Courgettes", value: 102, display: "102" },
      { name: "Carottes", value: 95, display: "95" },
      { name: "Salade", value: 88, display: "88" },
      { name: "Pommes", value: 75, display: "75" },
    ],
    chartColor: "accent",
  },
  {
    role: "admin",
    roleLabel: "Admin marketplace",
    q: "Quel producteur a généré le plus de ventes ce mois-ci ?",
    summary: "Voici le classement des producteurs par ventes ce mois-ci. La Ferme du Vallon est en tête avec 1 455,55 €.",
    table: {
      headers: ["Producteur", "Commandes", "Chiffre d'affaires"],
      rows: [
        ["Ferme du Vallon", "123", "1 455,55 €"],
        ["Maraîchage Bio Soleil", "98", "1 203,20 €"],
        ["Élevage du Vernet", "67", "890,40 €"],
        ["Vignoble des Coteaux", "45", "1 739,49 €"],
        ["Fromagerie du Col", "34", "542,10 €"],
      ],
    },
    sql: "SELECT p.name AS name, COUNT(o.id) AS commandes, ROUND(SUM(oi.line_total_eur), 2) AS revenue FROM order_items AS oi JOIN orders AS o ON oi.order_id = o.id JOIN producers AS p ON oi.producer_id = p.id GROUP BY p.name ORDER BY revenue DESC LIMIT 5",
    scope: "FULL ACCESS",
    tokens: "1 450",
    latency: "3,1",
    tagLabel: "SQL EXÉCUTÉ",
    chartTitle: "Ventes par producteur",
    chartData: [
      { name: "Vallon", value: 1456, display: "1 456 €" },
      { name: "Bio Soleil", value: 1203, display: "1 203 €" },
      { name: "Vernet", value: 890, display: "890 €" },
      { name: "Coteaux", value: 1739, display: "1 739 €" },
      { name: "Col", value: 542, display: "542 €" },
    ],
    chartColor: "accent",
  },
  {
    role: "client",
    roleLabel: "Client",
    q: "Quelles sont mes dernières commandes ?",
    summary: "Voici vos 5 dernières commandes. Votre prochaine livraison est prévue samedi 14 juillet.",
    table: {
      headers: ["Date", "Producteur", "Montant", "Statut"],
      rows: [
        ["12/07", "Ferme du Vallon", "48,50 €", "Prête"],
        ["10/07", "Vignoble des Coteaux", "32,00 €", "Récupérée"],
        ["07/07", "Maraîchage Bio Soleil", "27,30 €", "Récupérée"],
        ["05/07", "Fromagerie du Col", "15,80 €", "Récupérée"],
        ["03/07", "Élevage du Vernet", "63,20 €", "Récupérée"],
      ],
    },
    sql: "SELECT o.created_at AS date, p.name AS producer, ROUND(SUM(oi.line_total_eur), 2) AS amount, o.status FROM orders AS o JOIN order_items AS oi ON oi.order_id = o.id JOIN producers AS p ON oi.producer_id = p.id WHERE o.customer_id = :customer_id GROUP BY o.id ORDER BY o.created_at DESC LIMIT 5",
    scope: "SCOPE VÉRIFIÉ",
    tokens: "980",
    latency: "1,8",
    tagLabel: "SQL EXÉCUTÉ",
    chartTitle: "Montant par commande",
    chartData: [
      { name: "12/07", value: 49, display: "49 €" },
      { name: "10/07", value: 32, display: "32 €" },
      { name: "07/07", value: 27, display: "27 €" },
      { name: "05/07", value: 16, display: "16 €" },
      { name: "03/07", value: 63, display: "63 €" },
    ],
    chartColor: "accent",
  },
];

// SQL syntax highlighting (same tokenizer as real SqlBlock)
const SQL_KEYWORDS = new Set([
  "SELECT", "FROM", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "ON",
  "GROUP", "BY", "ORDER", "HAVING", "LIMIT", "AND", "OR", "IN", "NOT", "AS",
  "DESC", "ASC", "COUNT", "SUM", "COALESCE", "DISTINCT", "CASE", "WHEN", "THEN",
  "ELSE", "END", "DATE", "ROUND", "MAX", "MIN", "AVG",
]);

function renderSqlTokens(text: string) {
  const tokenRe = /('(?:[^']|'')*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|([(),.;*=<>+\-/]+)|(\s+)|([^\s])/g;
  const nodes: React.ReactNode[] = [];
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = tokenRe.exec(text)) !== null) {
    const [full, str, num, ident, punct, ws] = m;
    if (str) {
      nodes.push(<span key={key++} className="text-foreground/90">{str}</span>);
    } else if (num) {
      nodes.push(<span key={key++} className="font-heading text-muted-foreground tabular-nums">{num}</span>);
    } else if (ident) {
      const upper = ident.toUpperCase();
      if (SQL_KEYWORDS.has(upper)) {
        nodes.push(<span key={key++} className="font-medium text-accent/90">{ident}</span>);
      } else {
        nodes.push(<span key={key++} className="text-foreground">{ident}</span>);
      }
    } else if (punct) {
      nodes.push(<span key={key++} className="text-muted-foreground">{punct}</span>);
    } else if (ws) {
      nodes.push(ws);
    } else {
      nodes.push(full);
    }
  }
  return nodes;
}

function InteractiveDemo() {
  const [activeIdx, setActiveIdx] = useState(0);
  const active = DEMO_SCENARIOS[activeIdx];
  const maxChart = Math.max(...active.chartData.map((d) => d.value));

  return (
    <div className="flex flex-col bg-background text-left">
      {/* Window header (Mac-style dots) */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-secondary/20">
        <div className="flex items-center gap-2">
          <BrandMark size={16} className="shrink-0" />
          <span className="text-xs text-muted-foreground">Tevet-7 · Drive Producteur</span>
        </div>
        <div className="flex gap-2">
          <div className="w-3 h-3 rounded-full bg-red-500/80" />
          <div className="w-3 h-3 rounded-full bg-yellow-500/80" />
          <div className="w-3 h-3 rounded-full bg-green-500/80" />
        </div>
      </div>

      {/* Role selector tabs (Producteur / Gestionnaire / Analyste) */}
      <div className="flex border-b border-border">
        {DEMO_SCENARIOS.map((s, i) => (
          <button
            key={s.role}
            onClick={() => setActiveIdx(i)}
            className={`flex-1 px-3 py-2 text-xs font-medium transition-colors ${
              i === activeIdx
                ? "text-foreground border-b-2 border-accent bg-secondary/10"
                : "text-muted-foreground hover:text-foreground hover:bg-secondary/5"
            }`}
          >
            {s.roleLabel}
          </button>
        ))}
      </div>

      {/* Chat thread */}
      <div className="p-4 space-y-4 text-left">
        {/* User question */}
        <AnimatePresence mode="wait">
          <motion.div
            key={`q-${activeIdx}`}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="flex justify-end"
          >
            <div className="max-w-[80%] rounded-md rounded-br-sm bg-primary px-3 py-2 text-sm text-foreground text-left">
              {active.q}
            </div>
          </motion.div>
        </AnimatePresence>

        {/* Assistant response */}
        <AnimatePresence mode="wait">
          <motion.div
            key={`a-${activeIdx}`}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15, delay: 0.05 }}
            className="flex justify-start text-left"
          >
            <div className="flex items-start gap-2.5 w-full text-left">
              {/* Avatar */}
              <span className="flex w-8 h-8 shrink-0 items-center justify-center rounded-md border border-border bg-background">
                <BrandMark size={18} className="shrink-0" />
              </span>

              {/* Response card */}
              <div className="flex-1 min-w-0 rounded-md border border-border bg-background p-4 text-left">
                {/* Summary text */}
                <p className="text-sm text-foreground leading-relaxed font-body mb-3 text-left">
                  {active.summary}
                </p>

                {/* Data table (properly formatted, like a real report) */}
                <div className="overflow-x-auto mb-3 text-left">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="border-b border-border">
                        {active.table.headers.map((h, i) => (
                          <th key={i} className={`py-1.5 px-2 font-heading text-muted-foreground font-medium ${i === 0 ? "text-left" : "text-right"}`}>
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {active.table.rows.map((row, ri) => (
                        <tr key={ri} className="border-b border-border/40 hover:bg-secondary/10 transition-colors">
                          {row.map((cell, ci) => (
                            <td key={ci} className={`py-1.5 px-2 ${ci === 0 ? "text-left text-foreground font-body" : "text-right text-muted-foreground tabular-nums"}`}>
                              {cell}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Chart */}
                <div className="rounded-md border border-border bg-background p-3 mb-3 text-left">
                  <div className="mb-3">
                    <span className="font-heading text-xs text-foreground">{active.chartTitle}</span>
                  </div>
                  <div className="h-32 flex items-end justify-between gap-2 px-1">
                    {active.chartData.map((item, i) => (
                      <div key={i} className="flex-1 flex flex-col items-center gap-1 h-full justify-end min-w-0">
                        <span className="text-[10px] text-muted-foreground tabular-nums whitespace-nowrap">
                          {item.display}
                        </span>
                        <motion.div
                          initial={{ height: 0 }}
                            animate={{ height: `${(item.value / maxChart) * 100}%` }}
                          transition={{ duration: 0.4, delay: i * 0.06 }}
                          className={`w-full rounded-t-sm min-h-[4px] ${active.chartColor === "amber" ? "bg-amber-600/60" : "bg-accent"}`}
                        />
                        <span className="text-[10px] text-muted-foreground truncate max-w-full">{item.name}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* SQL block (syntax-highlighted) */}
                {active.sql && (
                  <div className="mb-3 text-left">
                    <details className="group">
                      <summary className="flex cursor-pointer items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted-foreground hover:text-foreground list-none">
                        <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180 shrink-0" />
                        <Database size={11} className="shrink-0" />
                        SQL exécuté
                      </summary>
                      <div className="mt-1.5 rounded-md border border-border bg-secondary/20 p-2.5 overflow-x-auto">
                        <pre className="text-[11px] leading-relaxed font-mono">
                          <code>{renderSqlTokens(active.sql)}</code>
                        </pre>
                      </div>
                    </details>
                  </div>
                )}

                {/* Footer */}
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-2 text-[11px] uppercase tracking-wide text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    <Check size={12} className="text-accent shrink-0" />
                    {active.scope}
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <span className="font-heading text-foreground tabular-nums">{active.tokens}</span>
                    tokens
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <span className="font-heading text-foreground tabular-nums">{active.latency}</span>
                    s
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-md border border-border bg-secondary px-1.5 text-[10px] text-muted-foreground whitespace-nowrap">
                    <Database size={10} className="shrink-0" />
                    {active.tagLabel}
                  </span>
                </div>
              </div>
            </div>
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Bottom: role hint */}
      <div className="border-t border-border px-4 py-2 text-center">
        <span className="text-[10px] text-muted-foreground/60">
          Testez en tant que {DEMO_SCENARIOS.map((s, i) => (
            <button
              key={s.role}
              onClick={() => setActiveIdx(i)}
              className={`mx-1 underline-offset-2 hover:underline ${i === activeIdx ? "text-accent font-medium" : ""}`}
            >
              {s.roleLabel.toLowerCase()}
            </button>
          ))}
        </span>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Social proof bar
// ─────────────────────────────────────────────────────────────────────────────

function SocialProof() {
  return (
    <section className="py-10 border-y border-border/50">
      <div className="max-w-4xl mx-auto px-4">
        <p className="text-center text-xs text-muted-foreground/60 mb-6 uppercase tracking-wider">
          Déjà en production chez
        </p>
        <div className="flex items-center justify-center gap-8 flex-wrap">
          <div className="flex items-center gap-2">
            <BrandMark size={18} />
            <span className="font-heading text-base text-muted-foreground/50">Drive Producteur</span>
          </div>
        </div>
        <div className="flex items-center justify-center gap-8 mt-6 flex-wrap">
          {[
            { value: "<3s", label: "Latence moyenne" },
            { value: "39/39", label: "Tests validés" },
            { value: "100%", label: "Données scopées" },
            { value: "5 min", label: "Configuration" },
          ].map((s) => (
            <div key={s.label} className="text-center">
              <div className="font-heading text-xl text-foreground">{s.value}</div>
              <div className="text-[10px] text-muted-foreground">{s.label}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Problem / Solution
// ─────────────────────────────────────────────────────────────────────────────

function ProblemSolution() {
  return (
    <section className="py-20 px-4">
      <div className="max-w-4xl mx-auto">
        <div className="grid md:grid-cols-2 gap-8">
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-5 w-5" />
              <span className="text-sm font-medium">Le problème</span>
            </div>
            <h3 className="font-heading text-2xl text-foreground">
              Vos équipes attendent des jours pour des rapports SQL.
            </h3>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li className="flex items-start gap-2"><X className="h-4 w-4 text-destructive/60 shrink-0 mt-0.5" /> Le support IT est surchargé de requêtes</li>
              <li className="flex items-start gap-2"><X className="h-4 w-4 text-destructive/60 shrink-0 mt-0.5" /> Les producteurs ne voient pas leurs ventes en temps réel</li>
              <li className="flex items-start gap-2"><X className="h-4 w-4 text-destructive/60 shrink-0 mt-0.5" /> Les tableaux Excel sont obsolètes avant d'être partagés</li>
              <li className="flex items-start gap-2"><X className="h-4 w-4 text-destructive/60 shrink-0 mt-0.5" /> Personne ne peut anticiper les ruptures de stock</li>
            </ul>
          </div>

          <div className="space-y-4">
            <div className="flex items-center gap-2 text-accent">
              <Check className="h-5 w-5" />
              <span className="text-sm font-medium">La solution</span>
            </div>
            <h3 className="font-heading text-2xl text-foreground">
              Vos producteurs parlent à leurs données en français.
            </h3>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li className="flex items-start gap-2"><Check className="h-4 w-4 text-accent shrink-0 mt-0.5" /> Chaque producteur pose ses questions directement</li>
              <li className="flex items-start gap-2"><Check className="h-4 w-4 text-accent shrink-0 mt-0.5" /> L'IA génère et valide le SQL automatiquement</li>
              <li className="flex items-start gap-2"><Check className="h-4 w-4 text-accent shrink-0 mt-0.5" /> Réponse immédiate avec graphiques</li>
              <li className="flex items-start gap-2"><Check className="h-4 w-4 text-accent shrink-0 mt-0.5" /> Prévisions de rupture par Machine Learning</li>
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Features
// ─────────────────────────────────────────────────────────────────────────────

const FEATURES = [
  { icon: Database, title: "Agent SQL intelligent", desc: "Posez une question en français. L'IA génère le SQL, le valide, l'exécute et vous répond." },
  { icon: Shield, title: "Données scopées par tenant", desc: "Chaque producteur ne voit que ses propres données. Le scoping est injecté au niveau du SQL." },
  { icon: Zap, title: "Réponses en temps réel", desc: "La réponse s'affiche au fur et à mesure. Pas de spinner, pas d'attente." },
  { icon: BarChart3, title: "Graphiques automatiques", desc: "Ventes, stock, revenus. Les graphiques sont générés depuis vos données réelles." },
  { icon: Lock, title: "Protection IA intégrée", desc: "Détection d'injection de prompt, masquage des données personnelles, modération du contenu." },
  { icon: Users, title: "Multi-workspace natif", desc: "Chaque workspace a son schéma, ses rôles et son agent. Configuration en 4 étapes." },
];

function Features() {
  return (
    <section id="features" className="py-20 px-4 border-t border-border/50">
      <div className="max-w-5xl mx-auto">
        <h2 className="font-heading text-3xl text-foreground text-center mb-3">
          Tout ce qu'il faut pour interroger vos données
        </h2>
        <p className="text-center text-muted-foreground mb-12 max-w-xl mx-auto">
          Pas un chatbot. Un agent IA enterprise avec sécurité, guardrails et Machine Learning.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-px bg-border/30 rounded-lg overflow-hidden">
          {FEATURES.map((f) => (
            <div key={f.title} className="bg-card p-6 hover:bg-secondary/20 transition-colors">
              <f.icon className="h-6 w-6 text-accent mb-3" strokeWidth={1.5} />
              <h3 className="font-heading text-base text-foreground mb-1.5">{f.title}</h3>
              <p className="text-sm text-muted-foreground leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// How it works
// ─────────────────────────────────────────────────────────────────────────────

function HowItWorks() {
  const steps = [
    { num: "01", icon: Database, title: "Connectez vos données", desc: "PostgreSQL, CSV ou SQLite. Le schéma est détecté automatiquement." },
    { num: "02", icon: Users, title: "Définissez les rôles", desc: "Choisissez qui voit quoi. Admin, producteur, client. Le scope s'applique partout." },
    { num: "03", icon: MessageSquare, title: "Posez vos questions", desc: "En français. L'IA génère le SQL, valide la sécurité, exécute et répond avec des graphiques." },
  ];

  return (
    <section id="how" className="py-20 px-4 border-t border-border/50">
      <div className="max-w-4xl mx-auto">
        <h2 className="font-heading text-3xl text-foreground text-center mb-12">
          Configuration en 5 minutes
        </h2>
        <div className="grid md:grid-cols-3 gap-8">
          {steps.map((s) => (
            <div key={s.num} className="text-center">
              <div className="inline-flex items-center justify-center w-12 h-12 rounded-full border border-border mb-4">
                <s.icon className="h-5 w-5 text-accent" strokeWidth={1.5} />
              </div>
              <div className="font-heading text-xs text-muted-foreground/50 mb-1">{s.num}</div>
              <h3 className="font-heading text-base text-foreground mb-2">{s.title}</h3>
              <p className="text-sm text-muted-foreground">{s.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Use cases
// ─────────────────────────────────────────────────────────────────────────────

function UseCases() {
  const cases = [
    {
      icon: TrendingUp, title: "Marketplace B2B",
      desc: "Ventes par producteur, commissions, top produits, prévisions de rupture.",
      example: "« Quels sont mes 5 produits les plus vendus ce mois-ci ? »",
    },
    {
      icon: BarChart3, title: "E-commerce",
      desc: "Revenus, panier moyen, conversion, stock optimal par catégorie.",
      example: "« Combien j'ai gagné net de commission en juin ? »",
    },
    {
      icon: AlertTriangle, title: "Logistique",
      desc: "Ruptures prévisionnelles, optimisation du stock, alertes automatiques.",
      example: "« Quel stock va me manquer samedi ? »",
    },
  ];

  return (
    <section className="py-20 px-4 border-t border-border/50">
      <div className="max-w-4xl mx-auto">
        <h2 className="font-heading text-3xl text-foreground text-center mb-12">
          Cas d'usage
        </h2>
        <div className="grid md:grid-cols-3 gap-6">
          {cases.map((c) => (
            <div key={c.title} className="rounded-lg border border-border bg-card p-5">
              <c.icon className="h-6 w-6 text-accent mb-3" strokeWidth={1.5} />
              <h3 className="font-heading text-base text-foreground mb-1.5">{c.title}</h3>
              <p className="text-sm text-muted-foreground mb-3">{c.desc}</p>
              <div className="rounded-md bg-secondary/20 border border-border/50 p-2.5">
                <p className="text-xs text-muted-foreground italic">{c.example}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Pricing
// ─────────────────────────────────────────────────────────────────────────────

const PRICING = [
  {
    name: "Découverte", price: "0€", period: "/mois", highlight: false,
    features: ["1 workspace", "100 questions / mois", "Agent SQL + RAG", "Données scopées", "Communauté"],
    cta: "Commencer",
  },
  {
    name: "Pro", price: "49€", period: "/mois", highlight: true,
    features: ["Workspaces illimités", "10 000 questions / mois", "Réponses en temps réel", "Prévisions ML (stock)", "Guardrails avancés", "Support prioritaire"],
    cta: "Essayer 14 jours",
  },
  {
    name: "Enterprise", price: "Sur devis", period: "", highlight: false,
    features: ["Questions illimitées", "SSO (SAML/OIDC)", "On-premise / cloud privé", "Audit log persistant", "SLA 99,9%", "Account manager dédié"],
    cta: "Nous contacter",
  },
];

function Pricing({ onSignup }: { onSignup: () => void }) {
  return (
    <section id="pricing" className="py-20 px-4 border-t border-border/50">
      <div className="max-w-4xl mx-auto">
        <h2 className="font-heading text-3xl text-foreground text-center mb-3">
          Tarifs simples
        </h2>
        <p className="text-center text-muted-foreground mb-12">Commencez gratuitement. Changez de plan quand vous voulez.</p>
        <div className="grid md:grid-cols-3 gap-6">
          {PRICING.map((tier) => (
            <div key={tier.name}
              className={`rounded-lg border p-6 ${tier.highlight ? "border-accent bg-accent/5" : "border-border bg-card"}`}>
              {tier.highlight && (
                <span className="mb-3 inline-block rounded-full bg-accent/20 px-2.5 py-0.5 text-[10px] font-medium text-accent-foreground">
                  Recommandé
                </span>
              )}
              <h3 className="font-heading text-lg text-foreground mb-1">{tier.name}</h3>
              <div className="mb-4">
                <span className="font-heading text-3xl text-foreground">{tier.price}</span>
                <span className="text-sm text-muted-foreground">{tier.period}</span>
              </div>
              <ul className="space-y-1.5 mb-5">
                {tier.features.map((feat) => (
                  <li key={feat} className="flex items-start gap-2 text-sm text-muted-foreground">
                    <Check className="h-3.5 w-3.5 text-accent shrink-0 mt-0.5" />
                    {feat}
                  </li>
                ))}
              </ul>
              <button onClick={onSignup}
                className={`w-full rounded-md px-4 py-2 text-sm font-medium transition-colors ${
                  tier.highlight
                    ? "bg-primary text-foreground hover:bg-accent hover:text-accent-foreground"
                    : "border border-border text-foreground hover:bg-secondary/40"
                }`}>
                {tier.cta}
              </button>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// FAQ
// ─────────────────────────────────────────────────────────────────────────────

const FAQS = [
  { q: "Mes données sont-elles sécurisées ?", a: "Oui. Chaque requête SQL est validée par sqlglot, qui injecte le row-level scope au niveau de l'arbre syntaxique. Un producteur ne peut jamais voir les données d'un autre. L'IA génère du SQL mais n'accède jamais à la base directement." },
  { q: "Quels modèles d'IA sont supportés ?", a: "Tous les modèles compatibles OpenAI : Groq (Llama), DeepSeek, GLM-4.6, OpenRouter, Gemini. Le routeur essaie chaque fournisseur en ordre avec un circuit breaker. Si un modèle tombe, le suivant prend le relais automatiquement." },
  { q: "Puis-je utiliser mon propre modèle ?", a: "Oui. Tout fournisseur avec une API compatible OpenAI fonctionne. Ajoutez votre clé et votre URL dans la configuration et le routeur construit la chaîne automatiquement." },
  { q: "Combien de temps pour la configuration ?", a: "5 minutes. L'onboarding en 4 étapes : connectez vos données (URL Postgres ou CSV), le schéma est détecté, sélectionnez vos tables, définissez les rôles. Votre agent est prêt." },
  { q: "Quelle est la différence avec ChatGPT ?", a: "Tevet-7 est multi-tenant avec scoping SQL. ChatGPT ne l'est pas. Tevet-7 se connecte à votre base de données. Tevet-7 a du Machine Learning intégré (prévisions de stock). ChatGPT est un chatbot généraliste." },
  { q: "Mes données quittent-elles mon infrastructure ?", a: "Le modèle d'IA génère du texte (SQL), il n'accède jamais à vos données directement. Le SQL est validé puis exécuté localement. Seules les métadonnées (structure des tables, noms des colonnes) sont envoyées au modèle, jamais les données elles-mêmes." },
];

function FAQ() {
  const [openIdx, setOpenIdx] = useState<number | null>(0);

  return (
    <section id="faq" className="py-20 px-4 border-t border-border/50">
      <div className="max-w-2xl mx-auto">
        <h2 className="font-heading text-3xl text-foreground text-center mb-12">
          Questions fréquentes
        </h2>
        <div className="space-y-2">
          {FAQS.map((item, i) => (
            <div key={i} className="rounded-lg border border-border bg-card overflow-hidden">
              <button
                onClick={() => setOpenIdx(openIdx === i ? null : i)}
                className="w-full flex items-center justify-between px-4 py-3 text-left"
              >
                <span className="text-sm font-medium text-foreground">{item.q}</span>
                <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform shrink-0 ml-2 ${openIdx === i ? "rotate-180" : ""}`} />
              </button>
              <AnimatePresence>
                {openIdx === i && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="overflow-hidden"
                  >
                    <p className="px-4 pb-4 text-sm text-muted-foreground leading-relaxed">{item.a}</p>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Final CTA
// ─────────────────────────────────────────────────────────────────────────────

function FinalCTA({ onSignup }: { onSignup: () => void }) {
  return (
    <section className="relative py-24 px-4 border-t border-border/50 overflow-hidden">
      <HeptagonPattern opacity={0.05} />
      <div className="relative max-w-2xl mx-auto text-center">
        <BrandMark size={40} className="mx-auto mb-4" />
        <h2 className="font-heading text-3xl md:text-4xl text-foreground mb-4">
          Prêt à parler à vos données ?
        </h2>
        <p className="text-muted-foreground mb-8">
          Gratuit. Sans carte bancaire. Configuration en 5 minutes.
        </p>
        <button onClick={onSignup}
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-8 py-3 text-base font-medium text-foreground transition-all hover:bg-accent hover:text-accent-foreground hover:scale-[1.02]">
          Commencer maintenant
          <ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Footer
// ─────────────────────────────────────────────────────────────────────────────

function Footer() {
  const cols = [
    { title: "Produit", links: ["Fonctionnalités", "Tarifs", "Démo", "Documentation"] },
    { title: "Entreprise", links: ["À propos", "Blog", "Contact", "Carrières"] },
    { title: "Légal", links: ["CGV", "Politique de confidentialité", "Conditions d'utilisation", "RGPD"] },
  ];

  return (
    <footer className="border-t border-border px-4 py-12">
      <div className="max-w-5xl mx-auto">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8 mb-8">
          <div className="col-span-2 md:col-span-1">
            <BrandLogo size={24} className="mb-2" />
            <p className="text-xs text-muted-foreground max-w-[200px]">{APP_TAGLINE}</p>
          </div>
          {cols.map((col) => (
            <div key={col.title}>
              <h4 className="text-xs font-medium text-foreground mb-3 uppercase tracking-wider">{col.title}</h4>
              <ul className="space-y-2">
                {col.links.map((link) => (
                  <li key={link}>
                    <a href="#" className="text-xs text-muted-foreground hover:text-foreground transition-colors">{link}</a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-8 border-t border-border/50">
          <p className="text-xs text-muted-foreground">© 2025 {APP_NAME}. Tous droits réservés.</p>
          <div className="flex gap-4">
            <a href="#" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Twitter</a>
            <a href="https://github.com/Txchrixo/tevet-7" className="text-xs text-muted-foreground hover:text-foreground transition-colors">GitHub</a>
            <a href="#" className="text-xs text-muted-foreground hover:text-foreground transition-colors">LinkedIn</a>
          </div>
        </div>
      </div>
    </footer>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────────────────────────────────────

interface LandingPageProps {
  onSignup: () => void;
  onDemo: () => void;
}

export function LandingPage({ onSignup, onDemo }: LandingPageProps) {
  return (
    <div className="min-h-screen bg-background">
      <Navbar onSignup={onSignup} onDemo={onDemo} />
      <Hero onSignup={onSignup} onDemo={onDemo} />
      <SocialProof />
      <ProblemSolution />
      <Features />
      <HowItWorks />
      <div id="demo" />
      <UseCases />
      <Pricing onSignup={onSignup} />
      <FAQ />
      <FinalCTA onSignup={onSignup} />
      <Footer />
    </div>
  );
}
