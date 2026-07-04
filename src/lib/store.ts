import { create } from "zustand";
import { toast } from "sonner";

import {
  callBackend,
  decideApproval,
  deleteDocument,
  getApprovalDetail,
  listApprovals,
  uploadDocument,
  type ApprovalDecision,
  type DocumentUploadInput,
} from "./api";
import {
  activateTenant,
  getMe,
  login as loginApi,
  signup as signupApi,
  AuthApiError,
} from "./auth-api";
import {
  DEFAULT_IDENTITY_ID,
  IDENTITIES,
  getMockResponse,
} from "./mock-data";
import type {
  ApprovalDetail,
  ApprovalSummary,
  AssistantResponse,
  ChatMessage,
  DocumentInfo,
  Identity,
  Tenant,
  User,
} from "./types";

let idCounter = 0;
function makeId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${Date.now().toString(36)}-${idCounter}`;
}

/** Minimum typing-indicator duration so the assistant reveal feels smooth. */
const MIN_TYPING_MS = 400;
/** Simulated latency window used only for the mock fallback path. */
const MOCK_LATENCY_MIN_MS = 800;
const MOCK_LATENCY_JITTER_MS = 350;
/** Sonner toast id used for the demo-mode notice — prevents stacking. */
const DEMO_TOAST_ID = "tevet7-demo-mode";

/** localStorage key under which the JWT is persisted across reloads. */
export const AUTH_TOKEN_STORAGE_KEY = "tevet7.auth.token";

/**
 * The two top-level surfaces the admin can switch between. Producers only ever
 * see "copilot" — the ViewToggle is admin-only and `setIdentity` forces the
 * view back to copilot whenever a producer is selected.
 */
export type CopilotView = "copilot" | "ops";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export type BackendStatus = "connected" | "demo" | "unknown";

// ---------------------------------------------------------------------------
// Auth helpers
// ---------------------------------------------------------------------------

/**
 * Decode the payload of a JWT **without verifying the signature**.
 *
 * The signature is verified server-side; here we only read the claims so the
 * UI can derive the active identity (role, producer_id, tenant_id) from the
 * token without an extra round-trip. Returns null on any parse error.
 */
function decodeJwt(token: string): {
  sub?: string | number;
  email?: string;
  tenant_id?: string;
  role?: string;
  producer_id?: number;
  exp?: number;
} | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    // base64url → base64 → JSON
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const json = atob(base64);
    return JSON.parse(json) as {
      sub?: string | number;
      email?: string;
      tenant_id?: string;
      role?: string;
      producer_id?: number;
      exp?: number;
    };
  } catch {
    return null;
  }
}

/** Read the persisted JWT from localStorage (browser-only, no-op on SSR). */
function readTokenFromStorage(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Persist or clear the JWT in localStorage. */
function writeTokenToStorage(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) {
      window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
    } else {
      window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    }
  } catch {
    // localStorage can throw in private-mode Safari — fail silently.
  }
}

/** Build a chat-layer `Identity` from the auth state (JWT + user + tenant). */
function deriveIdentityFromAuth(state: CopilotState): Identity | null {
  if (!state.user || !state.token) return null;
  const claims = decodeJwt(state.token);
  const role = claims?.role ?? "producer";
  const producerId = claims?.producer_id ?? null;
  const tenantId = claims?.tenant_id ?? null;
  const tenant =
    state.tenants.find((t) => t.tenant_id === tenantId) ??
    state.activeTenant ??
    null;
  const isProducer = role === "producer" && producerId != null;

  const name = state.user.name || state.user.email;
  const initials =
    name
      .split(/[\s@.]+/)
      .filter(Boolean)
      .map((s) => s[0])
      .join("")
      .toUpperCase()
      .slice(0, 2) || "?";

  return {
    id: isProducer
      ? `producer-${producerId}`
      : role === "admin"
        ? `admin-${state.user.id}`
        : `user-${state.user.id}`,
    kind: isProducer ? "producer" : "admin",
    name,
    producerNumber: producerId != null ? `#${producerId}` : null,
    producerId,
    farmName: tenant?.name ?? null,
    role: isProducer ? "Producteur" : "Équipe Ops",
    initials,
    accent: "accent",
  };
}

