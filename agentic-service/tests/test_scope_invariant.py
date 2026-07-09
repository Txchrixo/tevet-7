"""CI gate for the in-scope compilation invariant.

Runs the fuzzing harness (scripts/verify_scope_invariant.py) so the
invariant is re-verified on every build, and asserts:
  - the harness self-test passes (its checks have teeth), and
  - zero invariant violations across all generated adversarial cases.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_HARNESS = Path(__file__).resolve().parent.parent / "scripts" / "verify_scope_invariant.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("verify_scope_invariant", _HARNESS)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_harness_self_test_has_teeth() -> None:
    """A known leak must be caught by both checks, else the sweep is vacuous."""
    h = _load_harness()
    con = h._seed_db()
    h._self_test(con)  # raises SystemExit if the checks are blind


def test_invariant_holds_on_all_cases() -> None:
    h = _load_harness()
    con = h._seed_db()
    tool = h._tool()
    violations = []
    for sql in h._cases():
        try:
            out = tool.validate_and_rewrite(sql)
        except (h.SqlSecurityError, h.SqlGenerationError):
            continue  # outcome R: rejected, safe
        syn_ok, why = h._syntactic_ok(out)
        assert syn_ok, f"syntactic invariant violated for {sql!r}: {why} -> {out!r}"
        sem_ok, why = h._semantic_ok(con, out)
        if not sem_ok:
            violations.append(f"{sql!r} -> {out!r} : {why}")
    assert not violations, f"semantic leaks: {violations}"


def test_case_volume_is_meaningful() -> None:
    """Guard against the generator silently shrinking to a trivial set."""
    h = _load_harness()
    assert len(h._cases()) >= 150
