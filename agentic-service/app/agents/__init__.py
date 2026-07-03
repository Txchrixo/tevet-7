"""Agents package.

An **agent** in Tevet-7 is the combination of:

- A **system prompt** (markdown, versioned, stored in ``app/prompts/``).
- A **set of tools** (from ``app/tools/``).
- An **orchestrator** that runs the LLM-in-a-loop until it produces a final
  answer or hits the step budget.

The orchestrator is intentionally simple in Phase 1 — a hand-rolled
``while step < max_steps`` loop. Phase 6 may migrate to LangGraph once we
need branching, parallel tool calls, or stateful sub-graphs.
"""

from app.agents.orchestrator import AgentOrchestrator, AgentResponse

__all__ = ["AgentOrchestrator", "AgentResponse"]
