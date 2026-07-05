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

        <div className="hidden md:flex items-center gap-8">
          {navLinks.map((l) => (
            <a key={l.href} href={l.href}
               className="text-sm text-muted-foreground hover:text-foreground transition-colors">
              {l.label}
            </a>
          ))}
        </div>

        <div className="hidden md:flex items-center gap-3">
          <button onClick={onDemo}
            className="text-sm text-muted-foreground hover:text-foreground transition-colors">
            Se connecter
          </button>
          <button onClick={onSignup}
            className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground">
            Essayer gratuitement
          </button>
        </div>

        <button className="md:hidden text-foreground" onClick={() => setMobileOpen(!mobileOpen)}>
          {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="md:hidden bg-background border-b border-border overflow-hidden"
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
            <span className="text-xs text-muted-foreground">Agent IA pour marketplaces B2B</span>
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
// Interactive Demo (looks like a real dashboard screenshot)
// ─────────────────────────────────────────────────────────────────────────────

const DEMO_QUESTIONS = [
  {
    q: "Quels sont mes 5 produits les plus vendus ce mois-ci ?",
    a: "Voici vos 5 produits les plus vendus ce mois-ci :\n\n1. Tomates cœur de bœuf\n   210 unités\n   807,36 €\n2. Courgettes\n   131 unités\n   262,00 €\n3. Carottes en bottes\n   122 unités\n   183,00 €\n4. Salade laitue\n   98 unités\n   147,00 €\n5. Pommes Gala\n   94 unités\n   188,00 €\n\nLes tomates représentent 22% de votre chiffre d'affaires du mois.",
    sql: "SELECT p.name, SUM(oi.quantity) AS units_sold FROM order_items oi JOIN products p ON oi.product_id = p.id GROUP BY p.name ORDER BY units_sold DESC LIMIT 5",
    tag: "Top produits",
    chart: [210, 131, 122, 98, 94],
    chartLabels: ["Tomates", "Courgettes", "Carottes", "Salade", "Pommes"],
  },
  {
    q: "Quel stock va me manquer samedi ?",
    a: "5 produits sont à risque de rupture samedi :\n\n1. Poireaux\n   91% de risque\n   Stock : 2,8 unités\n2. Courgettes\n   90% de risque\n   Stock : 0,9\n3. Salade laitue\n   84% de risque\n   Stock : 3,3\n4. Carottes\n   79% de risque\n   Rupture\n5. Tomates\n   77% de risque\n   Rupture",
    sql: null,
    tag: "Prévision ML",
    chart: [91, 90, 84, 79, 77],
    chartLabels: ["Poireaux", "Courgettes", "Salade", "Carottes", "Tomates"],
  },
  {
    q: "Combien j'ai gagné net de commission en juin ?",
    a: "Votre revenu net en juin :\n\nChiffre d'affaires brut\n4 825,50 €\n\nCommission marketplace (12%)\n579,06 €\n\nRevenu net\n4 246,44 €\n\nSoit +15% par rapport à mai (3 692,54 €).",
    sql: "SELECT SUM(line_total_eur) AS brut FROM order_items oi JOIN orders o ON oi.order_id = o.id WHERE o.created_at >= '2024-06-01' AND o.created_at < '2024-07-01'",
    tag: "Revenu net",
    chart: [4825, 579, 4246],
    chartLabels: ["Brut", "Commission", "Net"],
  },
];

function InteractiveDemo() {
  const [activeIdx, setActiveIdx] = useState(0);
  const [displayedAnswer, setDisplayedAnswer] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [showSql, setShowSql] = useState(false);
  const [showChart, setShowChart] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const activeDemo = DEMO_QUESTIONS[activeIdx];

  useEffect(() => {
    setIsTyping(true);
    setDisplayedAnswer("");
    setShowSql(false);
    setShowChart(false);
    let i = 0;
    const text = activeDemo.a;

    const typeChar = () => {
      if (i < text.length) {
        setDisplayedAnswer(text.slice(0, i + 1));
        i++;
        timeoutRef.current = setTimeout(typeChar, 12);
      } else {
        setIsTyping(false);
        setShowChart(true);
      }
    };

    timeoutRef.current = setTimeout(typeChar, 600);

    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [activeIdx, activeDemo.a]);

  const maxChart = Math.max(...activeDemo.chart);

  return (
    <div className="flex flex-col h-[520px]">
      {/* Window header (dashboard style) */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-secondary/20">
        <div className="flex items-center gap-2">
          <BrandMark size={16} />
          <span className="text-xs text-muted-foreground">Tevet-7 · Drive Producteur</span>
        </div>
        <div className="flex gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-muted-foreground/20" />
          <div className="w-2.5 h-2.5 rounded-full bg-muted-foreground/20" />
          <div className="w-2.5 h-2.5 rounded-full bg-muted-foreground/20" />
        </div>
      </div>

      {/* Chat + chart split (dashboard layout) */}
      <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
        {/* Chat area */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0">
          {/* Question */}
          <div className="flex justify-end">
            <div className="max-w-[85%] rounded-lg rounded-br-sm bg-primary px-3 py-2 text-sm text-foreground">
              {activeDemo.q}
            </div>
          </div>

          {/* Answer */}
          <div className="flex gap-2">
            <div className="shrink-0 w-7 h-7 rounded-full bg-accent/20 flex items-center justify-center mt-0.5">
              <Sparkles className="h-3.5 w-3.5 text-accent" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-xs text-accent mb-1">{activeDemo.tag}</div>
              <div className="text-sm text-foreground whitespace-pre-wrap leading-relaxed font-body">
                {displayedAnswer}
                {isTyping && <span className="inline-block w-1.5 h-4 bg-accent ml-0.5 animate-pulse" />}
              </div>

              {/* SQL toggle */}
              {activeDemo.sql && !isTyping && (
                <button onClick={() => setShowSql(!showSql)}
                  className="mt-2 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
                  <ChevronDown className={`h-3 w-3 transition-transform ${showSql ? "rotate-180" : ""}`} />
                  {showSql ? "Masquer" : "Voir"} la requête SQL
                </button>
              )}
              {showSql && activeDemo.sql && (
                <pre className="mt-1.5 rounded-md bg-secondary/30 border border-border/50 p-2 text-[11px] text-muted-foreground overflow-x-auto">
                  <code>{activeDemo.sql}</code>
                </pre>
              )}
            </div>
          </div>
        </div>

        {/* Chart panel (right side, dashboard style) */}
        <div className="md:w-64 border-t md:border-t-0 md:border-l border-border bg-secondary/10 p-3">
          <div className="text-xs text-muted-foreground mb-3 uppercase tracking-wider">
            {activeDemo.tag === "Prévision ML" ? "Risque de rupture" : activeDemo.tag === "Revenu net" ? "Répartition" : "Unités vendues"}
          </div>
          <AnimatePresence>
            {showChart && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="space-y-2"
              >
                {activeDemo.chart.map((val, i) => (
                  <div key={i} className="space-y-1">
                    <div className="flex justify-between text-[10px] text-muted-foreground">
                      <span>{activeDemo.chartLabels[i]}</span>
                      <span>{activeDemo.tag === "Prévision ML" ? `${val}%` : activeDemo.tag === "Revenu net" ? `${val.toLocaleString('fr-FR')} €` : `${val}`}</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-border/50 overflow-hidden">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${(val / maxChart) * 100}%` }}
                        transition={{ duration: 0.5, delay: i * 0.1 }}
                        className={`h-full rounded-full ${activeDemo.tag === "Prévision ML" ? "bg-amber-600/70" : "bg-accent"}`}
                      />
                    </div>
                  </div>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
          {isTyping && (
            <div className="space-y-2">
              {[0, 1, 2, 3, 4].map((i) => (
                <div key={i} className="space-y-1">
                  <div className="h-2 w-20 rounded bg-border/30 animate-pulse" />
                  <div className="h-1.5 rounded-full bg-border/20" />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Question selector (clickable chips) */}
      <div className="border-t border-border p-3 flex flex-wrap gap-2">
        {DEMO_QUESTIONS.map((d, i) => (
          <button key={i} onClick={() => setActiveIdx(i)}
            className={`rounded-full px-3 py-1 text-xs transition-all ${
              i === activeIdx
                ? "bg-accent text-accent-foreground"
                : "border border-border text-muted-foreground hover:text-foreground hover:border-accent/50"
            }`}>
            {d.tag}
          </button>
        ))}
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
