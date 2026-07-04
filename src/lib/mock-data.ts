import type {
  AssistantResponse,
  Identity,
  SecurityCheck,
  TraceStep,
} from "./types";

// ---------------------------------------------------------------------------
// Identities
// ---------------------------------------------------------------------------

export const IDENTITIES: Identity[] = [
  {
    id: "producer-42",
    kind: "producer",
    name: "Marie Dubois",
    producerNumber: "#42",
    producerId: 42,
    farmName: "Ferme du Vallon",
    role: "Productrice",
    initials: "MD",
    accent: "accent",
  },
  {
    id: "producer-99",
    kind: "producer",
    name: "Pierre Martin",
    producerNumber: "#99",
    producerId: 99,
    farmName: "Verger de la Côte",
    role: "Producteur",
    initials: "PM",
    accent: "primary",
  },
  {
    id: "admin",
    kind: "admin",
    name: "DP Admin",
    producerNumber: null,
    producerId: null,
    farmName: null,
    role: "Équipe Ops Drive Producteur",
    initials: "DA",
    accent: "foreground",
  },
];

export const DEFAULT_IDENTITY_ID = "producer-42";

// ---------------------------------------------------------------------------
// Example questions
// ---------------------------------------------------------------------------

export interface ExampleQuestion {
  id: string;
  /** The question text shown to the user and sent as a user message. */
  label: string;
  /** Optional hint about access scope. */
  hint?: string;
}

export const EXAMPLE_QUESTIONS: ExampleQuestion[] = [
  {
    id: "top-products",
    label: "Quels sont mes 5 produits les plus vendus ce mois-ci ?",
  },
  {
    id: "stock-saturday",
    label: "Quel stock va me manquer pour les retraits de samedi ?",
  },
  {
    id: "net-revenue-june",
    label: "Combien j'ai gagné net de commission en juin ?",
  },
  {
    id: "weekly-summary",
    label: "Fais-moi un résumé de mes ventes de la semaine.",
  },
  {
    id: "top-producers",
    label: "Quels producteurs ont le plus de commandes ?",
    hint: "Accès admin requis",
  },
];

// ---------------------------------------------------------------------------
// Trace helpers
// ---------------------------------------------------------------------------

function okSteps(durations = [120, 40, 180, 60, 340, 210]): TraceStep[] {
  return [
    {
      index: 1,
      title: "Compréhension de la question",
      detail: "Analyse sémantique de l'intention et extraction des entités (période, métrique, portée).",
      status: "ok",
      durationMs: durations[0],
    },
    {
      index: 2,
      title: "Sélection de l'outil : sql_read_tool",
      detail: "Le routeur choisit l'outil read-only SQL parmi le catalogue d'outils disponibles.",
      status: "ok",
      durationMs: durations[1],
    },
    {
      index: 3,
      title: "Génération SQL",
      detail: "Le modèle génère une requête SQL paramétrée d'après le schéma du tenant Drive Producteur.",
      status: "ok",
      durationMs: durations[2],
    },
    {
      index: 4,
      title: "Validation sqlglot (scoping injecté)",
      detail: "Le SQL est parsé, normalisé, et la clause de portée producer_id est injectée au niveau AST.",
      status: "ok",
      durationMs: durations[3],
    },
    {
      index: 5,
      title: "Exécution read-only",
      detail: "Exécution sur un utilisateur PostgreSQL limité (SELECT, vue matérialisée en lecture seule).",
      status: "ok",
      durationMs: durations[4],
    },
    {
      index: 6,
      title: "Synthèse de la réponse",
      detail: "Le modèle reformule les résultats en langage naturel et insère les visualisations.",
      status: "ok",
      durationMs: durations[5],
    },
  ];
}

function blockedSteps(): TraceStep[] {
  return [
    {
      index: 1,
      title: "Compréhension de la question",
      detail: "La question demande une agrégation cross-producer (tous les producteurs).",
      status: "ok",
      durationMs: 110,
    },
    {
      index: 2,
      title: "Sélection de l'outil : sql_read_tool",
      detail: "Le routeur identifie qu'une requête de synthèse multi-producteurs est nécessaire.",
      status: "warning",
      durationMs: 35,
    },
    {
      index: 3,
      title: "Validation sqlglot (scoping injecté)",
      detail: "La clause producer_id injectée entre en conflit avec le GROUP BY demandé. Scoping violation détectée.",
      status: "blocked",
      durationMs: 48,
    },
    {
      index: 4,
      title: "Exécution read-only",
      detail: "Exécution annulée — la requête a été rejetée par la couche de sécurité avant l'exécution.",
      status: "blocked",
      durationMs: 0,
    },
    {
      index: 5,
      title: "Synthèse de la réponse",
      detail: "Génération d'un message de refus poli expliquant la contrainte de portée.",
      status: "ok",
      durationMs: 140,
    },
  ];
}

const PRODUCER_SECURITY: SecurityCheck[] = [
  { label: "Read-only", status: "ok", detail: "Utilisateur PG `dp_readonly` — SELECT uniquement." },
  { label: "Scope producer_id appliqué", status: "ok", detail: "Clause injectée au niveau AST, non contournable." },
  { label: "Tables autorisées", status: "ok", detail: "orders, order_items, products, stocks, payments, pickup_bookings." },
  { label: "LIMIT 1000", status: "ok", detail: "Garantie par le wrapper d'exécution." },
];

