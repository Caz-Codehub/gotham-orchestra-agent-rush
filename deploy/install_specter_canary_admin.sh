#!/usr/bin/env bash
# Gotham 4.0 root-console-only Specter canary installer; no production changes.
set -Eeuo pipefail
umask 077
(( EUID == 0 )) || { echo 'BLOCKED: run as root on Vultr console'; exit 2; }
ARCHIVE="$1"
EXPECTED="$2"
[[ "$EXPECTED" =~ ^[a-f0-9]{64}$ ]] || exit 2
case "$ARCHIVE" in
  /home/gothamdeploy/gotham-v4-admin/specter-canary-*.tar.gz) ;;
  *) echo 'BLOCKED: archive outside approved staging location'; exit 2 ;;
esac
[[ -f "$ARCHIVE" && ! -L "$ARCHIVE" ]] || exit 2
test "$(sha256sum "$ARCHIVE" | awk '{print $1}')" = "$EXPECTED" || exit 2
test "$(systemctl is-active gotham.service)" = active || exit 2
for u in gothamspecter gothamworker gothambatmanapi gothamsandbox; do
  id "$u" >/dev/null || exit 2
  for g in docker sudo wheel adm; do
    id -nG "$u" | tr ' ' '\n' | grep -qx "$g" && { echo 'BLOCKED: privileged service group'; exit 2; }
  done
done
A="$(id -u gothamspecter)"
W="$(id -u gothamworker)"
B="$(id -u gothambatmanapi)"
test "$A" != "$W" && test "$A" != "$B" && test "$B" != "$W"
BASE=/var/lib/gotham-v4-canary/specter
for p in journal record verify; do
  test -d "$BASE/$p" && test ! -L "$BASE/$p"
  test "$(stat -c '%U' "$BASE/$p")" = gothamspecter
done
test "$(stat -c '%a' "$BASE/journal")" = 700
test "$(stat -c '%a' "$BASE/record")" = 2710
test "$(stat -c '%a' "$BASE/verify")" = 2710
test "$(stat -c '%G' "$BASE/record")" = gotham-specter-record
test "$(stat -c '%G' "$BASE/verify")" = gotham-specter-verify
UNIT=/etc/systemd/system/gotham-v4-specter-canary.service
TARGET=/opt/gotham-v4-specter-canary
if test -e "$UNIT" || test -L "$UNIT" || test -e "$TARGET" || test -L "$TARGET"; then
  echo 'BLOCKED: existing canary installation must be audited manually'; exit 2
fi
python3 - "$ARCHIVE" <<'PY'
import sys,tarfile
with tarfile.open(sys.argv[1],'r:gz') as t:
    entries=t.getmembers()
    if not entries: raise SystemExit('empty canary bundle')
    for m in entries:
        p=m.name.rstrip('/').split('/')
        # Git archives include a legitimate top-level "gotham/" directory.
        # Admit that exact directory and ordinary descendants; reject absolute
        # paths, traversal, empty components, links and special file types.
        if m.name in ('gotham', 'gotham/') and m.isdir():
            continue
        if not m.name.startswith('gotham/') or '..' in p or '.' in p or '' in p or not (m.isdir() or m.isfile()):
            raise SystemExit('unsafe canary bundle')
    need={'gotham/core/specter_service.py','gotham/core/specter_transport.py','gotham/core/audit.py'}
    if not need.issubset({m.name for m in entries if m.isfile()}):
        raise SystemExit('incomplete canary bundle')
print('PASS: source archive verified')
PY
STAGE="$(mktemp -d /opt/.gotham-v4-specter.XXXXXXXX)"
trap 'test ! -d "$STAGE" || rm -rf -- "$STAGE"' EXIT
tar -xzf "$ARCHIVE" -C "$STAGE" --no-same-owner --no-same-permissions
python3 -m compileall -q "$STAGE/gotham"
chown -R root:root "$STAGE"
chmod -R go-w "$STAGE"
mv -T "$STAGE" "$TARGET"
STAGE=""
cat > "$UNIT" <<EOF
[Unit]
Description=Gotham 4 Specter audit staging canary
After=local-fs.target
[Service]
Type=simple
User=gothamspecter
Group=gothamspecter
WorkingDirectory=$TARGET
Environment=PYTHONPATH=$TARGET
ExecStart=/usr/bin/python3 -m gotham.core.specter_service --journal $BASE/journal/canary.sqlite3 --record-socket $BASE/record/record.sock --verify-socket $BASE/verify/verify.sock --worker-uid $W --batman-api-uid $B
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_UNIX
ReadWritePaths=$BASE
CapabilityBoundingSet=
AmbientCapabilities=
Restart=no
[Install]
WantedBy=multi-user.target
EOF
chown root:root "$UNIT"
chmod 644 "$UNIT"
systemctl daemon-reload
systemctl start gotham-v4-specter-canary.service
systemctl is-active --quiet gotham-v4-specter-canary.service || {
  echo 'BLOCKED: auditor canary did not start'; exit 1
}
PYTHONPATH="$TARGET" runuser -u gothamworker -- /usr/bin/python3 - <<PY
from gotham.core.specter_transport import SpecterWriteClient,SpecterReadClient,SpecterTransportError
assert len(SpecterWriteClient("$BASE/record/record.sock").record(None,None,'Alfred','canary_uid_probe',{'fixture':True}))==64
try:
    SpecterReadClient("$BASE/verify/verify.sock").verify()
    raise AssertionError('worker can read verification socket')
except SpecterTransportError: pass
print('PASS: worker can append, cannot read')
PY
PYTHONPATH="$TARGET" runuser -u gothambatmanapi -- /usr/bin/python3 - <<PY
from gotham.core.specter_transport import SpecterWriteClient,SpecterReadClient,SpecterTransportError
assert SpecterReadClient("$BASE/verify/verify.sock").verify()['valid']
try:
    SpecterWriteClient("$BASE/record/record.sock").record(None,None,'Batman','forged',{})
    raise AssertionError('Batman API can append')
except SpecterTransportError: pass
print('PASS: Batman API can verify, cannot append')
PY
test "$(systemctl is-active gotham.service)" = active
echo 'PASS: distinct-UID Specter canary running; production active'
echo 'Canary not enabled at boot; orchestra and API still use previous stable staging service'
