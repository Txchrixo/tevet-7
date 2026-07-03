import { create } from "zustand";
import { toast } from "sonner";

import {
  DEFAULT_IDENTITY_ID,
  IDENTITIES,
  getResponseForExample,
  getResponseForMessage,
} from "./mock-data";
import type { AssistantResponse, ChatMessage, Identity } from "./types";

let idCounter = 0;
function makeId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${Date.now().toString(36)}-${idCounter}`;
}

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

  setIdentity: (identityId) => {
    const identity = identityById(identityId);
    set({
      identityId,
      identity,
      messages: [],
      selectedMessageId: null,
      isStreaming: false,
      inspectorOpen: false,
    });
    const scope = identity.producerNumber
      ? `Producer ${identity.producerNumber}`
      : "Admin (full access)";
    toast.success(`Scope modifié : interrogation en tant que ${scope}`, {
      description: identity.farmName ?? identity.role,
    });
  },

  sendExample: (questionId, label) => {
    runAssistant(get, set, label, () =>
      getResponseForExample(get().identity, questionId),
    );
  },

  sendMessage: (text) => {
    const trimmed = text.trim();
    if (!trimmed || get().isStreaming) return;
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
}));

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
