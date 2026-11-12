#!/usr/bin/env bash
# Rootless, versioned staging deployment on the EXISTING Vultr VM.
# NEVER touches production gotham.service, /opt/gotham, Caddy or privileged Docker.
set -Eeuo pipefail
umask 077
test "$(id -un)" = gothamdeploy || { echo "Only gothamdeploy may start this staging service"; exit 2; }
SRC="$(readlink -f "${1:?release source path required}")"
BASE="$HOME/gotham-v4-staging"
mkdir -p "$BASE" "$BASE/logs" "$BASE/data" "$BASE/audit"
test -f "$SRC/gotham/app.py" || { echo "Invalid release directory"; exit 2; }
test "$SRC" != /opt/gotham || exit 2

# Independent per-release virtualenv. Production packages are never altered.
python3 -m venv "$SRC/.venv"
"$SRC/.venv/bin/python" -m pip install -q -r "$SRC/requirements.txt"
"$SRC/.venv/bin/python" -m compileall -q "$SRC/gotham"

ENVFILE="$BASE/staging.env"
if [ ! -f "$ENVFILE" ]; then
  {
    printf 'GOTHAM_DATA_DIR=%s\n' "$BASE/data"
    printf 'GOTHAM_STORE_DB=%s\n' "$BASE/data/orchestra.sqlite3"
    printf 'GOTHAM_AUDIT_DB=%s\n' "$BASE/audit/specter.sqlite3"
    printf 'GOTHAM_LEDGER_PATH=%s\n' "$BASE/data/legacy.sqlite3"
    printf 'GOTHAM_SPECTER_DB=%s\n' "$BASE/audit/legacy-specter.sqlite3"
    printf 'GOTHAM_SPECTER_EXTERNAL=1\n'
    printf 'GOTHAM_INFERENCE_PROVIDER=ollama\n'
    printf 'GOTHAM_OLLAMA_MODEL=qwen2.5:1.5b\n'
    printf 'GOTHAM_MAX_MODEL_CALLS=48\n'
    printf 'GOTHAM_ORCHESTRA_MISSION_CALL_LIMIT=48\n'
    printf 'GOTHAM_LOCAL_CONTEXT_TOKENS=2048\n'
    printf 'GOTHAM_LOCAL_REQUEST_TIMEOUT_SECONDS=150\n'
    printf 'GOTHAM_ALLOW_PAID_INFERENCE=NO\n'
    python3 - <<'PY'
import secrets
for role in ("BATMAN", "OPERATOR", "VIEWER"):
    print("GOTHAM_"+role+"_TOKEN="+secrets.token_urlsafe(42))
PY
  } > "$ENVFILE"
fi
# Only upgrade the previous Gotham-generated 32-call CPU-local default.
# Preserve all other explicit budget choices and all staging secrets.
if grep -qx 'GOTHAM_MAX_MODEL_CALLS=32' "$ENVFILE"; then
  sed -i 's/^GOTHAM_MAX_MODEL_CALLS=32$/GOTHAM_MAX_MODEL_CALLS=48/' "$ENVFILE"
fi
if ! grep -q '^GOTHAM_ORCHESTRA_MISSION_CALL_LIMIT=' "$ENVFILE"; then
  printf 'GOTHAM_ORCHESTRA_MISSION_CALL_LIMIT=48\n' >> "$ENVFILE"
fi
# Preserve existing generated tokens and data, but add safe inference tuning
# without overwriting or leaking any prior staging credentials.
if ! grep -q '^GOTHAM_LOCAL_REQUEST_TIMEOUT_SECONDS=' "$ENVFILE"; then
  printf 'GOTHAM_LOCAL_REQUEST_TIMEOUT_SECONDS=150\n' >> "$ENVFILE"
fi
chmod 600 "$ENVFILE"

PIDFILE="$BASE/staging.pid"
WPIDFILE="$BASE/orchestra-worker.pid"
CURRENT="$BASE/current"
old_release=""
old_pid=""
old_worker_pid=""
if [ -L "$CURRENT" ]; then old_release="$(readlink -f "$CURRENT")"; fi
if [ -f "$PIDFILE" ]; then old_pid="$(cat "$PIDFILE")"; fi
if [ -f "$WPIDFILE" ]; then old_worker_pid="$(cat "$WPIDFILE")"; fi

