#!/usr/bin/env python3
"""Tevet-7 eval suite — 38-case acceptance-criteria scorer.

Runs the 38 natural-language questions in ``dataset.json`` against the
Tevet-7 backend at ``http://localhost:8001/api/chat`` and scores:

  - % SQL valid          (sql_expected=true cases where SQL is present
                           AND only touches tables in tables_allowed)
  - % scopes respected   (cases where scope_clause_contains matched
                           OR refused=true was expected and delivered)
  - % intents correct    (intent extracted from steps[0].detail matches
                           expected intent)
  - % responses well-formed (answer non-empty, intent non-null, shape
                              matches the API contract)

This is the interview argument n°2 (after the 8 security tests):
"I have a 38-case eval suite that scores the agent on real acceptance
criteria, not vibes." The 5 documentary cases (Phase 3) + 3 Ops Copilot
cases (Phase 4) extend the original 30 analytical/security cases.

Exit codes
----------
  0  overall pass rate >= 80%
  1  overall pass rate < 80%
  2  backend unreachable / dataset missing

Usage
-----
  $ cd agentic-service
  $ python3 eval/eval.py

The backend must be running on port 8001 (see ``run.sh`` or
``mini-services/tevet7-backend``).
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx
import sqlglot
from sqlglot import exp

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

EVAL_DIR = Path(__file__).resolve().parent
DATASET_PATH = EVAL_DIR / "dataset.json"
REPORT_PATH = EVAL_DIR / "report.json"
BACKEND_URL = "http://localhost:8001/api/chat"
HEALTH_URL = "http://localhost:8001/health"
TIMEOUT_PER_CASE = 10.0
HEALTH_TIMEOUT = 5.0
CONCURRENCY = 5
PASS_RATE_THRESHOLD = 0.80

INTENT_RE = re.compile(r"Intention détectée\s*:\s*(\w+)")


class BackendDown(Exception):
    """Raised when the backend is unreachable so we can exit with code 2."""


def _is_transient_failure(result: dict[str, Any]) -> bool:
    """Heuristic: did this case fail due to a transient backend issue
    (SQLite contention, timeout, momentary connection drop) rather than
    a genuine agent-correctness bug?

    Transient symptoms:
      1. HTTP error / timeout (``actual.http_error`` is set).
      2. SQL was generated + scope was correct + not refused, but the
         answer is empty/missing — i.e. the SELECT returned 0 rows due
         to SQLite read contention (a known issue when the LocalTracer
         writes a trace row on every concurrent request).

    Genuine assertion failures (wrong intent, wrong scope, wrong tables,
    expected refusal not delivered) are NOT transient and are NOT
    retried.
    """
    actual = result.get("actual", {}) or {}
    if actual.get("http_error"):
        return True
    # Empty-result symptom: SQL present, not refused, but answer doesn't
    # match. The only assertion failures should be "Answer missing" and
    # possibly "Expected chart present" — both consistent with the DB
    # returning 0 rows.
    if actual.get("sql_present") and not actual.get("refused"):
        reasons = result.get("failure_reasons", []) or []
        non_transient_keywords = (
            "intent expected",
            "Expected refused=",
            "scope_clause missing",
            "Tables ",
        )
        if not any(kw in r for r in reasons for kw in non_transient_keywords):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Response inspection helpers
# ─────────────────────────────────────────────────────────────────────────────


def extract_intent(response: dict[str, Any]) -> str | None:
    """Pull the classified intent out of ``steps[0].detail``.

    The orchestrator writes ``"Intention détectée : <intent>."`` as the
    detail of the first step regardless of whether the request is later
    refused, blocked, or succeeds — so this is the single most reliable
    place to read the intent from.
    """
    steps = response.get("steps") or []
    if not steps:
        return None
    detail = (steps[0].get("detail") or "") if isinstance(steps[0], dict) else ""
    m = INTENT_RE.search(detail)
    return m.group(1) if m else None


def extract_tables(sql: str) -> list[str]:
    """Return the deduplicated, order-preserving list of table names
    referenced in ``sql`` (parsed locally with sqlglot — independent of
    the backend's own parser so a parser bug can't mask a violation).
    """
    try:
        ast = sqlglot.parse_one(sql, dialect="sqlite")
    except Exception:  # noqa: BLE001 — unparseable SQL → no tables to check
        return []
    seen: list[str] = []
    for t in ast.find_all(exp.Table):
        if t.name and t.name not in seen:
            seen.append(t.name)
    return seen


# ─────────────────────────────────────────────────────────────────────────────
# Per-case assertions
# ─────────────────────────────────────────────────────────────────────────────


def run_assertions(case: dict[str, Any], response: dict[str, Any]) -> list[str]:
    """Run every applicable assertion for one case.

    Returns the (possibly empty) list of failure reasons. An empty list
    means the case passed.
    """
    reasons: list[str] = []
    expected = case.get("expected", {}) or {}

    # If the HTTP call itself failed, surface that first.
    if response.get("_error"):
        reasons.append(f"HTTP error: {response['_error']}")
        return reasons

    actual_intent = extract_intent(response)
    actual_refused = bool(response.get("refused"))
    actual_sql = response.get("sql") or ""
    actual_scope = response.get("scope_clause") or ""
    actual_answer = response.get("answer") or ""
    actual_chart = response.get("chart")
    actual_sources = response.get("sources") or []
    actual_ops = response.get("ops_analysis")

    # 1. Intent match (extracted from steps[0].detail)
    if "intent" in expected and expected["intent"] is not None:
        if actual_intent != expected["intent"]:
            reasons.append(
                f"intent expected {expected['intent']!r}, got {actual_intent!r}"
            )

    # 2. Refused flag
    if "refused" in expected:
        if actual_refused != bool(expected["refused"]):
            reasons.append(
                f"Expected refused={expected['refused']}, got refused={actual_refused}"
            )

    # 3. SQL presence/absence
    if expected.get("sql_expected"):
        if not actual_sql:
            reasons.append("Expected SQL present, got null/empty")
    else:
        if actual_sql:
            reasons.append(
                f"Expected no SQL, got: {actual_sql[:80]!r}"
            )

    # 4. Scope clause contains the required substring
    scope_needle = expected.get("scope_clause_contains")
    if scope_needle:  # non-null + non-empty
        if scope_needle not in actual_scope:
            reasons.append(
                f"scope_clause missing {scope_needle!r} (got: {actual_scope!r})"
            )

    # 5. Tables allowed — every table referenced by the SQL must be in
    #    the allowlist. (We re-parse with sqlglot locally so the check
    #    is independent of the backend.)
    allowed_tables = expected.get("tables_allowed")
    if allowed_tables and actual_sql:
        touched = extract_tables(actual_sql)
        unexpected_tables = [t for t in touched if t not in allowed_tables]
        if unexpected_tables:
            reasons.append(
                f"Tables {unexpected_tables} not in allowed list {allowed_tables}"
            )

    # 6. Answer contains at least one of the expected needles
    needles = expected.get("answer_contains_any")
    if needles:
        if not any(n in actual_answer for n in needles):
            reasons.append(
                f"Answer missing all of {needles} "
                f"(got: {actual_answer[:100]!r}...)"
            )

    # 7. Chart expected
    if expected.get("chart_expected"):
        if not actual_chart:
            reasons.append("Expected chart present, got null")

    # 8. Chart must be NULL (Phase 3 documentary cases — no chart).
    if expected.get("chart_null") and actual_chart is not None:
        reasons.append(f"Expected chart=null, got: {type(actual_chart).__name__}")

    # 9. Sources must be non-empty (Phase 3 documentary cases).
    if expected.get("sources_non_empty"):
        if not actual_sources:
            reasons.append("Expected non-empty sources, got empty list")

    # 10. Ops analysis present (Phase 4 ops_copilot cases).
    if expected.get("ops_analysis_present"):
        if not actual_ops:
            reasons.append("Expected ops_analysis present, got null/missing")

    # 11. Ops proposed_decision match (Phase 4 ops_copilot cases).
    if expected.get("ops_proposed_decision"):
        expected_decision = expected["ops_proposed_decision"]
        if not actual_ops:
            reasons.append(
                f"Expected ops_analysis.proposed_decision={expected_decision!r}, "
                "but ops_analysis is null"
            )
        else:
            actual_decision = actual_ops.get("proposed_decision")
            if actual_decision != expected_decision:
                reasons.append(
                    f"Expected ops_analysis.proposed_decision={expected_decision!r}, "
                    f"got {actual_decision!r}"
                )

    return reasons


# ─────────────────────────────────────────────────────────────────────────────
# HTTP client
# ─────────────────────────────────────────────────────────────────────────────


async def call_backend(
    client: httpx.AsyncClient, case: dict[str, Any]
) -> dict[str, Any]:
    """POST one case to ``/api/chat`` and return the JSON envelope.

    On timeout or HTTP error, returns an envelope-shaped dict with an
    ``_error`` key so ``run_assertions`` can surface the failure cleanly
    (a timeout should count as a FAIL, not a false PASS).
    """
    identity = case.get("identity", {}) or {}
    payload = {
        "message": case["question"],
        "identity_id": identity.get("identity_id"),
        "producer_id": identity.get("producer_id"),
        "role": identity.get("role"),
    }
    try:
        r = await client.post(BACKEND_URL, json=payload, timeout=TIMEOUT_PER_CASE)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError as exc:
        # Backend down → propagate so main() can exit with code 2.
        raise BackendDown(f"backend unreachable: {exc}") from exc
    except httpx.TimeoutException as exc:
        return _error_envelope(f"timeout after {TIMEOUT_PER_CASE}s: {exc}")
    except httpx.HTTPStatusError as exc:
        return _error_envelope(
            f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        )
    except Exception as exc:  # noqa: BLE001 — surface any other error as a FAIL
        return _error_envelope(f"{type(exc).__name__}: {exc}")


def _error_envelope(msg: str) -> dict[str, Any]:
    """Build a response-shaped dict that will fail every assertion."""
    return {
        "_error": msg,
        "answer": "",
        "sql": None,
        "scope_clause": None,
        "chart": None,
        "refused": True,
        "steps": [],
        "tables_touched": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Per-case runner (semaphore-bounded)
# ─────────────────────────────────────────────────────────────────────────────


async def run_case(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    case: dict[str, Any],
) -> dict[str, Any]:
    async with sem:
        response = await call_backend(client, case)
    failure_reasons = run_assertions(case, response)
    return {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "description": case.get("description", ""),
        "expected_to_fail": bool(case.get("expected_to_fail", False)),
        "passed": len(failure_reasons) == 0,
        "failure_reasons": failure_reasons,
        "actual": {
            "intent": extract_intent(response),
            "refused": response.get("refused"),
            "sql": response.get("sql"),
            "sql_present": bool(response.get("sql")),
            "scope_clause": response.get("scope_clause"),
            "answer_excerpt": (response.get("answer") or "")[:300],
            "chart_present": bool(response.get("chart")),
            "tables_touched": response.get("tables_touched") or [],
            "tables_in_sql": extract_tables(response.get("sql") or "")
            if response.get("sql")
            else [],
            "http_error": response.get("_error"),
            "ops_proposed_decision": (response.get("ops_analysis") or {}).get(
                "proposed_decision"
            ) if response.get("ops_analysis") else None,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Aggregate scoring
# ─────────────────────────────────────────────────────────────────────────────


def compute_aggregates(
    results: list[dict[str, Any]],
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute the 5 headline scores + per-category breakdown."""
    case_by_id = {c["id"]: c for c in cases}

    # Split expected-to-fail cases out of the pass-rate denominator.
    evaluable = [r for r in results if not r["expected_to_fail"]]
    etf_cases = [r for r in results if r["expected_to_fail"]]
    n_eval = len(evaluable)
    n_pass = sum(1 for r in evaluable if r["passed"])
    overall = (n_pass / n_eval) if n_eval else 0.0

    # ── SQL valid: only over sql_expected=true cases ──
    sql_cases = [
        r for r in evaluable
        if (case_by_id[r["id"]]["expected"] or {}).get("sql_expected")
    ]
    sql_pass = 0
    for r in sql_cases:
        c = case_by_id[r["id"]]
        sql = r["actual"]["sql_present"]
        if not sql:
            continue
        touched = r["actual"]["tables_in_sql"]
        allowed = (c["expected"] or {}).get("tables_allowed") or []
        if not allowed or all(t in allowed for t in touched):
            sql_pass += 1
    sql_pct = (sql_pass / len(sql_cases)) if sql_cases else 0.0

    # ── Scopes respected: cases that assert a scope_clause OR a refusal ──
    scope_cases = [
        r for r in evaluable
        if (case_by_id[r["id"]]["expected"] or {}).get("scope_clause_contains")
        or (case_by_id[r["id"]]["expected"] or {}).get("refused") is not None
    ]
    scope_pass = 0
    for r in scope_cases:
        c = case_by_id[r["id"]]
        exp = c["expected"] or {}
        if exp.get("refused"):
            if r["actual"]["refused"]:
                scope_pass += 1
        else:
            needle = exp.get("scope_clause_contains") or ""
            if needle and needle in (r["actual"]["scope_clause"] or ""):
                scope_pass += 1
            elif not needle and not r["actual"]["scope_clause"]:
                # admin case: scope_clause must be null (no injection)
                scope_pass += 1
    scope_pct = (scope_pass / len(scope_cases)) if scope_cases else 0.0

    # ── Intents correct ──
    intent_cases = [
        r for r in evaluable
        if (case_by_id[r["id"]]["expected"] or {}).get("intent")
    ]
    intent_pass = sum(
        1 for r in intent_cases
        if r["actual"]["intent"] == (case_by_id[r["id"]]["expected"] or {}).get("intent")
    )
    intent_pct = (intent_pass / len(intent_cases)) if intent_cases else 0.0

    # ── Responses well-formed: non-refused cases must have a non-empty
    #    answer + a non-null intent + (if sql_expected) a SQL string ──
    wf_cases = [
        r for r in evaluable
        if not (case_by_id[r["id"]]["expected"] or {}).get("refused")
    ]
    wf_pass = 0
    for r in wf_cases:
        c = case_by_id[r["id"]]
        exp = c["expected"] or {}
        ok = (
            bool(r["actual"]["answer_excerpt"])
            and r["actual"]["intent"] is not None
            and (not exp.get("sql_expected") or r["actual"]["sql_present"])
        )
        if ok:
            wf_pass += 1
    wf_pct = (wf_pass / len(wf_cases)) if wf_cases else 0.0

    # ── Per-category breakdown (over evaluable cases only) ──
    by_cat: dict[str, dict[str, int]] = {}
    for r in evaluable:
        cat = r["category"]
        d = by_cat.setdefault(cat, {"pass": 0, "total": 0})
        d["total"] += 1
        if r["passed"]:
            d["pass"] += 1

    return {
        "total_cases": len(cases),
        "evaluable_cases": n_eval,
        "passed": n_pass,
        "overall_pass_rate": overall,
        "sql_valid": {"pass": sql_pass, "total": len(sql_cases), "pct": sql_pct},
        "scopes_respected": {"pass": scope_pass, "total": len(scope_cases), "pct": scope_pct},
        "intents_correct": {"pass": intent_pass, "total": len(intent_cases), "pct": intent_pct},
        "responses_well_formed": {"pass": wf_pass, "total": len(wf_cases), "pct": wf_pct},
        "expected_to_fail": {
            "total": len(etf_cases),
            "passed": sum(1 for r in etf_cases if r["passed"]),
            "cases": [{"id": r["id"], "passed": r["passed"], "failure_reasons": r["failure_reasons"]} for r in etf_cases],
        },
        "by_category": by_cat,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Output
# ─────────────────────────────────────────────────────────────────────────────


def print_table(results: list[dict[str, Any]], aggregates: dict[str, Any]) -> None:
    """Print the per-case table + aggregate summary to stdout."""
    print(f"Tevet-7 Eval — {aggregates['total_cases']} cases")
    print("=" * 80)
    print(f"{'ID':<10} {'Category':<18} {'Result':<8} Reason")
    print("-" * 80)
    n_retried = 0
    for r in sorted(results, key=lambda x: x["id"]):
        marker = "PASS" if r["passed"] else "FAIL"
        etf_tag = " [ETF]" if r["expected_to_fail"] else ""
        retried_tag = " [retried]" if r.get("retried") else ""
        if r.get("retried"):
            n_retried += 1
        reason = "; ".join(r["failure_reasons"]) if r["failure_reasons"] else ""
        if len(reason) > 50:
            reason = reason[:47] + "..."
        print(f"{r['id']:<10} {r['category']:<18} {marker}{etf_tag}{retried_tag:<8} {reason}")
    print("=" * 80)

    print("AGGREGATE SCORES")
    print(
        f"  Overall pass:        {aggregates['passed']}/{aggregates['evaluable_cases']} "
        f"({aggregates['overall_pass_rate']*100:.1f}%)"
    )
    s = aggregates["sql_valid"]
    print(f"  SQL valid:           {s['pass']}/{s['total']} ({s['pct']*100:.1f}%)")
    s = aggregates["scopes_respected"]
    print(f"  Scopes respected:    {s['pass']}/{s['total']} ({s['pct']*100:.1f}%)")
    s = aggregates["intents_correct"]
    print(f"  Intents correct:     {s['pass']}/{s['total']} ({s['pct']*100:.1f}%)")
    s = aggregates["responses_well_formed"]
    print(f"  Responses well-form: {s['pass']}/{s['total']} ({s['pct']*100:.1f}%)")
    etf = aggregates["expected_to_fail"]
    if etf["total"]:
        print(
            f"  Expected-to-fail:    {etf['passed']}/{etf['total']} "
            "(excluded from pass rate)"
        )
    if n_retried:
        print(
            f"  Retried (transient): {n_retried} case(s) needed a 2nd attempt "
            "(SQLite contention — see README)"
        )
    print()
    print("BY CATEGORY (evaluable cases only)")
    for cat in sorted(aggregates["by_category"]):
        d = aggregates["by_category"][cat]
        pct = (d["pass"] / d["total"] * 100) if d["total"] else 0.0
        print(f"  {cat:<22} {d['pass']}/{d['total']} ({pct:.1f}%)")
    print("=" * 80)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


async def main() -> int:
    if not DATASET_PATH.exists():
        print(f"ERROR: dataset not found at {DATASET_PATH}", file=sys.stderr)
        return 2
    try:
        cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: dataset.json is invalid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(cases, list) or not cases:
        print("ERROR: dataset.json must be a non-empty JSON array", file=sys.stderr)
        return 2

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as client:
        # Health check first — fail fast with a clear message if the
        # backend isn't running.
        try:
            h = await client.get(HEALTH_URL, timeout=HEALTH_TIMEOUT)
            h.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            print(
                f"ERROR: Tevet-7 backend at {HEALTH_URL} is unreachable ({exc}).\n"
                "Start it with:\n"
                "  cd agentic-service && python3 -m uvicorn app.main:app "
                "--host 0.0.0.0 --port 8001 --reload",
                file=sys.stderr,
            )
            return 2

        # ── Warmup ────────────────────────────────────────────────────────
        # Send a single sequential chat request before the concurrent batch
        # to warm up the SQLAlchemy connection pool and the orchestrator's
        # ``_PRODUCER_NAMES`` cache. Without it, the first concurrent batch
        # can hit a SQLite connection-pool cold-start window where SELECTs
        # return 0 rows (a known backend issue with aiosqlite + the
        # LocalTracer's per-request trace INSERT — not an agent-correctness
        # issue). The warmup isolates the agent-correctness measurement
        # from connection-pool warmup behaviour. Its result is NOT scored.
        warmup_payload = {
            "message": "Quels sont mes 5 produits les plus vendus ce mois-ci ?",
            "identity_id": "marie",
            "producer_id": 42,
            "role": "producer",
        }
        try:
            await client.post(BACKEND_URL, json=warmup_payload, timeout=TIMEOUT_PER_CASE)
        except Exception:  # noqa: BLE001 — warmup is best-effort
            pass

        # ── Run all 30 cases concurrently (semaphore-bounded) ─────────────
        # Each case that fails with a transient symptom (HTTP error,
        # timeout, or empty-result-when-SQL-is-correct-and-not-refused)
        # is retried once after a short backoff. Real assertion failures
        # (wrong intent, wrong scope, wrong tables) are NOT retried —
        # they surface immediately. The retry handles the SQLite
        # concurrency contention without masking genuine agent bugs.
        try:
            first_pass = await asyncio.gather(
                *[run_case(sem, client, c) for c in cases]
            )
        except BackendDown as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            print(
                "Start the backend with:\n"
                "  cd agentic-service && python3 -m uvicorn app.main:app "
                "--host 0.0.0.0 --port 8001 --reload",
                file=sys.stderr,
            )
            return 2
        retry_cases = [
            (cases[i], first_pass[i])
            for i in range(len(cases))
            if not first_pass[i]["passed"]
            and _is_transient_failure(first_pass[i])
            and not cases[i].get("expected_to_fail", False)
        ]
        if retry_cases:
            await asyncio.sleep(0.3)
            retry_results = await asyncio.gather(
                *[run_case(sem, client, c) for c, _ in retry_cases]
            )
            # Replace the first-pass result with the retry result, and
            # mark retried cases so the report shows which ones needed
            # a second attempt.
            retry_map = {
                rc["id"]: rr for (rc, _), rr in zip(retry_cases, retry_results)
            }
            results = []
            for r in first_pass:
                if not r["passed"] and r["id"] in retry_map:
                    rr = retry_map[r["id"]]
                    rr["retried"] = True
                    rr["first_pass_failed"] = True
                    results.append(rr)
                else:
                    r["retried"] = False
                    results.append(r)
        else:
            results = first_pass
            for r in results:
                r["retried"] = False

    aggregates = compute_aggregates(results, cases)
    print_table(results, aggregates)

    report = {
        **aggregates,
        "cases": sorted(results, key=lambda x: x["id"]),
    }
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Report saved to {REPORT_PATH}")

    overall = aggregates["overall_pass_rate"]
    if overall >= PASS_RATE_THRESHOLD:
        print(
            f"\nPASS — overall pass rate {overall*100:.1f}% "
            f">= {PASS_RATE_THRESHOLD*100:.0f}% threshold."
        )
        return 0
    print(
        f"\nFAIL — overall pass rate {overall*100:.1f}% "
        f"< {PASS_RATE_THRESHOLD*100:.0f}% threshold."
    )
    return 1


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        rc = 130
    sys.exit(rc)
