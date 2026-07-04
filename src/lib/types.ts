// Core domain types for the Tevet-7 Producer Copilot prototype.

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
  /**
   * Documentary (RAG) citations. Populated when the agent answered by
   * searching the indexed document corpus rather than generating SQL.
   * Empty/undefined for analytical responses.
   */
  sources?: Source[];
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
