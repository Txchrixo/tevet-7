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
