import { create } from "zustand";
import { toast } from "sonner";

import {
  DEFAULT_IDENTITY_ID,
  IDENTITIES,
  getResponseForExample,
  getResponseForMessage,
} from "./mock-data";
import {
  DEMO_EMAIL,
  DEMO_PASSWORD,
  AuthApiError,
  activateTenant,
  createTenant as authCreateTenant,
  getAuthToken,
  getMe,
  listMyTenants,
  login as authLogin,
  signup as authSignup,
  setAuthToken,
  setActiveTenantId,
  getActiveTenantId,
} from "./auth-api";
import {
  DEFAULT_TENANT_ID,
  AdminApiError,
  getPlatformStats,
  getTenantConfig,
  getTenantConversations,
  getTenantStats,
  getTenantUsers,
  listAllTenants,
  resetDemoTenant,
} from "./admin-api";
import type {
  AssistantResponse,
  AuthUser,
  ChatMessage,
  Conversation,
  Identity,
  PlatformStats,
  PlatformTenant,
  TenantConfig,
  TenantMembership,
  TenantStats,
  TenantUser,
  TraceStep,
} from "./types";

let idCounter = 0;
function makeId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${Date.now().toString(36)}-${idCounter}`;
}

export type AdminView = "none" | "tenant" | "platform";

/** Auth mode — controls which surface is rendered (AuthScreen vs chat). */
export type AuthMode = "loading" | "anonymous" | "authenticated" | "demo";

interface AdminData {
  /** The tenant currently displayed in the tenant admin view. */
  tenantId: string;
  users: TenantUser[];
  config: TenantConfig | null;
  conversations: Conversation[];
  stats: TenantStats | null;
  tenants: PlatformTenant[];
  platformStats: PlatformStats | null;
  /** Set when an admin API call fails — surfaces in the admin UI banner. */
  error: string | null;
}

const emptyAdminData: AdminData = {
  tenantId: DEFAULT_TENANT_ID,
  users: [],
  config: null,
  conversations: [],
  stats: null,
  tenants: [],
  platformStats: null,
  error: null,
};

interface CopilotState {
  // --- Auth ---
  authMode: AuthMode;
  user: AuthUser | null;
  tenants: TenantMembership[];
  activeTenant: TenantMembership | null;
  authLoading: boolean;
  /** True when the session is a public demo. Shows the
   * "DÉMO PUBLIQUE" badge + blocks destructive actions. */
  isDemoSession: boolean;

  // --- Chat identity + messages ---
  identityId: string;
  identity: Identity;
  /** Demo identity override (Marie/Pierre/Admin) — when set, chat calls send
   * body identity instead of JWT so the user can switch without re-login. */
  demoIdentityOverride: Identity | null;
  messages: ChatMessage[];
  /** Id of the assistant message currently being inspected in the right panel. */
  selectedMessageId: string | null;
  /** True while the assistant is "thinking" (typing indicator). */
  isStreaming: boolean;
  /** Whether the inspector panel is open on desktop. */
  inspectorOpen: boolean;

  // --- Admin console ---
  adminView: AdminView;
  adminLoading: boolean;
  adminData: AdminData;

  // --- Identity / chat actions ---
  setIdentity: (identityId: string) => void;
  setDemoIdentityOverride: (identityId: string | null) => void;
  sendExample: (questionId: string, label: string) => void;
  sendMessage: (text: string) => void;
  selectMessage: (messageId: string | null) => void;
  toggleInspector: () => void;
  setInspectorOpen: (open: boolean) => void;
  resetConversation: () => void;

  // --- Auth actions ---
  bootstrap: () => Promise<void>;
  login: (
    email: string,
    password: string,
  ) => Promise<{ ok: true } | { ok: false; error: string }>;
  signup: (
    email: string,
    password: string,
    name: string,
  ) => Promise<{ ok: true } | { ok: false; error: string }>;
  tryDemoLogin: () => Promise<void>;
  enterDemoMode: () => void;
  logout: () => void;
  switchTenant: (tenantId: string) => Promise<void>;
  createTenant: (name: string, slug: string) => Promise<{ ok: true } | { ok: false; error: string }>;

  // --- Admin actions ---
  setAdminView: (view: AdminView) => void;
  loadTenantAdmin: (tenantId?: string) => Promise<void>;
  loadPlatformAdmin: () => Promise<void>;
  resetDemo: () => Promise<void>;
}

function identityById(id: string): Identity {
  return IDENTITIES.find((i) => i.id === id) ?? IDENTITIES[0];
}

/**
 * Heuristic — the platform owner is the DP Admin identity. The real backend
 * `/api/auth/me` response carries `is_platform_owner: true` for that account,
 * but the local mock identities do not have a backend yet so we use the
 * identity `kind` as the source of truth.
 */
export function isPlatformOwner(identity: Identity): boolean {
  return identity.kind === "admin";
}

/** Tenant admins — also the DP Admin identity in the demo mock model. */
export function isTenantAdmin(identity: Identity): boolean {
  return identity.kind === "admin";
}

function describeAdminError(err: unknown): string {
  if (err instanceof AdminApiError) {
    if (err.status === 401 || err.status === 403) {
      return "Accès refusé — permissions insuffisantes pour la console admin.";
    }
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return "Erreur inconnue";
}

/** Returns "MD" for "Marie Dubois" etc. — used to derive initials from a real user name. */
function initialsFromName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/**
 * Derives a chat-side `Identity` from the authenticated user + their active
 * tenant membership. Used so the existing chat UI (which reads `identity.kind`
 * and `identity.producerId`) keeps working when the user is logged in via the
 * real backend.
 */
function identityFromAuthUser(
  user: AuthUser,
  tenant: TenantMembership | null,
): Identity {
  const isAdmin = tenant?.role === "admin";
  const producerId = tenant?.producer_id ?? null;
  return {
    id: `user-${user.id}`,
    kind: isAdmin ? "admin" : "producer",
    name: user.name,
    producerNumber: producerId != null ? `#${producerId}` : null,
    producerId,
    farmName: null,
    role: isAdmin ? "Équipe Ops" : "Producteur",
    initials: initialsFromName(user.name),
    accent: "accent",
  };
}

