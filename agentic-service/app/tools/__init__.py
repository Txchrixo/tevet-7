"""Tools package.

A **tool** is a thin, audited function the agent can call. Each tool:

- Wraps a Connector (or another external service).
- Enforces its own pre/post conditions on top of the connector's.
- Reports its result to the orchestrator in a structured ``ToolResult``.
- Is traced as a Langfuse span.

Available tools
---------------

- ``SqlReadTool`` (Phase 1) - read-only SQL on the tenant's allowed tables,
  with mandatory row-level scoping enforced by sqlglot rewriting. See
  ``sql_tool.py``.

Planned tools
-------------

- ``DocumentSearchTool`` (Phase 3) - pgvector RAG over tenant-uploaded docs.
- ``BusinessActionTool`` (Phase 4) - proposes a write, queues it for human
  approval, never executes directly.
- ``VisualizationTool`` (Phase 2) - turns a QueryResult into a chart spec.

The orchestrator (``app/agents/orchestrator.py``) picks the tool list per
agent based on the agent's configuration.
"""

from app.tools.sql_tool import SqlReadTool, ToolResult

__all__ = ["SqlReadTool", "ToolResult"]
