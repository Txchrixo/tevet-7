import type {
  AssistantResponse,
  ChartSpec,
  ChartType,
  DocumentInfo,
  Identity,
  SecurityCheck,
  Source,
  TraceStatus,
  TraceStep,
} from "./types";

// ---------------------------------------------------------------------------
// Backend contract — POST /api/chat (proxied by Next.js route handler)
// ---------------------------------------------------------------------------
//
// The FastAPI service (under agentic-service/) speaks snake_case JSON. The
// frontend `AssistantResponse` type uses camelCase, so we map fields 1:1 here.
// The semantic shape is identical: answer, sql, scope clause, chart spec,
// token counts, latency, tool calls, trace steps, security checks, refusal
// flag. The backend also returns a `tables_touched` array which we ignore.
//
// The browser calls the relative `/api/chat` (same origin). A Next.js route
// handler at `src/app/api/chat/route.ts` proxies the request server-side to
// `http://localhost:8001/api/chat`. This avoids any dependency on the Caddy
// gateway (port 81) or `XTransformPort` query — the proxy works regardless
// of which port the Preview Panel uses to serve the app.

const BACKEND_URL = "/api/chat";
const BACKEND_TIMEOUT_MS = 12000;

// -- Raw backend types (snake_case) ----------------------------------------

interface BackendChartSeries {
  key: string;
  label: string;
  color?: string;
}

interface BackendChart {
  type: ChartType;
  title?: string;
  xKey: string;
  series: BackendChartSeries[];
  data: Record<string, string | number>[];
  unit?: string;
}

interface BackendStep {
  index: number;
  title: string;
  detail: string;
  status: TraceStatus;
  duration_ms: number;
}

interface BackendSecurityCheck {
  label: string;
  status: TraceStatus;
  detail?: string;
}

interface BackendResponse {
  answer: string;
  sql: string | null;
  scope_clause: string | null;
  chart: BackendChart | null;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  tool_calls: string[];
  steps: BackendStep[];
  security_checks: BackendSecurityCheck[];
  refused: boolean;
  tables_touched?: string[];
  /** RAG citations — present only for documentary answers (Phase 3). */
  sources?: BackendSource[];
}

interface BackendSource {
  /**
   * The backend emits two source kinds today: `"document"` (RAG citation —
   * the shape described in the task contract) and `"sql"` (analytical
   * provenance metadata, e.g. `{type: "sql", tables: [...]}`). We filter to
   * `"document"` in `mapResponse` so the frontend never sees the sql-kind.
   */
  type: "document" | "sql" | string;
  title?: string;
  chunk_index?: number;
  document_id?: number;
  score?: number;
  /** Present on `type: "sql"` sources — ignored by the frontend. */
  tables?: string[];
}

interface BackendDocument {
  id: number;
  title: string;
  source_type: "pdf" | "text" | "manual";
  created_at: string;
  chunks_count: number;
  producer_id: number | null;
}

interface BackendDocumentListResponse {
  documents: BackendDocument[];
}

interface BackendUploadResponse {
  document_id: number;
  title: string;
  chunks_count: number;
}

// -- Mappers (snake_case → camelCase) --------------------------------------

function mapChart(c: BackendChart): ChartSpec {
  return {
    type: c.type,
    title: c.title,
    xKey: c.xKey,
    series: c.series.map((s) => ({
      key: s.key,
      label: s.label,
      color: s.color,
    })),
    data: c.data,
    unit: c.unit,
  };
}

function mapStep(s: BackendStep): TraceStep {
  return {
    index: s.index,
    title: s.title,
    detail: s.detail,
    status: s.status,
    durationMs: s.duration_ms,
  };
}

function mapSecurityCheck(s: BackendSecurityCheck): SecurityCheck {
  return {
    label: s.label,
    status: s.status,
    detail: s.detail,
  };
}

function mapResponse(r: BackendResponse): AssistantResponse {
  return {
    answer: r.answer,
    sql: r.sql,
    scopeClause: r.scope_clause,
    chart: r.chart ? mapChart(r.chart) : undefined,
    tokensIn: r.tokens_in,
    tokensOut: r.tokens_out,
    latencyMs: r.latency_ms,
    toolCalls: r.tool_calls,
    steps: r.steps.map(mapStep),
    securityChecks: r.security_checks.map(mapSecurityCheck),
    refused: r.refused,
    // Keep only documentary citations — the backend also emits `{type: "sql",
    // tables: [...]}` entries on analytical responses (provenance metadata,
    // not user-facing citations). Those are filtered out so the chat
    // message's "Sources citées" block only ever shows RAG citations.
    sources: r.sources
      ?.filter((s) => s.type === "document")
      .map(mapSource),
  };
}

function mapSource(s: BackendSource): Source {
  return {
    type: "document",
    title: s.title ?? "",
    chunkIndex: s.chunk_index ?? 0,
    documentId: s.document_id ?? 0,
    score: s.score,
  };
}

function mapDocument(d: BackendDocument): DocumentInfo {
  return {
    id: d.id,
    title: d.title,
    sourceType: d.source_type,
    createdAt: d.created_at,
    chunksCount: d.chunks_count,
    producerId: d.producer_id,
  };
}

// -- Public API ------------------------------------------------------------

