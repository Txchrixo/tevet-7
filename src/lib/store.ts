import { create } from "zustand";
import { toast } from "sonner";

import { callBackend } from "./api";
import {
  DEFAULT_IDENTITY_ID,
  IDENTITIES,
  getMockResponse,
} from "./mock-data";
import type { AssistantResponse, ChatMessage, Identity } from "./types";

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

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export type BackendStatus = "connected" | "demo" | "unknown";

interface CopilotState {
  identityId: string;
  identity: Identity;
  messages: ChatMessage[];
  /** Id of the assistant message currently being inspected in the right panel. */
  selectedMessageId: string | null;
  /** True while the assistant is "thinking" (typing indicator). */
  isStreaming: boolean;
  /** Whether the inspector panel is open on desktop. */
  inspectorOpen: boolean;
  /** Health of the FastAPI backend connection — drives the footer indicator. */
  backendStatus: BackendStatus;

  setIdentity: (identityId: string) => void;
  sendExample: (questionId: string, label: string) => void;
  sendMessage: (text: string) => void;
  selectMessage: (messageId: string | null) => void;
  toggleInspector: () => void;
  setInspectorOpen: (open: boolean) => void;
  resetConversation: () => void;
}

function identityById(id: string): Identity {
  return IDENTITIES.find((i) => i.id === id) ?? IDENTITIES[0];
}

export const useCopilotStore = create<CopilotState>((set, get) => ({
  identityId: DEFAULT_IDENTITY_ID,
  identity: identityById(DEFAULT_IDENTITY_ID),
  messages: [],
  selectedMessageId: null,
  isStreaming: false,
  inspectorOpen: false,
  backendStatus: "unknown",

  setIdentity: (identityId) => {
    const identity = identityById(identityId);
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
    });
    // Dismiss any lingering demo-mode notice when the scope changes.
    toast.dismiss(DEMO_TOAST_ID);
    const scope = identity.producerNumber
      ? `Producer ${identity.producerNumber}`
      : "Admin (full access)";
    toast.success(`Scope modifié : interrogation en tant que ${scope}`, {
      description: identity.farmName ?? identity.role,
    });
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