const ADMIN_SECURITY: SecurityCheck[] = [
  { label: "Read-only", status: "ok", detail: "Utilisateur PG `dp_admin_readonly` — SELECT uniquement." },
  { label: "Scope : full access (rôle admin)", status: "warning", detail: "Aucun filtre producer_id — accès à tous les producteurs du tenant." },
  { label: "Tables autorisées", status: "ok", detail: "orders, order_items, products, stocks, payments, pickup_bookings, producers." },
  { label: "LIMIT 1000", status: "ok", detail: "Garantie par le wrapper d'exécution." },
];

const REFUSAL_SECURITY: SecurityCheck[] = [
  { label: "Read-only", status: "ok", detail: "Vérifié avant parsing." },
  { label: "Scope producer_id requis", status: "blocked", detail: "La requête agrège sur l'ensemble des producteurs — non autorisé pour un rôle producer." },
  { label: "Tables autorisées", status: "ok", detail: "Vérification statique passée." },
  { label: "Exécution SQL", status: "blocked", detail: "Skippée — requête rejetée par sqlglot." },
];

// ---------------------------------------------------------------------------
// Per-identity, per-question mock responses
// ---------------------------------------------------------------------------

type ResponseMap = Record<string, AssistantResponse>;

// --- Producer #42 ---------------------------------------------------------

const p42TopProducts: AssistantResponse = {
  answer:
    "Vos **5 produits les plus vendus ce mois-ci** (Ferme du Vallon) :\n\n" +
    "1. **Tomates cœur de bœuf** — 142 unités · 565,80 €\n" +
    "2. **Courgettes** — 98 unités · 245,00 €\n" +
    "3. **Carottes en bottes** — 87 unités · 217,50 €\n" +
    "4. **Salade laitue** — 76 unités · 152,00 €\n" +
    "5. **Poireaux** — 64 unités · 192,00 €\n\n" +
    "Les tomates représentent **33 %** de votre chiffre d'affaires du mois. Pensez à anticiper le réassort pour le week-end.",
  sql:
    "SELECT p.name,\n" +
    "       SUM(oi.quantity)                       AS units_sold,\n" +
    "       SUM(oi.quantity * oi.unit_price)       AS revenue\n" +
    "FROM order_items oi\n" +
    "JOIN products p ON p.id = oi.product_id\n" +
    "JOIN orders   o ON o.id = oi.order_id\n" +
    "WHERE p.producer_id = 42\n" +
    "  AND o.status IN ('paid', 'fulfilled')\n" +
    "  AND o.created_at >= date_trunc('month', CURRENT_DATE)\n" +
    "GROUP BY p.name\n" +
    "ORDER BY units_sold DESC\n" +
    "LIMIT 5;",
  scopeClause: "WHERE p.producer_id = 42",
  chart: {
    type: "bar",
    title: "Top 5 produits — ce mois-ci",
    xKey: "name",
    series: [
      { key: "units", label: "Unités vendues", color: "accent" },
    ],
    data: [
      { name: "Tomates cœur de bœuf", units: 142 },
      { name: "Courgettes", units: 98 },
      { name: "Carottes en bottes", units: 87 },
      { name: "Salade laitue", units: 76 },
      { name: "Poireaux", units: 64 },
    ],
  },
  tokensIn: 312,
  tokensOut: 418,
  latencyMs: 1820,
  toolCalls: ["sql_read_tool"],
  steps: okSteps(),
  securityChecks: PRODUCER_SECURITY,
  refused: false,
};

const p42Stock: AssistantResponse = {
  answer:
    "Pour les **retraits de samedi**, 3 références risquent de vous manquer :\n\n" +
    "| Produit | Stock | Réservé | Manque |\n" +
    "|---|---:|---:|---:|\n" +
    "| Tomates cœur de bœuf | 18 | 24 | **-6** |\n" +
    "| Salade laitue | 8 | 14 | **-6** |\n" +
    "| Courgettes | 12 | 15 | **-3** |\n\n" +
    "Je recommande de réapprovisionner les tomates et la salade avant vendredi 18h. Les courgettes sont limites mais couvrables.",
  sql:
    "SELECT p.name,\n" +
    "       s.current_qty                                  AS stock,\n" +
    "       COALESCE(SUM(oi.quantity), 0)                  AS reserved,\n" +
    "       s.current_qty - COALESCE(SUM(oi.quantity), 0)  AS remaining\n" +
    "FROM products p\n" +
    "JOIN stocks          s  ON s.product_id = p.id\n" +
    "LEFT JOIN order_items oi ON oi.product_id = p.id\n" +
    "LEFT JOIN orders       o ON o.id = oi.order_id\n" +
    "     AND o.status IN ('paid', 'fulfilled')\n" +
    "LEFT JOIN pickup_bookings pb ON pb.id = o.pickup_booking_id\n" +
    "     AND pb.slot_date = CURRENT_DATE + INTERVAL '3 days'\n" +
    "WHERE p.producer_id = 42\n" +
    "GROUP BY p.name, s.current_qty\n" +
    "HAVING s.current_qty - COALESCE(SUM(oi.quantity), 0) < 10\n" +
    "ORDER BY remaining ASC\n" +
    "LIMIT 20;",
  scopeClause: "WHERE p.producer_id = 42",
  chart: {
    type: "bar",
    title: "Déficit prévu pour samedi",
    xKey: "name",
    series: [{ key: "deficit", label: "Manque (unités)", color: "muted" }],
    data: [
      { name: "Tomates cœur de bœuf", deficit: 6 },
      { name: "Salade laitue", deficit: 6 },
      { name: "Courgettes", deficit: 3 },
    ],
  },
  tokensIn: 286,
  tokensOut: 372,
  latencyMs: 1640,
  toolCalls: ["sql_read_tool"],
  steps: okSteps([130, 45, 195, 70, 360, 230]),
  securityChecks: PRODUCER_SECURITY,
  refused: false,
};

