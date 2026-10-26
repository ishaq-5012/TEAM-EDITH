#!/usr/bin/env bash
# VerifyFlow smoke test, for pre-release (staging) and post-release (production) checks. Read-only, except that
# the optional sign-in check creates and ends one session for the smoke account.
#
#   BASE_URL=https://verifyflow.example.org deploy/smoke.sh
#   BASE_URL=https://verifyflow.example.org SMOKE_EMAIL=smoke@yourorg.example SMOKE_PASSWORD=... deploy/smoke.sh
#
# SMOKE_EMAIL / SMOKE_PASSWORD: a dedicated, least-privilege account (role: auditor) that you create. Pass the
# password from a secret store; it is never printed. Exit code: number of failed checks (0 = all passed).
set -uo pipefail

BASE="${BASE_URL:?set BASE_URL, e.g. https://verifyflow.example.org}"
BASE="${BASE%/}"
API="$BASE/api/v1"
failures=0
jar="$(mktemp)"; hdrs="$(mktemp)"; body="$(mktemp)"
trap 'rm -f "$jar" "$hdrs" "$body"' EXIT

pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; failures=$((failures + 1)); }
check() { if eval "$2"; then pass "$1"; else fail "$1"; fi; }
req() {  # req METHOD URL [curl args...] -> status code; headers in $hdrs, body in $body
  local method="$1" url="$2"; shift 2
  curl -sS -o "$body" -D "$hdrs" -w '%{http_code}' -X "$method" -b "$jar" -c "$jar" "$@" "$url" 2>/dev/null || echo 000
}
header() { grep -i "^$1:" "$hdrs" | head -1 | cut -d' ' -f2- | tr -d '\r'; }

echo "Smoke test against $BASE"
# Right after a deploy the API may still be starting: wait up to SMOKE_WAIT_SECONDS for /health to answer.
for _ in $(seq 1 "${SMOKE_WAIT_SECONDS:-60}"); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' "$API/health" 2>/dev/null)" = 200 ] && break
  sleep 1
done

echo "Health"
s=$(req GET "$API/health")
check "GET /health is 200 and ok" '[ "$s" = 200 ] && grep -q "\"status\":\"ok\"" "$body"'
check "every response carries X-Request-ID" '[ -n "$(header X-Request-ID)" ]'
s=$(req GET "$API/health/ready")
check "GET /health/ready is 200 (database, migrations, storage)" '[ "$s" = 200 ]'
check "schema is at the latest migration" 'grep -q "\"migrations\":\"ok\"" "$body"'
check "private storage is writable" 'grep -q "\"storage\":\"ok\"" "$body"'
check "processing runs in worker mode" 'grep -q "\"mode\":\"worker\"" "$body"'
check "no interrupted processing jobs" 'grep -q "\"stale_running\":0" "$body"'

echo "Exposure"
s=$(req GET "$BASE/api/docs");          check "interactive API docs are not served" '[ "$s" = 404 ]'
s=$(req GET "$BASE/api/openapi.json");  check "OpenAPI schema is not served" '[ "$s" = 404 ]'
s=$(req GET "$API/applications");       check "anonymous API access is refused (401)" '[ "$s" = 401 ]'
s=$(req GET "$API/audit/events");       check "anonymous audit access is refused (401)" '[ "$s" = 401 ]'
s=$(req POST "$API/auth/login" -H 'Content-Type: application/json' -H 'Origin: https://attacker.example' \
      --data '{"email":"nobody@example.org","password":"not-a-real-password"}')
check "cross-site sign-in attempt is rejected (403 origin_rejected)" '[ "$s" = 403 ] && grep -q origin_rejected "$body"'

if [[ "$BASE" == https://* ]]; then
  echo "HTTPS and headers"
  s=$(req GET "$BASE/")
  check "SPA is served (200)" '[ "$s" = 200 ]'
  check "Strict-Transport-Security is set" '[ -n "$(header Strict-Transport-Security)" ]'
  check "Content-Security-Policy restricts scripts to self" 'header Content-Security-Policy | grep -q "script-src '"'"'self'"'"'"'
  check "X-Content-Type-Options is nosniff" '[ "$(header X-Content-Type-Options)" = nosniff ]'
  check "frames are refused (frame-ancestors none)" 'header Content-Security-Policy | grep -q "frame-ancestors '"'"'none'"'"'"'
  plain="http://${BASE#https://}"
  s=$(curl -sS -o /dev/null -w '%{http_code}' "$plain/" 2>/dev/null || echo 000)
  check "plain HTTP redirects to HTTPS (301)" '[ "$s" = 301 ]'
else
  echo "HTTPS and headers: skipped (BASE_URL is not https://)"
fi

if [ -n "${SMOKE_EMAIL:-}" ] && [ -n "${SMOKE_PASSWORD:-}" ]; then
  echo "Sign-in (smoke account)"
  payload=$(printf '{"email":"%s","password":"%s"}' "$SMOKE_EMAIL" "$SMOKE_PASSWORD")
  s=$(req POST "$API/auth/login" -H 'Content-Type: application/json' -H "Origin: $BASE" --data "$payload")
  unset payload
  check "sign-in succeeds" '[ "$s" = 200 ]'
  cookie=$(grep -i '^set-cookie: __Host-vf_session=' "$hdrs" | head -1)
  check "session cookie is __Host-, Secure, HttpOnly, SameSite" \
    'echo "$cookie" | grep -qi "secure" && echo "$cookie" | grep -qi "httponly" && echo "$cookie" | grep -qi "samesite"'
  csrf=$(grep -o '"csrf_token":"[^"]*"' "$body" | cut -d'"' -f4)
  s=$(req GET "$API/auth/me");                     check "session works (GET /auth/me)" '[ "$s" = 200 ]'
  s=$(req POST "$API/auth/logout" -H "Origin: $BASE");  check "state change without CSRF token is refused (403)" '[ "$s" = 403 ]'
  s=$(req POST "$API/auth/logout" -H "Origin: $BASE" -H "X-CSRF-Token: $csrf"); check "sign-out succeeds" '[ "$s" = 204 ] || [ "$s" = 200 ]'
  s=$(req GET "$API/auth/me");                     check "session is gone after sign-out (401)" '[ "$s" = 401 ]'
else
  echo "Sign-in: skipped (set SMOKE_EMAIL and SMOKE_PASSWORD for a dedicated smoke account)"
fi

echo
if [ "$failures" -eq 0 ]; then echo "All smoke checks passed."; else echo "$failures smoke check(s) FAILED."; fi
exit "$failures"
