"""Tevet-7 agentic service.

Top-level package. Public submodules:

- ``app.main`` - FastAPI application factory and ASGI entrypoint.
- ``app.config`` - pydantic-settings based configuration.
- ``app.database`` - async SQLAlchemy engine + session dependency.
- ``app.schema`` (loaded from ``app/schema.yaml``) - the DP business schema.
- ``app.connectors`` - abstraction between agents and tenant data.
- ``app.tools`` - agent-callable functions (sql_tool, doc_search_tool, ...).
- ``app.agents`` - the agent loop orchestrator.
- ``app.api`` - HTTP routers (``/chat``, later ``/admin``, ``/onboarding``).
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
