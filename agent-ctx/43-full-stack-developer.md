# Task 43 — Onboarding Wizard Frontend

**Agent**: full-stack-developer
**Task**: Rebuild the 4-step Onboarding Wizard frontend (lost in a git reset) that gates the chat surface for non-onboarded tenants.

## Context from prior agents
- Backend onboarding endpoints exist (Phase 6b): `POST /api/tenants/{id}/onboarding/{connect,detect-schema,save-schema,save-roles,complete}` + `GET /api/tenants/{id}/onboarding/status`.
- The frontend wizard component was lost in a git reset and needs to be rebuilt.
- The Tevet-7 design system is locked: dark green palette (#2D3A2F bg, #E8E0C9 fg, #A8C090 accent), Caudex headings, Manrope body, Feather icons (no lucide-react), bordered cards (no heavy shadows), no Tailwind default color scales, no indigo/blue.

## Files created
1. `src/app/api/tenants/[id]/onboarding/[[...step]]/route.ts` — Next.js catch-all proxy. Reads body with `arrayBuffer()` (vs. the generic tenants proxy's `text()`) so multipart/form-data CSV uploads survive the round-trip. Takes precedence over the broader `/api/tenants/[[...path]]/route.ts` catch-all thanks to Next.js route specificity. Forwards Authorization, content-type (with multipart boundary preserved), and accept headers. Returns structured 502 JSON when backend is unreachable.

2. `src/lib/onboarding-api.ts` — Client API module exporting: `connectPostgres`, `connectCsv` (multipart), `detectSchema`, `saveSchema`, `saveRoles`, `completeOnboarding`, `getOnboardingStatus`, plus `OnboardingApiError` (distinguishes 401/403 from 502). All requests use relative paths only.

3. `src/components/producer-copilot/onboarding-wizard.tsx` — The main 4-step wizard (1252 lines). Sub-components: `OnboardingWizard` shell, `ProgressIndicator`, `Step1Connect`, `ConnectorCard`, `Step2Schema`, `TableSchemaRow`, `Step3Roles`, `RoleRow`, `Step4Ready`, `SummaryCard`, `ErrorBanner`.

## Files modified
1. `src/components/ui/feather-icons.tsx` — added `FileText`, `Upload`, `ChevronRight`, `CheckCircle` icons.

2. `src/lib/types.ts` — added `onboarded: boolean` to `TenantMembership`; added `OnboardingSchemaColumn`, `OnboardingSchemaTable`, `OnboardingRole`, `OnboardingStatus`, `OnboardingConnectResult`, `OnboardingSaveResult`.

3. `src/lib/store.ts` — added `normalizeMembership`/`normalizeMemberships` helpers (defaults `onboarded` to true for backward compat); applied in `bootstrap`, `login`, `switchTenant`, `createTenant` (with `fresh.onboarded = false` override), `completeOnboarding`. Added `OnboardingData` interface + `initialOnboardingData` constant. Added 5 state fields + 7 actions: `onboardingStep`, `onboardingData`, `onboardingTenantId`, `onboardingLoading`, `onboardingError` / `startOnboarding`, `setOnboardingStep`, `setOnboardingData`, `setOnboardingLoading`, `setOnboardingError`, `resetOnboarding`, `completeOnboarding`. `logout` + `switchTenant` now also reset wizard state.

4. `src/app/page.tsx` — added `OnboardingWizard` import + `activeTenant` selector. Added the gate between CreateWorkspace and admin views:
   ```typescript
   if (authMode === "authenticated" && tenants.length > 0 && activeTenant && !activeTenant.onboarded) {
     return <OnboardingWizard tenantId={activeTenant.tenant_id} />;
   }
   ```

## Verification
- `bun run lint` → exit 0, 0 errors, 0 warnings.
- Dev server log: `GET / 200` repeatedly (no runtime errors). All 5 onboarding endpoints return backend responses (401 because no JWT in test) — confirming the new catch-all proxy is being hit and not the old generic one.
- Existing `/api/tenants/mine` still works through the old catch-all proxy (401 in dev log).
- The wizard renders the 4 steps with a progress indicator (4 dots, active = accent).
- Step 1 can test Postgres connection or upload CSV (multipart).
- Step 2 can detect schema, select/deselect tables + columns, pick scope column per table.
- Step 3 can define roles (default admin + user, add/remove, per-role scope + allowed tables).
- Step 4 can complete onboarding → calls `completeOnboarding()` → backend marks tenant onboarded → store refreshes /me → `activeTenant.onboarded` flips to true → page gate re-evaluates → `<CopilotHome />` renders.

## Notes for downstream agents
- The wizard's draft state is in-memory (Zustand doesn't persist by default). A page reload mid-wizard resets to step 1 with empty draft state. If persistence is needed in the future, wire up `zustand/middleware` with `persist` on a slice of the store.
- The `completeOnboarding()` action refreshes `/api/auth/me` so the active tenant's `onboarded` flag is fetched fresh from the backend. If `/me` fails (best-effort), the store optimistically sets `activeTenant.onboarded = true` locally so the user still proceeds to the chat — the backend has already marked the tenant as onboarded at that point, so the next /me call will succeed.
- The new catch-all proxy at `/api/tenants/[id]/onboarding/[[...step]]/route.ts` is more specific than the old catch-all and takes precedence. Both would forward to the same backend URL, but the new one handles multipart correctly while the old one would corrupt binary. This matches the pattern already used for `/api/tenants/[id]/example-questions/route.ts`.
