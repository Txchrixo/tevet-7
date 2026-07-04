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
