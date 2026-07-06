"use client";

/**
 * LandingPage - production-grade SaaS landing page with i18n (EN/FR).
 *
 * Sections: Navbar → Hero → Social proof → Problem/Solution → Features →
 * How it works → Use cases → Pricing → FAQ → CTA → Footer
 *
 * Language: English by default, switchable to Français via footer dropdown.
 */

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Shield, Database, Zap, BarChart3, Lock, Users,
  ArrowRight, Check, Menu, X, ChevronDown,
  MessageSquare, Sparkles, TrendingUp, AlertTriangle,
  Globe,
} from "lucide-react";
import { APP_NAME } from "@/lib/constants";
import { BrandMark, BrandLogo } from "@/components/producer-copilot/brand-mark";
import { useCopilotStore } from "@/lib/store";
import {
  Reveal,
  RevealGroup,
  RevealItem,
  HeptagonDraw,
  WordReveal,
  blurFocus,
  slideFromLeft,
  slideFromRight,
  cardRise,
  stepPop,
  cardPlace,
  tierRise,
  tierElevate,
  hazeClear,
  fadeUp,
  scaleIn,
  staggerChildren,
} from "./landing-motion";

// ─────────────────────────────────────────────────────────────────────────────
// i18n dictionary
// ─────────────────────────────────────────────────────────────────────────────

type Lang = "en" | "fr";