/**
 * Adapts the backend `/api/chat` envelope (snake_case) to the frontend's
 * `AssistantResponse` (camelCase). Unknown / missing fields fall back to safe
 * defaults so the inspector never crashes.
 *
 * Field conversions:
 *   - `scope_clause`  → `scopeClause`
 *   - `tokens_in`     → `tokensIn`
 *   - `tokens_out`    → `tokensOut`
 *   - `latency_ms`    → `latencyMs`
 *   - `tool_calls`    → `toolCalls`
 *   - `security_checks` → `securityChecks` (fields are already camelCase)
 *   - `steps[].duration_ms` → `steps[].durationMs`
 */
function adaptBackendResponse(raw: unknown): AssistantResponse {
  const r =
    (typeof raw === "object" && raw !== null ? raw : {}) as Record<
      string,
      unknown
    >;
  const rawSteps = Array.isArray(r.steps) ? (r.steps as Record<string, unknown>[]) : [];
  const steps: TraceStep[] = rawSteps.map((s) => ({
    index: typeof s.index === "number" ? s.index : 0,
    title: typeof s.title === "string" ? s.title : "",
    detail: typeof s.detail === "string" ? s.detail : "",
    status: (s.status === "ok" || s.status === "warning" || s.status === "blocked"
      ? s.status
      : "ok") as TraceStep["status"],
    durationMs: typeof s.duration_ms === "number" ? s.duration_ms : 0,
  }));
  const rawChecks = Array.isArray(r.security_checks)
    ? (r.security_checks as Record<string, unknown>[])
    : [];
  const securityChecks: AssistantResponse["securityChecks"] = rawChecks.map((c) => ({
    label: typeof c.label === "string" ? c.label : "",
    status: (c.status === "ok" || c.status === "warning" || c.status === "blocked"
      ? c.status
      : "ok") as AssistantResponse["securityChecks"][number]["status"],
    detail: typeof c.detail === "string" ? c.detail : undefined,
  }));
  const toolCalls = Array.isArray(r.tool_calls)
    ? (r.tool_calls as string[])
    : [];
  return {
    answer: typeof r.answer === "string" ? r.answer : "Réponse vide.",
    sql: typeof r.sql === "string" ? r.sql : null,
    scopeClause:
      typeof r.scope_clause === "string" ? r.scope_clause : null,
    chart:
      (r.chart as AssistantResponse["chart"] | null | undefined) ?? undefined,
    tokensIn: typeof r.tokens_in === "number" ? r.tokens_in : 0,
    tokensOut: typeof r.tokens_out === "number" ? r.tokens_out : 0,
    latencyMs: typeof r.latency_ms === "number" ? r.latency_ms : 0,
    toolCalls,
    steps,
    securityChecks,
    refused: Boolean(r.refused),
  };
}

