#!/usr/bin/env python3
"""E2E test of the multi-tenant onboarding flow: wizard -> connector -> agent.

Steps (mirrors the 4-step frontend wizard):
  1. Signup a fresh user
  2. Create a workspace (tenant)
  3. Onboarding: connect CSV -> detect schema -> save schema -> save roles -> complete
  4. Chat as the new tenant: analytical questions on the uploaded CSV
  5. Negative checks: chat BEFORE onboarding must refuse; scoping must hold
"""
import io
import json
import sys
import time
import httpx

BASE = "http://127.0.0.1:8001"
STAMP = int(time.time())
EMAIL = f"e2e-{STAMP}@example.com"
SLUG = f"e2e-fleet-{STAMP}"

CSV = """delivery_id,driver_id,city,distance_km,price_eur,delivered_at
1,7,Lyon,12.5,18.90,2026-06-01
2,7,Lyon,8.2,12.50,2026-06-02
3,9,Paris,22.1,31.00,2026-06-02
4,7,Marseille,15.0,21.75,2026-06-03
5,9,Paris,5.4,9.90,2026-06-04
6,7,Lyon,18.3,25.40,2026-06-05
7,9,Lille,30.2,44.10,2026-06-06
8,7,Lyon,9.9,14.00,2026-06-07
"""

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(f"{name}: {detail}")


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=60)

    print("== 1. Signup ==")
    r = c.post("/api/auth/signup", json={"email": EMAIL, "password": "s3cure-pass!", "name": "E2E Owner"})
    check("signup 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    token0 = r.json()["token"]

    print("== 2. Create workspace ==")
    r = c.post("/api/tenants", json={"name": "E2E Fleet", "slug": SLUG},
               headers={"Authorization": f"Bearer {token0}"})
    check("create tenant 200", r.status_code == 200, f"{r.status_code} {r.text[:300]}")
    body = r.json()
    tenant_id = body["tenant"]["id"]
    token = body["token"]  # JWT with the new tenant context
    hdr = {"Authorization": f"Bearer {token}"}
    print(f"  tenant_id={tenant_id}")

    print("== 2b. Chat BEFORE onboarding must refuse cleanly ==")
    r = c.post("/api/chat", json={"message": "Combien de livraisons ce mois ?"}, headers=hdr)
    pre = r.json() if r.status_code == 200 else {}
    check("pre-onboarding chat handled", r.status_code in (200, 400, 409),
          f"{r.status_code} {r.text[:200]}")
    check("pre-onboarding: no SQL executed", not (pre.get("sql_used") or pre.get("sql")),
          str(pre)[:200])

    print("== 3a. Connect CSV ==")
    r = c.post(
        f"/api/tenants/{tenant_id}/onboarding/connect",
        data={"connector_type": "csv"},
        files={"file": ("deliveries.csv", io.BytesIO(CSV.encode()), "text/csv")},
        headers=hdr,
    )
    check("connect 200 + ok", r.status_code == 200 and r.json().get("ok"),
          f"{r.status_code} {r.text[:300]}")

    print("== 3b. Detect schema ==")
    r = c.post(f"/api/tenants/{tenant_id}/onboarding/detect-schema", headers=hdr)
    check("detect-schema 200", r.status_code == 200, f"{r.status_code} {r.text[:300]}")
    detected = r.json()
    schema_config = detected.get("schema_config") or detected.get("schema") or detected
    tables = schema_config.get("tables", [])
    check("1 table detected", len(tables) == 1, json.dumps(detected)[:300])
    cols = [col["name"] for col in tables[0].get("columns", [])] if tables else []
    check("columns detected", set(cols) >= {"driver_id", "city", "price_eur"}, str(cols))

    print("== 3c. Save schema (select tables) ==")
    r = c.post(f"/api/tenants/{tenant_id}/onboarding/save-schema",
               json={"schema_config": schema_config}, headers=hdr)
    check("save-schema 200", r.status_code == 200, f"{r.status_code} {r.text[:300]}")

    print("== 3d. Save roles (driver scoped by driver_id, admin unscoped) ==")
    r = c.post(f"/api/tenants/{tenant_id}/onboarding/save-roles",
               json={"roles_config": {
                   "driver": {"scope_column": "driver_id"},
                   "admin": {"scope_column": None},
               }}, headers=hdr)
    check("save-roles 200", r.status_code == 200, f"{r.status_code} {r.text[:300]}")

    print("== 3e. Complete ==")
    r = c.post(f"/api/tenants/{tenant_id}/onboarding/complete", headers=hdr)
    check("complete 200 + onboarded", r.status_code == 200 and r.json().get("onboarded"),
          f"{r.status_code} {r.text[:300]}")

    r = c.get(f"/api/tenants/{tenant_id}/onboarding/status", headers=hdr)
    check("status shows onboarded", r.status_code == 200 and r.json().get("onboarded") is True,
          f"{r.status_code} {r.text[:300]}")

    print("== 4. Agent on the new tenant's data (admin = tenant owner) ==")
    r = c.post("/api/chat", json={"message": "Combien de livraisons au total ?"}, headers=hdr)
    check("chat count 200", r.status_code == 200, f"{r.status_code} {r.text[:300]}")
    resp = r.json() if r.status_code == 200 else {}
    sql = resp.get("sql") or resp.get("sql_used") or ""
    answer = resp.get("answer") or ""
    print(f"  sql: {sql}")
    print(f"  answer: {answer[:160]}")
    table_name = tables[0]["name"]
    check("SQL generated on tenant table", table_name.lower() in sql.lower(), sql)
    check("COUNT query (not SUM of an id)", "count(*)" in sql.lower(), sql)
    check("count answer contains 8", "8" in answer, answer[:200])

    r = c.post("/api/chat", json={"message": "Quel est le total des price_eur ?"}, headers=hdr)
    resp = r.json() if r.status_code == 200 else {}
    sql = resp.get("sql") or resp.get("sql_used") or ""
    answer = resp.get("answer") or ""
    print(f"  sql: {sql}")
    print(f"  answer: {answer[:160]}")
    check("sum chat 200", r.status_code == 200, f"{r.status_code}")
    check("SUM SQL on price_eur", "sum" in sql.lower() and "price_eur" in sql.lower(), sql)
    # 18.90+12.50+31.00+21.75+9.90+25.40+44.10+14.00 = 177.55
    check("sum answer contains 177.55", "177.55" in answer.replace(",", "."), answer[:200])

    print("== 5. Demo tenant unaffected (dp still answers) ==")
    r = c.post("/api/auth/login", json={"email": "marie@tevet7.dev", "password": "tevet7demo"})
    check("marie login 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    mtoken = r.json()["token"]
    r = c.post("/api/chat", json={"message": "Quels sont mes 5 produits les plus vendus ce mois-ci ?"},
               headers={"Authorization": f"Bearer {mtoken}"})
    resp = r.json() if r.status_code == 200 else {}
    check("dp chat still works", r.status_code == 200 and "producer_id = 42" in (resp.get("sql") or ""),
          f"{r.status_code} {str(resp)[:200]}")

    print()
    if failures:
        print(f"E2E RESULT: {len(failures)} FAILURE(S)")
        for f in failures:
            print(" -", f)
        return 1
    print("E2E RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
