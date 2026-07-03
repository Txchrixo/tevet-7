"""Connectors package.

A **Connector** is the abstraction between a Tevet-7 agent and a tenant's
data. Different tenants expose their data differently:

- Drive Producteur (Phase 1): a read-only Postgres replica -> ``PostgresConnector``.
- A Shopify merchant tenant (future): the Shopify Admin API -> ``ShopifyConnector``.
- A generic SaaS tenant (future): their REST API -> ``RestApiConnector``.

All connectors implement :class:`app.connectors.base.Connector`. Agents and
tools only ever talk to the ``Connector`` interface, so adding a new tenant
type does not require touching agent code.

See ``base.py`` for the contract and ``QueryResult`` dataclass.
"""

from app.connectors.base import Connector, QueryResult

__all__ = ["Connector", "QueryResult"]
