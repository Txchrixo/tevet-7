# Task 4 — Rebrand to "Tevet-7" + apply strict design system

**Agent:** full-stack-developer
**Task ID:** 4

## What was asked

Completely rebrand the existing OpsPilot AI Producer Copilot prototype to
"Tevet-7" and apply a strict new design system: dark green palette
(#2D3A2F / #E8E0C9 / #5A6B4A / #A8C090 / #605E58 / #A4A096), Caudex serif
headings + Manrope body, Feather icons (local SVGs, no lucide-react in our
code), custom heptagon brand mark, "ledger/journal" aesthetic for all numbers.
All Phase 0 functionality (3 identities, 5 example questions, SQL scoping
highlight, charts, inspector trace, refusal path, sticky footer, mobile
sheets) must remain IDENTICAL — only the visual design changes.

## Work Log

- Read worklog.md (Tasks 0–3) and all existing src/ files to understand the
  Phase 0 prototype structure.
- Created `src/components/ui/feather-icons.tsx` — 30 inline SVG components
  copied from feathericons.com (MIT): Menu, X, Send, ChevronDown, Check,
  AlertTriangle, AlertOctagon, Shield, ShieldOff, Database, Clock, Hash, Copy,
  Activity, ArrowRight, ArrowUp, Settings, Cpu, Zap, Server, Search, User,
  Lock, Plus, MessageSquare, BarChart2, TrendingUp, RefreshCw, Eye. Each
  accepts `{ size?, className?, strokeWidth? }` defaulting to size=20,
  strokeWidth=1.75.
- Created `src/components/producer-copilot/brand-mark.tsx` — three exports:
  - `BrandMark` — heptagon (7-sided regular polygon) SVG outline in accent
    (#A8C090) with a filled circle node at the top vertex in foreground
    (#E8E0C9). Circumradius 9, centered at (12,12), coordinates precomputed.
  - `BrandWordmark` — "Tevet" in Caudex (foreground) + "-" (muted) + "7" in
    accent. Uses `font-heading`.
  - `BrandLogo` — BrandMark + BrandWordmark side by side.
- Rewrote `src/app/layout.tsx` — removed Geist next/font imports, added 4 font
  `<link>` tags (preconnect + Caudex + Manrope stylesheets), set
  `<html lang="fr" className="dark">`, ThemeProvider with
  `defaultTheme="dark" forcedTheme="dark" enableSystem={false}`, body
  `font-body antialiased bg-background text-foreground`, metadata title
  "Tevet-7 — Producer Copilot (Drive Producteur)". Added eslint-disable
  comments for the `no-page-custom-font` rule (unavoidable per spec).
- Rewrote `src/app/globals.css` — single dark theme in `:root` (no `.dark`
  color overrides). Tokens: `--font-heading: 'Caudex', serif`,
  `--font-body: 'Manrope', sans-serif`, `--font-mono: ui-monospace, 'SF
  Mono', monospace`, `--radius: 0.375rem`. The 6 brand colors + 2 surface
  variants (secondary/muted = #3A4A3C, same green hue). `--destructive` set
  to muted (#A4A096) — no red. Chart colors mapped to palette tokens. Base
  layer: headings use `font-heading` + `letter-spacing: -0.01em`; `.tabular-nums`
  utility.
- Rewrote `src/components/producer-copilot/header.tsx` — BrandLogo on left,
  thin separator, "Drive Producteur" badge (uppercase tracking-wide caption),
  scope breadcrumb with producer number in Caudex accent, Phase 0 badge,
  Settings button (feather), inspector toggle (feather Eye), mobile Menu
  button. Removed theme toggle. All icons from feather-icons.
- Rewrote `src/components/producer-copilot/footer.tsx` — sticky `mt-auto`, thin
  top border, flat bg-background (no blur). Left: "Tevet-7 · Phase 0
  Prototype", center: "Drive Producteur tenant", right: feather Shield
  (accent) + "Scoping actif". All Manrope caption uppercase tracking-wide.
- Rewrote `src/components/producer-copilot/identity-switcher.tsx` —
  shadcn DropdownMenu. Trigger: avatar circle (initials in Caudex on
  primary/accent bg), name (Manrope 500), subtitle with producer number in
  Caudex. Feather ChevronDown. Selected item: feather Check in accent.
  Feather Shield (admin) / User (producer) icons. No emerald.
- Rewrote `src/components/producer-copilot/sidebar.tsx` — IdentitySwitcher at
  top, "Nouvelle conv." button (feather Plus, ghost/outline), "Réinitialiser"
  as subtle text button (feather RefreshCw), "EXEMPLES" section label
  (uppercase tracking-wide caption), example chips with feather Hash icon
  (hover → accent), the "sera refusé" chip has dashed border + feather
  ShieldOff + muted text. History with ledger numbers "01"/"02"/"03" in
  Caudex accent.
- Rewrote `src/components/producer-copilot/sql-block.tsx` — shadcn Collapsible.
  Trigger: feather Database + "SQL exécuté" (uppercase caption muted) + badge
  ("Scoping appliqué" with accent/10 bg + accent text + accent/30 border, or
  "Full access" with muted styling). Content: `<pre>` with bg #232E25 (darker
  green), border, padding 16px, rounded-md. Line numbers in Caudex (muted,
  tabular-nums). Scoping highlight: precise regex scanner
  `/([A-Za-z_][A-Za-z0-9_]*\.)?producer_id\s*=\s*\d+/i` wraps the whole
  `producer_id = N` (or `alias.producer_id = N`) span in accent (#A8C090) +
  font-weight 500. Tokenizer uses palette colors (keywords → accent/90,
  strings → foreground, numbers → Caudex muted, comments → muted).
- Rewrote `src/components/producer-copilot/chart-display.tsx` — recharts
  BarChart/LineChart. COLOR_MAP keys renamed to palette tokens (accent,
  primary, foreground, muted, border) → hex values. Axis ticks in Caudex
  (fontFamily: 'Caudex, serif', fontSize 11, fill #A4A096). Grid lines
  #605E58 at 0.4 opacity. Tooltip bg #2D3A2F, border #605E58, text #E8E0C9.
  Chart title in Caudex (font-heading).
- Rewrote `src/components/producer-copilot/inspector.tsx` — header "TRACE DE
  L'AGENT" (uppercase caption muted) + feather X close. Empty state: feather
  Eye + "Sélectionnez un message pour voir la trace". Steps: ledger numbers
  "01"–"06" in Caudex accent, vertical thin connector line (border) between
  steps, title (Manrope 500), detail (caption muted), duration in Caudex
  muted. Status icons: ok → Check (accent), warning → AlertTriangle (muted),
  blocked → ShieldOff (muted). "SÉCURITÉ" section with checklist. SQL block
  (same component). "COÛT & TOKENS" section: grid of TOKENS ENTRÉE / SORTIE
  / TOTAL / LATENCE / COÛT / DURÉE — values in Caudex (large), labels in
  Manrope caption uppercase muted. Footer note "Trace simulée — en
  production, journalisée dans Langfuse." All borders 1px #605E58, no
  shadows.
- Rewrote `src/components/producer-copilot/chat-message.tsx` — user message:
  bg-secondary, Manrope, rounded-md, right-aligned. Assistant: bg-background
  + border, BrandMark avatar in bordered square (replaces emerald gradient
  Bot). Footer: micro-labels uppercase tracking-wide muted — "SCOPE VÉRIFIÉ"
  + accent Check, tokens in Caudex tabular-nums, latency in Caudex,
  sql_read_tool badge. TypingIndicator: 3 muted dots with framer-motion
  bounce. REFUSED: card has dashed border, header row with feather ShieldOff
  (muted) + "Action refusée" (Manrope 500 muted — NOT red), reason text
  below, no SQL block, footer shows "ACTION REFUSÉE · scoping violation" in
  muted.
- Rewrote `src/components/producer-copilot/chat-input.tsx` — bordered
  container (border, bg-background, rounded-md), input Manrope with muted
  placeholder "Posez votre question à l'agent Tevet-7…", send button
  bg-primary text-primary-foreground, hover → bg-accent. Feather ArrowUp
  icon.
- Updated `src/components/producer-copilot/markdown.tsx` — removed all
  emerald classes, list markers → accent, inline code → accent on
  bg-secondary, tables bordered with bg-secondary/50 header.
- Updated `src/lib/mock-data.ts` — renamed chart series color keys from
  Tailwind default scale names (emerald/teal/amber/rose) to palette tokens
  (accent/primary/foreground/muted). No "OpsPilot" string references found
  in mock-data (only in chat-input placeholder, which was rewritten).
- Updated `src/lib/types.ts` — comment rebranded OpsPilot → Tevet-7.
- Rewrote `src/app/page.tsx` — removed lucide-react Bot/Sparkles imports.
  WelcomeState: BrandMark hero in bordered square (border, bg-background,
  text-accent) instead of emerald gradient. "Bonjour {name}" h1 in Caudex.
  Description mentions "Tevet-7" + "Producer Copilot". Scope badge:
  border-accent/30 bg-accent/5 text-accent. sql_read_tool badge with feather
  Zap (muted). Example cards: border, bg-background, hover border-accent/60.
  "›" prefix in Caudex accent. Bottom hint uppercase tracking-wide muted.
  Page wrapper bg-background (removed bg-muted/30). Removed backdrop-blur
  from chat-input dock + footer. Kept 3-zone layout, sticky footer, mobile
  Sheets.
- `bun run lint` → 0 errors, 0 warnings (after adding eslint-disable comments
  for the unavoidable `no-page-custom-font` rule required by the design
  system spec).
- Verification greps: 0 matches for `lucide-react` in producer-copilot/ +
  page.tsx; 0 matches for `emerald|teal|indigo|slate|gray-|blue-` (and
  `amber|rose|sky`) in producer-copilot/ + app/; 0 matches for `OpsPilot` in
  src/.
- agent-browser end-to-end verification: page loads (title "Tevet-7 —
  Producer Copilot (Drive Producteur)"), "Bonjour Marie" h1, 5 example
  questions with "SERA REFUSÉ · SCOPING PRODUCER" hint on top-producers,
  history ledger 01/02/03. Clicked "5 produits les plus vendus" → response +
  SQL block with line numbers + "SCOPING APPLIQUÉ" badge + accent-highlighted
  `producer_id = 42`. Clicked top-producers as producer → REFUSAL with dashed
  border, "Action refusée" header (ShieldOff muted), "ACTION REFUSÉE ·
  SCOPING VIOLATION" footer, 483 tokens, 0,9 s. Inspector opens with "TRACE
  DE L'AGENT" heading. Identity switch → Admin → toast "Scope modifié" +
  "Bonjour DP". 0 console errors.

## Stage Summary

- Brand: prototype fully rebranded from "OpsPilot AI" to "Tevet-7". Custom
  heptagon brand mark (7-sided polygon referencing the "7") drawn as SVG
  outline in accent (#A8C090) with a filled foreground node at the top
  vertex. Wordmark "Tevet-7" with the "7" in accent.
- Design system: strict 6-color dark green palette applied everywhere
  (background #2D3A2F, foreground #E8E0C9, primary #5A6B4A, accent #A8C090,
  border #605E58, muted-foreground #A4A096) + 2 surface variants in the same
  green hue. No red — error/refusal states use muted-foreground + dashed
  borders + ShieldOff icon. No Tailwind default color scales anywhere.
- Typography: Caudex (serif) for all headings, display, hero, and ALL
  numbers/metrics (tokens, latency, IDs, step numbers, chart axis ticks, SQL
  line numbers) — the "ledger/journal" feel. Manrope (sans) for body, labels,
  UI copy. Loaded via `<link>` tags in layout `<head>` (no next/font).
- Icons: 30 Feather icons as local inline SVG components
  (`src/components/ui/feather-icons.tsx`). Zero lucide-react imports in
  producer-copilot/ or page.tsx. shadcn/ui internal components keep their
  own lucide-react (untouched, as instructed).
- Components: minimalist — thin 1px borders instead of shadows, rounded-md,
  generous spacing. Buttons primary (#5A6B4A bg, #2D3A2F text) with accent
  hover. Cards bg-background + border. Inputs border + muted placeholder.
- Functionality: 100% preserved — 3 identities (Marie #42, Pierre #99, DP
  Admin), 5 example questions, SQL block with precise scoping highlight
  (`producer_id = N` in accent), charts in palette colors, inspector trace
  with ledger-numbered steps + COÛT & TOKENS grid, refusal path with dashed
  treatment, sticky footer, mobile Sheets. All verified via agent-browser.
- Lint: 0 errors, 0 warnings. Dev server compiles clean (HTTP 200).
- Files created: `src/components/ui/feather-icons.tsx`,
  `src/components/producer-copilot/brand-mark.tsx`.
- Files modified: `src/app/layout.tsx`, `src/app/globals.css`,
  `src/app/page.tsx`, `src/lib/types.ts`, `src/lib/mock-data.ts`, and all 10
  files in `src/components/producer-copilot/` (header, footer,
  identity-switcher, sidebar, chat-message, sql-block, chart-display,
  inspector, chat-input, markdown).
