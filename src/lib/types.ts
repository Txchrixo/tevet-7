// Core domain types for the Tevet-7 platform (configurable AI agent platform).

export type IdentityKind = "producer" | "admin";

export interface Identity {
  id: string;
  kind: IdentityKind;
  name: string;
  /** Producer number, e.g. "#42". Null for the admin identity. */
  producerNumber: string | null;
  /** Internal numeric producer id used in the SQL `WHERE producer_id = X` clause. */
  producerId: number | null;
  farmName: string | null;
  role: string;
  initials: string;
  accent: string; // tailwind color token, e.g. "emerald" | "amber" | "teal"
}

export type ChartType = "bar" | "line";

export interface ChartSpec {
  type: ChartType;
  title?: string;
  /** X-axis data key. */
  xKey: string;
  /** Bars/lines to render. */
  series: { key: string; label: string; color?: string }[];
  /** Raw rows. */
  data: Record<string, string | number>[];
  /** Optional unit appended to axis ticks / tooltips. */
  unit?: string;
}

export type TraceStatus = "ok" | "warning" | "blocked";

export interface TraceStep {
  index: number;
  title: string;
  detail: string;
  status: TraceStatus;
  durationMs: number;
}

export interface SecurityCheck {
  label: string;
  status: TraceStatus;
  detail?: string;
}

/**
 * A single ML stock-shortage prediction, returned by the `forecast_tool`
 * (Phase 5). One entry per product the agent ran through the trained
 * RandomForest model — `probability` is the model's confidence that the
 * product will run out of stock within the forecast horizon.
 */
export interface ForecastPrediction {
  product_name: string;
  /** Model confidence in [0, 1] that the product will run out of stock. */
  probability: number;
  /** Current stock level (units) used as a feature. */
  stock_available: number;
  /** Units sold over the trailing 7 days — features + context. */
  sales_7d: number;
  /** Short human-readable label for the most influential feature. */
  top_factor: string;
}

export interface AssistantResponse {
  answer: string;
  /** SQL displayed in the message and inspector. Null for refusals. */
  sql: string | null;
  /** Clause injected by the scoping layer, e.g. "WHERE producer_id = 42". */
  scopeClause: string | null;
  chart?: ChartSpec;
  tokensIn: number;
  tokensOut: number;
  latencyMs: number;
  toolCalls: string[];
  steps: TraceStep[];
  securityChecks: SecurityCheck[];
  /** True when the agent refused to answer (scoping violation for a producer). */
  refused: boolean;
  /**
   * Documentary (RAG) citations. Populated when the agent answered by
   * searching the indexed document corpus rather than generating SQL.
   * Empty/undefined for analytical responses.
   */
  sources?: Source[];
  /**
   * ML stock-shortage predictions (Phase 5). Populated only when the agent
   * routed the question through the `forecast_tool` instead of the
   * `sql_read_tool` — i.e. "Quel stock va me manquer samedi ?". Empty for
   * analytical + documentary responses. Renders a distinct "PRÉDICTIONS ML"
   * block beneath the answer text.
   */
  forecastPredictions?: ForecastPrediction[];
}

/**
 * A documentary citation returned alongside a RAG answer.
 *
 * `score` is optional — exposed only when the backend's retriever surfaces a
 * similarity score for the chunk (cosine distance, reranker confidence, etc.).
 */
export interface Source {
  type: "document";
  title: string;
  chunkIndex: number;
  documentId: number;
  /** Optional retrieval score in [0, 1]. Backend-dependent. */
  score?: number;
}

/** A document indexed in the RAG corpus (CGV, FAQ, procédure, etc.). */
export interface DocumentInfo {
  id: number;
  title: string;
  sourceType: "pdf" | "text" | "manual";
  createdAt: string;
  chunksCount: number;
  producerId: number | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** Only present for assistant messages. */
  response?: AssistantResponse;
  /** ISO timestamp. */
  createdAt: number;
  /** Indicates the assistant message is still being "streamed". */
  streaming?: boolean;
}

export interface ConversationHistoryItem {
  id: string;
  title: string;
  preview: string;
  identityId: string;
  updatedAt: number;
}

// ---------------------------------------------------------------------------
// Ops Console — human-in-the-loop approval queue (Phase 4)
// ---------------------------------------------------------------------------

/** The recommendation produced by the agent for a given onboarding dossier. */
export type ProposedDecision = "approve" | "reject" | "request_info";

/** The lifecycle state of an approval request (an admin decision advances it). */
export type ApprovalStatus = "pending" | "approved" | "rejected" | "overridden";

/** A single issue the agent flagged while reviewing the dossier. */
export interface ApprovalIssue {
  severity: "info" | "warning" | "critical";
  code: string;
  message: string;
}

/** A single check the agent ran against the dossier (SIRET, docs, address, …). */
export interface ApprovalCheck {
  name: string;
  status: "ok" | "warning" | "blocked";
  detail: string;
}

/**
 * The full agent pre-analysis attached to an approval. The backend stores this
 * as a JSON string in the approval row's `agent_analysis` column — the proxy +
 * mapper parse it back into this shape before handing it to the UI.
 */
