"""Tests for Phase B1 — Auth rate limiting."""
from __future__ import annotations
import sys
from pathlib import Path
_AGENTIC = Path(__file__).resolve().parent.parent
if str(_AGENTIC) not in sys.path: sys.path.insert(0, str(_AGENTIC))
import pytest
from app.auth.rate_limit import check_auth_rate_limit, clear_auth_rate_limit, get_client_ip

@pytest.fixture(autouse=True)
def _clear():
    clear_auth_rate_limit()
    yield
    clear_auth_rate_limit()

def test_allows_under_cap():
    for _ in range(5):
        assert check_auth_rate_limit("1.2.3.4")[0] is True

def test_blocks_over_cap():
    for _ in range(5):
        check_auth_rate_limit("1.2.3.4")
    assert check_auth_rate_limit("1.2.3.4")[0] is False

def test_isolated_per_ip():
    for _ in range(5):
        check_auth_rate_limit("1.1.1.1")
    assert check_auth_rate_limit("2.2.2.2")[0] is True

def test_get_client_ip_direct():
    from unittest.mock import MagicMock
    request = MagicMock()
    request.headers = {}
    request.client = MagicMock(host="192.168.1.1")
    assert get_client_ip(request) == "192.168.1.1"

def test_get_client_ip_forwarded():
    from unittest.mock import MagicMock
    request = MagicMock()
    request.headers = {"x-forwarded-for": "10.0.0.1, 192.168.1.1"}
    request.client = MagicMock(host="192.168.1.1")
    assert get_client_ip(request) == "10.0.0.1"