const p42Revenue: AssistantResponse = {
  answer:
    "En **juin 2025**, votre chiffre d'affaires brut capturé s'élève à **4 820,00 €**.\n\n" +
    "- Commission Drive Producteur (12 %) : **-578,40 €**\n" +
    "- **Net à percevoir : 4 241,60 €**\n\n" +
    "Le versement sera effectué le 15 du mois suivant sur votre IBAN enregistré. Détail disponible dans l'espace producteur.",
  sql:
    "SELECT\n" +
    "  SUM(pay.amount)                       AS gross,\n" +
    "  SUM(pay.amount) * 0.12                AS commission,\n" +
    "  SUM(pay.amount) - SUM(pay.amount)*0.12 AS net\n" +
    "FROM payments pay\n" +
    "JOIN orders      o  ON o.id = pay.order_id\n" +
    "JOIN order_items oi ON oi.order_id = o.id\n" +
    "JOIN products    p  ON p.id = oi.product_id\n" +
    "WHERE p.producer_id = 42\n" +
    "  AND pay.status = 'captured'\n" +
    "  AND pay.captured_at >= '2025-06-01'\n" +
    "  AND pay.captured_at <  '2025-07-01';",
  scopeClause: "WHERE p.producer_id = 42",
  tokensIn: 244,
  tokensOut: 298,
  latencyMs: 1380,
  toolCalls: ["sql_read_tool"],
  steps: okSteps([110, 38, 165, 55, 320, 190]),
  securityChecks: PRODUCER_SECURITY,
  refused: false,
};

const p42Weekly: AssistantResponse = {
  answer:
    "Voici le **résumé de vos ventes sur les 7 derniers jours** :\n\n" +
    "- **101 commandes** au total\n" +
    "- **4 470 €** de chiffre d'affaires brut\n" +
    "- Panier moyen : **44,26 €**\n\n" +
    "Le pic est attendu le samedi (28 commandes, 1 340 €). Le dimanche reste calme (6 commandes). Le jeudi affiche une bonne dynamique en milieu de semaine.",
  sql:
    "SELECT date_trunc('day', o.created_at)         AS day,\n" +
    "       COUNT(DISTINCT o.id)                     AS orders,\n" +
    "       SUM(oi.quantity * oi.unit_price)         AS revenue\n" +
    "FROM orders o\n" +
    "JOIN order_items oi ON oi.order_id = o.id\n" +
    "JOIN products    p  ON p.id = oi.product_id\n" +
    "WHERE p.producer_id = 42\n" +
    "  AND o.status IN ('paid', 'fulfilled')\n" +
    "  AND o.created_at >= CURRENT_DATE - INTERVAL '7 days'\n" +
    "GROUP BY day\n" +
    "ORDER BY day ASC;",
  scopeClause: "WHERE p.producer_id = 42",
  chart: {
    type: "line",
    title: "Ventes des 7 derniers jours",
    xKey: "day",
    series: [
      { key: "orders", label: "Commandes", color: "accent" },
      { key: "revenue", label: "CA (€)", color: "primary" },
    ],
    data: [
      { day: "Lun", orders: 8, revenue: 320 },
      { day: "Mar", orders: 12, revenue: 510 },
      { day: "Mer", orders: 10, revenue: 430 },
      { day: "Jeu", orders: 15, revenue: 680 },
      { day: "Ven", orders: 22, revenue: 1050 },
      { day: "Sam", orders: 28, revenue: 1340 },
      { day: "Dim", orders: 6, revenue: 240 },
    ],
  },
  tokensIn: 298,
  tokensOut: 392,
  latencyMs: 1720,
  toolCalls: ["sql_read_tool"],
  steps: okSteps([125, 42, 175, 58, 350, 215]),
  securityChecks: PRODUCER_SECURITY,
  refused: false,
};

// --- Producer #99 ---------------------------------------------------------

