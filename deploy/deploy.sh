#!/usr/bin/env bash
# Release with health verification and automatic rollback. Run ON the target host as root/deploy user.
# Usage: deploy.sh <git-ref>      Releases live in /opt/gotham/releases/<ref>; /opt/gotham/current is a symlink.
set -euo pipefail
REF=${1:?git ref}; BASE=/opt/gotham; REL=$BASE/releases/$REF; PREV=$(readlink -f $BASE/current || true)
HEALTH=${GOTHAM_HEALTH_URL:-http://127.0.0.1:8000/api/v4/health}
mkdir -p $BASE/releases; [ -d "$REL" ] || git clone --quiet --branch "$REF" --depth 1 "${GOTHAM_REPO:-https://github.com/Caz-Codehub/gotham-orchestra-agent-rush.git}" "$REL"
[ -x $BASE/venv/bin/pip ] || python3 -m venv $BASE/venv
$BASE/venv/bin/pip install -q -r "$REL/requirements.txt"
/opt/gotham/current/deploy/backup.sh /var/lib/gotham /var/lib/gotham-audit /var/backups/gotham 2>/dev/null || $REL/deploy/backup.sh /var/lib/gotham /var/lib/gotham-audit /var/backups/gotham || true
ln -sfn "$REL" $BASE/current
systemctl restart gotham-api gotham-worker
for i in $(seq 1 20); do curl -fsS "$HEALTH" >/dev/null 2>&1 && ok=1 && break; sleep 2; done
if [ "${ok:-0}" != 1 ]; then
  echo "health check failed; rolling back to ${PREV:-none}" >&2
  [ -n "$PREV" ] && ln -sfn "$PREV" $BASE/current && systemctl restart gotham-api gotham-worker
  exit 1
fi
echo "deployed $REF"
