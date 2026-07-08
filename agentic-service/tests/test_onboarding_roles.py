"""Tests for the onboarding role/scope plumbing (multi-tenant RLS).

Covers the three pieces that make a wizard-defined custom role (e.g.
"driver" scoped by ``driver_id``) actually enforce row-level security:

1. ``_stamp_roles_on_schema`` - the declared roles must reach the saved
   schema (``allowed_for_roles`` + ``tenant_scope_column``), otherwise the
   sqlglot rewriter has nothing to match.
2. ``resolve_role_scope`` - the roles_config is the source of truth for
   (scope_column, scope_value); the legacy fallback is FAIL-CLOSED (only
   "admin" is unscoped).
3. The end-to-end wiring is exercised by ``scripts/e2e_rls.py`` against a
   live backend; these unit tests pin the pure logic.
"""

from __future__ import annotations

import pytest

from app.tenants import onboarding
from app.tenants.onboarding import _stamp_roles_on_schema, resolve_role_scope


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _schema(scope_col: str | None = None, roles: list[str] | None = None) -> dict:
    """A minimal auto-detected CSV schema (one 'deliveries' table)."""
    return {
        "metadata": {"default_limit": 1000},
        "tables": [
            {
                "name": "deliveries",
                "tenant_scope_column": scope_col,
                "allowed_for_roles": roles if roles is not None else ["producer", "admin"],
                "columns": [
                    {"name": "delivery_id", "type": "integer"},
                    {"name": "driver_id", "type": "integer"},
                    {"name": "city", "type": "text"},
                    {"name": "price_eur", "type": "decimal"},
                ],
            }
        ],
        "forbidden_tables": [],
    }


DRIVER_ROLES = {"driver": {"scope_column": "driver_id"}, "admin": {"scope_column": None}}


# ─────────────────────────────────────────────────────────────────────────────
# 1. _stamp_roles_on_schema
# ─────────────────────────────────────────────────────────────────────────────


def test_stamp_adds_declared_roles_to_allowed_for_roles() -> None:
    schema = _schema()
    changed = _stamp_roles_on_schema(schema, DRIVER_ROLES)
    assert changed is True
    assert "driver" in schema["tables"][0]["allowed_for_roles"]
    # Existing roles are preserved, admin is always present.
    assert {"producer", "admin"} <= set(schema["tables"][0]["allowed_for_roles"])


def test_stamp_sets_tenant_scope_column_when_column_exists() -> None:
    schema = _schema(scope_col=None)
    _stamp_roles_on_schema(schema, DRIVER_ROLES)
    assert schema["tables"][0]["tenant_scope_column"] == "driver_id"


def test_stamp_skips_scope_column_missing_from_table() -> None:
    """A scoped role whose column doesn't exist in the table must NOT be
    stamped - the rewriter would emit invalid SQL."""
    schema = _schema(scope_col=None)
    _stamp_roles_on_schema(schema, {"region_mgr": {"scope_column": "region_id"}})
    assert schema["tables"][0]["tenant_scope_column"] is None


def test_stamp_is_idempotent() -> None:
    schema = _schema()
    assert _stamp_roles_on_schema(schema, DRIVER_ROLES) is True
    # Second run: nothing left to change.
    assert _stamp_roles_on_schema(schema, DRIVER_ROLES) is False


def test_stamp_unscoped_roles_only_touch_allowed_for_roles() -> None:
    schema = _schema(scope_col=None)
    _stamp_roles_on_schema(schema, {"viewer": {"scope_column": None}})
    assert "viewer" in schema["tables"][0]["allowed_for_roles"]
    assert schema["tables"][0]["tenant_scope_column"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. resolve_role_scope
# ─────────────────────────────────────────────────────────────────────────────


def _patch_config(monkeypatch: pytest.MonkeyPatch, roles_config: dict | None) -> None:
    async def fake_get_config_row(tenant_id: str) -> dict | None:
        if roles_config is None:
            return None
        return {"tenant_id": tenant_id, "roles_config": roles_config}

    monkeypatch.setattr(onboarding, "_get_config_row", fake_get_config_row)


@pytest.mark.asyncio
async def test_resolve_scope_custom_role_uses_roles_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(monkeypatch, DRIVER_ROLES)
    assert await resolve_role_scope("t1", "driver", 7) == ("driver_id", 7)


@pytest.mark.asyncio
async def test_resolve_scope_declared_admin_is_unscoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(monkeypatch, DRIVER_ROLES)
    assert await resolve_role_scope("t1", "admin", None) == (None, None)


@pytest.mark.asyncio
async def test_resolve_scope_legacy_fallback_producer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No roles_config (demo tenant): producer scoped by producer_id."""
    _patch_config(monkeypatch, None)
    assert await resolve_role_scope("dp", "producer", 42) == ("producer_id", 42)


@pytest.mark.asyncio
async def test_resolve_scope_legacy_fallback_admin_unscoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(monkeypatch, None)
    assert await resolve_role_scope("dp", "admin", None) == (None, None)


@pytest.mark.asyncio
async def test_resolve_scope_fails_closed_for_unknown_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAIL-CLOSED: a role that is neither declared nor 'admin' must be
    scoped (by producer_id), never unscoped. This pins the semantics the
    old role-coercion in app/api/chat.py used to enforce for 'customer'."""
    _patch_config(monkeypatch, None)
    assert await resolve_role_scope("dp", "customer", 42) == ("producer_id", 42)
    assert await resolve_role_scope("dp", "mystery_role", 9) == ("producer_id", 9)


@pytest.mark.asyncio
async def test_resolve_scope_undeclared_role_on_onboarded_tenant_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A role missing from an onboarded tenant's roles_config falls back to
    the fail-closed rule, it does not become unscoped."""
    _patch_config(monkeypatch, DRIVER_ROLES)
    assert await resolve_role_scope("t1", "intruder", 3) == ("producer_id", 3)