// ---------------------------------------------------------------------------
// Store interface
// ---------------------------------------------------------------------------

interface CopilotState {
  // -- Auth (Phase 6a) ------------------------------------------------------
  /** The authenticated user. Null = NOT authenticated (demo mode). */
  user: User | null;
  /** The JWT. Null = NOT authenticated. Persisted in localStorage. */
  token: string | null;
  /** The user's tenant memberships (loaded via /api/auth/me). */
  tenants: Tenant[];
  /** The currently active tenant (matches the tenant_id claim in the JWT). */
  activeTenant: Tenant | null;
  /** True while login/signup/loadAuthFromStorage is in flight. */
  authLoading: boolean;
  /** Last auth error message — surfaced in the AuthScreen. */
  authError: string | null;
  /**
   * True when the "Essayer la démo" path failed because the backend was
   * unreachable, and we fell back to mock identities. The UI surfaces a
   * "Mode démo (backend hors ligne)" note when this is set.
   */
  demoFallback: boolean;

  // -- Identity (chat-layer) ------------------------------------------------
  /**
   * The active chat identity. When authenticated, this is DERIVED from the
   * JWT + active tenant. When NOT authenticated, this falls back to the
   * selected mock identity (marie/pierre/admin) via `identityId`.
   */
  identityId: string;
  identity: Identity;

  // -- Chat -----------------------------------------------------------------
  messages: ChatMessage[];
  /** Id of the assistant message currently being inspected in the right panel. */
  selectedMessageId: string | null;
  /** True while the assistant is "thinking" (typing indicator). */
  isStreaming: boolean;
  /** Whether the inspector panel is open on desktop. */
  inspectorOpen: boolean;
  /** Health of the FastAPI backend connection — drives the footer indicator. */
  backendStatus: BackendStatus;

  /** Indexed documents for the RAG corpus (CGV, FAQ, procédure, etc.). */
  documents: DocumentInfo[];
  /** True while `loadDocuments` is in flight (drives the skeleton). */
  documentsLoading: boolean;
  /** True while an upload or delete is in flight (disables the panel actions). */
  documentMutating: boolean;

  /** Active top-level surface — `ops` is admin-only (forced to `copilot` for producers). */
  view: CopilotView;
  /** Approval queue rows for the Ops Console (admin identity only). */
  approvals: ApprovalSummary[];
  /** True while `loadApprovals` is in flight. */
  approvalsLoading: boolean;
  /** Id of the approval currently selected in the Ops Console list. */
  selectedApprovalId: number | null;
  /** Full detail (approval + onboarding dossier) for the selected row. */
  selectedApprovalDetail: ApprovalDetail | null;
  /** True while a decision POST is in flight (disables the action buttons). */
  decisionInFlight: boolean;

  // -- Auth actions ---------------------------------------------------------
  /**
   * Log in with email + password. On success: persists the JWT to
   * localStorage, fetches the user's tenants, and re-derives the chat
   * identity from the JWT claims.
   *
   * Throws an `AuthApiError` on failure — the caller (AuthScreen) is
   * responsible for surfacing the error.
   */
  login: (email: string, password: string) => Promise<void>;
  /**
   * Sign up with email + password + name. Same flow as `login` after the
   * account is created (the backend returns a JWT immediately).
   */
  signup: (
    email: string,
    password: string,
    name: string,
  ) => Promise<void>;
  /** Clear auth state + localStorage. The chat identity reverts to mock. */
  logout: () => void;
  /**
   * Activate a different tenant. Calls /api/tenants/{id}/activate, gets a
   * new JWT, persists it, and re-derives the identity from the new claims.
   */
  setActiveTenant: (tenantId: string) => Promise<void>;
  /**
   * On app mount: read the JWT from localStorage, validate it via /api/auth/me,
   * and (if valid) populate the auth state. On failure: clear the token and
   * stay in demo mode.
   */
  loadAuthFromStorage: () => Promise<void>;
  /** Clear the last auth error (used when the AuthScreen closes/re-renders). */
  clearAuthError: () => void;
  /**
   * Skip authentication and use the mock identities (Marie / Pierre / Admin)
   * directly. Used by the AuthScreen's "Essayer la démo" button when the
   * backend is unreachable — falls back to the Phase 0 mock path so the
   * demo still works without forcing a signup.
   */
  enterDemoMode: () => void;