/** Calls `POST /api/chat` with the message + JWT, returns an `AssistantResponse`.
 *
 * Demo override: when `demoIdentityOverride` is set (Marie/Pierre/Admin switcher
 * on the demo tenant), sends body identity instead of JWT so the user can switch
 * without re-login. The backend's dual-mode fallback handles the scoping.
 */
async function callBackendChat(message: string): Promise<AssistantResponse> {
  const token = getAuthToken();
  const override = useCopilotStore.getState().demoIdentityOverride;
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };
  // When a demo identity override is active, send body identity (no JWT) so
  // the backend uses the override's producer_id/role instead of the JWT's.
  const useJwt = token && !override;
  if (useJwt) headers["authorization"] = `Bearer ${token}`;

  const body: Record<string, unknown> = { message };
  if (override) {
    body.identity_id = override.id;
    body.producer_id = override.producerId;
    body.role = override.kind;
  }

  const res = await fetch("/api/chat", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const text = await res.text();
  let parsed: unknown = null;
  if (text.length > 0) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }
  if (!res.ok) {
    const message =
      typeof parsed === "object" && parsed && "detail" in parsed
        ? String((parsed as { detail: unknown }).detail)
        : typeof parsed === "object" && parsed && "message" in parsed
          ? String((parsed as { message: unknown }).message)
          : `Chat backend ${res.status} ${res.statusText}`;
    throw new Error(message);
  }
  return adaptBackendResponse(parsed);
}

