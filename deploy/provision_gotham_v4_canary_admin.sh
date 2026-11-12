#!/usr/bin/env bash
# Gotham 4.0: STAGING-ONLY admin bootstrap. Must be run locally as root in
# the Vultr console. Does not start services, enable Docker, or touch production.
set -Eeuo pipefail
umask 077

if (( EUID != 0 )); then
  echo 'BLOCKED: execute via the Vultr root/admin console (not GitHub SSH)' >&2
  exit 2
fi
for tool in getent useradd groupadd usermod install chown chmod stat id; do
  command -v "$tool" >/dev/null || { echo "BLOCKED: missing $tool" >&2; exit 2; }
done
if [[ ! -f /etc/os-release ]]; then echo 'BLOCKED: unsupported host' >&2; exit 2; fi

# Refuse changes to hosts where Gotham production has not been identified.
if ! systemctl list-unit-files gotham.service --no-legend 2>/dev/null | grep -q 'gotham.service'; then
  echo 'BLOCKED: expected production service gotham.service not found; inspect host manually' >&2
  exit 2
fi

create_group() {
  local group="$1"
  getent group "$group" >/dev/null || groupadd --system "$group"
}
create_role() {
  local user="$1"
  if ! id "$user" >/dev/null 2>&1; then
    useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin "$user"
  fi
  [[ "$(id -u "$user")" != 0 ]] || { echo "BLOCKED: $user unexpectedly has UID 0" >&2; exit 2; }
  local g
  for g in docker sudo wheel adm; do
    if id -nG "$user" | tr ' ' '\n' | grep -qx "$g"; then
      echo "BLOCKED: $user already belongs to privileged group $g" >&2; exit 2
    fi
  done
}

create_group gotham-specter-record
create_group gotham-specter-verify
for role in gothamspecter gothamworker gothambatmanapi gothamsandbox; do
  create_role "$role"
done
# Verify that each role is distinct before modifying supplementary groups.
uids=()
for role in gothamspecter gothamworker gothambatmanapi gothamsandbox; do
  uids+=("$(id -u "$role")")
done
[[ "$(printf '%s\n' "${uids[@]}" | sort -u | wc -l)" -eq 4 ]] || {
  echo 'BLOCKED: service UID identities are not distinct' >&2; exit 2
}
usermod -a -G gotham-specter-record gothamworker
usermod -a -G gotham-specter-verify gothambatmanapi

BASE=/var/lib/gotham-v4-canary
# Fail before any path creation if a previously provisioned canary path
# is a symlink/non-directory. Never follow it into a production tree.
for candidate in "$BASE" "$BASE/specter" "$BASE/specter/journal" \
                 "$BASE/specter/record" "$BASE/specter/verify" "$BASE/sandbox"; do
  if [[ -L "$candidate" || ( -e "$candidate" && ! -d "$candidate" ) ]]; then
    echo "BLOCKED: unexpected canary path type: $candidate" >&2
    exit 2
  fi
done
if [[ -d "$BASE" && "$(stat -c '%U' "$BASE")" != root ]]; then
  echo "BLOCKED: existing canary root directory not owned by root" >&2
  exit 2
fi
# Only dedicated paths are created; never modify the existing /opt/gotham
# tree, Caddy, production unit, staging release or Docker daemon.
install -d -o root -g root -m 0711 "$BASE"
install -d -o gothamspecter -g gothamspecter -m 0711 "$BASE/specter"
install -d -o gothamspecter -g gothamspecter -m 0700 "$BASE/specter/journal"
install -d -o gothamspecter -g gotham-specter-record -m 2710 "$BASE/specter/record"
install -d -o gothamspecter -g gotham-specter-verify -m 2710 "$BASE/specter/verify"
# Reassert setgid on distro implementations whose install may mask it.
chmod 2710 "$BASE/specter/record" "$BASE/specter/verify"
# Dedicated executor workspace; no Docker privileges are granted here.
install -d -o gothamsandbox -g gothamsandbox -m 0700 "$BASE/sandbox"

assert_mode_owner() {
  local path="$1" owner="$2" group="$3" mode="$4"
  [[ "$(stat -c '%U' "$path")" = "$owner" ]] &&
  [[ "$(stat -c '%G' "$path")" = "$group" ]] &&
  [[ "$(stat -c '%a' "$path")" = "$mode" ]] || {
    echo "BLOCKED: canary path ownership/mode mismatch: $path" >&2; exit 2
  }
}
assert_mode_owner "$BASE/specter/journal" gothamspecter gothamspecter 700
assert_mode_owner "$BASE/specter/record" gothamspecter gotham-specter-record 2710
assert_mode_owner "$BASE/specter/verify" gothamspecter gotham-specter-verify 2710
assert_mode_owner "$BASE/sandbox" gothamsandbox gothamsandbox 700
test "$(systemctl is-active gotham.service)" = active || {
  echo 'BLOCKED: production service was not active; investigate before further work' >&2; exit 2
}
echo 'PASS: dedicated Gotham v4 canary identities and IPC directories are provisioned'
echo 'PASS: production service remains active'
echo 'PASS: no service started, no secret generated, no Docker group granted'
echo 'NEXT: inspect canary UID separation and deploy verified Specter service only'
