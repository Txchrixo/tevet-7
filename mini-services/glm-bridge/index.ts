/**
 * glm-bridge — OpenAI-compatible HTTP bridge to GLM-4.6 via z-ai-web-dev-sdk.
 *
 * THE PROBLEM
 * -----------
 * Tevet-7's agentic service is Python (FastAPI). The Z.ai SDK
 * (z-ai-web-dev-sdk) is Node.js only. We need GLM as the primary LLM
 * (free, no geo-block, function-calling capable) but can't call the SDK
 * from Python directly.
 *
 * THE SOLUTION
 * ------------
 * This mini-service exposes a minimal OpenAI-compatible HTTP API:
 *   POST /v1/chat/completions
 *     body: { messages, tools?, tool_choice?, temperature?, max_tokens?, stream? }
 *     resp: OpenAI ChatCompletion shape (or SSE stream of chunks)
 *
 * It translates OpenAI requests ↔ Z.ai SDK calls. The Python side calls
 * this as if it were OpenAI — no translation needed on the Python side.
 *
 * The bridge is a thin adapter: it maps tool_calls, streaming deltas,
 * and usage tokens. It does NOT do caching or fallback (the Python
 * ModelRouter handles those).
 *
 * Port: 3030 (dedicated, per mini-services convention).
 */

import ZAI from "z-ai-web-dev-sdk";

const PORT = 3030;
const MODEL = "glm-4.6";

// ─────────────────────────────────────────────────────────────────────────────
// ZAI client singleton (lazy init — the SDK reads env vars on first create).
// ─────────────────────────────────────────────────────────────────────────────

let _zai: ZAI | null = null;

async function getZai(): Promise<ZAI> {
  if (!_zai) {
    _zai = await ZAI.create();
    console.log("[glm-bridge] ZAI SDK initialized");
  }
  return _zai;
}

// ─────────────────────────────────────────────────────────────────────────────
// Request translation: OpenAI messages → ZAI messages
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Map OpenAI messages to ZAI SDK messages.
 *
 * The Z.ai SDK accepts the SAME message shape as OpenAI:
 *   - {role: "system"|"user"|"assistant", content: string}
 *   - {role: "assistant", content, tool_calls: [...]}  (assistant with tool calls)
 *   - {role: "tool", tool_call_id: "...", content: "..."}  (tool result)
 *
 * We pass messages through AS-IS (the SDK handles tool_calls + tool results
 * natively). We only coerce content to string (the SDK expects string, not
 * null/undefined).
 */