  // -- Identity / chat actions ----------------------------------------------
  setIdentity: (identityId: string) => void;
  sendExample: (questionId: string, label: string) => void;
  sendMessage: (text: string) => void;
  selectMessage: (messageId: string | null) => void;
  toggleInspector: () => void;
  setInspectorOpen: (open: boolean) => void;
  resetConversation: () => void;

  loadDocuments: () => Promise<void>;
  addDocument: (input: DocumentUploadInput) => Promise<void>;
  removeDocument: (id: number) => Promise<void>;

  setView: (view: CopilotView) => void;
  loadApprovals: () => Promise<void>;
  selectApproval: (id: number | null) => Promise<void>;
  decide: (
    id: number,
    decision: ApprovalDecision,
    reason: string,
  ) => Promise<void>;
}

function identityById(id: string): Identity {
  return IDENTITIES.find((i) => i.id === id) ?? IDENTITIES[0];
}

/**
 * Recompute the chat-layer `identity` from the current auth state.
 *
 * - Authenticated → derive from JWT claims + active tenant.
 * - NOT authenticated → fall back to the mock identity selected via
 *   `identityId` (Marie / Pierre / Admin).
 *
 * Returns the partial state to merge (or an empty object if the identity is
 * unchanged — we let zustand dedupe).
 */
function recomputeIdentity(state: CopilotState): Partial<CopilotState> {
  const derived = deriveIdentityFromAuth(state);
  const identity = derived ?? identityById(state.identityId);
  // If the identity id changes (e.g. on login), reset the chat session so
  // messages from the previous identity don't leak across contexts.
  const previous = state.identity;
  const shouldResetChat =
    derived !== null &&
    previous !== null &&
    (derived.id !== previous.id || derived.kind !== previous.kind);
  if (shouldResetChat) {
    return {
      identity,
      messages: [],
      selectedMessageId: null,
      isStreaming: false,
      inspectorOpen: false,
      backendStatus: "unknown",
      documents: [],
      documentsLoading: true,
      approvals: [],
      selectedApprovalId: null,
      selectedApprovalDetail: null,
      view: "copilot",
    };
  }
  return { identity };
}

