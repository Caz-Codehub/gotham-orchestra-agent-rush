#!/usr/bin/env bash
# Ephemeral, non-root smoke check for Gotham 4.0; NEVER changes system services.
set -Eeuo pipefail
SRC="${1:?source root is required}"
test "$(id -un)" = gothamdeploy || { echo 'BLOCKED: only gothamdeploy can run this'; exit 2; }
test -f "$SRC/gotham/app.py" || exit 2
if ss -ltn | grep -Eq '127[.]0[.]0[.]1:8001[[:space:]]'; then
  echo 'BLOCKED: staging port 8001 already in use'; exit 2
fi
cd "$SRC"
python3 -m venv "$SRC/.venv"
"$SRC/.venv/bin/python" -m pip install -q -r requirements.txt
export GOTHAM_DATA_DIR="$SRC/data"
export GOTHAM_STORE_DB="$SRC/data/gotham.sqlite3"
export GOTHAM_AUDIT_DB="$SRC/audit/specter.sqlite3"
export GOTHAM_LEDGER_PATH="$SRC/data/legacy-ledger.sqlite3"
export GOTHAM_SPECTER_EXTERNAL=1
export GOTHAM_INFERENCE_PROVIDER=ollama
export GOTHAM_OLLAMA_MODEL=qwen2.5:1.5b
export GOTHAM_ALLOW_PAID_INFERENCE=NO
export GOTHAM_BATMAN_TOKEN=staging-smoke-only-not-for-real-use
export GOTHAM_OPERATOR_TOKEN=staging-smoke-only-not-for-real-use
mkdir -p "$SRC/data" "$SRC/audit"
"$SRC/.venv/bin/python" -m uvicorn gotham.app:app --host 127.0.0.1 --port 8001 --workers 1 > "$SRC/smoke.log" 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true' EXIT
success=0
for i in $(seq 1 40); do
  if curl -fsS --max-time 3 http://127.0.0.1:8001/api/v4/health > "$SRC/health.json" 2>/dev/null; then
    if "$SRC/.venv/bin/python" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["status"]=="ok"' "$SRC/health.json"; then
      success=1
      break
    fi
  fi
  if ! kill -0 "$pid" 2>/dev/null; then break; fi
  sleep 1
done
if [ "$success" -ne 1 ]; then
  echo "FAIL: isolated API health check"; tail -n 30 "$SRC/smoke.log"; exit 1
fi
echo "PASS: staging API localhost:8001 Gotham v4 /api/v4/health"
test "$(systemctl is-active gotham)" = active || { echo "BLOCKED: existing production is not active"; exit 1; }
echo "PASS: original Gotham production service remains active"
echo "PASS: ephemeral staging process will be stopped after test"