export interface AgentAnalysis {
  issues: ApprovalIssue[];
  checks: ApprovalCheck[];
  confidence: number;
  proposed_decision: ProposedDecision;
  proposed_reason: string;
}

/**
 * The full onboarding dossier that produced an approval. Surfaced in the
 * detail panel — every field the agent looked at is also visible to the
 * human reviewer.
 */
export interface OnboardingDossier {
  id: number;
  legal_name: string;
  siret: string;
  siret_valid: boolean;
  email: string;
  phone: string;
  declared_address: string;
  rib_document_present: boolean;
  id_document_present: boolean;
  professional_certificate_present: boolean;
  professional_certificate_expiry: string | null;
  document_address: string | null;
  submitted_at: string;
  status: ApprovalStatus;
  rejection_reason: string | null;
}

/** A row in the Ops Console list (left column). */
export interface ApprovalSummary {
  id: number;
  onboarding_id: number;
  legal_name: string;
  siret: string;
  proposed_decision: ProposedDecision;
  proposed_reason: string;
  confidence: number;
  status: ApprovalStatus;
  created_at: string;
  agent_analysis: AgentAnalysis;
  /** Present on decided rows — populated by the decide endpoint. */
  decided_by?: string | null;
  decided_at?: string | null;
  human_reason?: string | null;
  /** Final human decision (approve/reject/override) — null while pending. */
  final_decision?: "approve" | "reject" | "override" | null;
}

/** Full detail response returned by GET /api/approvals/{id}. */
export interface ApprovalDetail {
  approval: ApprovalSummary;
  onboarding: OnboardingDossier;
}

// ---------------------------------------------------------------------------
// Authentication & multi-tenancy (Phase 6a)
// ---------------------------------------------------------------------------
//
// The frontend speaks to the backend via JWT. The token carries the active
// tenant context (`tenant_id`, `role`, `producer_id`) and is attached to
// every API request via `Authorization: Bearer <token>`. When the user is
// NOT authenticated, the app falls back to the mock identities (Marie /
// Pierre / Admin) — the demo path described in the worklog.

/** The authenticated user record returned by /api/auth/login + /api/auth/me. */
export interface User {
  id: number;
  email: string;
  name: string;
}

/**
 * A tenant membership returned by /api/auth/me and /api/tenants/mine.
 *
 * `is_demo: true` flags the seeded Drive Producteur tenant (Marie / Pierre /
 * Admin demo accounts) — useful for surfacing a "Demo" badge in the tenant
 * switcher.
 */
export interface Tenant {
  tenant_id: string;
  name: string;
  slug: string;
  role: string;
  is_demo: boolean;
}

/** Auth response envelope returned by /api/auth/login + /api/auth/signup. */
export interface AuthResult {
  user: User;
  token: string;
}

/** /api/auth/me envelope — user + their tenant memberships. */
export interface MeResult {
  user: User;
  memberships: Tenant[];
}

// ---------------------------------------------------------------------------
// Onboarding wizard (Phase 6b)
// ---------------------------------------------------------------------------
//
// A freshly created tenant has no data connector and no schema/roles
// configured. The onboarding wizard walks the user through 4 steps:
//   1. Connect data (Postgres URL or CSV file upload)
//   2. Detect schema (auto-detect tables/columns, pick which to expose)
//   3. Define roles (admin + scoped roles with allowed tables)
//   4. Ready (summary + redirect to the agent chat)
//
// All of these types are persisted server-side on the backend; the frontend
// keeps a working copy in the store while the user is in the wizard.

/** The data source the tenant connected to during onboarding. */
export type ConnectorType = "postgres" | "csv" | "sqlite_demo";

/** Result of POST /onboarding/connect — the connection test outcome. */
export interface ConnectionTest {
  ok: boolean;
  error: string | null;
  tables_count: number;
}

/** A single column inside an auto-detected table. */
export interface SchemaColumn {
  name: string;
  type: string;
  description: string;
  /** User can toggle whether the agent sees this column. */
  selected: boolean;
}

/** A table detected from the connector (Postgres introspection or CSV header). */
export interface SchemaTable {
  name: string;
  description: string;
  columns: SchemaColumn[];
  /** User can toggle whether the agent sees this table. */
  selected: boolean;
  /**
   * The column the user picked as the RLS scope (e.g. "producer_id" or
   * "team_id"). Null = no row-level scoping on this table.
   */
  scope_column: string | null;
}

/** Auto-detected schema draft returned by /onboarding/detect-schema. */
export interface SchemaDraft {
  tables: SchemaTable[];
}

/** A role defined in step 3 of the wizard. */
export interface RoleConfig {
  name: string;
  /** Which column to scope by (null = admin / unscoped). */
  scope_column: string | null;
  /** Tables this role is allowed to query. */
  allowed_tables: string[];
}

/** GET /onboarding/status — drives the wizard gate in page.tsx. */
export interface OnboardingStatus {
  onboarded: boolean;
  connector_type: ConnectorType | null;
  schema_tables_count: number;
  roles_count: number;
}