/**
 * Send a chat message to the FastAPI backend and return its AssistantResponse.
 *
 * Builds the request body from the active identity:
 *   - `identity_id`: identity.id (e.g. "producer-42", "admin")
 *   - `producer_id`: identity.producerId (null for admin)
 *   - `role`:        identity.kind ("producer" | "admin")
 *
 * Uses an AbortController to enforce an 8-second timeout. Any failure —
 * network error, non-2xx status, parse error, or timeout — throws an Error
 * so the caller can fall back to the mock layer.
 */
export async function callBackend(
  message: string,
  identity: Identity,
): Promise<AssistantResponse> {
  const body = {
    message,
    identity_id: identity.id,
    producer_id: identity.producerId,
    role: identity.kind,
  };

  const controller = new AbortController();
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    BACKEND_TIMEOUT_MS,
  );

  try {
    const res = await fetch(BACKEND_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    if (!res.ok) {
      throw new Error(
        `Backend responded with HTTP ${res.status} ${res.statusText}`,
      );
    }

    let json: unknown;
    try {
      json = await res.json();
    } catch (parseErr) {
      throw new Error(
        `Backend returned non-JSON body: ${
          parseErr instanceof Error ? parseErr.message : String(parseErr)
        }`,
      );
    }

    return mapResponse(json as BackendResponse);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(`Backend timed out after ${BACKEND_TIMEOUT_MS} ms`);
    }
    // Re-throw unchanged — the store handles the fallback.
    throw err;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

// ---------------------------------------------------------------------------
// Document corpus API — RAG (Phase 3)
// ---------------------------------------------------------------------------
//
// All requests go through the relative `/api/documents` path. Next.js route
// handlers proxy them server-side to `http://localhost:8001/api/documents`
// (same pattern as the chat proxy) — the browser never talks to the FastAPI
// service directly, so the prototype works on any port the Preview Panel
// serves the app on.

const DOCUMENTS_URL = "/api/documents";
const DOCUMENTS_TIMEOUT_MS = 30_000;

/** Upload input — either an attached PDF file or raw text content. */
export type DocumentUploadInput =
  | { kind: "file"; title: string; file: File }
  | { kind: "text"; title: string; content: string };

export interface DocumentUploadResult {
  documentId: number;
  title: string;
  chunksCount: number;
}

/**
 * List indexed documents.
 *
 * We deliberately do NOT scope the GET by `producer_id` from the frontend,
 * even when the active identity is a producer. The seeded corpus (CGV, FAQ,
 * Procédure, Politique de retrait) is tenant-level (`producer_id = null`) and
 * is visible to every producer — the RAG retriever returns these chunks to
 * producers, so the panel must show them too (otherwise the user would see
 * "Source citée : FAQ Producteurs" in a chat answer without ever having seen
 * the document listed).
 *
 * The `identity` parameter is kept on the signature for future use (e.g.
 * surfacing a "your docs" filter chip) and to keep the call site symmetric
 * with `uploadDocument`.
 */
export async function listDocuments(
  _identity: Identity,
): Promise<DocumentInfo[]> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    DOCUMENTS_TIMEOUT_MS,
  );

  try {
    const res = await fetch(DOCUMENTS_URL, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    if (!res.ok) {
      throw new Error(
        `listDocuments → HTTP ${res.status} ${res.statusText}`,
      );
    }
    const json = (await res.json()) as BackendDocumentListResponse;
    return (json.documents ?? []).map(mapDocument);
  } finally {
    window.clearTimeout(timeoutId);
  }
}

/**
 * Upload a document (PDF file or raw text) for indexing. The backend chunks
 * the content, embeds it, and stores the chunks in the RAG vector store.
 *
 * Returns `{ documentId, title, chunksCount }` so the UI can show a toast
 * like "Document indexé (12 chunks)".
 */
export async function uploadDocument(
  input: DocumentUploadInput,
  identity: Identity,
): Promise<DocumentUploadResult> {
  const fd = new FormData();
  fd.append("title", input.title);
  if (input.kind === "file") {
    fd.append("source_type", "pdf");
    fd.append("file", input.file, input.file.name || "upload.pdf");
  } else {
    fd.append("source_type", "text");
    fd.append("content", input.content);
  }
  if (identity.producerId != null) {
    fd.append("producer_id", String(identity.producerId));
  }

  const controller = new AbortController();
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    DOCUMENTS_TIMEOUT_MS,
  );

  try {
    const res = await fetch(DOCUMENTS_URL, {
      method: "POST",
      body: fd,
      signal: controller.signal,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(
        `uploadDocument → HTTP ${res.status} ${res.statusText}${text ? `: ${text}` : ""}`,
      );
    }
    const json = (await res.json()) as BackendUploadResponse;
    return {
      documentId: json.document_id,
      title: json.title,
      chunksCount: json.chunks_count,
    };
  } finally {
    window.clearTimeout(timeoutId);
  }
}

/** Delete an indexed document by id. */
export async function deleteDocument(id: number): Promise<void> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    DOCUMENTS_TIMEOUT_MS,
  );

  try {
    const res = await fetch(`${DOCUMENTS_URL}/${id}`, {
      method: "DELETE",
      signal: controller.signal,
    });
    if (!res.ok) {
      throw new Error(
        `deleteDocument → HTTP ${res.status} ${res.statusText}`,
      );
    }
  } finally {
    window.clearTimeout(timeoutId);
  }
}
