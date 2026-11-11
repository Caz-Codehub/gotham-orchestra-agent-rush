#!/usr/bin/env bash
# Safely prepare and start a LOCAL-ONLY Gotham 4.0 staging API on an existing Vultr VM.
# Deliberately DOES NOT modify /opt/gotham, the gotham.service, Caddy, public firewall,
# the production data/audit ledgers, or paid inference settings.
set -Eeuo pipefail
umask 077

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root on the existing Gotham VM, not from Windows PowerShell." >&2
  exit 2
fi
SRC="${GOTHAM_STAGE_SOURCE:-/opt/gotham-v4-staging/source}"
ROOT="${GOTHAM_STAGE_ROOT:-/opt/gotham-v4-staging}"
VENV="$ROOT/venv"
ENVFILE=/etc/gotham-v4-staging.env
UNIT=/etc/systemd/system/gotham-v4-staging.service

[ -f "$SRC/gotham/app.py" ] || { echo "Missing staging checkout: $SRC" >&2; exit 2; }
[ -f "$SRC/requirements.txt" ] || exit 2
if [ -d /opt/gotham ] && [ "$(readlink -f "$SRC")" = "$(readlink -f /opt/gotham)" ]; then
  echo "Refusing to operate against production tree" >&2
  exit 2
fi
if ss -ltn | grep -Eq '127[.]0[.]0[.]1:8001[[:space:]]'; then
  if ! systemctl is-active --quiet gotham-v4-staging; then
    echo "Port 8001 already in use by something else; refusing to overwrite" >&2
    exit 2
  fi
fi
echo "Gotham 4.0 staging: preparing separate Python environment"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install -q -r "$SRC/requirements.txt" -r "$SRC/requirements-dev.txt"
"$VENV/bin/python" -m compileall -q "$SRC/gotham"
echo "Running targeted security acceptance checks"
(
  cd "$SRC"
  "$VENV/bin/python" -m pytest -q --maxfail=1 \
    tests/test_v4_acceptance.py::test_sentinel_detects_introduced_weaknesses_with_reproducible_report \
    tests/test_v4_api.py::test_mission_lifecycle_through_api_with_artifact_integrity_and_audit
)
if ! id gothamstage >/dev/null 2>&1; then
  useradd --system --home-dir "$ROOT" --shell /usr/sbin/nologin gothamstage
fi
install -d -m 750 -o gothamstage -g gothamstage "$ROOT/data" "$ROOT/audit"
chmod 755 "$ROOT" "$SRC"
# Make sure the staging account can traverse and read source/venv without granting write access to code.
chmod -R a+rX "$SRC" "$VENV"
if [ ! -f "$ENVFILE" ]; then
  BATMAN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"
  OPERATOR="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"
  VIEWER="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"
  cat > "$ENVFILE" <<EOF
GOTHAM_DATA_DIR=$ROOT/data
GOTHAM_STORE_DB=$ROOT/data/gotham.sqlite3
GOTHAM_AUDIT_DB=$ROOT/audit/specter.sqlite3
GOTHAM_LEDGER_PATH=$ROOT/data/legacy-ledger.sqlite3
GOTHAM_SPECTER_DB=$ROOT/audit/legacy-specter.sqlite3
GOTHAM_SPECTER_EXTERNAL=1
GOTHAM_INFERENCE_PROVIDER=ollama
GOTHAM_OLLAMA_MODEL=qwen2.5:1.5b
GOTHAM_MAX_MODEL_CALLS=6
GOTHAM_LOCAL_CONTEXT_TOKENS=2048
GOTHAM_ALLOW_PAID_INFERENCE=NO
GOTHAM_BATMAN_TOKEN=$BATMAN
GOTHAM_OPERATOR_TOKEN=$OPERATOR
GOTHAM_VIEWER_TOKEN=$VIEWER
EOF
  chmod 600 "$ENVFILE"
fi
cat > "$UNIT" <<EOF
[Unit]
Description=Gotham 4.0 isolated staging API (localhost only)
After=network-online.target ollama.service
Wants=network-online.target

[Service]
Type=simple
User=gothamstage
Group=gothamstage
WorkingDirectory=$SRC
EnvironmentFile=$ENVFILE
ExecStart=$VENV/bin/uvicorn gotham.app:app --host 127.0.0.1 --port 8001 --workers 1
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$ROOT/data $ROOT/audit

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now gotham-v4-staging.service >/dev/null
echo "Waiting for the staging localhost health check"
ok=0
for i in $(seq 1 20); do
  if curl -fsS --max-time 2 http://127.0.0.1:8001/api/v4/health >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
if [ "$ok" -ne 1 ]; then
  systemctl stop gotham-v4-staging.service || true
  echo "Staging health check FAILED; staging stopped. Original production service untouched." >&2
  exit 1
fi
echo "PASS Gotham 4.0 staging health on localhost:8001"
if systemctl is-active --quiet gotham.service; then
  echo "PASS existing Gotham production service remains active"
else
  echo "WARN existing Gotham production service inactive; no production changes were made"
fi
echo "STAGING_ONLY: No public routing, no worker, no paid inference, no production cutover."
echo "Release SHA: $(git -C "$SRC" rev-parse --short HEAD)"