export const useCopilotStore = create<CopilotState>((set, get) => ({
  // -- Auth -----------------------------------------------------------------
  user: null,
  token: null,
  tenants: [],
  activeTenant: null,
  authLoading: false,
  authError: null,
  demoFallback: false,

  // -- Identity / chat ------------------------------------------------------
  identityId: DEFAULT_IDENTITY_ID,
  identity: identityById(DEFAULT_IDENTITY_ID),
  messages: [],
  selectedMessageId: null,
  isStreaming: false,
  inspectorOpen: false,
  backendStatus: "unknown",
  documents: [],
  documentsLoading: false,
  documentMutating: false,

  view: "copilot",
  approvals: [],
  approvalsLoading: false,
  selectedApprovalId: null,
  selectedApprovalDetail: null,
  decisionInFlight: false,

  // -----------------------------------------------------------------------
  // Auth actions
  // -----------------------------------------------------------------------

  login: async (email, password) => {
    if (get().authLoading) return;
    set({ authLoading: true, authError: null, demoFallback: false });
    try {
      const { user, token } = await loginApi(email, password);
      writeTokenToStorage(token);
      // Set the token + user immediately so deriveIdentityFromAuth can run.
      set({ user, token });
      // Fetch the user's tenant memberships (best-effort — a freshly created
      // user may legitimately have zero tenants).
      let tenants: Tenant[] = [];
      try {
        const me = await getMe(token);
        tenants = me.memberships;
        // Use the user record from /me if it's more authoritative.
        set({ user: me.user, tenants });
      } catch (err) {
        console.warn(
          "getMe failed after login — proceeding without tenant list",
          err instanceof Error ? err.message : err,
        );
      }
      // Resolve the active tenant from the JWT's tenant_id claim.
      const claims = decodeJwt(token);
      const tenantId = claims?.tenant_id ?? null;
      const activeTenant =
        tenants.find((t) => t.tenant_id === tenantId) ?? null;
      set({ activeTenant, authLoading: false });
      // Recompute the chat identity from the new auth state.
      set(recomputeIdentity(get()));
      toast.success(`Connecté en tant que ${user.name || user.email}`, {
        description: activeTenant
          ? `${activeTenant.name} · ${activeTenant.role}`
          : "Aucun tenant actif",
      });
    } catch (err) {
      const message =
        err instanceof AuthApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Échec de la connexion";
      set({ authLoading: false, authError: message });
      throw err;
    }
  },

  signup: async (email, password, name) => {
    if (get().authLoading) return;
    set({ authLoading: true, authError: null, demoFallback: false });
    try {
      const { user, token } = await signupApi(email, password, name);
      writeTokenToStorage(token);
      set({ user, token });
      // A freshly created user has zero tenants — try getMe anyway (the
      // backend may seed a demo membership).
      let tenants: Tenant[] = [];
      try {
        const me = await getMe(token);
        tenants = me.memberships;
        set({ user: me.user, tenants });
      } catch (err) {
        console.warn(
          "getMe failed after signup — proceeding without tenant list",
          err instanceof Error ? err.message : err,
        );
      }
      const claims = decodeJwt(token);
      const tenantId = claims?.tenant_id ?? null;
      const activeTenant =
        tenants.find((t) => t.tenant_id === tenantId) ?? null;
      set({ activeTenant, authLoading: false });
      set(recomputeIdentity(get()));
      if (tenants.length === 0) {
        toast.success(`Compte créé — bienvenue ${user.name || user.email}`, {
          description:
            "Aucun tenant. Utilisez la démo ou créez un tenant (Phase 6b).",
        });
      } else {
        toast.success(`Compte créé — bienvenue ${user.name || user.email}`, {
          description: activeTenant
            ? `${activeTenant.name} · ${activeTenant.role}`
            : "Tenant actif",
        });
      }
    } catch (err) {
      const message =
        err instanceof AuthApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Échec de l'inscription";
      set({ authLoading: false, authError: message });
      throw err;
    }
  },

  logout: () => {
    writeTokenToStorage(null);
    set({
      user: null,
      token: null,
      tenants: [],
      activeTenant: null,
      authError: null,
      demoFallback: false,
      // Reset the chat session so messages from the authenticated identity
      // don't leak into the demo session.
      messages: [],
      selectedMessageId: null,
      isStreaming: false,
      inspectorOpen: false,
      backendStatus: "unknown",
      documents: [],
      approvals: [],
      selectedApprovalId: null,
      selectedApprovalDetail: null,
      view: "copilot",
      identityId: DEFAULT_IDENTITY_ID,
      identity: identityById(DEFAULT_IDENTITY_ID),
    });
    toast.success("Déconnecté", {
      description: "Vous êtes en mode démo (identités mock).",
    });
  },

  setActiveTenant: async (tenantId) => {
    const token = get().token;
    if (!token) return;
    set({ authLoading: true, authError: null });
    try {
      const { token: newToken } = await activateTenant(tenantId, token);
      writeTokenToStorage(newToken);
      const activeTenant =
        get().tenants.find((t) => t.tenant_id === tenantId) ?? null;
      set({ token: newToken, activeTenant, authLoading: false });
      set(recomputeIdentity(get()));
      toast.success("Tenant activé", {
        description: activeTenant?.name ?? tenantId,
      });
    } catch (err) {
      const message =
        err instanceof AuthApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Échec de l'activation du tenant";
      set({ authLoading: false, authError: message });
      toast.error("Activation échouée", { description: message });
    }
  },

  loadAuthFromStorage: async () => {
    const token = readTokenFromStorage();
    if (!token) {
      // No persisted token — stay in demo mode (the AuthScreen is shown).
      return;
    }
    set({ authLoading: true, authError: null });
    try {
      const me = await getMe(token);
      const claims = decodeJwt(token);
      const tenantId = claims?.tenant_id ?? null;
      const activeTenant =
        me.memberships.find((t) => t.tenant_id === tenantId) ?? null;
      set({
        user: me.user,
        token,
        tenants: me.memberships,
        activeTenant,
        authLoading: false,
      });
      set(recomputeIdentity(get()));
    } catch (err) {
      // The token is invalid/expired OR the backend is down. We can't tell
      // the difference from the error type alone — clear the token to be
      // safe (a backend-outage during demo just re-prompts the AuthScreen,
      // which has a "Essayer la démo" fallback).
      console.warn(
        "loadAuthFromStorage failed — clearing persisted token",
        err instanceof Error ? err.message : err,
      );
      writeTokenToStorage(null);
      set({
        user: null,
        token: null,
        tenants: [],
        activeTenant: null,
        authLoading: false,
        // If the backend was reachable enough to return a 401, this is a real
        // "token expired" — surface it. If it was a 502/network error, the
        // AuthScreen "Essayer la démo" path will retry the backend.
        authError:
          err instanceof AuthApiError && err.status === 401
            ? "Session expirée — reconnectez-vous."
            : null,
      });
    }
  },

  clearAuthError: () => set({ authError: null }),

  enterDemoMode: () => {
    // Skip auth — use the mock identities directly. The token stays null so
    // the chat API falls back to the body-identity path (Phase 0 behaviour).
    set({
      demoFallback: true,
      authError: null,
      authLoading: false,
      identityId: DEFAULT_IDENTITY_ID,
      identity: identityById(DEFAULT_IDENTITY_ID),
      messages: [],
      selectedMessageId: null,
      isStreaming: false,
      inspectorOpen: false,
      backendStatus: "unknown",
      documents: [],
      approvals: [],
      selectedApprovalId: null,
      selectedApprovalDetail: null,
      view: "copilot",
    });
    toast("Mode démo (backend hors ligne)", {
      id: DEMO_TOAST_ID,
      description:
        "Le service Tevet-7 est injoignable — réponses simulées depuis le mock local.",
    });
  },

  // -----------------------------------------------------------------------
  // Identity / chat actions
  // -----------------------------------------------------------------------

  setIdentity: (identityId) => {
    // When authenticated, the identity is derived from the JWT — switching
    // to a mock identity would break the auth context. We no-op + toast.
    if (get().token) {
      toast.error("Identité verrouillée", {
        description:
          "Vous êtes connecté — déconnectez-vous pour changer d'identité.",
      });
      return;
    }
    const identity = identityById(identityId);
    // The Ops Console is admin-only — switching to a producer identity forces
    // the view back to copilot. When switching TO admin we keep the current
    // view unchanged (per spec: "don't force ops"), defaulting to copilot if
    // this is the first time the admin identity is selected.
    const nextView: CopilotView = identity.kind === "admin"
      ? get().view
      : "copilot";
    set({
      identityId,
      identity,
      messages: [],
      selectedMessageId: null,
      isStreaming: false,
      inspectorOpen: false,
      // Reset the backend status so the footer reflects the new conversation
      // session — it'll be re-evaluated on the next message.
      backendStatus: "unknown",
      // Reset the document list — the new identity may have a different scope
      // (producer #42 vs producer #99 vs admin full-access). loadDocuments()
      // is re-triggered from the page-level effect that watches identity.
      documents: [],
      documentsLoading: true,
      // Reset the Ops Console state — the new identity may not be allowed to
      // see approvals at all, and even if it is the queue must be re-fetched.
      view: nextView,
      approvals: [],
      approvalsLoading: false,
      selectedApprovalId: null,
      selectedApprovalDetail: null,
    });
    // Dismiss any lingering demo-mode notice when the scope changes.
    toast.dismiss(DEMO_TOAST_ID);
    const scope = identity.producerNumber
      ? `Producer ${identity.producerNumber}`
      : "Admin (full access)";
    toast.success(`Scope modifié : interrogation en tant que ${scope}`, {
      description: identity.farmName ?? identity.role,
    });
    // Kick off the scoped fetch immediately — the page-level effect will
    // also fire, but Zustand dedupes by replacing the in-flight promise
    // (the latest documents list wins).
    void get().loadDocuments();
  },

  sendExample: (_questionId, label) => {
    // The label IS the user message — the backend / mock layer routes based
    // on its content, so the question id is no longer needed at this layer.
    void runAssistant(get, set, label);
  },

  sendMessage: (text) => {
    const trimmed = text.trim();
    if (!trimmed || get().isStreaming) return;
    void runAssistant(get, set, trimmed);
  },

  selectMessage: (messageId) => {
    set({ selectedMessageId: messageId, inspectorOpen: messageId !== null });
  },

  toggleInspector: () => set((s) => ({ inspectorOpen: !s.inspectorOpen })),
  setInspectorOpen: (open) => set({ inspectorOpen: open }),
  resetConversation: () =>
    set({
      messages: [],
      selectedMessageId: null,
      isStreaming: false,
      backendStatus: "unknown",
    }),

  loadDocuments: async () => {
    const identity = get().identity;
    set({ documentsLoading: true });
    try {
      const documents = await listDocuments(identity);
      set({ documents, documentsLoading: false });
    } catch (err) {
      console.warn(
        "Documents backend unreachable, leaving panel empty",
        err instanceof Error ? err.message : err,
      );
      set({ documents: [], documentsLoading: false });
    }
  },

  addDocument: async (input) => {
    if (get().documentMutating) return;
    const identity = get().identity;
    set({ documentMutating: true });
    try {
      const result = await uploadDocument(input, identity);
      toast.success("Document indexé", {
        description: `${result.title} · ${result.chunksCount} chunk${result.chunksCount > 1 ? "s" : ""}`,
      });
      await get().loadDocuments();
    } catch (err) {
      console.warn(
        "Upload failed",
        err instanceof Error ? err.message : err,
      );
      toast.error("Indexation échouée", {
        description:
          err instanceof Error
            ? err.message
            : "Le backend n'a pas pu indexer ce document.",
      });
    } finally {
      set({ documentMutating: false });
    }
  },

  removeDocument: async (id) => {
    if (get().documentMutating) return;
    const previous = get().documents;
    // Optimistic delete — the list updates immediately, and we roll back if
    // the backend rejects the call.
    set({
      documents: previous.filter((d) => d.id !== id),
      documentMutating: true,
    });
    try {
      await deleteDocument(id);
      toast.success("Document supprimé");
      await get().loadDocuments();
    } catch (err) {
      console.warn(
        "Delete failed",
        err instanceof Error ? err.message : err,
      );
      set({ documents: previous });
      toast.error("Suppression échouée", {
        description:
          err instanceof Error ? err.message : "Le backend est injoignable.",
      });
    } finally {
      set({ documentMutating: false });
    }
  },

  // -----------------------------------------------------------------------
  // Ops Console — approval queue (admin-only)
  // -----------------------------------------------------------------------

  setView: (view) => {
    const identity = get().identity;
    // Defensive: producers can never enter the ops view. The ViewToggle is
    // hidden for them, but this guard also catches any client-side race.
    const next: CopilotView =
      view === "ops" && identity.kind !== "admin" ? "copilot" : view;
    set({ view: next });
    // Per spec — loading the approvals happens when the view switches to ops.
    if (next === "ops") {
      void get().loadApprovals();
    }
  },

  loadApprovals: async () => {
    const identity = get().identity;
    if (identity.kind !== "admin") {
      // Hard guard — even if a producer somehow calls this, do not hit the
      // admin-only endpoint. The backend would reject anyway, but we avoid
      // the network round-trip and the noisy 403.
      set({ approvals: [], approvalsLoading: false });
      return;
    }
    set({ approvalsLoading: true });
    try {
      const approvals = await listApprovals(identity);
      set({ approvals, approvalsLoading: false });
    } catch (err) {
      console.warn(
        "Approvals backend unreachable, leaving queue empty",
        err instanceof Error ? err.message : err,
      );
      set({ approvals: [], approvalsLoading: false });
      toast.error("Ops Console injoignable", {
        description:
          err instanceof Error
            ? err.message
            : "Le backend Tevet-7 est injoignable.",
      });
    }
  },

  selectApproval: async (id) => {
    if (id === null) {
      set({ selectedApprovalId: null, selectedApprovalDetail: null });
      return;
    }
    set({ selectedApprovalId: id, selectedApprovalDetail: null });
    try {
      const detail = await getApprovalDetail(id);
      // Guard against races: only commit if the user hasn't selected another
      // row while this fetch was in flight.
      if (get().selectedApprovalId === id) {
        set({ selectedApprovalDetail: detail });
      }
    } catch (err) {
      console.warn(
        "Approval detail fetch failed",
        err instanceof Error ? err.message : err,
      );
      if (get().selectedApprovalId === id) {
        set({ selectedApprovalDetail: null });
      }
      toast.error("Dossier injoignable", {
        description:
          err instanceof Error ? err.message : "Backend Tevet-7 injoignable.",
      });
    }
  },

  decide: async (id, decision, reason) => {
    if (get().decisionInFlight) return;
    const identity = get().identity;
    if (identity.kind !== "admin") return;
    set({ decisionInFlight: true });
    try {
      const detail = await decideApproval(
        id,
        decision,
        reason,
        identity.id,
      );
      toast.success("Décision enregistrée", {
        description: `${detail.approval.legal_name} · ${
          decision === "approve"
            ? "Approuvé"
            : decision === "reject"
              ? "Rejeté"
              : "Outrepassé"
        }`,
      });
      // Update the selected detail in place + refresh the list so the row
      // moves to the "decided" group with its new status badge.
      set({
        selectedApprovalDetail: detail,
        decisionInFlight: false,
      });
      await get().loadApprovals();
    } catch (err) {
      console.warn(
        "Decide failed",
        err instanceof Error ? err.message : err,
      );
      set({ decisionInFlight: false });
      toast.error("Décision échouée", {
        description:
          err instanceof Error ? err.message : "Backend Tevet-7 injoignable.",
      });
    }
  },
}));