function mapMessages(messages: any[]): any[] {
  return messages.map((m) => {
    const msg: any = { role: m.role, content: String(m.content ?? "") };
    // Preserve tool_calls (assistant message requesting a tool call).
    if (m.tool_calls && Array.isArray(m.tool_calls)) {
      msg.tool_calls = m.tool_calls;
    }
    // Preserve tool_call_id (tool result message).
    if (m.tool_call_id) {
      msg.tool_call_id = m.tool_call_id;
    }
    return msg;
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Response translation: ZAI response → OpenAI ChatCompletion shape
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Build an OpenAI-compatible ChatCompletion from a ZAI chat response.
 *
 * The Z.ai SDK returns tool_calls in the SAME shape as OpenAI
 * (message.tool_calls = [{id, type, function: {name, arguments}}]).
 * We pass them through directly. The finish_reason is "tool_calls" when
 * the LLM requested a tool call, "stop" otherwise.
 */
function buildCompletion(
  zaiResponse: any,
  model: string
): any {
  const choice = zaiResponse?.choices?.[0];
  const message = choice?.message || {};
  const content = message.content || "";
  const toolCalls = message.tool_calls || [];
  const finishReason = choice?.finish_reason || "stop";
  const usage = zaiResponse?.usage || {};
  return {
    id: zaiResponse?.id || `glm-${Date.now()}`,
    object: "chat.completion",
    created: zaiResponse?.created || Math.floor(Date.now() / 1000),
    model,
    choices: [
      {
        index: 0,
        message: {
          role: "assistant",
          content,
          ...(toolCalls.length > 0 ? { tool_calls: toolCalls } : {}),
        },
        finish_reason: finishReason,
      },
    ],
    usage: {
      prompt_tokens: usage.prompt_tokens || 0,
      completion_tokens: usage.completion_tokens || 0,
      total_tokens:
        (usage.prompt_tokens || 0) + (usage.completion_tokens || 0),
    },
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// HTTP server (Bun.serve)
// ─────────────────────────────────────────────────────────────────────────────

const server = Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);

    // ── Health ──
    if (url.pathname === "/health" || url.pathname === "/") {
      return new Response(JSON.stringify({ status: "ok", model: MODEL }), {
        headers: { "content-type": "application/json" },
      });
    }

    // ── Models list (OpenAI-compatible) ──
    if (url.pathname === "/v1/models" && req.method === "GET") {
      return new Response(
        JSON.stringify({
          object: "list",
          data: [{ id: MODEL, object: "model", owned_by: "z-ai" }],
        }),
        { headers: { "content-type": "application/json" } }
      );
    }

    // ── Chat completions ──
    if (url.pathname === "/v1/chat/completions" && req.method === "POST") {
      try {
        const body = await req.json();
        const messages = mapMessages(body.messages || []);
        const temperature = body.temperature ?? 0.0;
        const maxTokens = body.max_tokens ?? 800;
        const stream = body.stream ?? false;
        const tools = body.tools;  // OpenAI tools array — pass through to SDK
        const toolChoice = body.tool_choice;  // "auto" | "none" | {type:"function",...}

        const zai = await getZai();

        // Build the SDK call kwargs. The Z.ai SDK accepts the same tools +
        // tool_choice shape as OpenAI (we verified this with a direct test).
        const sdkKwargs: any = {
          messages: messages as any,
          temperature,
          max_tokens: maxTokens,
        };
        if (tools && Array.isArray(tools) && tools.length > 0) {
          sdkKwargs.tools = tools;
          if (toolChoice) {
            sdkKwargs.tool_choice = toolChoice;
          }
        }

        if (stream) {
          // ── Streaming via SSE ──
          sdkKwargs.stream = true;
          const streamResp = await zai.chat.completions.create(sdkKwargs);

          const encoder = new TextEncoder();
          const sseStream = new ReadableStream({
            async start(controller) {
              try {
                for await (const chunk of streamResp as any) {
                  const delta = chunk?.choices?.[0]?.delta || {};
                  const content = delta.content || "";
                  const toolCalls = delta.tool_calls;
                  // Build the OpenAI chunk delta — include content + tool_calls
                  // (the LLM may stream either or both).
                  const deltaObj: any = {};
                  if (content) deltaObj.content = content;
                  if (toolCalls) deltaObj.tool_calls = toolCalls;
                  const finishReason = chunk?.choices?.[0]?.finish_reason || null;
                  const openaiChunk = {
                    id: `glm-${Date.now()}`,
                    object: "chat.completion.chunk",
                    created: Math.floor(Date.now() / 1000),
                    model: MODEL,
                    choices: [
                      {
                        index: 0,
                        delta: deltaObj,
                        finish_reason: finishReason,
                      },
                    ],
                  };
                  controller.enqueue(
                    encoder.encode(`data: ${JSON.stringify(openaiChunk)}\n\n`)
                  );
                }
                // Final chunk with usage (if available).
                const finalChunk = {
                  id: `glm-${Date.now()}`,
                  object: "chat.completion.chunk",
                  created: Math.floor(Date.now() / 1000),
                  model: MODEL,
                  choices: [],
                  usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
                };
                controller.enqueue(
                  encoder.encode(`data: ${JSON.stringify(finalChunk)}\n\n`)
                );
                controller.enqueue(encoder.encode("data: [DONE]\n\n"));
                controller.close();
              } catch (err: any) {
                controller.error(err);
              }
            },
          });

          return new Response(sseStream, {
            headers: {
              "content-type": "text/event-stream",
              "cache-control": "no-cache",
              connection: "keep-alive",
            },
          });
        }

        // ── Non-streaming ──
        const zaiResp = await zai.chat.completions.create(sdkKwargs);

        const completion = buildCompletion(zaiResp, MODEL);
        return new Response(JSON.stringify(completion), {
          headers: { "content-type": "application/json" },
        });
      } catch (err: any) {
        console.error("[glm-bridge] chat error:", err);
        return new Response(
          JSON.stringify({
            error: {
              message: err?.message || "glm-bridge internal error",
              type: "bridge_error",
            },
          }),
          { status: 500, headers: { "content-type": "application/json" } }
        );
      }
    }

    // ── 404 ──
    return new Response(JSON.stringify({ error: "not found", path: url.pathname }), {
      status: 404,
      headers: { "content-type": "application/json" },
    });
  },
});

console.log(`[glm-bridge] listening on http://localhost:${PORT} (model=${MODEL})`);
