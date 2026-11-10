#!/usr/bin/env bash
# Release with pre-deploy backup, health + functional verification and AUTOMATIC ROLLBACK.
# Usage: deploy.sh <git-ref>
# Env (defaults suit the single-VM layout in docs/GOTHAM_DEPLOYMENT.md; all overridable so the flow can be simulated locally):
#   GOTHAM_BASE=/opt/gotham  GOTHAM_REPO=<git url>  GOTHAM_VENV=$BASE/venv  GOTHAM_SKIP_PIP=0
#   GOTHAM_RESTART_CMD="systemctl restart gotham-api gotham-worker"  GOTHAM_HEALTH_URL=http://127.0.0.1:8000/api/v4/health
#   GOTHAM_DATA=/var/lib/gotham GOTHAM_AUDIT_DIR=/var/lib/gotham-audit GOTHAM_BACKUP_DIR=/var/backups/gotham
#   GOTHAM_SMOKE_URL / GOTHAM_OPERATOR_TOKEN / GOTHAM_BATMAN_TOKEN: when all set, deploy_smoke must pass or we roll back.
set -uo pipefail
REF=${1:?git ref}
BASE=${GOTHAM_BASE:-/opt/gotham}; REL=$BASE/releases/$REF; VENV=${GOTHAM_VENV:-$BASE/venv}
REPO=${GOTHAM_REPO:-https://github.com/Caz-Codehub/gotham-orchestra-agent-rush.git}
RESTART=${GOTHAM_RESTART_CMD:-systemctl restart gotham-api gotham-worker}
HEALTH=${GOTHAM_HEALTH_URL:-http://127.0.0.1:8000/api/v4/health}
DATA=${GOTHAM_DATA:-/var/lib/gotham}; AUDIT=${GOTHAM_AUDIT_DIR:-/var/lib/gotham-audit}; BK=${GOTHAM_BACKUP_DIR:-/var/backups/gotham}
KEEP_RELEASES=${GOTHAM_KEEP_RELEASES:-5}
PREV=$(readlink -f "$BASE/current" 2>/dev/null || true)
log() { echo "[deploy $(date -u +%H:%M:%S)] $*"; }
die() { log "ERROR: $*"; exit 1; }

rollback() {
  log "ROLLING BACK: $1"
  if [ -n "$PREV" ] && [ -d "$PREV" ]; then
    ln -sfn "$PREV" "$BASE/current"; bash -c "$RESTART" || true
    for i in $(seq 1 20); do curl -fsS "$HEALTH" >/dev/null 2>&1 && { log "rollback healthy on $(basename "$PREV")"; exit 1; }; sleep 1; done
    log "CRITICAL: rollback target did not become healthy; restore from $BK"; exit 2
  fi
  log "no previous release to roll back to"; exit 1
}

mkdir -p "$BASE/releases" || die "cannot create $BASE/releases"
if [ ! -d "$REL" ]; then
  git clone --quiet --branch "$REF" --depth 1 "$REPO" "$REL" || { rm -rf "$REL"; die "clone of $REF failed (nothing changed)"; }
fi
if [ "${GOTHAM_SKIP_PIP:-0}" != 1 ]; then
  [ -x "$VENV/bin/pip" ] || python3 -m venv "$VENV" || die "venv creation failed"
  "$VENV/bin/pip" install -q -r "$REL/requirements.txt" || die "dependency install failed (nothing changed)"
fi
# Static gate BEFORE touching the running service: the release must at least compile.
"${VENV}/bin/python" -m compileall -q "$REL/gotham" || die "release does not compile (nothing changed)"
# Pre-deploy backup (skipped when there is no data yet).
if [ -f "$DATA/gotham.sqlite3" ]; then
  "$REL/deploy/backup.sh" "$DATA" "$AUDIT" "$BK" >/dev/null || die "pre-deploy backup failed; refusing to deploy"
  log "pre-deploy backup ok"
fi
ln -sfn "$REL" "$BASE/current"
bash -c "$RESTART" || rollback "restart command failed"
ok=0; for i in $(seq 1 30); do curl -fsS "$HEALTH" >/dev/null 2>&1 && ok=1 && break; sleep 1; done
[ "$ok" = 1 ] || rollback "health check failed"
if [ -n "${GOTHAM_SMOKE_URL:-}" ] && [ -n "${GOTHAM_OPERATOR_TOKEN:-}" ] && [ -n "${GOTHAM_BATMAN_TOKEN:-}" ]; then
  "$REL/deploy/smoke_test.sh" "$GOTHAM_SMOKE_URL" "$GOTHAM_OPERATOR_TOKEN" "$GOTHAM_BATMAN_TOKEN" >"$BASE/last_smoke.log" 2>&1 \
    || rollback "functional smoke test failed (see $BASE/last_smoke.log)"
  log "smoke test passed"
fi
# prune old releases (never the current or previous)
ls -1dt "$BASE"/releases/* 2>/dev/null | tail -n +$((KEEP_RELEASES+1)) | while read -r d; do
  [ "$(readlink -f "$d")" = "$(readlink -f "$BASE/current")" ] || [ "$(readlink -f "$d")" = "$PREV" ] || rm -rf "$d"; done
log "deployed $REF (previous: ${PREV:-none})"
