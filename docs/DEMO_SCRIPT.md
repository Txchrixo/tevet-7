# Tevet-7 — Demo Video Script (3 minutes / 180 seconds)

**Audience**: engineering recruiters, engineering managers, founder/CTOs evaluating AI agents for enterprise.
**Tone**: calm, factual, no hype. Show, don't tell.
**Setup**: screen recording at 1920×1080, 30 fps. UI in French (production locale), voice-over in English.
**Pacing**: one beat per row. If a row has multiple UI actions, allow ~1 second of silence between them.

---

## Segment map

| # | Time | Segment | Duration |
|---|------|---------|----------|
| 1 | 0:00–0:15 | Intro — what is Tevet-7 | 15 s |
| 2 | 0:15–0:40 | Producer Copilot — SQL + row-level scoping | 25 s |
| 3 | 0:40–1:00 | Identity switch — multi-tenant scoping | 20 s |
| 4 | 1:00–1:20 | Refusal path — security by construction | 20 s |
| 5 | 1:20–1:40 | RAG — documentary search with citations | 20 s |
| 6 | 1:40–2:00 | ML forecast — stock rupture prediction | 20 s |
| 7 | 2:00–2:25 | Ops Copilot + human-in-the-loop | 25 s |
| 8 | 2:25–2:45 | Admin console + tracing | 20 s |
| 9 | 2:45–3:00 | Multi-tenant pitch + closing | 15 s |

---

## Full script

