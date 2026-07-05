/**
 * Feature flags (#44).
 *
 * Simple client-side feature flags. No external service needed.
 * Flags are stored in localStorage and can be overridden via URL param:
 * /?flag__experimental_feature=true
 */

type FlagValue = boolean | string | number;
type Flags = Record<string, FlagValue>;

const DEFAULT_FLAGS: Flags = {
  // All features are ON by default (we ship features, not experiments)
  streaming: true,
  guardrails: true,
  conversation_memory: true,
  semantic_reranker: true,
  dark_mode: true,
  export: true,
  team_management: true,
};

const STORAGE_KEY = "tevet7.flags";

function loadFlags(): Flags {
  if (typeof window === "undefined") return DEFAULT_FLAGS;
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return { ...DEFAULT_FLAGS, ...JSON.parse(stored) };
  } catch {}
  // Check URL overrides
  const params = new URLSearchParams(window.location.search);
  const overrides: Flags = {};
  for (const [key, value] of params.entries()) {
    if (key.startsWith("flag__")) {
      const flagName = key.slice(6);
      overrides[flagName] = value === "true" ? true : value === "false" ? false : value;
    }
  }
  if (Object.keys(overrides).length > 0) {
    const merged = { ...DEFAULT_FLAGS, ...overrides };
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(merged)); } catch {}
    return merged;
  }
  return DEFAULT_FLAGS;
}

export function getFlag(name: string): FlagValue | undefined {
  return loadFlags()[name];
}

export function isFlagEnabled(name: string): boolean {
  return loadFlags()[name] === true;
}

export function setFlag(name: string, value: FlagValue): void {
  if (typeof window === "undefined") return;
  const flags = loadFlags();
  flags[name] = value;
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(flags)); } catch {}
}

export function getAllFlags(): Flags {
  return loadFlags();
}