const p99TopProducts: AssistantResponse = {
  answer:
    "Vos **5 produits les plus vendus ce mois-ci** (Verger de la Côte) :\n\n" +
    "1. **Pommes Gala** — 210 unités · 630,00 €\n" +
    "2. **Pommes Reinette** — 165 unités · 577,50 €\n" +
    "3. **Jus de pomme 1L** — 76 unités · 342,00 €\n" +
    "4. **Poires Conférence** — 88 unités · 308,00 €\n" +
    "5. **Mirabelles** — 54 unités · 270,00 €\n\n" +
    "Les pommes (Gala + Reinette) représentent **48 %** du CA du mois. Le jus de pomme transformé affiche une belle marge.",
  sql:
    "SELECT p.name,\n" +
    "       SUM(oi.quantity)                       AS units_sold,\n" +
    "       SUM(oi.quantity * oi.unit_price)       AS revenue\n" +
    "FROM order_items oi\n" +
    "JOIN products p ON p.id = oi.product_id\n" +
    "JOIN orders   o ON o.id = oi.order_id\n" +
    "WHERE p.producer_id = 99\n" +
    "  AND o.status IN ('paid', 'fulfilled')\n" +
    "  AND o.created_at >= date_trunc('month', CURRENT_DATE)\n" +
    "GROUP BY p.name\n" +
    "ORDER BY units_sold DESC\n" +
    "LIMIT 5;",
  scopeClause: "WHERE p.producer_id = 99",
  chart: {
    type: "bar",
    title: "Top 5 produits — ce mois-ci",
    xKey: "name",
    series: [{ key: "units", label: "Unités vendues", color: "primary" }],
    data: [
      { name: "Pommes Gala", units: 210 },
      { name: "Pommes Reinette", units: 165 },
      { name: "Poires Conférence", units: 88 },
      { name: "Jus de pomme 1L", units: 76 },
      { name: "Mirabelles", units: 54 },
    ],
  },
  tokensIn: 318,
  tokensOut: 421,
  latencyMs: 1855,
  toolCalls: ["sql_read_tool"],
  steps: okSteps(),
  securityChecks: PRODUCER_SECURITY,
  refused: false,
};

const p99Stock: AssistantResponse = {
  answer:
    "Pour les **retraits de samedi**, 3 références risquent de vous manquer :\n\n" +
    "| Produit | Stock | Réservé | Manque |\n" +
    "|---|---:|---:|---:|\n" +
    "| Pommes Gala | 45 | 60 | **-15** |\n" +
    "| Jus de pomme 1L | 20 | 32 | **-12** |\n" +
    "| Poires Conférence | 15 | 18 | **-3** |\n\n" +
    "Le déficit sur les Pommes Gala est significatif. Une cueillette supplémentaire jeudi matin est recommandée pour couvrir la demande du week-end.",
  sql:
    "SELECT p.name,\n" +
    "       s.current_qty                                  AS stock,\n" +
    "       COALESCE(SUM(oi.quantity), 0)                  AS reserved,\n" +
    "       s.current_qty - COALESCE(SUM(oi.quantity), 0)  AS remaining\n" +
    "FROM products p\n" +
    "JOIN stocks          s  ON s.product_id = p.id\n" +
    "LEFT JOIN order_items oi ON oi.product_id = p.id\n" +
    "LEFT JOIN orders       o ON o.id = oi.order_id\n" +
    "     AND o.status IN ('paid', 'fulfilled')\n" +
    "LEFT JOIN pickup_bookings pb ON pb.id = o.pickup_booking_id\n" +
    "     AND pb.slot_date = CURRENT_DATE + INTERVAL '3 days'\n" +
    "WHERE p.producer_id = 99\n" +
    "GROUP BY p.name, s.current_qty\n" +
    "HAVING s.current_qty - COALESCE(SUM(oi.quantity), 0) < 10\n" +
    "ORDER BY remaining ASC\n" +
    "LIMIT 20;",
  scopeClause: "WHERE p.producer_id = 99",
  chart: {
    type: "bar",
    title: "Déficit prévu pour samedi",
    xKey: "name",
    series: [{ key: "deficit", label: "Manque (unités)", color: "muted" }],
    data: [
      { name: "Pommes Gala", deficit: 15 },
      { name: "Jus de pomme 1L", deficit: 12 },
      { name: "Poires Conférence", deficit: 3 },
    ],
  },
  tokensIn: 292,
  tokensOut: 380,
  latencyMs: 1695,
  toolCalls: ["sql_read_tool"],
  steps: okSteps([130, 45, 195, 70, 360, 230]),
  securityChecks: PRODUCER_SECURITY,
  refused: false,
};