const T = {
  en: {
    badge: "Configurable AI agent for your data",
    heroTitle1: "Your data speaks.",
    heroTitle2: "Your AI agent listens.",
    heroSubtitle: "Ask questions in plain English. The AI generates SQL, validates security, and responds in real time. No code. No waiting.",
    ctaSignup: "Get started free",
    ctaDemo: "View demo",
    navFeatures: "Features",
    navHow: "How it works",
    navDemo: "Demo",
    navPricing: "Pricing",
    navFaq: "FAQ",
    navLogin: "Log in",
    navTry: "Try free",
    proofLabel: "Already in production at",
    metrics: [
      { value: "<3s", label: "Avg latency" },
      { value: "39/39", label: "Tests passing" },
      { value: "100%", label: "Data scoped" },
      { value: "5 min", label: "Setup time" },
    ],
    problemTitle: "The problem",
    problemHeadline: "Your teams wait days for SQL reports.",
    problems: [
      "IT support is overwhelmed with requests",
      "Producers can't see their sales in real time",
      "Excel spreadsheets are outdated before they're shared",
      "No one can anticipate stock shortages",
    ],
    solutionTitle: "The solution",
    solutionHeadline: "Your producers talk to their data in plain English.",
    solutions: [
      "Each producer asks questions directly",
      "AI generates and validates SQL automatically",
      "Instant responses with charts",
      "Stock shortage predictions with Machine Learning",
    ],
    featuresTitle: "Everything you need to query your data",
    featuresSubtitle: "Not a chatbot. An enterprise AI agent with security, guardrails, and ML.",
    features: [
      { icon: Database, title: "Smart SQL agent", desc: "Ask a question in plain English. The AI generates SQL, validates it, executes it, and answers." },
      { icon: Shield, title: "Tenant-scoped data", desc: "Each producer only sees their own data. Scoping is injected at the SQL level." },
      { icon: Zap, title: "Real-time responses", desc: "The answer appears as it's generated. No spinner. No waiting." },
      { icon: BarChart3, title: "Automatic charts", desc: "Sales, stock, revenue. Charts generated from your real data." },
      { icon: Lock, title: "Built-in AI protection", desc: "Prompt injection detection, PII masking, content moderation." },
      { icon: Users, title: "Native multi-workspace", desc: "Each workspace has its schema, roles, and agent. Setup in 4 steps." },
    ],
    howTitle: "Setup in 5 minutes",
    howSteps: [
      { num: "01", icon: Database, title: "Connect your data", desc: "PostgreSQL, CSV, or SQLite. Schema is auto-detected." },
      { num: "02", icon: Users, title: "Define roles", desc: "Choose who sees what. Admin, producer, customer. Scope applies everywhere." },
      { num: "03", icon: MessageSquare, title: "Ask questions", desc: "In plain English. AI generates SQL, validates security, executes, and answers with charts." },
    ],
    useCasesTitle: "Use cases",
    useCases: [
      { icon: TrendingUp, title: "B2B Marketplace", desc: "Sales by producer, commissions, top products, shortage forecasts.", example: "What are my top 5 best-selling products this month?" },
      { icon: BarChart3, title: "E-commerce", desc: "Revenue, average basket, conversion, optimal stock by category.", example: "How much did I earn net of commission in June?" },
      { icon: AlertTriangle, title: "Logistics", desc: "Predictive shortages, stock optimization, automatic alerts.", example: "What stock will I run out of on Saturday?" },
    ],
    pricingTitle: "Simple pricing",
    pricingSubtitle: "Start free. Upgrade when you want.",
    pricing: [
      { name: "Discovery", price: "$0", period: "/mo", highlight: false, features: ["1 workspace", "100 questions / month", "SQL agent + RAG", "Scoped data", "Community"], cta: "Get started" },
      { name: "Pro", price: "$49", period: "/mo", highlight: true, features: ["Unlimited workspaces", "10,000 questions / month", "Real-time streaming", "ML stock forecasts", "Advanced guardrails", "Priority support"], cta: "Try 14 days" },
      { name: "Enterprise", price: "Custom", period: "", highlight: false, features: ["Unlimited questions", "SSO (SAML/OIDC)", "On-premise / private cloud", "Persistent audit log", "99.9% SLA", "Dedicated account manager"], cta: "Contact us" },
    ],
    recommended: "Recommended",
    faqTitle: "Frequently asked questions",
    faqs: [
      { q: "Is my data secure?", a: "Yes. Every SQL query is validated by sqlglot, which injects row-level scope at the AST level. A producer can never see another producer's data. The AI generates SQL but never accesses the database directly." },
      { q: "Which AI models are supported?", a: "All OpenAI-compatible models: Groq (Llama), DeepSeek, GLM-4.6, OpenRouter, Gemini. The router tries each provider in order with a circuit breaker. If one goes down, the next takes over automatically." },
      { q: "Can I use my own model?", a: "Yes. Any provider with an OpenAI-compatible API works. Add your key and URL to the config and the router builds the chain automatically." },
      { q: "How long does setup take?", a: "5 minutes. The 4-step onboarding: connect your data (Postgres URL or CSV), schema is auto-detected, select your tables, define roles. Your agent is ready." },
      { q: "How is this different from ChatGPT?", a: "Tevet-7 is multi-tenant with SQL scoping. ChatGPT is not. Tevet-7 connects to your database. Tevet-7 has built-in Machine Learning (stock forecasts). ChatGPT is a generalist chatbot." },
      { q: "Does my data leave my infrastructure?", a: "The AI model generates text (SQL), it never accesses your data directly. The SQL is validated then executed locally. Only metadata (table structure, column names) is sent to the model, never the data itself." },
    ],
    ctaTitle: "Ready to talk to your data?",
    ctaSubtitle: "Free. No credit card. Setup in 5 minutes.",
    ctaButton: "Get started now",
    footerCols: [
      { title: "Product", links: ["Features", "Pricing", "Demo", "Docs"] },
      { title: "Company", links: ["About", "Contact"] },
      { title: "Legal", links: ["Terms", "Privacy"] },
      { title: "Connect", links: ["X (Twitter)", "GitHub", "LinkedIn"] },
    ],
    socialLinks: [
      { label: "GitHub", href: "https://github.com/Txchrixo/tevet-7" },
      { label: "LinkedIn", href: "#" },
    ],
    rights: "All rights reserved.",
    tryAs: "Try as",
    demoScenarios: [
      { role: "producteur" as const, roleLabel: "Marc · Producer", q: "What are my top 5 best-selling products this month?", summary: "Here are your top 5 best-selling products this month. Tomatoes account for 22% of your revenue." },
      { role: "client" as const, roleLabel: "Alexis · Customer", q: "What are my recent orders?", summary: "Here are your 5 most recent orders. Your next pickup is scheduled for Saturday, July 14." },
      { role: "admin" as const, roleLabel: "Maxime · Admin", q: "Which producer generated the most sales this month?", summary: "Here's the producer ranking by sales this month. Ferme du Vallon leads with 1,455.55." },
    ],
    tagline: "Configurable AI agent platform",
  },
  fr: {
    badge: "Agent IA configurable pour vos données",
    heroTitle1: "Vos données parlent.",
    heroTitle2: "Votre agent IA écoute.",
    heroSubtitle: "Posez vos questions en français. L'IA génère le SQL, valide la sécurité, et répond en temps réel. Sans code. Sans attendre.",
    ctaSignup: "Commencer gratuitement",
    ctaDemo: "Voir la démo",
    navFeatures: "Fonctionnalités",
    navHow: "Comment ça marche",
    navDemo: "Démo",
    navPricing: "Tarifs",
    navFaq: "FAQ",
    navLogin: "Se connecter",
    navTry: "Essayer gratuitement",
    proofLabel: "Déjà en production chez",
    metrics: [
      { value: "<3s", label: "Latence moyenne" },
      { value: "39/39", label: "Tests validés" },
      { value: "100%", label: "Données scopées" },
      { value: "5 min", label: "Configuration" },
    ],
    problemTitle: "Le problème",
    problemHeadline: "Vos équipes attendent des jours pour des rapports SQL.",
    problems: [
      "Le support IT est surchargé de requêtes",
      "Les producteurs ne voient pas leurs ventes en temps réel",
      "Les tableaux Excel sont obsolètes avant d'être partagés",
      "Personne ne peut anticiper les ruptures de stock",
    ],
    solutionTitle: "La solution",
    solutionHeadline: "Vos producteurs parlent à leurs données en français.",
    solutions: [
      "Chaque producteur pose ses questions directement",
      "L'IA génère et valide le SQL automatiquement",
      "Réponse immédiate avec graphiques",
      "Prévisions de rupture par Machine Learning",
    ],
    featuresTitle: "Tout ce qu'il faut pour interroger vos données",
    featuresSubtitle: "Pas un chatbot. Un agent IA enterprise avec sécurité, guardrails et Machine Learning.",
    features: [
      { icon: Database, title: "Agent SQL intelligent", desc: "Posez une question en français. L'IA génère le SQL, le valide, l'exécute et vous répond." },
      { icon: Shield, title: "Données scopées par tenant", desc: "Chaque producteur ne voit que ses propres données. Le scoping est injecté au niveau du SQL." },
      { icon: Zap, title: "Réponses en temps réel", desc: "La réponse s'affiche au fur et à mesure. Pas de spinner, pas d'attente." },
      { icon: BarChart3, title: "Graphiques automatiques", desc: "Ventes, stock, revenus. Les graphiques sont générés depuis vos données réelles." },
      { icon: Lock, title: "Protection IA intégrée", desc: "Détection d'injection de prompt, masquage des données personnelles, modération du contenu." },
      { icon: Users, title: "Multi-workspace natif", desc: "Chaque workspace a son schéma, ses rôles et son agent. Configuration en 4 étapes." },
    ],
    howTitle: "Configuration en 5 minutes",
    howSteps: [
      { num: "01", icon: Database, title: "Connectez vos données", desc: "PostgreSQL, CSV ou SQLite. Le schéma est détecté automatiquement." },
      { num: "02", icon: Users, title: "Définissez les rôles", desc: "Choisissez qui voit quoi. Admin, producteur, client. Le scope s'applique partout." },
      { num: "03", icon: MessageSquare, title: "Posez vos questions", desc: "En français. L'IA génère le SQL, valide la sécurité, exécute et répond avec des graphiques." },
    ],
    useCasesTitle: "Cas d'usage",
    useCases: [
      { icon: TrendingUp, title: "Marketplace B2B", desc: "Ventes par producteur, commissions, top produits, prévisions de rupture.", example: "Quels sont mes 5 produits les plus vendus ce mois-ci ?" },
      { icon: BarChart3, title: "E-commerce", desc: "Revenus, panier moyen, conversion, stock optimal par catégorie.", example: "Combien j'ai gagné net de commission en juin ?" },
      { icon: AlertTriangle, title: "Logistique", desc: "Ruptures prévisionnelles, optimisation du stock, alertes automatiques.", example: "Quel stock va me manquer samedi ?" },
    ],
    pricingTitle: "Tarifs simples",
    pricingSubtitle: "Commencez gratuitement. Changez de plan quand vous voulez.",
    pricing: [
      { name: "Découverte", price: "0€", period: "/mois", highlight: false, features: ["1 workspace", "100 questions / mois", "Agent SQL + RAG", "Données scopées", "Communauté"], cta: "Commencer" },
      { name: "Pro", price: "49€", period: "/mois", highlight: true, features: ["Workspaces illimités", "10 000 questions / mois", "Réponses en temps réel", "Prévisions ML (stock)", "Guardrails avancés", "Support prioritaire"], cta: "Essayer 14 jours" },
      { name: "Enterprise", price: "Sur devis", period: "", highlight: false, features: ["Questions illimitées", "SSO (SAML/OIDC)", "On-premise / cloud privé", "Audit log persistant", "SLA 99,9%", "Account manager dédié"], cta: "Nous contacter" },
    ],
    recommended: "Recommandé",
    faqTitle: "Questions fréquentes",
    faqs: [
      { q: "Mes données sont-elles sécurisées ?", a: "Oui. Chaque requête SQL est validée par sqlglot, qui injecte le row-level scope au niveau de l'arbre syntaxique. Un producteur ne peut jamais voir les données d'un autre. L'IA génère du SQL mais n'accède jamais à la base directement." },
      { q: "Quels modèles d'IA sont supportés ?", a: "Tous les modèles compatibles OpenAI : Groq (Llama), DeepSeek, GLM-4.6, OpenRouter, Gemini. Le routeur essaie chaque fournisseur en ordre avec un circuit breaker. Si un modèle tombe, le suivant prend le relais automatiquement." },
      { q: "Puis-je utiliser mon propre modèle ?", a: "Oui. Tout fournisseur avec une API compatible OpenAI fonctionne. Ajoutez votre clé et votre URL dans la configuration et le routeur construit la chaîne automatiquement." },
      { q: "Combien de temps pour la configuration ?", a: "5 minutes. L'onboarding en 4 étapes : connectez vos données (URL Postgres ou CSV), le schéma est détecté, sélectionnez vos tables, définissez les rôles. Votre agent est prêt." },
      { q: "Quelle est la différence avec ChatGPT ?", a: "Tevet-7 est multi-tenant avec scoping SQL. ChatGPT ne l'est pas. Tevet-7 se connecte à votre base de données. Tevet-7 a du Machine Learning intégré (prévisions de stock). ChatGPT est un chatbot généraliste." },
      { q: "Mes données quittent-elles mon infrastructure ?", a: "Le modèle d'IA génère du texte (SQL), il n'accède jamais à vos données directement. Le SQL est validé puis exécuté localement. Seules les métadonnées (structure des tables, noms des colonnes) sont envoyées au modèle, jamais les données elles-mêmes." },
    ],
    ctaTitle: "Prêt à parler à vos données ?",
    ctaSubtitle: "Gratuit. Sans carte bancaire. Configuration en 5 minutes.",
    ctaButton: "Commencer maintenant",
    footerCols: [
      { title: "Produit", links: ["Fonctionnalités", "Tarifs", "Démo", "Documentation"] },
      { title: "Entreprise", links: ["À propos", "Contact"] },
      { title: "Légal", links: ["CGV", "Confidentialité"] },
      { title: "Connect", links: ["X (Twitter)", "GitHub", "LinkedIn"] },
    ],
    socialLinks: [
      { label: "GitHub", href: "https://github.com/Txchrixo/tevet-7" },
      { label: "LinkedIn", href: "#" },
    ],
    rights: "Tous droits réservés.",
    tryAs: "Testez en tant que",
    demoScenarios: [
      { role: "producteur" as const, roleLabel: "Marc · Producteur", q: "Quels sont mes 5 produits les plus vendus ce mois-ci ?", summary: "Voici vos 5 produits les plus vendus ce mois-ci. Les tomates représentent 22% de votre chiffre d'affaires." },
      { role: "client" as const, roleLabel: "Alexis · Client", q: "Quelles sont mes dernières commandes ?", summary: "Voici vos 5 dernières commandes. Votre prochaine livraison est prévue samedi 14 juillet." },
      { role: "admin" as const, roleLabel: "Maxime · Admin", q: "Quel producteur a généré le plus de ventes ce mois-ci ?", summary: "Voici le classement des producteurs par ventes ce mois-ci. La Ferme du Vallon est en tête avec 1 455,55 €." },
    ],
    tagline: "Plateforme d'agents IA configurable",
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// Heptagon background pattern
// ─────────────────────────────────────────────────────────────────────────────

function HeptagonPattern({ opacity = 0.03 }: { opacity?: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const spotlightRef = useRef<HTMLDivElement>(null);
  const rippleRef = useRef<HTMLDivElement>(null);

  // Cursor-following spotlight: a brighter copy of the pattern is revealed
  // through a radial mask that tracks the mouse. The base layer stays dim;
  // only the area near the cursor "wakes up". Uses rAF + direct DOM style
  // updates (no React re-renders) so it's cheap even with two instances.
  useEffect(() => {
    let raf = 0;
    const onMove = (e: MouseEvent) => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const c = containerRef.current;
        const s = spotlightRef.current;
        if (!c || !s) return;
        const rect = c.getBoundingClientRect();
        // Skip work when the section is off-screen.
        if (rect.bottom < 0 || rect.top > window.innerHeight) return;
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const mask = `radial-gradient(circle 260px at ${x}px ${y}px, black 0%, black 38%, transparent 72%)`;
        s.style.WebkitMaskImage = mask;
        s.style.maskImage = mask;
      });
    };
    window.addEventListener("mousemove", onMove, { passive: true });
    return () => {
      window.removeEventListener("mousemove", onMove);
      cancelAnimationFrame(raf);
    };
  }, []);

  // Click ripple: a brief expanding ring at the click point. Re-triggered by
  // toggling a class so it replays on each click. Only fires when the click
  // lands within the section bounds.
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const c = containerRef.current;
      const r = rippleRef.current;
      if (!c || !r) return;
      const rect = c.getBoundingClientRect();
      if (e.clientY < rect.top || e.clientY > rect.bottom) return;
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      r.style.left = `${x}px`;
      r.style.top = `${y}px`;
      // Restart the animation by removing + re-adding the class.
      r.classList.remove("hept-ripple-active");
      void r.offsetWidth; // force reflow
      r.classList.add("hept-ripple-active");
    };
    window.addEventListener("click", onClick, { passive: true });
    return () => window.removeEventListener("click", onClick);
  }, []);

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 pointer-events-none overflow-hidden"
      style={{
        opacity,
        // Fade the pattern out toward the top + bottom edges so it melts into
        // the adjacent sections instead of being cut hard at the seam.
        WebkitMaskImage:
          "linear-gradient(to bottom, transparent 0%, black 18%, black 82%, transparent 100%)",
        maskImage:
          "linear-gradient(to bottom, transparent 0%, black 18%, black 82%, transparent 100%)",
      }}
    >
      {/* Base dim pattern */}
      <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg" className="absolute inset-0">
        <defs>
          <pattern id="heptagon-pattern" x="0" y="0" width="60" height="60" patternUnits="userSpaceOnUse">
            <path d="M 30 8 L 47.7 18.5 L 50.5 38.5 L 37.6 53 L 22.4 53 L 9.5 38.5 L 12.3 18.5 Z" fill="none" stroke="var(--accent, #A8C090)" strokeWidth="0.75" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#heptagon-pattern)" />
      </svg>
      {/* Spotlight layer: same pattern at higher contrast, revealed only near
          the cursor via a radial mask. Opacity lifts ~5x vs base + thicker
          stroke so the "woken up" heptagons are clearly more visible. */}
      <div
        ref={spotlightRef}
        className="absolute inset-0"
        style={{
          opacity: 7,
          WebkitMaskImage: "radial-gradient(circle 0px at -999px -999px, black 0%, transparent 70%)",
          maskImage: "radial-gradient(circle 0px at -999px -999px, black 0%, transparent 70%)",
        }}
      >
        <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg" className="absolute inset-0">
          <defs>
            <pattern id="heptagon-pattern-bright" x="0" y="0" width="60" height="60" patternUnits="userSpaceOnUse">
              <path d="M 30 8 L 47.7 18.5 L 50.5 38.5 L 37.6 53 L 22.4 53 L 9.5 38.5 L 12.3 18.5 Z" fill="none" stroke="var(--accent, #A8C090)" strokeWidth="1.75" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#heptagon-pattern-bright)" />
        </svg>
      </div>
      {/* Click ripple: a brief expanding ring at the click point. */}
      <div
        ref={rippleRef}
        className="hept-ripple pointer-events-none absolute"
        style={{ marginLeft: "-40px", marginTop: "-40px" }}
      />
      <style>{`
        .hept-ripple {
          width: 80px; height: 80px; border-radius: 9999px;
          border: 1px solid var(--accent, #A8C090);
          opacity: 0;
          transform: scale(0.2);
        }
        .hept-ripple.hept-ripple-active {
          animation: hept-ripple 0.9s cubic-bezier(0.16, 1, 0.3, 1);
        }
        @keyframes hept-ripple {
          0%   { opacity: 0.5; transform: scale(0.2); }
          60%  { opacity: 0.18; transform: scale(2.4); }
          100% { opacity: 0; transform: scale(3.2); }
        }
      `}</style>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Navbar
