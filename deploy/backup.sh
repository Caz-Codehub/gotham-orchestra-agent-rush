#!/usr/bin/env bash
# Consistent online backup of the mission store, audit journal (+key) and artifacts. Usage: backup.sh DATA_DIR AUDIT_DIR OUT_DIR
set -euo pipefail
DATA=${1:?data dir}; AUDIT=${2:?audit dir}; OUT=${3:?output dir}; KEEP=${GOTHAM_BACKUP_KEEP:-7}
TS=$(date -u +%Y%m%dT%H%M%SZ); TMP=$(mktemp -d); mkdir -p "$OUT"
python3 - "$DATA/gotham.sqlite3" "$TMP/gotham.sqlite3" <<'PY'
import sqlite3,sys
s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()
PY
python3 - "$AUDIT/specter.sqlite3" "$TMP/specter.sqlite3" <<'PY'
import sqlite3,sys
s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()
PY
[ -f "$AUDIT/specter.key" ] && cp "$AUDIT/specter.key" "$TMP/specter.key"
[ -d "$DATA/artifacts" ] && cp -r "$DATA/artifacts" "$TMP/artifacts"
tar -C "$TMP" -czf "$OUT/gotham-$TS.tgz" .
( cd "$OUT" && sha256sum "gotham-$TS.tgz" > "gotham-$TS.tgz.sha256" )
rm -rf "$TMP"; chmod 600 "$OUT/gotham-$TS.tgz"
ls -1t "$OUT"/gotham-*.tgz | tail -n +$((KEEP+1)) | while read -r f; do rm -f "$f" "$f.sha256"; done
echo "$OUT/gotham-$TS.tgz"
