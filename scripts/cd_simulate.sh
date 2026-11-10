#!/usr/bin/env bash
# CD simulation: exercises deploy/deploy.sh end-to-end on THIS machine, standing in for the Vultr VM.
# Releases come from a local bare git repo; "systemd" is replaced by a restart script that manages API+worker processes.
# Scenarios: A good release -> B BROKEN release (must auto-roll back) -> C good release; data must survive all of them.
set -uo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd); cd "$HERE"
W=$(mktemp -d /tmp/gotham-cd-XXXX); PORT=${PORT:-8013}; PASS=0; FAIL=0
PY=${PYTHON:-$HERE/.venv/bin/python}
export GOTHAM_BASE=$W/opt GOTHAM_VENV=$HERE/.venv GOTHAM_SKIP_PIP=1 GOTHAM_DATA=$W/data GOTHAM_AUDIT_DIR=$W/audit GOTHAM_BACKUP_DIR=$W/backups
export GOTHAM_DATA_DIR=$GOTHAM_DATA GOTHAM_AUDIT_DB=$GOTHAM_AUDIT_DIR/specter.sqlite3 GOTHAM_STORE_DB=$GOTHAM_DATA/gotham.sqlite3
export GOTHAM_BATMAN_TOKEN=batman-token-0123456789abcdef GOTHAM_OPERATOR_TOKEN=operator-token-0123456789abcd
export GOTHAM_SPECTER_DB=$W/legacy-specter.sqlite3 GOTHAM_LEDGER_PATH=$W/ledger.sqlite3
export GOTHAM_HEALTH_URL=http://127.0.0.1:$PORT/api/v4/health GOTHAM_SMOKE_URL=http://127.0.0.1:$PORT GOTHAM_REPO=file://$W/origin.git
export GOTHAM_RESTART_CMD="$W/restart.sh"
mkdir -p "$W/run" "$GOTHAM_DATA" "$GOTHAM_AUDIT_DIR"
cat > "$W/restart.sh" <<R
#!/usr/bin/env bash
for f in $W/run/*.pid; do [ -f "\$f" ] && kill \$(cat "\$f") 2>/dev/null; rm -f "\$f"; done; sleep 1
cd $GOTHAM_BASE/current
nohup $PY -m uvicorn gotham.app:app --port $PORT > $W/api.log 2>&1 & echo \$! > $W/run/api.pid
nohup $PY -m gotham.core.worker > $W/worker.log 2>&1 & echo \$! > $W/run/worker.pid
R
chmod +x "$W/restart.sh"
ok() { echo "  PASS  $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL  $1"; FAIL=$((FAIL+1)); }
chk() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
cleanup() { for f in $W/run/*.pid; do [ -f "$f" ] && kill $(cat "$f") 2>/dev/null; done; }; trap cleanup EXIT

# --- build the "origin" with three releases
git clone -q --no-hardlinks "$HERE" "$W/src" && cd "$W/src"
git config user.email sim@gotham.local; git config user.name sim
rsync -a --exclude .git --exclude .venv --exclude data "$HERE/" "$W/src/" 2>/dev/null || cp -r "$HERE/gotham" "$HERE/deploy" "$HERE/rules" "$HERE/docker" "$HERE/requirements.txt" "$W/src/"
git add -A; git commit -q -m "release A" --allow-empty; git branch -f release-a
echo "THIS IS NOT PYTHON ((" >> gotham/app.py; git commit -qam "release B (broken: syntax error)"; git branch -f release-b
git checkout -q release-a; git checkout -q -b rc; sed -i "s/4.0.0-dev/4.0.1-sim/" gotham/core/api.py; git commit -qam "release C"; git branch -f release-c
git clone -q --bare "$W/src" "$W/origin.git"; cd "$HERE"

echo "== Scenario 1: first deploy of release A (no previous release, no data yet)"
bash deploy/deploy.sh release-a > "$W/d1.log" 2>&1; chk "deploy A succeeds" "[ $? -eq 0 ] || grep -q 'deployed release-a' $W/d1.log"
chk "current -> release-a" "[ \"\$(basename \$(readlink -f $GOTHAM_BASE/current))\" = release-a ]"
chk "health reports 4.0.0-dev" "curl -fsS $GOTHAM_HEALTH_URL | grep -q 4.0.0-dev"
echo "== Smoke test on A"
chk "smoke test (7 checks) passes" "bash deploy/smoke_test.sh $GOTHAM_SMOKE_URL $GOTHAM_OPERATOR_TOKEN $GOTHAM_BATMAN_TOKEN | grep -c PASS | grep -q '^7$'"
MID=$(curl -fsS -H "Authorization: Bearer $GOTHAM_OPERATOR_TOKEN" -H 'Content-Type: application/json' -d '{"kind":"log_analysis","goal":"seed mission for data-survival check","params":{"files":{"a.log":"x"},"log":"a.log"}}' $GOTHAM_SMOKE_URL/api/v4/missions | $PY -c "import sys,json;print(json.load(sys.stdin)['mission']['id'])")

echo "== Scenario 2: deploy BROKEN release B (must be refused/rolled back)"
bash deploy/deploy.sh release-b > "$W/d2.log" 2>&1; RC=$?
chk "deploy B exits non-zero" "[ $RC -ne 0 ]"
chk "B rejected by the pre-switch compile gate (service untouched)" "grep -q 'does not compile' $W/d2.log"
chk "current still -> release-a" "[ \"\$(basename \$(readlink -f $GOTHAM_BASE/current))\" = release-a ]"
chk "service still healthy on A" "curl -fsS $GOTHAM_HEALTH_URL | grep -q 4.0.0-dev"

echo "== Scenario 2b: release that compiles but FAILS HEALTH after restart (runtime break) -> rollback"
cd "$W/src"; git checkout -q release-a; git checkout -q -b rb2; sed -i "s/^app=FastAPI(/raise RuntimeError('boot failure')\napp=FastAPI(/" gotham/app.py; git commit -qam "release B2 (import-time crash)"; git branch -f release-b2
git push -q --force "$W/origin.git" release-b2:release-b2; cd "$HERE"
bash deploy/deploy.sh release-b2 > "$W/d2b.log" 2>&1; RC=$?
chk "deploy B2 exits non-zero" "[ $RC -eq 1 ]"
chk "rollback logged and healthy" "grep -q 'ROLLING BACK' $W/d2b.log && grep -q 'rollback healthy on release-a' $W/d2b.log"
chk "current back on release-a" "[ \"\$(basename \$(readlink -f $GOTHAM_BASE/current))\" = release-a ]"
chk "service healthy after rollback" "curl -fsS $GOTHAM_HEALTH_URL | grep -q 4.0.0-dev"

echo "== Scenario 3: deploy good release C (smoke-gated)"
bash deploy/deploy.sh release-c > "$W/d3.log" 2>&1; chk "deploy C succeeds incl. smoke" "grep -q 'smoke test passed' $W/d3.log && grep -q 'deployed release-c' $W/d3.log"
chk "health reports 4.0.1-sim" "curl -fsS $GOTHAM_HEALTH_URL | grep -q 4.0.1-sim"
chk "pre-deploy backup written and checksummed" "ls $GOTHAM_BACKUP_DIR/*.tgz >/dev/null 2>&1 && ls $GOTHAM_BACKUP_DIR/*.sha256 >/dev/null 2>&1"
chk "mission from release A still readable after C (data survives)" "curl -fsS -H 'Authorization: Bearer $GOTHAM_OPERATOR_TOKEN' $GOTHAM_SMOKE_URL/api/v4/missions/$MID | grep -q $MID"
chk "audit chain still valid across releases" "curl -fsS -H 'Authorization: Bearer $GOTHAM_BATMAN_TOKEN' $GOTHAM_SMOKE_URL/api/v4/audit/verify | grep -q '\"valid\":true'"
echo; echo "CD simulation: $PASS passed, $FAIL failed (workdir $W)"; [ $FAIL -eq 0 ]
