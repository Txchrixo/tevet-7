"""Tests for Phase B2 — Refresh tokens."""
from __future__ import annotations
import sys
from pathlib import Path
_AGENTIC = Path(__file__).resolve().parent.parent
if str(_AGENTIC) not in sys.path: sys.path.insert(0, str(_AGENTIC))
import pytest
from jose import JWTError
from app.auth.jwt import (
    _ACCESS_TOKEN_EXPIRY, _REFRESH_TOKEN_EXPIRY,
    create_access_token, create_refresh_token, create_token_pair,
    verify_refresh_token, verify_token,
)

def test_refresh_token_has_type_marker():
    token = create_refresh_token({"sub": "1", "email": "t@t.com"})
    claims = verify_refresh_token(token)
    assert claims["type"] == "refresh"

def test_refresh_longer_than_access():
    assert _REFRESH_TOKEN_EXPIRY > _ACCESS_TOKEN_EXPIRY

def test_verify_refresh_rejects_access_token():
    access = create_access_token({"sub": "1"})
    with pytest.raises(JWTError):
        verify_refresh_token(access)

def test_token_pair_returns_two():
    access, refresh = create_token_pair({"sub": "1", "email": "t@t.com"})
    assert access != refresh
    claims = verify_token(access)
    assert claims["sub"] == "1"
    refresh_claims = verify_refresh_token(refresh)
    assert refresh_claims["type"] == "refresh"

def test_refresh_carries_claims():
    data = {"sub": "42", "tenant_id": "dp", "role": "producer"}
    _, refresh = create_token_pair(data)
    claims = verify_refresh_token(refresh)
    assert claims["sub"] == "42"
    assert claims["tenant_id"] == "dp"

def test_refresh_invalid_signature_rejected():
    token = create_refresh_token({"sub": "1"})
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(JWTError):
        verify_refresh_token(tampered)
