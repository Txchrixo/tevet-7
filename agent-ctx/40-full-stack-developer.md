# Task ID 40 — full-stack-developer — Phase 6c admin console frontend

## Goal
Build the Tevet-7 admin console frontend (2 surfaces: tenant admin + platform owner) with a Next.js catch-all proxy to the FastAPI admin backend at `http://localhost:8001/api/admin/*`. Backend assumed to be built in parallel.

## Project state observed
- Worklog contains Tasks 0–5 (Phase 0 prototype + Tevet-7 rebrand). No Phase 6a/6b tasks logged yet.
- On disk: project is at Phase 0 state. `src/lib/api.ts`, `src/components/producer-copilot/ops-console.tsx`, `src/components/producer-copilot/view-toggle.tsx`, and any auth/login flow referenced in the task spec do NOT exist yet.
- The 3 mock identities in `src/lib/mock-data.ts` (Marie #42, Pierre #99, DP Admin) carry the project; DP Admin (kind="admin") is treated as both tenant admin and platform owner.
- Decision: build the admin console so it works against the documented FastAPI contract and degrades gracefully (502 + ErrorBanner) when the backend is offline. Don't wait for the backend; don't introduce a fake auth system.

## Files created
1. `src/app/api/admin/[[...path]]/route.ts` — Next.js catch-all proxy. GET/POST/PUT/DELETE forward path segments + query string + Authorization header + JSON body to `http://localhost:8001/api/admin/*`. Returns structured JSON 502 (`{error, message, backend}`) on fetch failure.
2. `src/lib/admin-api.ts` — admin client. `getAuthToken`/`setAuthToken` (localStorage JWT), `AdminApiError`, 7 typed functions: `getTenantUsers`, `getTenantConfig`, `getTenantConversations(limit=50)`, `getTenantStats`, `listAllTenants`, `getPlatformStats`, `resetDemoTenant`. All use relative `/api/admin/...`. Exports `DEFAULT_TENANT_ID = "dp"`.
3. `src/components/producer-copilot/admin-console.tsx` (≈920 lines) — the main admin UI. `AdminConsole({mode})` switches between `TenantAdminView` and `PlatformOwnerView`. Tenant: 4 stat cards + refusal rate SmallStat, users list (max-h-96 scroll), config panel, conversations table (max-h-96 scroll, sticky header). Platform: 5 stat cards + avg latency SmallStat, tenants table (sticky header, clickable rows → tenant admin mode), "Reset démo" outline button with AlertDialog confirmation. Shared primitives: AdminHeader (with ArrowLeft "Retour à l'agent"), StatCard, PanelHeader, ConfigRow, RoleBadge, Th, Td, EmptyPanel, LoadingState, ErrorBanner.

## Files modified
1. `src/lib/types.ts` — appended Phase 6c types: TenantUser, TenantConfig, Conversation, TenantStats, PlatformTenant, PlatformStats, ResetResult. `schema_config`/`roles_config` typed as `unknown` (no `any`).
2. `src/lib/store.ts` — extended zustand store with `adminView`, `adminLoading`, `adminData`, plus actions `setAdminView`, `loadTenantAdmin(tenantId?)`, `loadPlatformAdmin()`, `resetDemo()`. `setIdentity` bounces non-admins out of admin views. Exported `isPlatformOwner`/`isTenantAdmin` helpers. `describeAdminError` translates AdminApiError 401/403 to "Accès refusé".
3. `src/app/page.tsx` — `Home()` branches on `adminView` ("tenant" → `<AdminConsole mode="tenant" />` + Footer; "platform" → `<AdminConsole mode="platform" />` + Footer; else → existing `CopilotHome`). All Phase 0 functionality preserved verbatim in the new `CopilotHome` function.
4. `src/components/producer-copilot/header.tsx` — replaced the dead Settings button with a new `UserDropdown` (radix DropdownMenu). Trigger: avatar + name + ChevronDown. For admins: "Console admin" (Settings icon → setAdminView("tenant")) + "Console platform" (Globe icon → setAdminView("platform")). For non-admins: muted note "Console admin réservée aux administrateurs du tenant." Brand/breadcrumb/inspector toggle untouched.
5. `src/app/globals.css` — added `.admin-scroll` (thin scrollbar, `var(--border)` thumb, transparent track, hover → `var(--muted-foreground)`) inside `@layer base`. Used by UsersPanel, ConversationsPanel, TenantsPanel.
6. `src/components/ui/feather-icons.tsx` — added 7 new Feather icons (Users, ArrowLeft, Home, Layers, Trash, Globe, Sliders). Same API as the existing 30. Zero lucide-react in producer-copilot/.

## Verification
- `bun run lint` → exit 0, 0 errors, 0 warnings. (Two `eslint-disable-next-line react-hooks/exhaustive-deps` warnings cleaned up — the empty-dep `useEffect(() => { void loadTenantAdmin(); }, [])` did not need the disable.)
- `curl http://localhost:3000/` → 200. Dev server compiles clean.
- `curl http://localhost:3000/api/admin/platform/stats` → 502 with `{"error":"admin_backend_unreachable","message":"fetch failed","backend":"http://localhost:8001/api/admin/platform/stats"}` — confirms the proxy works and the admin UI will fall back to the ErrorBanner state when the backend is offline.
- Verification greps: 0 matches for `lucide-react|indigo|blue-|slate|emerald|teal|amber|rose|sky-` in admin-console.tsx, header.tsx, store.ts, admin-api.ts. All Feather icons, all palette tokens.

## Behaviour summary
- Login as DP Admin → user dropdown shows "Console admin" + "Console platform".
- Click "Console admin" → AdminConsole mode=tenant loads with stats + users + config + conversations for the "dp" tenant (or ErrorBanner if backend down).
- Click "Console platform" → AdminConsole mode=platform loads with global stats + tenants list.
- Click a tenant row → switches to tenant admin mode for that tenant (loads fresh data).
- Click "Reset démo" → AlertDialog confirmation → resetDemo → toast "Démo réinitialisée" → reloads platform data.
- "Retour à l'agent" (ArrowLeft button in AdminHeader) → setAdminView("none") → back to chat.
- Marie/Pierre → no admin entries in their dropdown (muted note instead); setAdminView also rejects them with a toast; switching identity away from admin bounces the user back to the chat.
- Existing Phase 0 chat / inspector / sidebar / identity switcher / welcome state / sticky footer all preserved unchanged.

## Design system compliance
- Tevet-7 dark green palette (#2D3A2F / #E8E0C9 / #5A6B4A / #A8C090 / #605E58 / #A4A096) — no Tailwind default color scales anywhere.
- Caudex for all headings + all numbers (stat cards, table cells, ledger #ids, latency, tokens, cost). Manrope for body / labels / captions.
- Feather icons only (37 total now) — zero lucide-react in producer-copilot/.
- Stat cards: border (no shadow). Tables: border-border rows, sticky headers. Scrollable lists: max-h-96 + custom `.admin-scroll` scrollbar.
- Sticky footer preserved (`min-h-screen flex flex-col` + `mt-auto`).
- All API requests via relative path (`/api/admin/...`); the Next.js catch-all proxy performs the cross-origin hop to `localhost:8001` and forwards the JWT.

## Limitations
- Backend not running yet (Phase 6a/6b work logged in parallel) — admin UI shows the ErrorBanner gracefully. Once the FastAPI admin service is up on port 8001 with the documented contract, the UI will populate live.
- No real auth/login flow yet — the JWT is read from `localStorage` (key `tevet7.jwt`); the existing mock identity switcher remains the way to flip between producer/admin personas. When a real login flow is added, it just needs to call `setAuthToken(jwt)` and the admin client will pick it up automatically.
