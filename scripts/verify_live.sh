#!/usr/bin/env bash
# Check a live HTTPS deployment; does not execute missions or require secrets.
set -Eeuo pipefail
URL="${1:?Usage: bash scripts/verify_live.sh https://PUBLIC_IP.sslip.io}"
[[ "$URL" == https://* ]] || { echo 'ERROR: URL must start with https://' >&2; exit 2; }
for PATH_PART in / /health /api/agents /api/sample; do
  response_code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "${URL%/}${PATH_PART}") || {
    echo "FAIL: HTTPS request failed: $PATH_PART" >&2; exit 1;
  }
  [[ "$response_code" == 200 ]] || { echo "FAIL: ${PATH_PART} returned HTTP $response_code" >&2; exit 1; }
  echo "PASS HTTP 200: ${PATH_PART}"
done
curl -fsS --max-time 15 "${URL%/}/health" | python3 -m json.tool
printf '\nNOTE: Health endpoints passing does NOT prove live Vultr inference or Docker isolation.\n'
printf 'Run an authenticated mission and containment probe on the VM for final proof.\n'