| Time | Action | What to show | What to say (voice-over) |
|------|--------|--------------|---------------------------|
| 0:00 | Hold on the AuthScreen with the Tevet-7 logo and the "DÉMO PUBLIQUE" badge visible. | Login screen, Drive Producteur tenant selected, "Essayer la démo" button pulsing softly. | "Tevet-7 is a configurable AI agent platform for enterprises. The first tenant is Drive Producteur, a French short-supply-chain marketplace." |
| 0:08 | Slow zoom out to reveal the tagline + stack badges (FastAPI, Next.js, multi-tenant auth). | Stack footer: `FastAPI · Next.js · sqlglot · Langfuse · scikit-learn`. | "I built the full stack: FastAPI backend, Next.js frontend, multi-tenant auth, and six different agent capabilities." |
| 0:15 | Click **"Essayer la démo"** → identity picker appears → click **Marie (Producteur #42)**. | Identity switcher modal listing Marie (#42), Pierre (#99), Admin. Marie's card highlights on hover. | "Let's log in as Marie, producer number 42." |
| 0:22 | Type in the chat box: *"Quels sont mes 5 produits les plus vendus ce mois-ci ?"* → press Enter. | Producer Copilot view, chat input, send button. Loading skeleton appears. | "She asks for her top 5 products this month." |
| 0:30 | Render the assistant message: markdown answer, SQL block with `WHERE producer_id = 42` highlighted in yellow, bar chart of 5 products. | Answer card: "Vos 5 produits les plus vendus : Tomates cerises, Courgettes, Salade, Radis, Aubergines." SQL block with the predicate highlighted. Recharts BarChart below. | "The agent writes SQL, but sqlglot rewrites the AST to enforce row-level security. Marie only ever sees her own rows — the predicate is injected server-side, not by the prompt." |
| 0:36 | Click the message bubble → inspector trace slides in from the right. | Trace panel: 6 spans (intent → plan → SQL gen → sqlglot rewrite → execute → answer), each with latency and a green "security: ok" tag. | "Every message opens an inspector trace. Six steps, security checks at each boundary." |
| 0:40 | Click the identity switcher in the top bar → select **Pierre (Producteur #99)**. | Top-bar avatar swaps to Pierre, banner reads "Connecté en tant que Pierre — #99". Previous chat clears. | "Now let's switch to Pierre, producer 99, via the demo identity switcher." |
| 0:48 | Replay the same question: *"Quels sont mes 5 produits les plus vendus ce mois-ci ?"* | Same question in the input, new response renders. | "Same question, different producer." |
| 0:55 | Show the new answer: Pommes, Cidre, Poires, Jus de pomme, Calvados. SQL block now shows `WHERE producer_id = 99`. | Answer card with Normandy products. SQL predicate highlighted. Bar chart re-rendered. | "Different products, different SQL predicate — same prompt. The scoping is enforced server-side, so a producer can never read another producer's rows, even by prompt injection." |
| 1:00 | Still as Marie, type: *"Quels producteurs ont le plus de commandes ?"* | Chat input, send. Loading spinner briefly. | "Now let's test the security boundary. Marie asks to see all producers ranked by orders." |
| 1:08 | Render the refusal card: red left border, icon shield, text *"Action refusée — scoping violation"*, plus a short explanation paragraph. | Refusal message: "Cette requête demanderait des données appartenant à d'autres producteurs. Le scoping a été vérifié avant l'exécution SQL." No SQL block, no chart. | "The agent refuses before executing any SQL. The scoping check happens in the planner, not in the LLM — so the LLM cannot be jailbroken into leaking data." |
| 1:15 | Click the message → trace shows the refusal at step 2 (plan), with a red "scoping_violation" span. | Inspector: 2 spans, second one red, labeled "scoping_violation", "refused: producer scope cannot be lifted". | "The trace shows the refusal happened at the planning step — no SQL was ever generated." |
| 1:20 | Clear chat. Type: *"Quelles pièces sont nécessaires pour valider un producteur ?"* | Chat input, send. Loading skeleton. | "The agent also handles documentary questions." |
| 1:28 | Render the answer with three cited sources: FAQ Producteur §3, CGV Article 12, Procédure d'onboarding §2. Each citation is a clickable chip. | Answer card with markdown list: "KBIS, attestation d'assurance, RIB, extrait D1…". Below: three source chips with relevance scores (0.91, 0.84, 0.79). | "It searches documents with FTS5 BM25 ranking, and cites its sources with relevance scores — so the user can audit where the answer came from." |
| 1:38 | Hover one source chip → tooltip shows the matching snippet. | Tooltip: "Article 12 — Le producteur doit fournir un KBIS de moins de 3 mois…". | "No black-box answers. Every claim is traceable to a source." |
| 1:40 | Clear chat. Type: *"Quel stock va me manquer samedi ?"* | Chat input, send. Loading skeleton with "FORECAST_TOOL" badge. | "Now a predictive question — which stock will run out by Saturday?" |
| 1:48 | Render the forecast card: list of products with probability bars, top entry "Poireaux — 91% de risque". "FORECAST_TOOL" badge visible. | Forecast card: Poireaux 91%, Courgettes 64%, Tomates cerises 38%. Each row has a red/orange probability bar. Footer: "RandomForest, 6000 rows, F1 = 0.83". | "A RandomForest model predicts stock ruptures. F1 score: 0.83, trained on six thousand historical rows. The model is invoked as a tool — the agent decides when to call it." |
| 1:58 | Click the message → trace shows a "FORECAST_TOOL" span with model latency and version. | Inspector: 7 spans, span #4 labeled "FORECAST_TOOL v1.2", 120 ms, "rows=42". | "The forecast is its own trace span — model version, latency, input rows, all logged." |
| 2:00 | Open the identity switcher → select **Admin**. Top nav reveals "Ops Console" and "Console admin" links. | Top bar transforms: admin badge, two new menu items appear. | "Now let's switch to the admin role." |
| 2:06 | Click **"Ops Console"** → grid of 4 onboarding dossiers appears. Each card shows producer name, dossier status, and the agent's proposed decision. | Ops Console: 4 cards — "Ferme des Collines", "EARL du Val", "Maraîchage Bio Sud", "Vergers de l'Oise". Each card has a proposed decision (Approuver / Refuser / Demande d'info) and a confidence score. | "The Ops Copilot pre-analyzes onboarding dossiers — it pulls documents, checks completeness, and proposes a decision." |
| 2:16 | Click **"Approuver"** on the Ferme des Collines card → confirmation modal → confirm → toast "Décision enregistrée". | Modal: "Confirmer l'approbation de Ferme des Collines ?" with a free-text "Notes" field. Toast slides in bottom-right: "Décision enregistrée —Ferme des Collines approuvé par admin." | "But the admin always confirms. The agent proposes, the human decides. This is human-in-the-loop — the pattern enterprises actually want." |
| 2:23 | Show the dossier card now in "Approuvé" state with the admin's name and timestamp. | Card status badge flips to green "Approuvé", footer "par Admin · il y a 2 s". | "Every override is logged with who, when, and why." |
| 2:25 | Click **"Console admin"** in the top nav. | Admin console opens: stats header (5 conversations, 1280 tokens, $0.0004 cost, 1.2 s avg latency), then a table of recent traces. | "Every conversation is traced end-to-end. In dev, traces stay local; in production, they ship to Langfuse." |
| 2:33 | Scroll the trace table slowly. Highlight columns: tenant, user, tool calls, tokens, cost, latency, status. | Trace table rows: 5 conversations, each with its span count, tool breakdown, and cost. Top row cost: $0.0004. | "Five conversations, twelve hundred tokens, four cents of a cent — and every span is searchable. If you can't observe it, you can't improve it." |
| 2:40 | Click one trace row → expand to show the 6 spans inline. | Inline expansion: intent → plan → SQL → rewrite → execute → answer, with latencies. | "Token cost, latency, tool calls, security verdicts — all in one row." |
| 2:45 | Navigate back to the AuthScreen. Zoom on the "DÉMO PUBLIQUE" badge and the "Créer mon propre tenant" CTA button. | AuthScreen, CTA button glowing: "Créer mon propre tenant". | "Tevet-7 is multi-tenant by design. Anyone can sign up, create a workspace, connect their data via PostgreSQL or CSV, and get their own configured agent." |
| 2:52 | Hold on the CTA. Overlay appears: "39 cas de test · 8 tests de sécurité · 100% de passage". | Overlay text fades in over the CTA: "39 cas de test · 8 tests de sécurité · 100% de passage". | "Thirty-nine evaluation cases, eight security tests, all passing. The repo is open source — link in the description." |
| 2:58 | Fade to the Tevet-7 logo + GitHub URL + contact line. | End card: logo, `github.com/…/tevet-7`, contact email. | "Thanks for watching." |
| 3:00 | End. | Cut. | — |

---

## Production notes

- **B-roll**: none. The whole demo is a single screen recording. If a segment feels slow, trim silence rather than speeding up the tape.
- **Captions**: hardcode English subtitles for the French UI labels on first appearance (e.g. *"Essayer la démo = Try the demo"*), then drop the translation.
- **Audio**: record voice-over in a separate pass, not live. Aim for −16 LUFS, mono.
- **Anonymization**: producer names and products are fictitious. No real PII appears.
- **Retakes likely needed**: segment 4 (refusal) and segment 7 (HITL) — make sure the toast and the trace expansion are both fully visible before cutting.
- **Total runtime budget**: 180 s. If first cut is over 200 s, trim segments 5 and 8 first; never cut segment 4 (security) or segment 7 (HITL) — those are the differentiators.
