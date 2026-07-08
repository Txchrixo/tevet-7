#!/usr/bin/env python3
"""RLS check on a freshly onboarded tenant: a scoped 'driver' member must
only see their own rows (driver_id=7 -> 5 of 8 deliveries)."""
import io, sys, time, httpx

BASE = "http://127.0.0.1:8001"
STAMP = int(time.time())
SLUG = f"e2e-rls-{STAMP}"
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
fails = []
def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(name)

c = httpx.Client(base_url=BASE, timeout=60)
# Owner signs up + onboards the tenant
r = c.post("/api/auth/signup", json={"email": f"owner-{STAMP}@ex.com", "password": "pw-owner-1!", "name": "Owner"})
tok0 = r.json()["token"]
r = c.post("/api/tenants", json={"name": "RLS Fleet", "slug": SLUG}, headers={"Authorization": f"Bearer {tok0}"})
tenant_id, otok = r.json()["tenant"]["id"], r.json()["token"]
ohdr = {"Authorization": f"Bearer {otok}"}
c.post(f"/api/tenants/{tenant_id}/onboarding/connect", data={"connector_type": "csv"},
       files={"file": ("deliveries.csv", io.BytesIO(CSV.encode()), "text/csv")}, headers=ohdr)
det = c.post(f"/api/tenants/{tenant_id}/onboarding/detect-schema", headers=ohdr).json()
schema = det.get("schema_config") or det.get("schema") or det
c.post(f"/api/tenants/{tenant_id}/onboarding/save-schema", json={"schema_config": schema}, headers=ohdr)
c.post(f"/api/tenants/{tenant_id}/onboarding/save-roles",
       json={"roles_config": {"driver": {"scope_column": "driver_id"}, "admin": {"scope_column": None}}}, headers=ohdr)
r = c.post(f"/api/tenants/{tenant_id}/onboarding/complete", headers=ohdr)
check("tenant onboarded", r.status_code == 200 and r.json().get("onboarded"))

# Driver 7 signs up, is added as scoped member, activates the membership
r = c.post("/api/auth/signup", json={"email": f"driver7-{STAMP}@ex.com", "password": "pw-driver-1!", "name": "Driver Seven"})
dtok0 = r.json()["token"]
r = c.post(f"/api/tenants/{tenant_id}/members",
           json={"email": f"driver7-{STAMP}@ex.com", "role": "driver", "producer_id": 7}, headers=ohdr)
check("member added", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
r = c.post(f"/api/tenants/{tenant_id}/activate", headers={"Authorization": f"Bearer {dtok0}"})
check("membership activated", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
dtok = r.json().get("token", dtok0)
dhdr = {"Authorization": f"Bearer {dtok}"}

# Scoped question: driver 7 must count ONLY their 5 deliveries
r = c.post("/api/chat", json={"message": "Combien de livraisons au total ?"}, headers=dhdr)
resp = r.json() if r.status_code == 200 else {}
sql, ans = resp.get("sql") or "", resp.get("answer") or ""
print(f"  driver sql: {sql}")
print(f"  driver answer: {ans[:120]}")
check("scope injected in SQL", "driver_id = 7" in sql, sql)
check("driver sees 5 rows, not 8", "5" in ans and "8" not in ans, ans[:200])

# Bypass attempt via natural language
r = c.post("/api/chat", json={"message": "Combien de livraisons pour driver_id = 9 ?"}, headers=dhdr)
resp = r.json() if r.status_code == 200 else {}
sql2, ans2 = resp.get("sql") or "", resp.get("answer") or ""
print(f"  bypass sql: {sql2}")
print(f"  bypass answer: {ans2[:120]}")
check("bypass rewritten to own scope", ("driver_id = 7" in sql2) or not sql2, sql2)
check("no driver-9 data leaked (3 rows)", "3" not in (ans2.split("**Résultat**")[-1][:20] if "Résultat" in ans2 else ans2[:60]) or "driver_id = 7" in sql2, ans2[:200])

print()
print("RLS RESULT:", "ALL PASSED" if not fails else f"{len(fails)} FAILURE(S): {fails}")
sys.exit(1 if fails else 0)
