# Task ID 42 — full-stack-developer — UI fixes + reapply rebranding

## Goal
Reapply the Tevet-7 rebranding (lost in a git reset) and fix the UI inconsistencies the user identified: page title still said "Producer Copilot", footer said "Phase 0 Prototype", inspector had two close buttons, sidebar had inconsistent styles, and the "Essayer la démo" button had to login via the real backend (marie@tevet7.dev / tevet7demo) with a graceful fallback to demo mode.

## Project state observed
- Project at Phase 6c state on disk (admin console exists, but no auth flow yet — `auth-screen.tsx` and `view-toggle.tsx` didn't exist).
- Backend (FastAPI on port 8001) IS running and exposes `POST /api/auth/login`, `GET /api/auth/me`, `GET /api/tenants/mine`, `POST /api/tenants/{id}/activate`, `POST /api/chat`. The demo seed user `marie@tevet7.dev` / `tevet7demo` is a producer #42 on the "dp" (Drive Producteur) tenant.
- Existing Next.js admin proxy at `src/app/api/admin/[[...path]]/route.ts` — pattern reused for the new auth/tenants/chat proxies.
- Read previous agents' work records in `/agent-ctx/` (Tasks 2, 4, 40) to understand the design system (Tevet-7 dark green palette, Caudex/Manrope, Feather icons only, no lucide-react in producer-copilot/).

## Files created
1. `src/app/api/auth/[[...path]]/route.ts` — Next.js proxy for `/api/auth/*` → `localhost:8001/api/auth/*`. Forwards method, path, query, Authorization header, JSON body. Returns 502 on backend unreachable.
2. `src/app/api/tenants/[[...path]]/route.ts` — same pattern for `/api/tenants/*`.
3. `src/app/api/chat/route.ts` — Next.js proxy for `POST /api/chat` → `localhost:8001/api/chat`. Forwards the JWT so the backend can read identity from the token.
4. `src/lib/auth-api.ts` — auth + tenant client. Exports `login`, `getMe`, `listMyTenants`, `activateTenant`, `getAuthToken`/`setAuthToken` (localStorage key `tevet7.jwt` shared with `admin-api.ts`), `getActiveTenantId`/`setActiveTenantId`, `DEMO_EMAIL`/`DEMO_PASSWORD` constants, and an `AuthApiError` class with an `unreachable` flag (true when the failure was a network/502).
5. `src/components/producer-copilot/auth-screen.tsx` — Tevet-7-styled login screen. H1 "Tevet-7", subtitle "Plateforme d'agents IA configurable. Connectez-vous pour accéder à votre agent — chaque question est sécurisée par un scope tenant.", email + password form, "Se connecter" button, "Essayer la démo" button (calls `tryDemoLogin()`), "Continuer sans backend (mock data)" link (calls `enterDemoMode()`), inline error banner, sticky footer.
6. `src/components/producer-copilot/view-toggle.tsx` — `ViewToggle` component: two-segment tablist "Agent" ↔ "Ops Console" reflecting + driving `adminView` in the store. "Ops Console" disabled for non-admins (with tooltip). Hidden on mobile (the user dropdown carries admin entries instead). Feather icons `Terminal` + `Sliders`.

## Files modified
1. `src/app/layout.tsx` — metadata title `Tevet-7 — Configurable AI Agent Platform`, description mentions "plateforme d'agents IA configurable" + "Premier tenant : Drive Producteur".
2. `src/components/producer-copilot/brand-mark.tsx` — `BrandMark` now uses a `useEffect` + `useState` "mounted" guard: returns a same-sized empty `<span>` before mount, the actual SVG after mount. Prevents any SSR/client mismatch on the inline `var(--accent, #A8C090)` CSS variable resolution.
3. `src/components/ui/feather-icons.tsx` — header comment "Producer Copilot UI" → "Tevet-7 UI". Added 3 new icons: `LogOut`, `Mail`, `Terminal`.
4. `src/lib/types.ts` — header comment "Tevet-7 Producer Copilot prototype" → "Tevet-7 agent platform". Added `TenantMembership` + `AuthUser` types for the auth flow.
5. `src/components/producer-copilot/chart-display.tsx` — `colorFor()` now also accepts raw hex strings (e.g. `"#A8C090"` returned by the live backend), not just palette keys. Previously a hex color would fall through to the default and break multi-series charts.
6. `src/lib/store.ts` — major extension:
   - New state: `authMode` ("loading" / "anonymous" / "authenticated" / "demo"), `user`, `tenants`, `activeTenant`, `authLoading`.
   - New actions: `bootstrap()` (validates stored JWT via `/api/auth/me` on mount), `login(email, password)`, `tryDemoLogin()` (calls `login(DEMO_EMAIL, DEMO_PASSWORD)` and falls back to `enterDemoMode()` + muted toast on unreachable), `enterDemoMode()`, `logout()`, `switchTenant(tenantId)`.
   - `sendMessage` / `sendExample` now branch on `authMode`: when `"authenticated"`, calls `POST /api/chat` with the JWT and adapts the snake_case envelope to the camelCase `AssistantResponse` (`scope_clause` → `scopeClause`, `tokens_in` → `tokensIn`, `tokens_out` → `tokensOut`, `latency_ms` → `latencyMs`, `tool_calls` → `toolCalls`, `steps[].duration_ms` → `steps[].durationMs`, `security_checks` → `securityChecks`). When `"demo"`, uses the existing mock-data layer unchanged.
   - `identity` is derived from `(user, activeTenant)` when authenticated via `identityFromAuthUser()` so the rest of the chat UI keeps working.
   - Network errors during chat are surfaced as a synthetic refused assistant message + a toast (so the chat thread never breaks).
7. `src/components/ui/sheet.tsx` — added `hideClose?: boolean` prop to `SheetContent`. When true, the auto-injected X close button at the top-right corner is suppressed. Used by the mobile inspector Sheet so we don't end up with two close buttons (Sheet's X + Inspector's "Fermer l'inspecteur" X).
8. `src/components/producer-copilot/header.tsx` — full rewrite of the brand area:
   - `BrandLogo` (Tevet-7 wordmark) = app identity.
   - Tenant badge = dynamic (`activeTenant?.name ?? "Drive Producteur"`), muted (small text, accent dot, bordered, NOT the app name).
   - Scope breadcrumb: "SCOPE / PRODUCER #42" or "SCOPE / Admin (full access)".
   - Phase badge: "Phase 0" → "Phase 6a".
   - Added `<ViewToggle />` (Agent ↔ Ops Console).
   - `UserDropdown` now shows the user's email + a "Se déconnecter" entry when authenticated (or in demo mode).
9. `src/components/producer-copilot/footer.tsx` — full rewrite:
   - Left: "Tevet-7 · Plateforme d'agents IA · Connecté en tant que {email}" (when authenticated), "· Mode démo" (when demo), "· Non connecté" (otherwise).
   - Center: "Tenant : {tenantName}" (dynamic).
   - Right: Shield icon + "Scoping actif".
   - Sticky `mt-auto` preserved.
10. `src/components/producer-copilot/sidebar.tsx` — full rewrite for visual consistency:
    - When authenticated: renders a new `TenantUserPanel` (shows the logged-in user + a tenant switcher if the user has multiple memberships). When in demo mode: renders the existing `IdentitySwitcher`.
    - Both example chips and history items now use the SAME border + bg + padding + hover style.
    - Section labels uniform: `<SectionLabel icon>` with uppercase tracking-wide caption muted.
    - `SectionSeparator` (thin `border-border`) between sections.
    - "HISTORIQUE" renamed "HISTORIQUE RÉCENT" with a subtle "Historique cosmétique — non persistant" note at the bottom.
11. `src/components/producer-copilot/identity-switcher.tsx` — removed the redundant static "Tenant · Drive Producteur" badge at the bottom of the dropdown (the header tenant badge already shows this).
12. `src/app/page.tsx` — full rewrite of `Home()`:
    - Calls `bootstrap()` on mount.
    - `authMode === "loading"` → minimal placeholder (BrandMark + "Tevet-7 · chargement").
    - `authMode === "anonymous"` → `<AuthScreen />`.
    - `adminView === "tenant"` / `"platform"` → `<AdminConsole />` + `<Footer />` (unchanged).
    - Otherwise → `<CopilotHome />`.
    - `WelcomeState` now says "Je suis votre agent Tevet-7" (not "Producer Copilot").
    - Chat dock caption "Prototype Phase 0 — réponses simulées" → "Prototype Phase 6a — réponses de l'agent Tevet-7".
    - Mobile inspector Sheet now passes `hideClose` so only the Inspector's own "Fermer l'inspecteur" close button shows (was the source of the "deux btns closes" bug).

## Verification (all confirmed)
- `bun run lint` → exit 0, 0 errors, 0 warnings.
- `rg -i "producer copilot" src/` → 0 content matches (folder name `producer-copilot/` doesn't count).
- `rg "Phase 0 Prototype" src/` → 0 matches.
- `rg "OpsPilot" src/` → 0 matches.
- Browser tab title = `Tevet-7 — Configurable AI Agent Platform` (verified via `agent-browser get title`).
- AuthScreen H1 = "Tevet-7", subtitle mentions "Plateforme d'agents IA configurable" + "sécurisée par un scope tenant".
- "Essayer la démo" button → calls real `POST /api/auth/login` (marie@tevet7.dev / tevet7demo), stores JWT in localStorage, loads `/api/auth/me` + `/api/tenants/mine`, switches to chat with REAL backend data. Verified: the first example question returns "180 unités" (real backend) instead of "142 unités" (mock). Real SQL `WHERE oi.producer_id = 42` shown in the SQL block.
- Footer (authenticated): "TEVET-7 · PLATEFORME D'AGENTS IA · CONNECTÉ EN TANT QUE MARIE@TEVET7.DEV" + "TENANT : DRIVE PRODUCTEUR" + "SCOPING ACTIF".
- Header tenant badge: dynamic "DRIVE PRODUCTEUR" (muted, bordered, with accent dot — not the app name).
- Phase badge: "PHASE 6A" (was "Phase 0").
- ViewToggle: "Agent" (selected) / "Ops Console" (disabled for producer Marie, enabled for admin).
- Inspector has only ONE close button ("Fermer l'inspecteur") on both desktop and mobile. The mobile Sheet's auto-X is hidden via `hideClose`.
- Sidebar sections visually consistent: same border + bg + padding + hover, uniform section labels, thin separators.
- Mobile (375px): sidebar + inspector in Sheets (no horizontal scroll — `document.documentElement.scrollWidth - clientWidth === 0`). "Ouvrir le menu" opens sidebar Sheet, "Ouvrir l'inspecteur" opens inspector Sheet.
- No hydration errors in the browser console (only the pre-existing Radix `DialogContent` description accessibility warning, unrelated to this task).
- No "Received NaN" errors after fixing `adaptBackendResponse` to convert `duration_ms` → `durationMs` on each step (was leaking `undefined` into the inspector's `totalMs` reduce).
- Backend reachability confirmed: `curl http://localhost:3000/api/auth/login` → 200 with JWT; `/api/auth/me` → 200 with user + memberships; `/api/tenants/mine` → 200 with 1 tenant; `/api/chat` → 200 with real envelope (180 unités, real SQL, real chart).
- Inspector shows real backend stats: TOKENS ENTRÉE 850 / SORTIE 412 / TOTAL 1262 / LATENCE 0,00 s / COÛT 0,0227 € / DURÉE 3 ms.

## Behaviour summary
- First visit (no JWT): `bootstrap()` sets `authMode = "anonymous"` → AuthScreen renders.
- Click "Essayer la démo": tries real backend login → success (backend is up) → JWT stored → `/api/auth/me` + `/api/tenants/mine` loaded → chat renders with Marie Dubois / producer #42 / Drive Producteur tenant. Toast: "Connecté en tant que marie@tevet7.dev".
- Click "Essayer la démo" with backend down: `tryDemoLogin()` catches the `AuthApiError` (unreachable flag) → falls back to `enterDemoMode()` → toast "Mode démo (backend hors ligne)" with the error detail.
- Click an example question (authenticated): `POST /api/chat` with JWT → real backend response (180 unités, real SQL, real chart) → chat message + inspector trace show real numbers.
- Click an example question (demo mode): existing mock-data path → 142 unités (mock).
- User dropdown → "Se déconnecter" → clears JWT + tenantId, back to AuthScreen.
- Header ViewToggle "Ops Console": disabled for Marie (producer). Would be enabled for an admin identity.
- Sidebar (authenticated): TenantUserPanel with Marie's info + "Drive Producteur" tenant (no switcher since she has only 1 membership). Sidebar (demo): IdentitySwitcher with 3 mock identities (Marie / Pierre / DP Admin).
- Mobile: header collapses, ViewToggle hidden, sidebar + inspector behind "Ouvrir le menu" / "Ouvrir l'inspecteur" buttons (Sheets).

## Design system compliance
- Tevet-7 dark green palette everywhere (#2D3A2F / #E8E0C9 / #5A6B4A / #A8C090 / #605E58 / #A4A096) — no Tailwind default color scales, no indigo/blue.
- Caudex for headings + all numbers; Manrope for body / labels / captions.
- Feather icons only (now 40 total) — zero lucide-react in producer-copilot/. shadcn/ui internals (Sheet, DropdownMenu) keep their own lucide-react (untouched).
- All API requests via relative paths (`/api/auth/...`, `/api/tenants/...`, `/api/chat`) — Next.js proxies perform the cross-origin hop to localhost:8001.
- Sticky footer preserved (`min-h-screen flex flex-col` + `mt-auto`).
- `agentic-service/` untouched. `worklog.md` untouched (will append Task 42 section).

## Limitations
- The `agentic-service/` backend must be running on port 8001 for the real demo login to work. If it's down, the "Essayer la démo" button falls back to mock demo mode (which uses the 142-unités mock data, not the real 180-unités data).
- The sidebar history is still cosmetic (seeded, not persistent). Marked "Historique cosmétique — non persistant" so it's honest.
- The ViewToggle's "Ops Console" is disabled for producers. To test the admin console via the ViewToggle, log in as the demo admin (`admin@tevet7.dev` / `tevet7demo` — not wired to a button, but the email/password form accepts it).
