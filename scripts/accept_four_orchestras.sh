#!/usr/bin/env bash
# Run one bounded all-four-orchestra synthetic analysis mission against isolated staging.
# Owner-invoked from GitHub Actions; no production endpoint, no Docker, no paid inference.
set -Eeuo pipefail
umask 077
test "$(id -un)" = gothamdeploy || exit 2
BASE="$HOME/gotham-v4-staging"
ENVFILE="$BASE/staging.env"
test -f "$ENVFILE" || { echo "BLOCKED: staging has not been deployed"; exit 2; }
set -a
source "$ENVFILE"
set +a
URL="http://127.0.0.1:8001"
curl -fsS --max-time 5 "$URL/api/v4/health" >/dev/null
read -r -d '' PAYLOAD <<'JSON' || true
{"kind":"orchestra","goal":"Produce a bounded, evidence-honest four-domain analysis of synthetic research, code, defensive logs and a disposable training lab without executing untrusted code.","params":{"orchestra":"all","scope":"An owned, offline, disposable cyberdefense training laboratory with synthetic data."}}
JSON
response="$(curl -fsS --max-time 15 -H "Authorization: Bearer $GOTHAM_OPERATOR_TOKEN" \
  -H 'Content-Type: application/json' --data "$PAYLOAD" "$URL/api/v4/missions")"
mid="$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["mission"]["id"])')"
test -n "$mid"
echo "Submitted synthetic all-orchestra mission: $mid"
status=""
for i in $(seq 1 180); do
  response="$(curl -fsS --max-time 15 -H "Authorization: Bearer $GOTHAM_OPERATOR_TOKEN" "$URL/api/v4/missions/$mid")"
  status="$(printf '%s' "$response" | python3 -c 'import json,sys;print(json.load(sys.stdin)["mission"]["status"])')"
  case "$status" in
    completed_unverified|failed|cancelled|blocked|verified) break ;;
  esac
  sleep 10
done
printf '%s' "$response" > "$BASE/acceptance-last-result.json"
if [ "$status" != completed_unverified ]; then
  echo "FAIL: orchestral mission did not complete analysis. Status: $status"
  printf '%s' "$response" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("Task errors:", [(t.get("kind"),t.get("agent"),str(t.get("error") or "")[:100]) for t in d.get("tasks",[]) if t.get("status") not in ("succeeded",)])' || true
  exit 1
fi
printf '%s' "$response" | python3 -c '
import json,sys
d=json.load(sys.stdin)
m=d["mission"]
tasks=d["tasks"]
assert len(tasks)==21, len(tasks)
assert sum(t["kind"]=="orchestra_specialist" and t["status"]=="succeeded" for t in tasks)==12
assert sum(t["kind"]=="orchestra_plan" and t["status"]=="succeeded" for t in tasks)==4
assert sum(t["kind"]=="orchestra_review" and t["status"]=="succeeded" for t in tasks)==4
assert sum(t["kind"]=="orchestra_synthesis" and t["status"]=="succeeded" for t in tasks)==1
assert m["result"]["analysis_complete"] is True
assert m["result"]["verified"] is False
assert m["result"]["execution_verified"] is False
print("PASS: all 12 specialist slots, 4 captain plans/reviews, Alfred synthesis")
print("PASS: analysis is labeled unverified, not imaginary tool execution")
'
audit="$(curl -fsS --max-time 15 -H "Authorization: Bearer $GOTHAM_BATMAN_TOKEN" "$URL/api/v4/audit/verify")"
# An off-host immutable run artifact can anchor a known-good journal head.
# Never copy the HMAC key, full event bodies or mission inputs into Actions.
printf '%s' "$audit" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["valid"] is True; assert len(d["head"])==64; print("PASS: Batman-only Specter hash-chain verified")'
printf '%s' "$audit" | python3 -c '
import json,sys,datetime
d=json.load(sys.stdin)
anchor={
    "schema":"gotham-specter-audit-anchor-v1",
    "mission_id":sys.argv[1],
    "head_hmac_sha256":d["head"],
    "verified_events":d["checked"],
    "chain_valid":d["valid"],
    "created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "purpose":"Off-host checkpoint of isolated staging audit chain; no private key or prompts"
}
with open(sys.argv[2],"w") as f:
    json.dump(anchor,f,sort_keys=True,indent=2)
' "$mid" "$BASE/acceptance-audit-anchor.json"
chmod 600 "$BASE/acceptance-audit-anchor.json"
test "$(systemctl is-active gotham)" = active
echo "PASS: original Gotham production service still active"
