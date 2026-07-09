"""CI gate for the permission-constrained benchmark.

Asserts the headline guarantees hold on the reference dataset:
  - zero leaks escaped (no out-of-scope value ever reaches a result);
  - 100% accuracy under constraint on honest generations;
  - the gold answer is genuinely scope-masked (differs across actors),
    so the benchmark is not vacuous.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def mod():
    return importlib.import_module("eval.permission_eval")


def test_no_leak_escapes_and_full_accuracy(mod, capsys) -> None:
    rc = mod.main()
    assert rc == 0
    report = (mod.Path(mod.__file__).resolve().parent / "permission_report.json")
    import json
    data = json.loads(report.read_text())
    assert data["leakage"]["escaped"] == 0
    assert data["leakage"]["attempts"] >= 6
    assert data["leakage"]["containment_rate"] == 1.0
    assert data["accuracy_under_constraint"] == 1.0
    assert not data["failures"]


def test_gold_is_scope_masked(mod) -> None:
    """Same question must yield different correct answers per actor - else
    the benchmark would trivially pass without measuring isolation."""
    con = mod._db()
    differing = 0
    for q in mod.QUESTIONS:
        golds = {a["name"]: mod._gold(con, q, a) for a in mod.ACTORS}
        if len(set(map(str, golds.values()))) > 1:
            differing += 1
    # At least most questions have actor-dependent answers.
    assert differing >= 4


def test_denied_column_refused_for_drivers_allowed_for_admin(mod) -> None:
    con = mod._db()
    q5 = next(q for q in mod.QUESTIONS if q.id == "q5")
    golds = {a["name"]: mod._gold(con, q5, a) for a in mod.ACTORS}
    assert golds["driver-7"] == "REFUSED"
    assert golds["driver-9"] == "REFUSED"
    assert golds["admin"] not in ("REFUSED", None)