/**
 * Shared helper that pushes the user message, shows the typing indicator,
 * then reveals the assistant response.
 *
 * Flow:
 *   1. Append the user message + set `isStreaming=true`.
 *   2. Race the real backend call (`callBackend`) against a minimum 400 ms
 *      typing delay — `Promise.all` ensures the indicator stays visible for
 *      at least 400 ms even when the backend is fast.
 *   3. On success: build the assistant message from the real backend
 *      response, set `backendStatus="connected"`.
 *   4. On failure (network / non-2xx / parse / timeout): log a warning,
 *      set `backendStatus="demo"`, show a muted "Mode démo" toast, then
 *      fall back to `getMockResponse` with the existing simulated latency
 *      so the prototype keeps working with the backend offline.
 */
async function runAssistant(
  get: () => CopilotState,
  set: (partial: Partial<CopilotState>) => void,
  userText: string,
) {
  if (get().isStreaming) return;

  const identity = get().identity;

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

  let response: AssistantResponse;

  try {
    // Race the backend call against a minimum typing-indicator duration.
    const [backendResponse] = await Promise.all([
      callBackend(userText, identity),
      sleep(MIN_TYPING_MS),
    ]);
    response = backendResponse;
    set({ backendStatus: "connected" });
    // A successful backend call implicitly clears any prior demo notice.
    toast.dismiss(DEMO_TOAST_ID);
  } catch (err) {
    console.warn(
      "Backend unreachable, using mock fallback",
      err instanceof Error ? err.message : err,
    );
    set({ backendStatus: "demo" });
    // Muted, on-brand toast — NOT a warning color. Uses sonner's neutral
    // styling (popover bg + muted-foreground text via the Toaster config).
    toast("Mode démo (backend hors ligne)", {
      id: DEMO_TOAST_ID,
      description:
        "Le service Tevet-7 est injoignable — réponses simulées depuis le mock local.",
    });
    // Keep the existing simulated latency for the mock fallback so the
    // typing indicator feels natural alongside the real path.
    const mockDelay =
      MOCK_LATENCY_MIN_MS + Math.random() * MOCK_LATENCY_JITTER_MS;
    await sleep(mockDelay);
    response = getMockResponse(userText, identity);
  }

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
}
