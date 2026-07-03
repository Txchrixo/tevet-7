"""Agent orchestrator — the LLM-in-a-loop core.

Phase 1 uses a hand-rolled loop for clarity. Phase 6 may migrate to LangGraph
once we need branching, parallel tool calls, or stateful sub-graphs.

Loop semantics
--------------

1. Compose the prompt: ``[system, ...history, user_message]``.
2. Call the LLM with the tool definitions attached.
3. Inspect the LLM response:
   a. If it's a tool call → execute the tool, append the result to history,
      loop back to step 1.
   b. If it's a final answer → parse it (the agent is required to return the
      JSON schema from its prompt), return ``AgentResponse``.
4. If ``step`` reaches ``max_steps`` without a final answer, return an
   ``AgentResponse`` with an "I'm sorry, I couldn't complete this" answer.
5. Every LLM call and every tool call is wrapped in a Langfuse span, so a
   full trace is visible in the Langfuse UI.

This is the standard "ReAct"-style loop, deliberately minimal. We avoid
libraries like LangChain to keep the control flow auditable.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger("tevet7.orchestrator")


# ─────────────────────────────────────────────────────────────────────────────
# Tool protocol
# ─────────────────────────────────────────────────────────────────────────────


class Tool(Protocol):
    """Structural type every tool passed to the orchestrator must satisfy.

    Concrete tools (e.g. ``SqlReadTool``) don't need to inherit from this —
    they just need to expose ``run`` with this signature. The orchestrator
    inspects ``tool.__class__.__name__`` to know which tool the LLM called.
    """

    async def run(self, question: str) -> Any:  # ToolResult | ...
        ...


# ─────────────────────────────────────────────────────────────────────────────
# Result
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class AgentResponse:
    """Final structured response returned by ``AgentOrchestrator.run``.

    These fields map 1:1 to the JSON schema the Producer Copilot prompt
    promises the user (``answer``, ``sql_used``, ``chart``, ``sources``),
    plus internal fields for observability and quota accounting.
    """

    answer: str
    sql_used: str | None = None
    chart: dict[str, Any] | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)

    # Internal / observability
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens_used: int = 0
    latency_ms: int = 0
    steps_taken: int = 0
    # True if the loop exited because of max_steps (used for SLO dashboards).
    hit_step_budget: bool = False
    # Langfuse trace URL (set by the wrapper in Phase 1).
    trace_url: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────


class AgentOrchestrator:
    """Minimal ReAct-style orchestrator.

    Parameters
    ----------
    llm_client:
        Abstract LLM client. In Phase 1 this is a thin wrapper around
        ``openai.AsyncOpenAI`` exposing ``async def chat(messages, tools)``
        returning a normalised response object with ``content`` and
        ``tool_calls``.
    tools:
        List of tool instances satisfying the ``Tool`` protocol. Their
        ``run`` method is invoked when the LLM requests them.
    system_prompt:
        The rendered system prompt (e.g. from
        ``app/prompts/producer_copilot.md`` with ``{{producer_id}}`` etc.
        already substituted).
    max_steps:
        Safety cap on the number of LLM round-trips per request. Default 5.
    """

    def __init__(
        self,
        llm_client: Any,
        tools: list[Tool],
        system_prompt: str,
        max_steps: int = 5,
    ) -> None:
        self.llm_client = llm_client
        self.tools = {tool.__class__.__name__: tool for tool in tools}
        self.system_prompt = system_prompt
        self.max_steps = max_steps

    async def run(self, user_message: str, context: dict[str, Any]) -> AgentResponse:
        """Execute the agent loop and return a structured response.

        Parameters
        ----------
        user_message:
            The natural-language message from the end user.
        context:
            Verified identity context (tenant_id, user_id, role,
            scope_value, ...). This is passed to tools at construction
            time, NOT in this method — but we keep it here so the
            orchestrator can include safe metadata in Langfuse spans.

        Returns
        -------
        AgentResponse
        """
        started_at = time.monotonic()
        history: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message},
        ]
        tool_calls_log: list[dict[str, Any]] = []
        tokens_used = 0

        for step in range(1, self.max_steps + 1):
            # TODO(Phase 1): wrap this call in a Langfuse span named
            # `agent.llm_call` with the step number as a metadata field.
            llm_response = await self._call_llm(history)
            tokens_used += getattr(llm_response, "tokens_used", 0)

            # Case A: LLM wants to call one or more tools.
            if getattr(llm_response, "tool_calls", None):
                for call in llm_response.tool_calls:
                    tool_name = call["name"]
                    tool_input = call["input"]
                    tool = self.tools.get(tool_name)
                    if tool is None:
                        # LLM hallucinated a tool name. Feed the error back.
                        history.append(
                            {
                                "role": "tool",
                                "name": tool_name,
                                "content": f"ERROR: tool '{tool_name}' is not available.",
                            }
                        )
                        continue

                    # TODO(Phase 1): wrap in a Langfuse span named
                    # `agent.tool_call` with tool name + input as metadata.
                    try:
                        result = await tool.run(**tool_input) if isinstance(tool_input, dict) \
                            else await tool.run(tool_input)
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("Tool %s raised", tool_name)
                        result = {"error": f"{exc!r}"}

                    tool_calls_log.append(
                        {"name": tool_name, "input": tool_input, "step": step}
                    )
                    history.append(
                        {
                            "role": "tool",
                            "name": tool_name,
                            "content": self._serialise_tool_result(result),
                        }
                    )
                # Loop back: the LLM will see the tool results.
                continue

            # Case B: LLM produced a final answer.
            final = self._parse_final_answer(llm_response.content)
            return AgentResponse(
                answer=final.get("answer", ""),
                sql_used=final.get("sql_used"),
                chart=final.get("chart"),
                sources=final.get("sources", []),
                tool_calls=tool_calls_log,
                tokens_used=tokens_used,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                steps_taken=step,
                hit_step_budget=False,
            )

        # Case C: ran out of steps.
        return AgentResponse(
            answer=(
                "Je suis désolé, je n'ai pas pu traiter votre demande dans le "
                "budget d'étapes autorisé. Pouvez-vous reformuler plus "
                "précisément ?"
            ),
            tool_calls=tool_calls_log,
            tokens_used=tokens_used,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            steps_taken=self.max_steps,
            hit_step_budget=True,
        )

    # ───────────────────────────────────────────────────────────────────────
    # Private helpers (stubs in Phase 0)
    # ───────────────────────────────────────────────────────────────────────
    async def _call_llm(self, history: list[dict[str, Any]]) -> Any:
        """Send the conversation to the LLM with tool definitions attached.

        TODO(Phase 1): use ``openai.AsyncOpenAI().chat.completions.create``
        with ``tools=[...]`` derived from the tool instances.
        """
        raise NotImplementedError("Phase 1: wire up the LLM client.")

    def _parse_final_answer(self, content: str) -> dict[str, Any]:
        """Parse the LLM's final JSON answer.

        The Producer Copilot prompt requires a JSON object with ``answer``,
        ``sql_used``, ``chart``, ``sources``. We tolerate minor formatting
        issues (markdown code fences, trailing prose) by extracting the
        first JSON object from the string.

        TODO(Phase 1): implement robust extraction + schema validation.
        """
        raise NotImplementedError("Phase 1: implement final-answer parsing.")

    @staticmethod
    def _serialise_tool_result(result: Any) -> str:
        """Serialise a tool result to a string for the LLM history.

        For ``SqlReadTool`` we send back the columns + first N rows + the
        executed SQL — never the raw connection object.
        """
        # TODO(Phase 1): implement per-tool-type serialisation.
        return str(result)