const p99Revenue: AssistantResponse = {
  answer:
    "En **juin 2025**, votre chiffre d'affaires brut capturé s'élève à **6 150,00 €**.\n\n" +
    "- Commission Drive Producteur (12 %) : **-738,00 €**\n" +
    "- **Net à percevoir : 5 412,00 €**\n\n" +
    "Le versement sera effectué le 15 du mois suivant sur votre IBAN enregistré. Détail disponible dans l'espace producteur.",
  sql:
    "SELECT\n" +
    "  SUM(pay.amount)                       AS gross,\n" +
    "  SUM(pay.amount) * 0.12                AS commission,\n" +
    "  SUM(pay.amount) - SUM(pay.amount)*0.12 AS net\n" +
    "FROM payments pay\n" +
    "JOIN orders      o  ON o.id = pay.order_id\n" +
    "JOIN order_items oi ON oi.order_id = o.id\n" +
    "JOIN products    p  ON p.id = oi.product_id\n" +
    "WHERE p.producer_id = 99\n" +
    "  AND pay.status = 'captured'\n" +
    "  AND pay.captured_at >= '2025-06-01'\n" +
    "  AND pay.captured_at <  '2025-07-01';",
  scopeClause: "WHERE p.producer_id = 99",
  tokensIn: 248,
  tokensOut: 301,
  latencyMs: 1410,
  toolCalls: ["sql_read_tool"],
  steps: okSteps([110, 38, 165, 55, 320, 190]),
  securityChecks: PRODUCER_SECURITY,
  refused: false,
};

const p99Weekly: AssistantResponse = {
  answer:
    "Voici le **résumé de vos ventes sur les 7 derniers jours** :\n\n" +
    "- **135 commandes** au total\n" +
    "- **4 710 €** de chiffre d'affaires brut\n" +
    "- Panier moyen : **34,89 €**\n\n" +
    "Le pic est le samedi (32 commandes, 1 240 €). Volume régulier toute la semaine — bon dynamisme sur les pommes transformées (jus).",
  sql:
    "SELECT date_trunc('day', o.created_at)         AS day,\n" +
    "       COUNT(DISTINCT o.id)                     AS orders,\n" +
    "       SUM(oi.quantity * oi.unit_price)         AS revenue\n" +
    "FROM orders o\n" +
    "JOIN order_items oi ON oi.order_id = o.id\n" +
    "JOIN products    p  ON p.id = oi.product_id\n" +
    "WHERE p.producer_id = 99\n" +
    "  AND o.status IN ('paid', 'fulfilled')\n" +
    "  AND o.created_at >= CURRENT_DATE - INTERVAL '7 days'\n" +
    "GROUP BY day\n" +
    "ORDER BY day ASC;",
  scopeClause: "WHERE p.producer_id = 99",
  chart: {
    type: "line",
    title: "Ventes des 7 derniers jours",
    xKey: "day",
    series: [
      { key: "orders", label: "Commandes", color: "primary" },
      { key: "revenue", label: "CA (€)", color: "accent" },
    ],
    data: [
      { day: "Lun", orders: 14, revenue: 410 },
      { day: "Mar", orders: 18, revenue: 560 },
      { day: "Mer", orders: 16, revenue: 490 },
      { day: "Jeu", orders: 20, revenue: 720 },
      { day: "Ven", orders: 26, revenue: 980 },
      { day: "Sam", orders: 32, revenue: 1240 },
      { day: "Dim", orders: 9, revenue: 310 },
    ],
  },
  tokensIn: 305,
  tokensOut: 401,
  latencyMs: 1760,
  toolCalls: ["sql_read_tool"],
  steps: okSteps([125, 42, 175, 58, 350, 215]),
  securityChecks: PRODUCER_SECURITY,
  refused: false,
};

// --- Admin ----------------------------------------------------------------

const adminTopProducers: AssistantResponse = {
  answer:
    "Voici les **7 producteurs avec le plus de commandes** ce mois-ci, tous producteurs confondus :\n\n" +
    "1. **Ferme du Vallon** (#42) — 312 commandes\n" +
    "2. **Verger de la Côte** (#99) — 298 commandes\n" +
    "3. **Maraîchers du Soleil** (#17) — 245 commandes\n" +
    "4. **Élevage des Prés** (#58) — 198 commandes\n" +
    "5. **Fromagerie du Col** (#23) — 176 commandes\n" +
    "6. **Apiculteur des Cimes** (#71) — 142 commandes\n" +
    "7. **Vignoble des Bruyères** (#34) — 128 commandes\n\n" +
    "Les deux premiers représentent **22 %** du volume mensuel. Aucune clause `producer_id` n'est appliquée — votre rôle admin donne un accès complet au tenant Drive Producteur.",
  sql:
    "SELECT p.producer_id,\n" +
    "       pr.farm_name,\n" +
    "       COUNT(DISTINCT o.id) AS orders\n" +
    "FROM order_items oi\n" +
    "JOIN products  p  ON p.id = oi.product_id\n" +
    "JOIN producers pr ON pr.id = p.producer_id\n" +
    "JOIN orders    o  ON o.id = oi.order_id\n" +
    "WHERE o.status IN ('paid', 'fulfilled')\n" +
    "  AND o.created_at >= date_trunc('month', CURRENT_DATE)\n" +
    "GROUP BY p.producer_id, pr.farm_name\n" +
    "ORDER BY orders DESC\n" +
    "LIMIT 10;",
  scopeClause: null,
  chart: {
    type: "bar",
    title: "Top producteurs — commandes du mois",
    xKey: "farm",
    series: [{ key: "orders", label: "Commandes", color: "foreground" }],
    data: [
      { farm: "Ferme du Vallon", orders: 312 },
      { farm: "Verger de la Côte", orders: 298 },
      { farm: "Maraîchers du Soleil", orders: 245 },
      { farm: "Élevage des Prés", orders: 198 },
      { farm: "Fromagerie du Col", orders: 176 },
      { farm: "Apiculteur des Cimes", orders: 142 },
      { farm: "Vignoble des Bruyères", orders: 128 },
    ],
  },
  tokensIn: 332,
  tokensOut: 445,
  latencyMs: 1960,
  toolCalls: ["sql_read_tool"],
  steps: okSteps([140, 48, 200, 75, 380, 240]),
  securityChecks: ADMIN_SECURITY,
  refused: false,
};