// ─────────────────────────────────────────────────────────────────────────────

function Navbar({ t, onLogin, onSignup }: { t: typeof T.en; onLogin: () => void; onSignup: () => void }) {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const navLinks = [
    { label: t.navFeatures, href: "#features" },
    { label: t.navHow, href: "#how" },
    { label: t.navDemo, href: "#demo" },
    { label: t.navPricing, href: "#pricing" },
    { label: t.navFaq, href: "#faq" },
  ];

  return (
    <nav className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${scrolled ? "bg-background/90 backdrop-blur-md" : "bg-transparent"}`}>
      <div className="max-w-[1230px] mx-auto px-4 lg:px-0 h-16 flex items-center justify-between">
        {/* Logo: clickable → scroll to top (home) */}
        <a href="#" onClick={(e) => { e.preventDefault(); window.scrollTo({ top: 0, behavior: "smooth" }); }} className="cursor-pointer">
          <BrandLogo size={26} />
        </a>
        {/* Nav links: hidden on < md */}
        <div className="hidden md:flex items-center gap-6">
          {navLinks.map((l) => (<a key={l.href} href={l.href} className="text-sm text-muted-foreground hover:text-foreground transition-colors">{l.label}</a>))}
        </div>
        {/* CTAs: "Log in" hidden on < sm, "Try free" always visible.
            "Log in" opens the AuthScreen in login mode; "Try free" opens
            it in signup mode. Neither starts the demo - the demo is only
            triggered from the Hero's "View demo" button. */}
        <div className="flex items-center gap-2 sm:gap-3">
          <button onClick={onLogin} className="hidden sm:block text-sm text-muted-foreground hover:text-foreground transition-colors">{t.navLogin}</button>
          <button onClick={onSignup} className="rounded-lg bg-primary px-3 sm:px-4 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground whitespace-nowrap">{t.navTry}</button>
          {/* Hamburger: only on < md */}
          <button className="md:hidden text-foreground ml-1" onClick={() => setMobileOpen(!mobileOpen)}>
            {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>
      <AnimatePresence>
        {mobileOpen && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="md:hidden bg-background border-b border-border overflow-hidden">
            <div className="px-4 py-4 space-y-3">
              {navLinks.map((l) => (<a key={l.href} href={l.href} onClick={() => setMobileOpen(false)} className="block text-sm text-muted-foreground hover:text-foreground">{l.label}</a>))}
              <button onClick={() => { setMobileOpen(false); onLogin(); }} className="block w-full text-left text-sm text-muted-foreground hover:text-foreground">{t.navLogin}</button>
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

function Hero({ t, onSignup, onDemo }: { t: typeof T.en; onSignup: () => void; onDemo: () => void }) {
  return (
    <section className="relative pt-32 pb-20 px-4 overflow-hidden">
      <HeptagonPattern opacity={0.1} />
      <div className="absolute inset-0 bg-gradient-to-b from-primary/5 via-transparent to-transparent pointer-events-none" />
      <div className="relative max-w-4xl mx-auto text-center">
        {/* Badge scales in with a soft overshoot — "chip materializing" */}
        <Reveal variants={scaleIn} amount={0.5} className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 mb-6">
          <Sparkles className="h-3 w-3 text-accent" />
          <span className="text-xs text-muted-foreground">{t.badge}</span>
        </Reveal>
        {/* Headline: word-by-word reveal, two lines. The second line (accent)
            starts after the first so the color shift lands deliberately. */}
        <h1 className="font-heading text-4xl md:text-6xl text-foreground leading-tight mb-4">
          <WordReveal text={t.heroTitle1} stagger={0.08} />
          <br />
          <span className="text-accent">
            <WordReveal text={t.heroTitle2} stagger={0.08} delay={0.3} />
          </span>
        </h1>
        <Reveal variants={fadeUp} amount={0.5} delay={0.5}>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto mb-8">{t.heroSubtitle}</p>
        </Reveal>
        <RevealGroup variants={staggerChildren(0.1, 0.65)} amount={0.5} className="flex flex-col sm:flex-row gap-3 justify-center mb-6">
          <RevealItem variants={scaleIn}>
            <button onClick={onSignup} className="inline-flex items-center gap-2 rounded-lg bg-primary px-7 py-3 text-base font-medium text-foreground transition-all hover:bg-accent hover:text-accent-foreground hover:scale-[1.02]">{t.ctaSignup}<ArrowRight className="h-4 w-4" /></button>
          </RevealItem>
          <RevealItem variants={scaleIn}>
            <button onClick={onDemo} className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-7 py-3 text-base font-medium text-foreground transition-all hover:bg-secondary/40">{t.ctaDemo}</button>
          </RevealItem>
        </RevealGroup>
      </div>
      {/* Demo window framed by the artwork. Desktop target: frame 1230×720,
          window 1080×620 (75px horizontal matting, 50px vertical matting).
          Responsive: frame shrinks to w-full with smaller heights on
          mobile (480px) and tablet (560px); padding reduces too. The window
          fills the frame's content box; its content area scrolls internally
          (themed scrollbar) to reveal the full agent answer. */}
      <Reveal variants={cardPlace} amount={0.2} delay={0.2} className="relative mx-auto mt-12 w-full max-w-[1230px]" style={{ perspective: "1200px" }}>
        <div
          className="rounded-lg border border-border/60 shadow-2xl flex items-stretch justify-center h-[480px] sm:h-[560px] lg:h-[720px] px-3 py-3 sm:px-4 sm:py-4 lg:px-[75px] lg:py-[50px]"
          style={{
            backgroundImage: "url('/art-bg.webp')",
            backgroundSize: "cover",
            backgroundPosition: "center",
          }}
        >
          <div className="rounded-lg border border-border bg-card overflow-hidden shadow-xl ring-1 ring-black/30 w-full h-full">
            <InteractiveDemo t={t} />
          </div>
        </div>
      </Reveal>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Interactive Demo
// ─────────────────────────────────────────────────────────────────────────────

interface DemoScenario {
  role: string;
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

const DEMO_DATA: Record<string, Omit<DemoScenario, "role" | "roleLabel" | "q" | "summary">> = {
  producteur: {
    table: { headers: ["Produit", "Unités", "CA"], rows: [["Tomates cœur de bœuf", "180", "807,36 €"], ["Courgettes", "102", "204,00 €"], ["Carottes en bottes", "95", "142,50 €"], ["Salade laitue", "88", "132,00 €"], ["Pommes Gala", "75", "150,00 €"]] },
    sql: "SELECT p.name AS name, SUM(oi.quantity) AS units_sold, ROUND(SUM(oi.line_total_eur), 2) AS revenue FROM order_items AS oi JOIN products AS p ON oi.product_id = p.id JOIN orders AS o ON oi.order_id = o.id WHERE o.created_at >= date('2024-07-01', 'start of month') GROUP BY p.name ORDER BY units_sold DESC LIMIT 5",
    scope: "FULL ACCESS", tokens: "1 168", latency: "2,7", tagLabel: "SQL",
    chartTitle: "Units sold by product",
    chartData: [{ name: "Tomates", value: 180, display: "180" }, { name: "Courgettes", value: 102, display: "102" }, { name: "Carottes", value: 95, display: "95" }, { name: "Salade", value: 88, display: "88" }, { name: "Pommes", value: 75, display: "75" }],
    chartColor: "accent" as const,
  },
  client: {
    table: { headers: ["Date", "Producer", "Amount", "Status"], rows: [["12/07", "Ferme du Vallon", "48,50 €", "Ready"], ["10/07", "Vignoble des Coteaux", "32,00 €", "Picked up"], ["07/07", "Maraîchage Bio Soleil", "27,30 €", "Picked up"], ["05/07", "Fromagerie du Col", "15,80 €", "Picked up"], ["03/07", "Élevage du Vernet", "63,20 €", "Picked up"]] },
    sql: "SELECT o.created_at AS date, p.name AS producer, ROUND(SUM(oi.line_total_eur), 2) AS amount, o.status FROM orders AS o JOIN order_items AS oi ON oi.order_id = o.id JOIN producers AS p ON oi.producer_id = p.id WHERE o.customer_id = :customer_id GROUP BY o.id ORDER BY o.created_at DESC LIMIT 5",
    scope: "SCOPE VERIFIED", tokens: "980", latency: "1,8", tagLabel: "SQL",
    chartTitle: "Amount per order",
    chartData: [{ name: "12/07", value: 49, display: "49 €" }, { name: "10/07", value: 32, display: "32 €" }, { name: "07/07", value: 27, display: "27 €" }, { name: "05/07", value: 16, display: "16 €" }, { name: "03/07", value: 63, display: "63 €" }],
    chartColor: "accent" as const,
  },
  admin: {
    table: { headers: ["Producer", "Orders", "Revenue"], rows: [["Ferme du Vallon", "123", "1 455,55 €"], ["Maraîchage Bio Soleil", "98", "1 203,20 €"], ["Élevage du Vernet", "67", "890,40 €"], ["Vignoble des Coteaux", "45", "1 739,49 €"], ["Fromagerie du Col", "34", "542,10 €"]] },
    sql: "SELECT p.name AS name, COUNT(o.id) AS commandes, ROUND(SUM(oi.line_total_eur), 2) AS revenue FROM order_items AS oi JOIN orders AS o ON oi.order_id = o.id JOIN producers AS p ON oi.producer_id = p.id GROUP BY p.name ORDER BY revenue DESC LIMIT 5",
    scope: "FULL ACCESS", tokens: "1 450", latency: "3,1", tagLabel: "SQL",
    chartTitle: "Sales by producer",
    chartData: [{ name: "Vallon", value: 1456, display: "1 456 €" }, { name: "Bio Soleil", value: 1203, display: "1 203 €" }, { name: "Vernet", value: 890, display: "890 €" }, { name: "Coteaux", value: 1739, display: "1 739 €" }, { name: "Col", value: 542, display: "542 €" }],
    chartColor: "accent" as const,
  },
};

const SQL_KEYWORDS = new Set(["SELECT", "FROM", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "ON", "GROUP", "BY", "ORDER", "HAVING", "LIMIT", "AND", "OR", "IN", "NOT", "AS", "DESC", "ASC", "COUNT", "SUM", "COALESCE", "DISTINCT", "CASE", "WHEN", "THEN", "ELSE", "END", "DATE", "ROUND", "MAX", "MIN", "AVG"]);

function renderSqlTokens(text: string) {
  const tokenRe = /('(?:[^']|'')*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|([(),.;*=<>+\-/]+)|(\s+)|([^\s])/g;
  const nodes: React.ReactNode[] = [];
  let m: RegExpExecArray | null; let key = 0;
  while ((m = tokenRe.exec(text)) !== null) {
    const [full, str, num, ident, punct, ws] = m;
    if (str) nodes.push(<span key={key++} className="text-foreground/90">{str}</span>);
    else if (num) nodes.push(<span key={key++} className="font-heading text-muted-foreground tabular-nums">{num}</span>);
    else if (ident) { const upper = ident.toUpperCase(); if (SQL_KEYWORDS.has(upper)) nodes.push(<span key={key++} className="font-medium text-accent/90">{ident}</span>); else nodes.push(<span key={key++} className="text-foreground">{ident}</span>); }
    else if (punct) nodes.push(<span key={key++} className="text-muted-foreground">{punct}</span>);
    else if (ws) nodes.push(ws);
    else nodes.push(full);
  }
  return nodes;
}

function InteractiveDemo({ t }: { t: typeof T.en }) {
  const [activeIdx, setActiveIdx] = useState(0);
  const scenario = t.demoScenarios[activeIdx];
  const data = DEMO_DATA[scenario.role];
  const maxChart = Math.max(...data.chartData.map((d) => d.value));

  return (
    <div className="flex flex-col bg-background text-left h-full">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-secondary/20 shrink-0">
        <div className="flex items-center gap-2"><BrandMark size={16} className="shrink-0" /><span className="text-xs text-muted-foreground">{APP_NAME} · Drive Producteur</span></div>
        <div className="flex gap-2"><div className="w-3 h-3 rounded-full bg-red-500/80" /><div className="w-3 h-3 rounded-full bg-yellow-500/80" /><div className="w-3 h-3 rounded-full bg-green-500/80" /></div>
      </div>
      <div className="p-4 space-y-4 text-left flex-1 min-h-0 overflow-y-auto demo-scroll">
        <AnimatePresence mode="wait">
          <motion.div key={`q-${activeIdx}`} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }} className="flex justify-end">
            <div className="max-w-[80%] rounded-lg rounded-br-sm bg-primary px-3 py-2 text-sm text-foreground text-left">{scenario.q}</div>
          </motion.div>
        </AnimatePresence>
        <AnimatePresence mode="wait">
          <motion.div key={`a-${activeIdx}`} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.15, delay: 0.05 }} className="flex justify-start text-left">
            <div className="flex items-start gap-2.5 w-full text-left">
              <span className="flex w-8 h-8 shrink-0 items-center justify-center rounded-md border border-border bg-background"><BrandMark size={18} className="shrink-0" /></span>
              <div className="flex-1 min-w-0 max-w-[640px] rounded-lg border border-border bg-background p-4 text-left">
                <p className="text-sm text-foreground leading-relaxed font-body mb-3 text-left">{scenario.summary}</p>
                <div className="overflow-x-auto mb-3 text-left">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead><tr className="border-b border-border">{data.table.headers.map((h, i) => (<th key={i} className={`py-1.5 px-2 font-heading text-muted-foreground font-medium ${i === 0 ? "text-left" : "text-right"}`}>{h}</th>))}</tr></thead>
                    <tbody>{data.table.rows.map((row, ri) => (<tr key={ri} className="border-b border-border/40 hover:bg-secondary/10 transition-colors">{row.map((cell, ci) => (<td key={ci} className={`py-1.5 px-2 ${ci === 0 ? "text-left text-foreground font-body" : "text-right text-muted-foreground tabular-nums"}`}>{cell}</td>))}</tr>))}</tbody>
                  </table>
                </div>
                <div className="rounded-md border border-border bg-background p-3 mb-3 text-left">
                  <div className="mb-3"><span className="font-heading text-xs text-foreground">{data.chartTitle}</span></div>
                  <div className="h-32 flex items-end justify-between gap-2 px-1">{data.chartData.map((item, i) => (<div key={i} className="flex-1 flex flex-col items-center gap-1 h-full justify-end min-w-0"><span className="text-[10px] text-muted-foreground tabular-nums whitespace-nowrap">{item.display}</span><motion.div initial={{ height: 0 }} animate={{ height: `${(item.value / maxChart) * 100}%` }} transition={{ duration: 0.4, delay: i * 0.06 }} className={`w-full rounded-t-sm min-h-[4px] ${data.chartColor === "amber" ? "bg-amber-600/60" : "bg-accent"}`} /><span className="text-[10px] text-muted-foreground truncate max-w-full">{item.name}</span></div>))}</div>
                </div>
                {data.sql && (<div className="mb-3 text-left"><details className="group"><summary className="flex cursor-pointer items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted-foreground hover:text-foreground list-none"><ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180 shrink-0" /><Database size={11} className="shrink-0" />SQL</summary><div className="mt-1.5 rounded-md border border-border bg-secondary/20 p-2.5 overflow-x-auto"><pre className="text-[11px] leading-relaxed font-mono"><code>{renderSqlTokens(data.sql)}</code></pre></div></details></div>)}
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-2 text-[11px] uppercase tracking-wide text-muted-foreground">
                  <span className="inline-flex items-center gap-1"><Check size={12} className="text-accent shrink-0" />{data.scope}</span>
                  <span className="inline-flex items-center gap-1"><span className="font-heading text-foreground tabular-nums">{data.tokens}</span>tokens</span>
                  <span className="inline-flex items-center gap-1"><span className="font-heading text-foreground tabular-nums">{data.latency}</span>s</span>
                  <span className="inline-flex items-center gap-1 rounded-md border border-border bg-secondary px-1.5 text-[10px] text-muted-foreground whitespace-nowrap"><Database size={10} className="shrink-0" />{data.tagLabel}</span>
                </div>
              </div>
            </div>
          </motion.div>
        </AnimatePresence>
      </div>
      <div className="border-t border-border px-4 py-2 text-center shrink-0">
        <span className="text-[10px] text-muted-foreground/60">{t.tryAs} {t.demoScenarios.map((s, i) => (<button key={s.role} onClick={() => setActiveIdx(i)} className={`mx-1 underline-offset-2 hover:underline ${i === activeIdx ? "text-accent font-medium" : ""}`}>{s.roleLabel}</button>))}</span>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Remaining sections (SocialProof, ProblemSolution, Features, HowItWorks, UseCases, Pricing, FAQ, CTA, Footer)
// ─────────────────────────────────────────────────────────────────────────────

function SocialProof({ t }: { t: typeof T.en }) {
  return (
    <section className="py-10">
      <div className="max-w-4xl mx-auto px-4">
        <Reveal variants={fadeUp} amount={0.4}>
          <p className="text-center text-xs text-muted-foreground/60 mb-6 uppercase tracking-wider">{t.proofLabel}</p>
        </Reveal>
        <Reveal variants={blurFocus} amount={0.4} className="flex items-center justify-center">
          <img src="/drive-logo.png" alt="Drive Producteur" className="h-12 sm:h-16 md:h-20 opacity-40 brightness-75 saturate-50 hover:opacity-100 hover:brightness-100 hover:saturate-100 transition-all duration-300" />
        </Reveal>
        <RevealGroup variants={staggerChildren(0.12, 0.1)} amount={0.4} className="flex items-center justify-center gap-8 mt-6 flex-wrap">
          {t.metrics.map((s) => (
            <RevealItem key={s.label} variants={blurFocus} className="text-center">
              <div className="font-heading text-xl text-foreground">{s.value}</div>
              <div className="text-[10px] text-muted-foreground">{s.label}</div>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  );
}

function ProblemSolution({ t }: { t: typeof T.en }) {
  return (
    <section className="py-20 px-4">
      <div className="max-w-4xl mx-auto">
        <div className="grid md:grid-cols-2 gap-8">
          {/* Problem column: slides in from the left, slightly tilted — "heavier, dragging in" */}
          <Reveal variants={slideFromLeft} amount={0.2} className="space-y-4">
            <div className="flex items-center gap-2 text-destructive"><AlertTriangle className="h-5 w-5" /><span className="text-sm font-medium">{t.problemTitle}</span></div>
            <h3 className="font-heading text-2xl text-foreground">{t.problemHeadline}</h3>
            <RevealGroup variants={staggerChildren(0.08, 0.2)} className="space-y-2 text-sm text-muted-foreground">
              {t.problems.map((p, i) => (
                <RevealItem key={i} variants={fadeUp} className="flex items-start gap-2">
                  <X className="h-4 w-4 text-destructive/60 shrink-0 mt-0.5" />{p}
                </RevealItem>
              ))}
            </RevealGroup>
          </Reveal>
          {/* Solution column: slides in from the right, delayed — "lighter, resolving the tension" */}
          <Reveal variants={slideFromRight} amount={0.2} delay={0.15} className="space-y-4">
            <div className="flex items-center gap-2 text-accent"><Check className="h-5 w-5" /><span className="text-sm font-medium">{t.solutionTitle}</span></div>
            <h3 className="font-heading text-2xl text-foreground">{t.solutionHeadline}</h3>
            <RevealGroup variants={staggerChildren(0.08, 0.35)} className="space-y-2 text-sm text-muted-foreground">
              {t.solutions.map((s, i) => (
                <RevealItem key={i} variants={fadeUp} className="flex items-start gap-2">
                  <Check className="h-4 w-4 text-accent shrink-0 mt-0.5" />{s}
                </RevealItem>
              ))}
            </RevealGroup>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function Features({ t }: { t: typeof T.en }) {
  return (
    <section id="features" className="py-20 px-4">
      <div className="max-w-5xl mx-auto">
        <Reveal variants={fadeUp} amount={0.3}>
          <h2 className="font-heading text-3xl text-foreground text-center mb-3">{t.featuresTitle}</h2>
        </Reveal>
        <Reveal variants={fadeUp} amount={0.3} delay={0.1}>
          <p className="text-center text-muted-foreground mb-12 max-w-xl mx-auto">{t.featuresSubtitle}</p>
        </Reveal>
        {/* Diagonal cascade: staggerChildren creates a sweep across the grid
            (left-to-right, row-by-row) so cards "assemble" rather than pop together. */}
        <RevealGroup variants={staggerChildren(0.08, 0.15)} amount={0.15} className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-px bg-border/30 rounded-lg overflow-hidden">
          {t.features.map((f) => (
            <RevealItem key={f.title} variants={cardRise} className="bg-card p-6 hover:bg-secondary/20 transition-colors">
              <f.icon className="h-6 w-6 text-accent mb-3" strokeWidth={1.5} />
              <h3 className="font-heading text-base text-foreground mb-1.5">{f.title}</h3>
              <p className="text-sm text-muted-foreground leading-relaxed">{f.desc}</p>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  );
}

function HowItWorks({ t }: { t: typeof T.en }) {
  return (
    <section id="how" className="py-20 px-4">
      <div className="max-w-4xl mx-auto">
        <Reveal variants={fadeUp} amount={0.3}>
          <h2 className="font-heading text-3xl text-foreground text-center mb-12">{t.howTitle}</h2>
        </Reveal>
        {/* Sequential reveal: each step pops in one after another (0 / 0.25 / 0.5s)
            so the process literally "unfolds" rather than appearing at once. */}
        <RevealGroup variants={staggerChildren(0.25, 0.2)} amount={0.2} className="grid md:grid-cols-3 gap-8 relative">
          {/* Connecting line that draws itself behind the steps (desktop only) */}
          <motion.div
            className="hidden md:block absolute top-6 left-[16.66%] right-[16.66%] h-px bg-border origin-left"
            initial={{ scaleX: 0 }}
            whileInView={{ scaleX: 1 }}
            viewport={{ once: false, amount: 0.3 }}
            transition={{ duration: 1.2, ease: [0.16, 1, 0.3, 1], delay: 0.3 }}
          />
          {t.howSteps.map((s) => (
            <RevealItem key={s.num} variants={stepPop} className="text-center relative">
              <div className="inline-flex items-center justify-center w-12 h-12 rounded-full border border-border bg-background mb-4 relative z-10"><s.icon className="h-5 w-5 text-accent" strokeWidth={1.5} /></div>
              <div className="font-heading text-xs text-muted-foreground/50 mb-1">{s.num}</div>
              <h3 className="font-heading text-base text-foreground mb-2">{s.title}</h3>
              <p className="text-sm text-muted-foreground">{s.desc}</p>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  );
}

function UseCases({ t }: { t: typeof T.en }) {
  return (
    <section className="py-20 px-4">
      <div className="max-w-4xl mx-auto">
        <Reveal variants={fadeUp} amount={0.3}>
          <h2 className="font-heading text-3xl text-foreground text-center mb-12">{t.useCasesTitle}</h2>
        </Reveal>
        {/* 3D card-place: each card tilts in from rotateX(10deg) as if laid on a
            table, staggered. The perspective is set on the parent so the tilt
            reads as depth, not a flat skew. */}
        <RevealGroup variants={staggerChildren(0.14, 0.15)} amount={0.2} className="grid md:grid-cols-3 gap-6" style={{ perspective: "1000px" }}>
          {t.useCases.map((c) => (
            <RevealItem key={c.title} variants={cardPlace} className="rounded-lg border border-border bg-card p-5" style={{ transformStyle: "preserve-3d" }}>
              <c.icon className="h-6 w-6 text-accent mb-3" strokeWidth={1.5} />
              <h3 className="font-heading text-base text-foreground mb-1.5">{c.title}</h3>
              <p className="text-sm text-muted-foreground mb-3">{c.desc}</p>
              <div className="rounded-md bg-secondary/20 border border-border/50 p-2.5">
                <p className="text-xs text-muted-foreground italic">{c.example}</p>
              </div>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  );
}

function Pricing({ t, onSignup }: { t: typeof T.en; onSignup: () => void }) {
  return (
    <section id="pricing" className="py-20 px-4">
      <div className="max-w-4xl mx-auto">
        <Reveal variants={fadeUp} amount={0.3}>
          <h2 className="font-heading text-3xl text-foreground text-center mb-3">{t.pricingTitle}</h2>
        </Reveal>
        <Reveal variants={fadeUp} amount={0.3} delay={0.1}>
          <p className="text-center text-muted-foreground mb-12">{t.pricingSubtitle}</p>
        </Reveal>
        {/* The highlighted (Pro) tier uses tierElevate (rises higher + scales up +
            delayed) so it visibly "lifts above" the side tiers, which use tierRise.
            This makes the recommendation feel physical, not just a colored border. */}
        <RevealGroup variants={staggerChildren(0.1, 0.1)} amount={0.2} className="grid md:grid-cols-3 gap-6 items-start">
          {t.pricing.map((tier) => (
            <RevealItem key={tier.name} variants={tier.highlight ? tierElevate : tierRise} className={`rounded-lg border p-6 ${tier.highlight ? "border-accent bg-accent/5" : "border-border bg-card"}`}>
              {tier.highlight && <span className="mb-3 inline-block rounded-full bg-accent/20 px-2.5 py-0.5 text-[10px] font-medium text-accent-foreground">{t.recommended}</span>}
              <h3 className="font-heading text-lg text-foreground mb-1">{tier.name}</h3>
              <div className="mb-4"><span className="font-heading text-3xl text-foreground">{tier.price}</span><span className="text-sm text-muted-foreground">{tier.period}</span></div>
              <ul className="space-y-1.5 mb-5">{tier.features.map((feat) => (<li key={feat} className="flex items-start gap-2 text-sm text-muted-foreground"><Check className="h-3.5 w-3.5 text-accent shrink-0 mt-0.5" />{feat}</li>))}</ul>
              <button onClick={onSignup} className={`w-full rounded-md px-4 py-2 text-sm font-medium transition-colors ${tier.highlight ? "bg-primary text-foreground hover:bg-accent hover:text-accent-foreground" : "border border-border text-foreground hover:bg-secondary/40"}`}>{tier.cta}</button>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  );
}

function FAQ({ t }: { t: typeof T.en }) {
  const [openIdx, setOpenIdx] = useState<number | null>(0);
  return (
    <section id="faq" className="relative py-20 px-4 overflow-hidden">
      {/*
        Painted artwork behind the FAQ content, constrained to the page
        max-width (1230px). Only the TOP corners are rounded (rounded-t-xl);
        the bottom is square so it meets the FinalCTA section cleanly. The
        painting itself fades to transparent at the bottom via a CSS mask
        (no dark green scrim overlay) — the image just dissolves into
        whatever is behind it.
      */}
      <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-full max-w-[1230px] px-4 pointer-events-none">
        <div
          className="relative w-full h-full rounded-t-xl overflow-hidden"
          style={{
            backgroundImage: "url('/art-bg-2.webp')",
            backgroundSize: "cover",
            backgroundPosition: "center",
            filter: "brightness(0.85) saturate(0.85) contrast(1.03)",
            // Mask the painting itself so it fades to transparent at the
            // bottom — no dark green overlay, the image just dissolves.
            WebkitMaskImage:
              "linear-gradient(to bottom, black 0%, black 72%, transparent 100%)",
            maskImage:
              "linear-gradient(to bottom, black 0%, black 72%, transparent 100%)",
          }}
        />
      </div>
      <div className="relative max-w-2xl mx-auto">
        <Reveal variants={fadeUp} amount={0.3}>
          <h2 className="font-heading text-3xl text-foreground text-center mb-12">{t.faqTitle}</h2>
        </Reveal>
        {/* Each question "surfaces from a haze": starts blurred + low, clears as
            it enters. Staggered so they emerge one-by-one like thoughts forming.
            The cards (bg-card, opaque) float on top of the painted wallpaper. */}
        <RevealGroup variants={staggerChildren(0.07, 0.1)} amount={0.15} className="space-y-2">
          {t.faqs.map((item, i) => (
            <RevealItem key={i} variants={hazeClear} className="rounded-lg border border-border bg-card/90 backdrop-blur-sm overflow-hidden shadow-lg">
              <button onClick={() => setOpenIdx(openIdx === i ? null : i)} className="w-full flex items-center justify-between px-4 py-3 text-left">
                <span className="text-sm font-medium text-foreground">{item.q}</span>
                <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform shrink-0 ml-2 ${openIdx === i ? "rotate-180" : ""}`} />
              </button>
              <AnimatePresence>{openIdx === i && (<motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden"><p className="px-4 pb-4 text-sm text-muted-foreground leading-relaxed">{item.a}</p></motion.div>)}</AnimatePresence>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  );
}

function FinalCTA({ t, onSignup }: { t: typeof T.en; onSignup: () => void }) {
  return (
    <section className="relative py-24 px-4 overflow-hidden">
      <HeptagonPattern opacity={0.11} />
      <div className="relative max-w-2xl mx-auto text-center">
        {/* The heptagon outline draws itself in (strokeDashoffset), then the
            top-vertex node pops in — "the call crystallizes". Replaces the
            static BrandMark with the animated HeptagonDraw. */}
        <Reveal variants={scaleIn} amount={0.5} className="flex justify-center mb-4">
          <HeptagonDraw size={40} />
        </Reveal>
        <h2 className="font-heading text-3xl md:text-4xl text-foreground mb-4">
          <WordReveal text={t.ctaTitle} stagger={0.08} delay={0.3} />
        </h2>
        <Reveal variants={fadeUp} amount={0.5} delay={0.6}>
          <p className="text-muted-foreground mb-8">{t.ctaSubtitle}</p>
        </Reveal>
        <Reveal variants={scaleIn} amount={0.5} delay={0.8}>
          <button onClick={onSignup} className="inline-flex items-center gap-2 rounded-lg bg-primary px-8 py-3 text-base font-medium text-foreground transition-all hover:bg-accent hover:text-accent-foreground hover:scale-[1.02]">{t.ctaButton}<ArrowRight className="h-4 w-4" /></button>
        </Reveal>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Language switcher + Footer
// ─────────────────────────────────────────────────────────────────────────────

function LanguageSwitcher({ lang, setLang }: { lang: Lang; setLang: (l: Lang) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"><Globe size={14} />{lang === "en" ? "English" : "Français"}<ChevronDown size={12} className={`transition-transform ${open ? "rotate-180" : ""}`} /></button>
      {open && (<div className="absolute bottom-full right-0 mb-1 rounded-md border border-border bg-card py-1 min-w-[120px] z-10"><button onClick={() => { setLang("en"); setOpen(false); }} className={`block w-full px-3 py-1.5 text-left text-xs hover:bg-secondary/30 ${lang === "en" ? "text-accent font-medium" : "text-muted-foreground"}`}>English</button><button onClick={() => { setLang("fr"); setOpen(false); }} className={`block w-full px-3 py-1.5 text-left text-xs hover:bg-secondary/30 ${lang === "fr" ? "text-accent font-medium" : "text-muted-foreground"}`}>Français</button></div>)}
    </div>
  );
}

function Footer({ t, lang, setLang }: { t: typeof T.en; lang: Lang; setLang: (l: Lang) => void }) {
  // Map link labels to routes
  const linkHref = (link: string): string => {
    const map: Record<string, string> = {
      "Features": "#features", "Pricing": "#pricing", "Demo": "#demo", "Docs": "/docs",
      "About": "/about", "Contact": "/contact",
      "Terms": "/terms", "Privacy": "/privacy",
      "Fonctionnalités": "#features", "Tarifs": "#pricing", "Démo": "#demo", "Documentation": "/docs",
      "À propos": "/about", "Contact": "/contact",
      "CGV": "/terms", "Confidentialité": "/privacy",
      "X (Twitter)": "https://x.com", "GitHub": "https://github.com/Txchrixo/tevet-7", "LinkedIn": "#",
    };
    return map[link] || "#";
  };

  return (
    <footer
      className="relative px-4 py-12 overflow-hidden"
      style={{
        // Progressive passage from the FinalCTA background (top) into the
        // footer's secondary color (bottom). The gradient holds var(--background)
        // solid for the first 20% so the seam with the FinalCTA is invisible,
        // then eases to the full var(--secondary) tint toward the bottom —
        // the progression is now clearly perceptible but still gradual.
        background:
          "linear-gradient(to bottom, var(--background) 0%, var(--background) 20%, color-mix(in srgb, var(--secondary) 50%, var(--background)) 45%, var(--secondary) 80%, var(--secondary) 100%)",
      }}
    >
      {/* Filigree: large BrandMark watermark in the background — slow fades in
          to its resting opacity (0.08). Custom variant because fadeUp would
          animate to opacity:1 which is wrong for a watermark. A radial mask
          softens the edges so the heptagon melts into the footer instead of
          being cut hard by the overflow-hidden boundary. */}
      <Reveal
        variants={{ hidden: { opacity: 0 }, visible: { opacity: 0.08, transition: { duration: 1.6, ease: [0.16, 1, 0.3, 1] } } }}
        amount={0.3}
        className="absolute -right-8 -bottom-8 pointer-events-none"
        style={{
          WebkitMaskImage:
            "radial-gradient(ellipse at 35% 35%, black 35%, transparent 80%)",
          maskImage:
            "radial-gradient(ellipse at 35% 35%, black 35%, transparent 80%)",
        }}
      >
        <BrandMark size={280} />
      </Reveal>
      <div className="relative max-w-5xl mx-auto">
        {/* Columns stagger in from below — the footer "settles into place" */}
        <RevealGroup variants={staggerChildren(0.08, 0.1)} amount={0.2} className="flex flex-wrap gap-8 mb-8">
          {t.footerCols.map((col) => (
            <RevealItem key={col.title} variants={fadeUp} className="w-1/2 sm:w-1/4 md:w-auto lg:flex-1 min-w-[120px]">
              <h4 className="text-xs font-medium text-foreground mb-3 uppercase tracking-wider">{col.title}</h4>
              <ul className="space-y-2">{col.links.map((link) => (<li key={link}><a href={linkHref(link)} className="text-xs text-muted-foreground hover:text-foreground transition-colors">{link}</a></li>))}</ul>
            </RevealItem>
          ))}
        </RevealGroup>
        {/* Bottom bar: copyright + social links + language switcher */}
        <Reveal variants={fadeUp} amount={0.3} delay={0.3}>
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-8 border-t border-border/50">
            <p className="text-xs text-muted-foreground">© 2025 {APP_NAME}. {t.rights}</p>
            <LanguageSwitcher lang={lang} setLang={setLang} />
          </div>
        </Reveal>
      </div>
    </footer>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────────────────────────────────────

interface LandingPageProps {
  /** Opens the AuthScreen in login mode (used by the "Log in" button). */
  onLogin: () => void;
  /** Opens the AuthScreen in signup mode (used by "Try free" / "Get started free"). */
  onSignup: () => void;
  /** Starts the public demo (used by the Hero "View demo" button). */
  onDemo: () => void;
}

export function LandingPage({ onLogin, onSignup, onDemo }: LandingPageProps) {
  const lang = useCopilotStore.getState().lang;
  const setLang = useCopilotStore.getState().setLang;
  const t = T[lang];
  return (
    <div className="min-h-screen bg-background">
      {/* Themed scrollbar for the demo window's internal scroll area.
          Thin rail, border-colored thumb, accent on hover — matches the
          Tevet-7 design tokens. */}
      <style>{`
        .demo-scroll { scrollbar-width: thin; scrollbar-color: var(--border) transparent; }
        .demo-scroll::-webkit-scrollbar { width: 6px; height: 6px; }
        .demo-scroll::-webkit-scrollbar-track { background: transparent; }
        .demo-scroll::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
        .demo-scroll::-webkit-scrollbar-thumb:hover { background: var(--accent); }
      `}</style>
      <Navbar t={t} onLogin={onLogin} onSignup={onSignup} />
      <Hero t={t} onSignup={onSignup} onDemo={onDemo} />
      <SocialProof t={t} />
      <ProblemSolution t={t} />
      <Features t={t} />
      <HowItWorks t={t} />
      <div id="demo" />
      <UseCases t={t} />
      <Pricing t={t} onSignup={onSignup} />
      <FAQ t={t} />
      <FinalCTA t={t} onSignup={onSignup} />
      <Footer t={t} lang={lang} setLang={setLang} />
    </div>
  );
}
