# Task 2 — full-stack-developer — Producer Copilot prototype

## What was asked
Build a visual prototype of the **Producer Copilot** (OpsPilot AI) in the existing Next.js 16 project at `/`. A B2B SaaS chat UI that simulates an AI agent answering a producer's business questions with SQL-backed data, mock only (no backend). Key demo: multi-tenant row-level security made visible — the same question yields different SQL scope and data depending on identity, with the `WHERE producer_id = X` clause highlighted in emerald.

## Files created / modified
- `src/lib/types.ts` — Identity, ChatMessage, AssistantResponse, ChartSpec, TraceStep, SecurityCheck.
- `src/lib/mock-data.ts` — 3 identities, 5 example questions, full response map `${identityId}:${questionId}` with realistic multi-line SQL, charts, trace steps, security checks; refusals for cross-producer questions asked by a producer; admin aggregated responses.
- `src/lib/store.ts` — zustand store (identity, messages, selectedMessageId, isStreaming, inspectorOpen) + simulated streaming latency.
- `src/components/theme-provider.tsx` — next-themes wrapper.
- `src/components/producer-copilot/sql-block.tsx` — dark editor-style SQL block with hand-rolled tokenizer + emerald highlight of the exact scope clause.
- `src/components/producer-copilot/markdown.tsx` — dependency-free Markdown renderer (paragraphs, lists, pipe tables, bold, inline code).
- `src/components/producer-copilot/chart-display.tsx` — recharts bar/line with emerald/teal/amber palette.
- `src/components/producer-copilot/chat-message.tsx` — user/assistant bubbles, markdown, SQL block, chart, footer + TypingIndicator.
- `src/components/producer-copilot/inspector.tsx` — agent trace (6 steps), security checklist, token/cost breakdown, empty state.
- `src/components/producer-copilot/identity-switcher.tsx`, `sidebar.tsx`, `header.tsx`, `chat-input.tsx`, `footer.tsx`.
- `src/app/page.tsx` — 3-zone responsive layout, sticky footer, mobile Sheets, welcome state.
- `src/app/layout.tsx` — lang fr, ThemeProvider, Sonner toaster, metadata.

## Mock scenarios implemented (per identity × question)
- **Producer #42 (Ferme du Vallon)** — top 5 products (tomates/courgettes/carottes/salade/poireaux, bar chart), stock shortfall for Saturday (3 refs, deficit bar chart + table), net revenue June (4820€ gross → 4241.60€ net), weekly sales summary (7-day line chart, 101 orders / 4470€).
- **Producer #99 (Verger de la Côte)** — same 4 questions with DIFFERENT data (pommes/poires/jus, 6150€ gross, 135 orders). Same SQL shape but `producer_id = 99`.
- **DP Admin** — tenant-wide aggregated versions of all 5 questions (no `producer_id` clause; security check shows "full access (admin)" as warning). Top producers question returns all 7 producers ranked.
- **Refusal path** — a producer asking "Quels producteurs ont le plus de commandes ?" gets a polite refusal, no SQL executed, inspector shows blocked trace ("scoping violation").
- **Free-form fallback** — any typed question gets a synthesized scoped weekly summary so the prototype never breaks.

## Quality / lint
- `bun run lint` → exit 0 (no errors).
- Dev server compiles cleanly, `GET /` returns HTTP 200.

## Limitations
- Fully client-side mock — no real SQL, Langfuse, or backend.
- Sidebar history is cosmetic (seeded, not interactive).
- Settings gear is non-functional.
- No conversation persistence across reloads.
EOF
