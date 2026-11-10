#!/usr/bin/env bash
# Verify checksum then restore into empty target dirs. Usage: restore.sh BACKUP.tgz DATA_DIR AUDIT_DIR
set -euo pipefail
B=${1:?backup}; DATA=${2:?data dir}; AUDIT=${3:?audit dir}
( cd "$(dirname "$B")" && sha256sum -c "$(basename "$B").sha256" )
TMP=$(mktemp -d); tar -C "$TMP" -xzf "$B"
mkdir -p "$DATA" "$AUDIT"
cp "$TMP/gotham.sqlite3" "$DATA/gotham.sqlite3"; [ -d "$TMP/artifacts" ] && cp -r "$TMP/artifacts" "$DATA/"
cp "$TMP/specter.sqlite3" "$AUDIT/specter.sqlite3"; [ -f "$TMP/specter.key" ] && cp "$TMP/specter.key" "$AUDIT/specter.key"
chmod 600 "$AUDIT"/specter.* ; rm -rf "$TMP"; echo restored