export const useCopilotStore = create<CopilotState>((set, get) => ({
  authMode: "loading",
  user: null,
  tenants: [],
  activeTenant: null,
  authLoading: false,
  isDemoSession: false,

  identityId: DEFAULT_IDENTITY_ID,
  identity: identityById(DEFAULT_IDENTITY_ID),
  demoIdentityOverride: null,
  messages: [],
  selectedMessageId: null,
  isStreaming: false,
  inspectorOpen: false,

  adminView: "none",
  adminLoading: false,
  adminData: emptyAdminData,

  // -------------------------------------------------------------------------
  // Auth actions
  // -------------------------------------------------------------------------

  /**
   * Called on app start. If we have a stored JWT, validate it via `/api/auth/me`
   * and load the user's tenants. If the JWT is invalid or absent, switch to
   * `anonymous` so the AuthScreen renders. Network failures fall back to
   * `anonymous` (the user can still click "Essayer la démo").
   */
  bootstrap: async () => {
    const token = getAuthToken();
    if (!token) {
      set({ authMode: "anonymous" });
      return;
    }
    try {
      const me = await getMe();
      const tenants = me.memberships ?? [];
      const activeTenant = pickActiveTenant(tenants);
      set({
        authMode: "authenticated",
        isDemoSession: false,
        user: me.user,
        tenants,
        activeTenant,
        identity: identityFromAuthUser(me.user, activeTenant),
      });
    } catch (err) {
      // Stale or invalid JWT — clear it and show the auth screen.
      setAuthToken(null);
      setActiveTenantId(null);
      set({ authMode: "anonymous", user: null, tenants: [], activeTenant: null });
      if (err instanceof AuthApiError && !err.unreachable) {
        // 401 / 403 etc. — silently clear. Other errors (502) are also silent
        // so the user just sees the auth screen.
      }
    }
  },

  /**
   * Real backend login. Stores the JWT, loads `/api/auth/me` + `/api/tenants/mine`,
   * activates the first tenant if none is active, then switches to `authenticated`.
   *
   * Returns `{ ok: false, error }` on failure so the AuthScreen can show an
   * inline error message. Network failures (backend unreachable) are surfaced
   * as `error` so the caller can decide whether to fall back to demo mode.
   */
  login: async (email, password) => {
    set({ authLoading: true });
    try {
      const { user, token } = await authLogin(email, password);
      setAuthToken(token);
      // Fetch memberships + tenants.
      const me = await getMe();
      const tenants = me.memberships ?? [];
      const activeTenant = pickActiveTenant(tenants);
      if (activeTenant) setActiveTenantId(activeTenant.tenant_id);
      set({
        authMode: "authenticated",
        isDemoSession: false,
        authLoading: false,
        user,
        tenants,
        activeTenant,
        identity: identityFromAuthUser(user, activeTenant),
        messages: [],
        selectedMessageId: null,
        isStreaming: false,
        inspectorOpen: false,
        adminView: "none",
      });
      return { ok: true as const };
    } catch (err) {
      set({ authLoading: false });
      const message =
        err instanceof AuthApiError
          ? err.unreachable
            ? "Backend Tevet-7 injoignable."
            : err.status === 401
              ? "Email ou mot de passe invalide."
              : err.message
          : err instanceof Error
            ? err.message
            : "Erreur inconnue";
      return { ok: false as const, error: message };
    }
  },

  signup: async (email, password, name) => {
    set({ authLoading: true });
    try {
      const { user, token } = await authSignup(email, password, name);
      setAuthToken(token);
      // New user has no memberships yet — they'll create a tenant next.
      set({
        authMode: "authenticated",
        isDemoSession: false,
        authLoading: false,
        user,
        tenants: [],
        activeTenant: null,
        identity: identityFromAuthUser(user, null),
        messages: [],
        selectedMessageId: null,
        isStreaming: false,
        inspectorOpen: false,
        adminView: "none",
      });
      return { ok: true as const };
    } catch (err) {
      set({ authLoading: false });
      const message =
        err instanceof AuthApiError
          ? err.unreachable
            ? "Backend Tevet-7 injoignable."
            : err.message
          : err instanceof Error
            ? err.message
            : "Erreur inconnue";
      return { ok: false as const, error: message };
    }
  },

  /**
   * Used by the "Essayer la démo" button. Tries the real backend login with
   * `marie@tevet7.dev` / `tevet7demo`; if the backend is unreachable, falls
   * back to `enterDemoMode()` with a muted toast.
   */
  tryDemoLogin: async () => {
    set({ authLoading: true });
    try {
      const result = await get().login(DEMO_EMAIL, DEMO_PASSWORD);
      if (result.ok) {
        set({ isDemoSession: true });
        toast.success("Connecté en tant que marie@tevet7.dev", {
          description: "Données réelles du tenant Drive Producteur.",
        });
        return;
      }
      // Login failed for a non-network reason (401, etc.) — surface the error
      // and fall back to demo mode so the user still sees the prototype.
      set({ authLoading: false, isDemoSession: true });
      get().enterDemoMode();
      toast("Mode démo (backend hors ligne)", {
        description: result.error,
      });
    } catch (err) {
      set({ authLoading: false });
      get().enterDemoMode();
      const reason =
        err instanceof AuthApiError && err.unreachable
          ? "Backend injoignable"
          : err instanceof Error
            ? err.message
            : "Erreur inconnue";
      toast("Mode démo (backend hors ligne)", {
        description: reason,
      });
    }
  },

  /**
   * Skips the backend entirely — runs the prototype against the mock data
   * layer. Used when the user explicitly chooses the demo path or when the
   * backend is unreachable.
   */
  enterDemoMode: () => {
    setAuthToken(null);
    setActiveTenantId(null);
    set({
      authMode: "demo",
      authLoading: false,
      user: null,
      tenants: [],
      activeTenant: null,
      identityId: DEFAULT_IDENTITY_ID,
      identity: identityById(DEFAULT_IDENTITY_ID),
      messages: [],
      selectedMessageId: null,
      isStreaming: false,
      inspectorOpen: false,
      adminView: "none",
    });
  },

  logout: () => {
    setAuthToken(null);
    setActiveTenantId(null);
    set({
      authMode: "anonymous",
      authLoading: false,
      isDemoSession: false,
      user: null,
      tenants: [],
      activeTenant: null,
      identityId: DEFAULT_IDENTITY_ID,
      identity: identityById(DEFAULT_IDENTITY_ID),
      messages: [],
      selectedMessageId: null,
      isStreaming: false,
      inspectorOpen: false,
      adminView: "none",
    });
  },

  /**
   * Switches the active tenant. Calls `POST /api/tenants/{id}/activate` to get
   * a fresh JWT scoped to the new tenant, then re-derives the chat identity.
   */
  switchTenant: async (tenantId) => {
    const token = getAuthToken();
    if (!token) return;
    try {
      const { membership, token: newToken } = await activateTenant(tenantId);
      setAuthToken(newToken);
      setActiveTenantId(membership.tenant_id);
      const tenants = get().tenants.map((t) =>
        t.tenant_id === membership.tenant_id
          ? { ...t, is_active: true }
          : { ...t, is_active: false },
      );
      const activeTenant = tenants.find((t) => t.tenant_id === membership.tenant_id) ?? null;
      const user = get().user;
      set({
        tenants,
        activeTenant,
        identity: user ? identityFromAuthUser(user, activeTenant) : get().identity,
        messages: [],
        selectedMessageId: null,
        isStreaming: false,
        inspectorOpen: false,
        adminView: "none",
      });
      toast.success(`Tenant activé : ${activeTenant?.name ?? tenantId}`);
    } catch (err) {
      const message =
        err instanceof AuthApiError
          ? err.unreachable
            ? "Backend injoignable"
            : err.message
          : err instanceof Error
            ? err.message
            : "Erreur inconnue";
      toast.error("Impossible de changer de tenant", { description: message });
    }
  },

  createTenant: async (name, slug) => {
    try {
      const { tenant, token: newToken } = await authCreateTenant(name, slug);
      setAuthToken(newToken);
      setActiveTenantId(tenant.tenant_id);
      const tenants = [...get().tenants, { ...tenant, is_active: true }];
      const activeTenant = tenants.find((t) => t.tenant_id === tenant.tenant_id) ?? null;
      const user = get().user;
      set({
        tenants,
        activeTenant,
        identity: user ? identityFromAuthUser(user, activeTenant) : get().identity,
        messages: [],
        selectedMessageId: null,
        isStreaming: false,
        inspectorOpen: false,
        adminView: "none",
      });
      toast.success(`Workspace créé : ${name}`);
      return { ok: true as const };
    } catch (err) {
      const message =
        err instanceof AuthApiError
          ? err.unreachable
            ? "Backend injoignable"
            : err.message
          : err instanceof Error
            ? err.message
            : "Erreur inconnue";
      return { ok: false as const, error: message };
    }
  },

  // -------------------------------------------------------------------------
  // Identity / chat actions
  // -------------------------------------------------------------------------

  setIdentity: (identityId) => {
    const identity = identityById(identityId);
    set({
      identityId,
      identity,
      messages: [],
      selectedMessageId: null,
      isStreaming: false,
      inspectorOpen: false,
      // Non-admins cannot stay in an admin view — bounce back to the agent.
      adminView: identity.kind === "admin" ? get().adminView : "none",
    });
    const scope = identity.producerNumber
      ? `Producer ${identity.producerNumber}`
      : "Admin (full access)";
    toast.success(`Scope modifié : interrogation en tant que ${scope}`, {
      description: identity.farmName ?? identity.role,
    });
  },

  setDemoIdentityOverride: (identityId) => {
    if (identityId === null) {
      set({ demoIdentityOverride: null });
      return;
    }
    const identity = identityById(identityId);
    set({
      demoIdentityOverride: identity,
      identity,
      identityId,
      messages: [],
      selectedMessageId: null,
      isStreaming: false,
      inspectorOpen: false,
      adminView: identity.kind === "admin" ? get().adminView : "none",
    });
    const scope = identity.producerNumber
      ? `Producer ${identity.producerNumber}`
      : "Admin (full access)";
    toast.success(`Identité démo : ${scope}`, {
      description: identity.farmName ?? identity.role,
    });
  },

  sendExample: (questionId, label) => {
    // Backend path — when authenticated, the example question is sent as a
    // plain message and the agent answers from the real DB.
    if (get().authMode === "authenticated") {
      void runBackendAssistant(get, set, label);
      return;
    }
    runAssistant(get, set, label, () =>
      getResponseForExample(get().identity, questionId),
    );
  },

  sendMessage: (text) => {
    const trimmed = text.trim();
    if (!trimmed || get().isStreaming) return;
    if (get().authMode === "authenticated") {
      void runBackendAssistant(get, set, trimmed);
      return;
    }
    runAssistant(get, set, trimmed, () =>
      getResponseForMessage(get().identity, trimmed),
    );
  },

  selectMessage: (messageId) => {
    set({ selectedMessageId: messageId, inspectorOpen: messageId !== null });
  },

  toggleInspector: () => set((s) => ({ inspectorOpen: !s.inspectorOpen })),
  setInspectorOpen: (open) => set({ inspectorOpen: open }),
  resetConversation: () =>
    set({ messages: [], selectedMessageId: null, isStreaming: false }),

  // -------------------------------------------------------------------------
  // Admin actions
  // -------------------------------------------------------------------------

  setAdminView: (view) => {
    if (view !== "none") {
      const identity = get().identity;
      if (identity.kind !== "admin") {
        toast.error("Console admin réservée aux administrateurs.");
        return;
      }
    }
    set({ adminView: view });
    if (view === "tenant") {
      void get().loadTenantAdmin();
    } else if (view === "platform") {
      void get().loadPlatformAdmin();
    }
  },

  loadTenantAdmin: async (tenantId) => {
    const tid = tenantId ?? get().adminData.tenantId ?? DEFAULT_TENANT_ID;
    set({
      adminLoading: true,
      adminData: { ...get().adminData, tenantId: tid, error: null },
    });
    try {
      const [users, config, conversations, stats] = await Promise.all([
        getTenantUsers(tid),
        getTenantConfig(tid).catch(() => null),
        getTenantConversations(tid),
        getTenantStats(tid).catch(() => null),
      ]);
      set({
        adminLoading: false,
        adminData: {
          ...get().adminData,
          tenantId: tid,
          users,
          config,
          conversations,
          stats,
          error: null,
        },
      });
    } catch (err) {
      set({
        adminLoading: false,
        adminData: { ...get().adminData, error: describeAdminError(err) },
      });
    }
  },

  loadPlatformAdmin: async () => {
    set({ adminLoading: true, adminData: { ...get().adminData, error: null } });
    try {
      const [tenants, platformStats] = await Promise.all([
        listAllTenants(),
        getPlatformStats().catch(() => null),
      ]);
      set({
        adminLoading: false,
        adminData: {
          ...get().adminData,
          tenants,
          platformStats,
          error: null,
        },
      });
    } catch (err) {
      set({
        adminLoading: false,
        adminData: { ...get().adminData, error: describeAdminError(err) },
      });
    }
  },

  resetDemo: async () => {
    set({ adminLoading: true });
    try {
      const result = await resetDemoTenant();
      toast.success("Démo réinitialisée", {
        description: `${result.orders_reseeded} commandes · ${result.docs_reseeded} documents reseedés.`,
      });
      await get().loadPlatformAdmin();
    } catch (err) {
      set({ adminLoading: false });
      toast.error("Réinitialisation impossible", {
        description: describeAdminError(err),
      });
    }
  },
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Picks the tenant to activate after login: the cached `activeTenantId` if the
 * user is still a member, else the first `is_active` membership, else the
 * first membership. Returns null if the user has no memberships.
 */
function pickActiveTenant(tenants: TenantMembership[]): TenantMembership | null {
  if (tenants.length === 0) return null;
  const cachedId = getActiveTenantId();
  if (cachedId) {
    const cached = tenants.find((t) => t.tenant_id === cachedId);
    if (cached) return cached;
  }
  const active = tenants.find((t) => t.is_active);
  if (active) return active;
  return tenants[0];
}

/**
 * Shared helper that pushes the user message, simulates the "thinking" delay,
 * then reveals the assistant response. Responses are computed up-front from
 * the mock layer so they stay deterministic per identity + question.
 */
function runAssistant(
  get: () => CopilotState,
  set: (partial: Partial<CopilotState>) => void,
  userText: string,
  computeResponse: () => AssistantResponse,
) {
  if (get().isStreaming) return;

  const userMessage: ChatMessage = {
    id: makeId("u"),
    role: "user",
    content: userText,
    createdAt: Date.now(),
  };

  set({
    messages: [...get().messages, userMessage],
    isStreaming: true,
    selectedMessageId: null,
  });

  // Simulate model latency before revealing the answer.
  const delay = 800 + Math.random() * 350;
  window.setTimeout(() => {
    const response = computeResponse();
    const assistantMessage: ChatMessage = {
      id: makeId("a"),
      role: "assistant",
      content: response.answer,
      response,
      createdAt: Date.now(),
      streaming: false,
    };
    // If the inspector is already open, live-update it with the new trace.
    // Otherwise leave it closed — the user can click the answer to inspect.
    const inspectorWasOpen = get().inspectorOpen;
    set({
      messages: [...get().messages, assistantMessage],
      isStreaming: false,
      selectedMessageId: inspectorWasOpen ? assistantMessage.id : null,
    });
  }, delay);
}

/**
 * Backend-backed assistant run. Pushes the user message immediately, shows the
 * typing indicator, calls `/api/chat` with the JWT, then pushes the assistant
 * message with the real envelope (SQL, chart, steps, security_checks).
 *
 * Network / HTTP errors are surfaced as a synthetic assistant message so the
 * chat thread doesn't break.
 */
async function runBackendAssistant(
  get: () => CopilotState,
  set: (partial: Partial<CopilotState>) => void,
  userText: string,
) {
  if (get().isStreaming) return;

  const userMessage: ChatMessage = {
    id: makeId("u"),
    role: "user",
    content: userText,
    createdAt: Date.now(),
  };

  set({
    messages: [...get().messages, userMessage],
    isStreaming: true,
    selectedMessageId: null,
  });

  try {
    const response = await callBackendChat(userText);
    const assistantMessage: ChatMessage = {
      id: makeId("a"),
      role: "assistant",
      content: response.answer,
      response,
      createdAt: Date.now(),
      streaming: false,
    };
    const inspectorWasOpen = get().inspectorOpen;
    set({
      messages: [...get().messages, assistantMessage],
      isStreaming: false,
      selectedMessageId: inspectorWasOpen ? assistantMessage.id : null,
    });
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "Erreur inconnue";
    const failureResponse: AssistantResponse = {
      answer:
        "⚠️ Le service agent n'a pas pu répondre.\n\n" +
        `Détail : ${message}\n\n` +
        "Réessayez dans un instant. Si le problème persiste, basculez en mode démo via le menu utilisateur.",
      sql: null,
      scopeClause: null,
      tokensIn: 0,
      tokensOut: 0,
      latencyMs: 0,
      toolCalls: [],
      steps: [],
      securityChecks: [],
      refused: true,
    };
    const assistantMessage: ChatMessage = {
      id: makeId("a"),
      role: "assistant",
      content: failureResponse.answer,
      response: failureResponse,
      createdAt: Date.now(),
      streaming: false,
    };
    set({
      messages: [...get().messages, assistantMessage],
      isStreaming: false,
    });
    toast.error("Échec de l'agent", { description: message });
  }
}
