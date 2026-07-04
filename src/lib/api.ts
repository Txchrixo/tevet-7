import type {
  AssistantResponse,
  ChartSpec,
  ChartType,
  Identity,
  SecurityCheck,
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