owned_pid() {
  test -n "$1" && [[ "$1" =~ ^[0-9]+$ ]] && kill -0 "$1" 2>/dev/null &&
  test -r "/proc/$1/cmdline" &&
  tr '\0' ' ' < "/proc/$1/cmdline" | grep -q 'uvicorn gotham.app:app'
}
stop_owned() {
  if owned_pid "$1"; then
    kill "$1"
    for i in $(seq 1 25); do kill -0 "$1" 2>/dev/null || break; sleep 0.2; done
  fi
}
# Only processes owned by gothamdeploy, launched from the dedicated staging
# release tree, and running the exact restricted orchestra module are eligible.
# Never match legacy production /opt/gotham workers or unrelated Python services.
owned_worker_pid() {
  local pid="$1" exe module
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  test -r "/proc/$pid/cmdline" || return 1
  exe="$(tr '\0' '\n' < "/proc/$pid/cmdline" | sed -n '1p')"
  module="$(tr '\0' '\n' < "/proc/$pid/cmdline" | sed -n '3p')"
  case "$exe" in
    "$BASE"/releases/*/.venv/bin/python) ;;
    *) return 1 ;;
  esac
  test "$module" = 'gotham.core.orchestra_worker'
}
stop_owned_worker() {
  if owned_worker_pid "$1"; then
    kill "$1"
    for i in $(seq 1 25); do kill -0 "$1" 2>/dev/null || break; sleep 0.2; done
    if kill -0 "$1" 2>/dev/null; then
      echo "BLOCKED: restricted staging worker $1 has not terminated" >&2
      return 1
    fi
  fi
}
reap_orphan_staging_workers() {
  local pid count=0
  while read -r pid; do
    [ -n "$pid" ] || continue
    if owned_worker_pid "$pid"; then
      echo "Stopping duplicate old staging-only orchestra worker PID $pid"
      stop_owned_worker "$pid"
      count=$((count+1))
    fi
  done < <(pgrep -u "$(id -u)" -f 'gotham.core.orchestra_worker' || true)
  echo "PASS: stale staging-only worker cleanup; matched $count"
}
launch_worker() {
  local dir="$1"
  cd "$dir"
  nohup bash -c 'set -a; source "$1"; set +a; exec "$2/.venv/bin/python" -m gotham.core.orchestra_worker' bash "$ENVFILE" "$dir" \
    </dev/null >>"$BASE/logs/orchestra-worker.log" 2>&1 &
  local pid=$!
  printf '%s\n' "$pid" > "$WPIDFILE"
  sleep 1
  kill -0 "$pid" 2>/dev/null || { echo "FAIL: restricted orchestra worker exited" >&2; return 1; }
  echo "PASS: restricted orchestra-only worker started"
}
accept_orchestra() {
  set -a
  source "$ENVFILE"
  set +a
  curl -fsS --max-time 5 -H "Authorization: Bearer $GOTHAM_OPERATOR_TOKEN" \
    http://127.0.0.1:8001/api/v4/orchestras > "$BASE/last-orchestras.json" || return 1
  "$SRC/.venv/bin/python" - "$BASE/last-orchestras.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert d['captains']==4 and d['specialists']==12
assert len(d['orchestras'])==4
assert all(len(o['specialists'])==3 and o['reports_to']=='Alfred' for o in d['orchestras'])
print('PASS four captains and twelve scoped specialist definitions')
PY
  for i in $(seq 1 12); do
    if curl -fsS --max-time 5 -H "Authorization: Bearer $GOTHAM_OPERATOR_TOKEN" \
      http://127.0.0.1:8001/api/v4/infra > "$BASE/last-infra.json"; then
      if "$SRC/.venv/bin/python" - "$BASE/last-infra.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert any(str(w.get('id','')).startswith('orchestra-worker-') for w in d.get('workers',[]))
PY
      then
        echo "PASS orchestral worker appears in the durable store"
        return 0
      fi
    fi
    sleep 1
  done
  echo "FAIL restricted orchestra worker was not observed by API" >&2
  return 1
}

launch_release() {
  local dir="$1"
  local pid
  cd "$dir"
  nohup bash -c 'set -a; source "$1"; set +a; exec "$2/.venv/bin/python" -m uvicorn gotham.app:app --host 127.0.0.1 --port 8001 --workers 1' bash "$ENVFILE" "$dir" \
    </dev/null >>"$BASE/logs/staging-api.log" 2>&1 &
  pid=$!
  printf '%s\n' "$pid" > "$PIDFILE"
  for i in $(seq 1 50); do
    if curl -fsS --max-time 2 http://127.0.0.1:8001/api/v4/health > "$BASE/last-health.json" 2>/dev/null; then
      if "$dir/.venv/bin/python" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["status"] == "ok"' "$BASE/last-health.json"; then
        echo "PASS staging API health"; return 0
      fi
    fi
    if ! kill -0 "$pid" 2>/dev/null; then break; fi
    sleep 0.3
  done
  echo "FAIL staging health check" >&2
  return 1
}

if [ -n "$old_pid" ] && ! owned_pid "$old_pid"; then
  echo "BLOCKED: stale or unowned PID; refusing to terminate process" >&2
  exit 2
fi
if [ -z "$old_pid" ] && ss -lnt | grep -q '127[.]0[.]0[.]1:8001[[:space:]]'; then
  echo "BLOCKED: port 8001 is occupied by an unknown service" >&2
  exit 2
fi

if [ -n "$old_worker_pid" ] && ! owned_worker_pid "$old_worker_pid"; then
  echo "BLOCKED: stale/unowned orchestra worker PID" >&2
  exit 2
fi
if [ -n "$old_worker_pid" ]; then stop_owned_worker "$old_worker_pid"; fi
# A previous deployment can leave behind a process no longer present in PIDFILE.
# Kill only the exact module launched from our own staging release tree.
reap_orphan_staging_workers
if [ -n "$old_pid" ]; then stop_owned "$old_pid"; fi
if launch_release "$SRC" && launch_worker "$SRC" && accept_orchestra; then
  ln -sfn "$SRC" "$BASE/current.new"
  mv -Tf "$BASE/current.new" "$CURRENT"
  echo "PASS rootless staging release activated"
  if systemctl is-active --quiet gotham.service; then
    echo "PASS existing Gotham production remains active"
  else
    echo "WARN production was not active before/after staging; no production changes made" >&2
  fi
  echo "STAGING ONLY: private localhost port 8001; orchestra-only worker; no Docker privileges; no public routing or paid inference"
  exit 0
fi

# Restore previous working staging release if new one failed.
bad_pid="$(cat "$PIDFILE" 2>/dev/null || true)"
bad_worker_pid="$(cat "$WPIDFILE" 2>/dev/null || true)"
stop_owned_worker "$bad_worker_pid"
stop_owned "$bad_pid"
if [ -n "$old_release" ] && [ -x "$old_release/.venv/bin/python" ]; then
  echo "Restoring preceding staging API"
  launch_release "$old_release" && launch_worker "$old_release" || { echo "CRITICAL: staging rollback failed"; exit 1; }
  ln -sfn "$old_release" "$BASE/current.new"
  mv -Tf "$BASE/current.new" "$CURRENT"
fi
exit 1