// Admin sees the same producer questions but with full access. We give the
// admin a tenant-wide version of the producer-scoped questions so the demo
// still feels coherent when switching identities.
const adminTopProducts: AssistantResponse = {
  answer:
    "Voici les **5 produits les plus vendus ce mois-ci, tous producteurs confondus** :\n\n" +
    "1. **Pommes Gala** (Verger de la Côte) — 210 unités\n" +
    "2. **Pommes Reinette** (Verger de la Côte) — 165 unités\n" +
    "3. **Tomates cœur de bœuf** (Ferme du Vallon) — 142 unités\n" +
    "4. **Courgettes** (Ferme du Vallon) — 98 unités\n" +
    "5. **Jus de pomme 1L** (Verger de la Côte) — 76 unités\n\n" +
    "Accès admin : aucune clause `producer_id` appliquée.",
  sql:
    "SELECT p.name,\n" +
    "       pr.farm_name,\n" +
    "       SUM(oi.quantity)                 AS units_sold\n" +
    "FROM order_items oi\n" +
    "JOIN products  p  ON p.id = oi.product_id\n" +
    "JOIN producers pr ON pr.id = p.producer_id\n" +
    "JOIN orders    o  ON o.id = oi.order_id\n" +
    "WHERE o.status IN ('paid', 'fulfilled')\n" +
    "  AND o.created_at >= date_trunc('month', CURRENT_DATE)\n" +
    "GROUP BY p.name, pr.farm_name\n" +
    "ORDER BY units_sold DESC\n" +
    "LIMIT 5;",
  scopeClause: null,
  chart: {
    type: "bar",
    title: "Top 5 produits — tous producteurs",
    xKey: "name",
    series: [{ key: "units", label: "Unités vendues", color: "foreground" }],
    data: [
      { name: "Pommes Gala", units: 210 },
      { name: "Pommes Reinette", units: 165 },
      { name: "Tomates cœur de bœuf", units: 142 },
      { name: "Courgettes", units: 98 },
      { name: "Jus de pomme 1L", units: 76 },
    ],
  },
  tokensIn: 320,
  tokensOut: 410,
  latencyMs: 1820,
  toolCalls: ["sql_read_tool"],
  steps: okSteps(),
  securityChecks: ADMIN_SECURITY,
  refused: false,
};

const adminStock: AssistantResponse = {
  answer:
    "Vue **admin agrégée** des ruptures prévues pour les retraits de samedi, tous producteurs confondus :\n\n" +
    "| Produit | Producteur | Stock | Réservé | Manque |\n" +
    "|---|---|---:|---:|---:|\n" +
    "| Pommes Gala | Verger de la Côte | 45 | 60 | **-15** |\n" +
    "| Jus de pomme 1L | Verger de la Côte | 20 | 32 | **-12** |\n" +
    "| Tomates cœur de bœuf | Ferme du Vallon | 18 | 24 | **-6** |\n" +
    "| Salade laitue | Ferme du Vallon | 8 | 14 | **-6** |\n\n" +
    "Je recommande de notifier les producteurs concernés avant vendredi 18h.",
  sql:
    "SELECT p.name,\n" +
    "       pr.farm_name,\n" +
    "       s.current_qty                                  AS stock,\n" +
    "       COALESCE(SUM(oi.quantity), 0)                  AS reserved,\n" +
    "       s.current_qty - COALESCE(SUM(oi.quantity), 0)  AS remaining\n" +
    "FROM products p\n" +
    "JOIN producers       pr ON pr.id = p.producer_id\n" +
    "JOIN stocks          s  ON s.product_id = p.id\n" +
    "LEFT JOIN order_items oi ON oi.product_id = p.id\n" +
    "LEFT JOIN orders       o ON o.id = oi.order_id\n" +
    "     AND o.status IN ('paid', 'fulfilled')\n" +
    "LEFT JOIN pickup_bookings pb ON pb.id = o.pickup_booking_id\n" +
    "     AND pb.slot_date = CURRENT_DATE + INTERVAL '3 days'\n" +
    "GROUP BY p.name, pr.farm_name, s.current_qty\n" +
    "HAVING s.current_qty - COALESCE(SUM(oi.quantity), 0) < 10\n" +
    "ORDER BY remaining ASC\n" +
    "LIMIT 20;",
  scopeClause: null,
  tokensIn: 290,
  tokensOut: 378,
  latencyMs: 1680,
  toolCalls: ["sql_read_tool"],
  steps: okSteps([130, 45, 195, 70, 360, 230]),
  securityChecks: ADMIN_SECURITY,
  refused: false,
};

