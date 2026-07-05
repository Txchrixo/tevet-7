/**
 * Dashboard i18n (#22). EN/FR translations for dashboard, onboarding, header, sidebar.
 * Reads lang from the global Zustand store.
 */

export type Lang = "en" | "fr";

const DASHBOARD_T = {
  en: {
    // Header
    phase: "Prototype",
    agent: "Agent",
    opsConsole: "Ops Console",
    inspect: "Inspect",
    // Sidebar
    newConversation: "New conv.",
    reset: "RESET",
    examples: "Examples",
    // Chat
    inputPlaceholder: "Ask your Tevet-7 agent...",
    send: "Send",
    welcome: "Hello",
    // Onboarding
    onboardingTitle: "Configure your agent",
    step1: "Connect your data",
    step2: "Detect schema",
    step3: "Select tables",
    step4: "Define roles",
    connect: "Connect",
    detect: "Detect schema",
    continue: "Continue",
    back: "Previous step",
    accessAgent: "Access the agent",
    // Inspector
    trace: "Trace",
    sql: "SQL",
    steps: "Steps",
    tokens: "tokens",
    scope: "Scope",
    security: "Security",
    // Chat message footer
    scopeVerified: "Scope verified",
    scopeFullAccess: "FULL ACCESS",
    sqlExecuted: "SQL executed",
    seconds: "s",
    clickToSeeTrace: "click to see the trace",
  },
  fr: {
    phase: "Prototype",
    agent: "Agent",
    opsConsole: "Ops Console",
    inspect: "Inspecteur",
    newConversation: "Nouvelle conv.",
    reset: "RÉINITIALISER",
    examples: "Exemples",
    inputPlaceholder: "Posez votre question a l'agent Tevet-7...",
    send: "Envoyer",
    welcome: "Bonjour",
    onboardingTitle: "Configurez votre agent",
    step1: "Connectez vos donnees",
    step2: "Detecter le schema",
    step3: "Selectionner les tables",
    step4: "Definir les roles",
    connect: "Connecter",
    detect: "Detecter le schema",
    continue: "Continuer",
    back: "Etape precedente",
    accessAgent: "Acceder a l'agent",
    trace: "Trace",
    sql: "SQL",
    steps: "Etapes",
    tokens: "tokens",
    scope: "Scope",
    security: "Securite",
    scopeVerified: "Scope verifie",
    scopeFullAccess: "FULL ACCESS",
    sqlExecuted: "SQL execute",
    seconds: "s",
    clickToSeeTrace: "cliquez pour voir la trace",
  },
};

export function getDashboardT(lang: Lang) {
  return DASHBOARD_T[lang];
}
