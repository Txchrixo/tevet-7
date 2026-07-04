// Core domain types for the Tevet-7 agent platform.

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
// Tevet-7 admin console
// ---------------------------------------------------------------------------

/** A tenant membership returned by `GET /api/auth/me` or `GET /api/tenants/mine`. */
export interface TenantMembership {
  tenant_id: string;
  name: string;
  slug: string;
  role: "producer" | "admin" | "customer" | string;
  producer_id: number | null;
  is_demo: boolean;
  is_active: boolean;
  /** True when the tenant has completed the onboarding wizard (data connected +
   * schema saved + roles saved + complete endpoint called). When false, the
   * frontend gates the chat surface and shows the OnboardingWizard instead. */
  onboarded: boolean;
}

/** Authenticated user as returned by `POST /api/auth/login` or `GET /api/auth/me`. */
export interface AuthUser {
  id: number;
  email: string;
  name: string;
  created_at: string | null;
}

/** A tenant admin as returned by `GET /api/admin/tenants/{id}/users`. */
export interface TenantUser {
  user_id: number;
  email: string;
  name: string;
  role: string;
  producer_id: number | null;
  joined_at: string;
}

/** Tenant configuration as returned by `GET /api/admin/tenants/{id}/config`. */
export interface TenantConfig {
  connector_type: string;
  schema_config: unknown;
  roles_config: unknown;
  onboarded: boolean;
  created_at: string;
}

/** A conversation trace row (tenant admin scope). */
export interface Conversation {
  id: string;
  user_message: string;
  intent: string;
  latency_ms: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  refused: boolean;
  created_at: string;
}

/** Tenant-level aggregated stats. */
export interface TenantStats {
  total_conversations: number;
  total_tokens: number;
  total_cost_usd: number;
  avg_latency_ms: number;
  refusal_rate: number;
  last_activity_at: string | null;
}

/** A tenant summary as seen by the platform owner. */
export interface PlatformTenant {
  id: string;
  name: string;
  slug: string;
  is_demo: boolean;
  onboarded: boolean;
  member_count: number;
  conversation_count: number;
  total_cost_usd: number;
  created_at: string;
}

/** Platform-wide aggregated stats. */
export interface PlatformStats {
  total_tenants: number;
  total_users: number;
  total_conversations: number;
  total_cost_usd: number;
  total_tokens: number;
  avg_latency_ms: number;
}

/** Result of `POST /api/admin/platform/reset-demo`. */
export interface ResetResult {
  reset: boolean;
  orders_reseeded: number;
  docs_reseeded: number;
}

// ---------------------------------------------------------------------------
// Phase 6d — Dynamic example questions
// ---------------------------------------------------------------------------

/**
 * A natural-language example question shown in the sidebar's "Exemples"
 * section. Generated server-side from the tenant's `schema_config` (see
 * `GET /api/tenants/{id}/example-questions`). The `hint` field is
 * optional — only set on the hardcoded Drive Producteur fallback
 * questions (e.g. the "Accès admin requis" hint on the top-producers
 * question).
 */
export interface ExampleQuestion {
  id: string;
  /** The question text shown to the user and sent as a user message. */
  label: string;
  /** Optional hint about access scope (e.g. "Accès admin requis"). */
  hint?: string;
}

// ---------------------------------------------------------------------------
// Tevet-7 onboarding wizard
// ---------------------------------------------------------------------------

/** A column detected in a tenant's source data (Postgres schema or CSV header). */
export interface OnboardingSchemaColumn {
  name: string;
  type: string;
  description?: string;
  /** Wizard-only flag — true when the user keeps this column in the agent's
   * scope. Deselected columns are dropped from the saved schema_config. */
  selected: boolean;
}

/** A table detected in a tenant's source data. */
export interface OnboardingSchemaTable {
  name: string;
  description?: string;
  columns: OnboardingSchemaColumn[];
  /** Wizard-only flag — true when the table is kept in the agent's scope. */
  selected: boolean;
  /** The RLS scope column for this table (e.g. "producer_id"). Null when the
   * table is global (no per-row scoping) or when the user hasn't picked one. */
  scope_column: string | null;
}

/** A role defined during onboarding step 3. Persisted as roles_config. */
export interface OnboardingRole {
  name: string;
  /** The column used for row-level scoping for this role. Null for admins
   * (full-tenant access). For producers, typically "producer_id". */
  scope_column: string | null;
  /** The tables this role can query. Empty array means no tables. */
  allowed_tables: string[];
}

/** Status returned by `GET /api/tenants/{id}/onboarding/status`. */
export interface OnboardingStatus {
  onboarded: boolean;
  connector_type: string | null;
  schema_tables_count: number;
  roles_count: number;
}

/** Result of `POST /api/tenants/{id}/onboarding/connect` (Postgres + CSV). */
export interface OnboardingConnectResult {
  ok: boolean;
  error: string | null;
  tables_count: number;
}

/** Result of `POST /api/tenants/{id}/onboarding/save-schema` and
 * `save-roles`, and `POST /api/tenants/{id}/onboarding/complete`. */
export interface OnboardingSaveResult {
  ok: boolean;
}