const adminRevenue: AssistantResponse = {
  answer:
    "Vue **admin agrégée** — chiffre d'affaires net perçu par Drive Producteur en juin 2025 :\n\n" +
    "- Brut capturé (tous producteurs) : **28 640,00 €**\n" +
    "- Commissions perçues (12 %) : **3 436,80 €**\n" +
    "- Net reversé aux producteurs : **25 203,20 €**\n\n" +
    "Aucune clause `producer_id` — votre rôle admin couvre tout le tenant.",
  sql:
    "SELECT\n" +
    "  SUM(pay.amount)                       AS gross,\n" +
    "  SUM(pay.amount) * 0.12                AS commission,\n" +
    "  SUM(pay.amount) - SUM(pay.amount)*0.12 AS net\n" +
    "FROM payments pay\n" +
    "JOIN orders o ON o.id = pay.order_id\n" +
    "WHERE pay.status = 'captured'\n" +
    "  AND pay.captured_at >= '2025-06-01'\n" +
    "  AND pay.captured_at <  '2025-07-01';",
  scopeClause: null,
  tokensIn: 250,
  tokensOut: 305,
  latencyMs: 1420,
  toolCalls: ["sql_read_tool"],
  steps: okSteps([110, 38, 165, 55, 320, 190]),
  securityChecks: ADMIN_SECURITY,
  refused: false,
};

const adminWeekly: AssistantResponse = {
  answer:
    "**Résumé agrégé des ventes du tenant** sur les 7 derniers jours :\n\n" +
    "- **387 commandes** au total\n" +
    "- **15 240 €** de chiffre d'affaires brut\n" +
    "- Panier moyen : **39,38 €**\n\n" +
    "Le samedi reste le jour fort (162 commandes). Aucune clause `producer_id` appliquée.",
  sql:
    "SELECT date_trunc('day', o.created_at)         AS day,\n" +
    "       COUNT(DISTINCT o.id)                     AS orders,\n" +
    "       SUM(oi.quantity * oi.unit_price)         AS revenue\n" +
    "FROM orders o\n" +
    "JOIN order_items oi ON oi.order_id = o.id\n" +
    "WHERE o.status IN ('paid', 'fulfilled')\n" +
    "  AND o.created_at >= CURRENT_DATE - INTERVAL '7 days'\n" +
    "GROUP BY day\n" +
    "ORDER BY day ASC;",
  scopeClause: null,
  chart: {
    type: "line",
    title: "Ventes du tenant — 7 derniers jours",
    xKey: "day",
    series: [
      { key: "orders", label: "Commandes", color: "foreground" },
      { key: "revenue", label: "CA (€)", color: "accent" },
    ],
    data: [
      { day: "Lun", orders: 42, revenue: 1560 },
      { day: "Mar", orders: 55, revenue: 2120 },
      { day: "Mer", orders: 48, revenue: 1840 },
      { day: "Jeu", orders: 60, revenue: 2480 },
      { day: "Ven", orders: 88, revenue: 3640 },
      { day: "Sam", orders: 162, revenue: 6800 },
      { day: "Dim", orders: 32, revenue: 1240 },
    ],
  },
  tokensIn: 310,
  tokensOut: 405,
  latencyMs: 1780,
  toolCalls: ["sql_read_tool"],
  steps: okSteps([125, 42, 175, 58, 350, 215]),
  securityChecks: ADMIN_SECURITY,
  refused: false,
};

// --- Refusal (producer asking an admin-only question) ---------------------

function refusalResponse(producerId: number, producerNumber: string): AssistantResponse {
  return {
    answer:
      "En tant que producteur, vous ne pouvez voir que **vos propres données**.\n\n" +
      "Cette question demande une agrégation sur l'ensemble des producteurs du tenant Drive Producteur. " +
      `Votre scope actuel est limité à \`producer_id = ${producerId}\` (${producerNumber}).\n\n` +
      "Si vous avez besoin de cette information, contactez l'équipe Ops Drive Producteur qui dispose d'un accès admin.",
    sql: null,
    scopeClause: `WHERE p.producer_id = ${producerId}  -- injecté puis rejeté`,
    tokensIn: 268,
    tokensOut: 215,
    latencyMs: 940,
    toolCalls: [],
    steps: blockedSteps(),
    securityChecks: REFUSAL_SECURITY,
    refused: true,
  };
}

// ---------------------------------------------------------------------------
// Map: `${identityId}:${questionId}` -> response
// ---------------------------------------------------------------------------

const RESPONSES: ResponseMap = {
  "producer-42:top-products": p42TopProducts,
  "producer-42:stock-saturday": p42Stock,
  "producer-42:net-revenue-june": p42Revenue,
  "producer-42:weekly-summary": p42Weekly,
  "producer-42:top-producers": refusalResponse(42, "#42"),

  "producer-99:top-products": p99TopProducts,
  "producer-99:stock-saturday": p99Stock,
  "producer-99:net-revenue-june": p99Revenue,
  "producer-99:weekly-summary": p99Weekly,
  "producer-99:top-producers": refusalResponse(99, "#99"),

  "admin:top-products": adminTopProducts,
  "admin:stock-saturday": adminStock,
  "admin:net-revenue-june": adminRevenue,
  "admin:weekly-summary": adminWeekly,
  "admin:top-producers": adminTopProducers,
};

