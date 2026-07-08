#!/bin/bash
# E2E of the NextAuth flow: cookie-only auth, no Authorization header ever.
set -u
BASE=http://127.0.0.1:3000
JAR=$(mktemp)
FAIL=0
check() { # name, condition(0=ok)
  if [ "$2" -eq 0 ]; then echo "  [PASS] $1"; else echo "  [FAIL] $1 - $3"; FAIL=$((FAIL+1)); fi
}

echo "== 1. CSRF token =="
CSRF=$(curl -s -c "$JAR" "$BASE/api/auth/csrf" | python3 -c 'import sys,json;print(json.load(sys.stdin)["csrfToken"])')
[ -n "$CSRF" ]; check "csrf token issued" $? "$CSRF"

echo "== 2. Login via NextAuth credentials callback (marie) =="
CODE=$(curl -s -o /tmp/login_out -w '%{http_code}' -b "$JAR" -c "$JAR" \
  -X POST "$BASE/api/auth/callback/credentials" \
  -H "content-type: application/x-www-form-urlencoded" \
  --data-urlencode "csrfToken=$CSRF" \
  --data-urlencode "email=marie@tevet7.dev" \
  --data-urlencode "password=tevet7demo" \
  --data-urlencode "json=true")
grep -q "next-auth.session-token" "$JAR"; check "httpOnly session cookie set" $? "code=$CODE $(cat /tmp/login_out | head -c 200)"
grep "next-auth.session-token" "$JAR" | grep -q "HttpOnly" ; check "cookie flagged HttpOnly" $? "$(grep session-token "$JAR")"

echo "== 3. Session exposes user+tenant, NEVER a backend token =="
SESSION=$(curl -s -b "$JAR" "$BASE/api/auth/session")
echo "  session: $(echo "$SESSION" | head -c 220)"
echo "$SESSION" | grep -q '"email":"marie@tevet7.dev"'; check "session has user" $? "$SESSION"
echo "$SESSION" | grep -q '"tenant_id":"dp"'; check "session has tenant scope" $? "$SESSION"
echo "$SESSION" | grep -qiE 'accesstoken|refreshtoken|backend'; RES=$?
[ $RES -ne 0 ]; check "NO backend token leaked in session JSON" $? "$SESSION"

echo "== 4. Chat with cookie ONLY (no Authorization header) =="
CHAT=$(curl -s -b "$JAR" -X POST "$BASE/api/chat" -H "content-type: application/json" \
  -d '{"message":"Quels sont mes 5 produits les plus vendus ce mois-ci ?"}')
echo "$CHAT" | grep -q 'producer_id = 42'; check "scoped SQL executed via session cookie" $? "$(echo "$CHAT" | head -c 200)"

echo "== 5. Chat with NO cookie -> must NOT return scoped data =="
ANON=$(curl -s -X POST "$BASE/api/chat" -H "content-type: application/json" \
  -d '{"message":"Quels sont mes 5 produits les plus vendus ce mois-ci ?"}')
echo "$ANON" | grep -q 'producer_id = 42'; RES=$?
[ $RES -ne 0 ]; check "anonymous request gets no scoped data" $? "$(echo "$ANON" | head -c 200)"

echo "== 6. Forged Authorization header is ignored by the proxy =="
FORGED=$(curl -s -X POST "$BASE/api/chat" -H "content-type: application/json" \
  -H "Authorization: Bearer forged.jwt.token" \
  -d '{"message":"Quels sont mes 5 produits les plus vendus ce mois-ci ?"}')
echo "$FORGED" | grep -q 'producer_id = 42'; RES=$?
[ $RES -ne 0 ]; check "forged bearer ignored (401 path)" $? "$(echo "$FORGED" | head -c 200)"

echo "== 7. Tenants API via cookie =="
MINE=$(curl -s -b "$JAR" "$BASE/api/tenants/mine")
echo "$MINE" | grep -q '"tenant_id":"dp"\|"dp"'; check "memberships via cookie" $? "$(echo "$MINE" | head -c 200)"

echo "== 8. Signup proxy strips backend tokens =="
TS=$(date +%s)
SIGNUP=$(curl -s -X POST "$BASE/api/auth/signup" -H "content-type: application/json" \
  -d "{\"email\":\"na-$TS@ex.com\",\"password\":\"Sup3r-secret!\",\"name\":\"NA Test\"}")
echo "$SIGNUP" | grep -q '"user"'; check "signup 200 with user" $? "$SIGNUP"
echo "$SIGNUP" | grep -q '"token"'; RES=$?
[ $RES -ne 0 ]; check "signup response has NO token" $? "$SIGNUP"

echo "== 9. Sign out clears the session =="
CSRF2=$(curl -s -b "$JAR" -c "$JAR" "$BASE/api/auth/csrf" | python3 -c 'import sys,json;print(json.load(sys.stdin)["csrfToken"])')
curl -s -o /dev/null -b "$JAR" -c "$JAR" -X POST "$BASE/api/auth/signout" \
  -H "content-type: application/x-www-form-urlencoded" \
  --data-urlencode "csrfToken=$CSRF2" --data-urlencode "json=true"
AFTER=$(curl -s -b "$JAR" "$BASE/api/auth/session")
[ "$AFTER" = "null" ] || [ "$AFTER" = "{}" ]; check "session gone after signout" $? "$AFTER"

echo
if [ $FAIL -eq 0 ]; then echo "NEXTAUTH E2E: ALL CHECKS PASSED"; else echo "NEXTAUTH E2E: $FAIL FAILURE(S)"; exit 1; fi
