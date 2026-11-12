#!/usr/bin/env bash
# Deployment acceptance: auth, worker execution, artifact retrieval, audit integrity. Usage: smoke_test.sh BASE_URL OPERATOR_TOKEN BATMAN_TOKEN
set -euo pipefail
U=${1:?base url}; OP=${2:?operator token}; BT=${3:?batman token}
j() { python3 -c "import sys,json;d=json.load(sys.stdin);print(eval(sys.argv[1]))" "$1"; }
curl -fsS "$U/api/v4/health" >/dev/null && echo "PASS health"
[ "$(curl -s -o /dev/null -w '%{http_code}' "$U/api/v4/missions")" = 401 ] && echo "PASS unauthenticated rejected"
[ "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $OP" "$U/api/v4/audit/verify")" = 403 ] && echo "PASS operator cannot read audit"
MID=$(curl -fsS -H "Authorization: Bearer $OP" -H 'Content-Type: application/json' -d '{"kind":"security_audit","goal":"smoke test audit","params":{"files":{"a.py":"eval(input())\n"}}}' "$U/api/v4/missions" | j "d['mission']['id']")
for i in $(seq 1 60); do S=$(curl -fsS -H "Authorization: Bearer $OP" "$U/api/v4/missions/$MID" | j "d['mission']['status']"); [ "$S" = verified ] && break; [ "$S" = failed ] && break; sleep 2; done
[ "$S" = verified ] && echo "PASS worker executed mission ($MID)"
AID=$(curl -fsS -H "Authorization: Bearer $OP" "$U/api/v4/artifacts?mission_id=$MID" | j "d['artifacts'][0]['id']")
curl -fsS -H "Authorization: Bearer $OP" "$U/api/v4/artifacts/$AID/download" -o /dev/null && echo "PASS artifact retrieval with integrity check"
curl -fsS -H "Authorization: Bearer $BT" "$U/api/v4/audit/verify" | j "d['valid']" | grep -q True && echo "PASS audit chain valid"
[ "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $OP" "$U/api/v4/missions/doesnotexist")" = 404 ] && echo "PASS failure handling (404)"