// Fallback used for any free-form user question that does not match an
// example question id. We synthesise a believable scoped response so the
// prototype never breaks.
function fallbackResponse(identity: Identity): AssistantResponse {
  const isProducer = identity.kind === "producer";
  const scopeClause = isProducer
    ? `WHERE p.producer_id = ${identity.producerId}`
    : null;

  const baseSql = isProducer
    ? "SELECT COUNT(DISTINCT o.id) AS orders,\n" +
      "       SUM(oi.quantity * oi.unit_price) AS revenue\n" +
      "FROM orders o\n" +
      "JOIN order_items oi ON oi.order_id = o.id\n" +
      "JOIN products    p  ON p.id = oi.product_id\n" +
      `${scopeClause}\n` +
      "  AND o.status IN ('paid', 'fulfilled')\n" +
      "  AND o.created_at >= CURRENT_DATE - INTERVAL '7 days';"
    : "SELECT COUNT(DISTINCT o.id) AS orders,\n" +
      "       SUM(oi.quantity * oi.unit_price) AS revenue\n" +
      "FROM orders o\n" +
      "JOIN order_items oi ON oi.order_id = o.id\n" +
      "WHERE o.status IN ('paid', 'fulfilled')\n" +
      "  AND o.created_at >= CURRENT_DATE - INTERVAL '7 days';";

  const answer = isProducer
    ? `Voici une synthèse des 7 derniers jours pour **${identity.farmName}** (${identity.producerNumber}).\n\n` +
      `- **84 commandes** traitées\n` +
      `- **3 120 €** de chiffre d'affaires brut\n` +
      `- Panier moyen : **37,14 €**\n\n` +
      `Votre scope est limité à \`producer_id = ${identity.producerId}\` — les autres producteurs ne sont jamais visibles.`
    : "Synthèse des 7 derniers jours pour l'ensemble du tenant Drive Producteur :\n\n" +
      "- **387 commandes** traitées\n- **15 240 €** de chiffre d'affaires brut\n\n" +
      "Accès admin : aucune clause `producer_id` appliquée.";

  return {
    answer,
    sql: baseSql,
    scopeClause,
    chart: {
      type: "bar",
      title: "Commandes par jour (7j)",
      xKey: "day",
      series: [{ key: "orders", label: "Commandes", color: "accent" }],
      data: [
        { day: "Lun", orders: isProducer ? 8 : 42 },
        { day: "Mar", orders: isProducer ? 12 : 55 },
        { day: "Mer", orders: isProducer ? 10 : 48 },
        { day: "Jeu", orders: isProducer ? 15 : 60 },
        { day: "Ven", orders: isProducer ? 22 : 88 },
        { day: "Sam", orders: isProducer ? 14 : 162 },
        { day: "Dim", orders: isProducer ? 3 : 32 },
      ],
    },
    tokensIn: 274,
    tokensOut: 330,
    latencyMs: 1540,
    toolCalls: ["sql_read_tool"],
    steps: okSteps(),
    securityChecks: isProducer ? PRODUCER_SECURITY : ADMIN_SECURITY,
    refused: false,
  };
}

/**
 * Try to match a free-form user message to one of the example question ids,
 * otherwise fall back to a synthesised scoped response.
 */
export function getResponseForMessage(
  identity: Identity,
  message: string,
): AssistantResponse {
  const normalized = message.trim().toLowerCase();
  const match = EXAMPLE_QUESTIONS.find((q) =>
    normalized.includes(q.label.toLowerCase().slice(0, 25)),
  );
  if (match) {
    const key = `${identity.id}:${match.id}`;
    const r = RESPONSES[key];
    if (r) return r;
  }
  return fallbackResponse(identity);
}

/** Direct lookup by example question id (used when clicking an example chip). */
export function getResponseForExample(
  identity: Identity,
  questionId: string,
): AssistantResponse {
  const key = `${identity.id}:${questionId}`;
  const r = RESPONSES[key];
  if (r) return r;
  return fallbackResponse(identity);
}

// Pre-baked conversation history shown in the sidebar (purely cosmetic).
export const SEED_HISTORY: { id: string; title: string; preview: string; identityId: string; updatedAt: number }[] = [
  {
    id: "h-1",
    title: "Ventes du week-end",
    preview: "Résumé des ventes des 7 derniers jours…",
    identityId: "producer-42",
    updatedAt: Date.now() - 1000 * 60 * 12,
  },
  {
    id: "h-2",
    title: "Stock pour samedi",
    preview: "Produits en rupture prévue pour les retraits…",
    identityId: "producer-42",
    updatedAt: Date.now() - 1000 * 60 * 60 * 3,
  },
  {
    id: "h-3",
    title: "Top producteurs du mois",
    preview: "Classement cross-producteur (admin)…",
    identityId: "admin",
    updatedAt: Date.now() - 1000 * 60 * 60 * 26,
  },
];
