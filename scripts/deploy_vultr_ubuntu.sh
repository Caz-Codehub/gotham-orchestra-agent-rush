#!/usr/bin/env bash
# Run on a fresh, single-purpose Ubuntu 24.04 Vultr Cloud Compute VM AFTER
# the hackathon $200 credit is confirmed and after /etc/gotham.env is created.
# Does not provision Vultr instances or make billing changes.
set -Eeuo pipefail

fail(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$(id -u)" == '0' ]] || fail 'Run with sudo on the Vultr VM.'
[[ "${GOTHAM_CREDITS_VERIFIED:-}" == 'YES' ]] || fail 'Budget guard: verify hackathon credit first, then explicitly set GOTHAM_CREDITS_VERIFIED=YES.'
[[ -n "${GOTHAM_PUBLIC_IP:-}" ]] || fail 'Supply the public IPv4 as GOTHAM_PUBLIC_IP (from Vultr Console).'
[[ "$GOTHAM_PUBLIC_IP" =~ ^[0-9.]+$ ]] || fail 'Invalid public IP format.'
python3 - "$GOTHAM_PUBLIC_IP" <<'PY' || fail 'Invalid public IPv4 address.'
import ipaddress, sys
ip = ipaddress.ip_address(sys.argv[1])
assert isinstance(ip, ipaddress.IPv4Address) and ip.is_global, 'Use a public IPv4 address'
PY
[[ -f /etc/gotham.env ]] || fail 'First create /etc/gotham.env with distinct GOTHAM_ACCESS_TOKEN and GOTHAM_BATMAN_TOKEN, inference provider and Vultr credentials. chmod 600 it.'
[[ "$(stat -c %a /etc/gotham.env)" == 600 ]] || fail '/etc/gotham.env must be chmod 600.'
for required in GOTHAM_ACCESS_TOKEN GOTHAM_BATMAN_TOKEN VULTR_INFERENCE_API_KEY VULTR_INFERENCE_MODEL; do
  grep -Eq "^${required}=.+" /etc/gotham.env || fail "Missing ${required} setting in /etc/gotham.env"
done
grep -Eq '^GOTHAM_INFERENCE_PROVIDER=vultr$' /etc/gotham.env || fail 'Set GOTHAM_INFERENCE_PROVIDER=vultr in /etc/gotham.env.'
grep -Eq '^GOTHAM_ALLOW_PAID_INFERENCE=I_ACCEPT_POTENTIAL_CHARGES$' /etc/gotham.env || fail 'Inference potentially billable. Explicit opt-in required.'
ROOT=$(cd "$(dirname "$0")/.." && pwd)
[[ -f "$ROOT/gotham/app.py" ]] || fail 'Run from the extracted Gotham source folder.'
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates caddy docker.io python3-venv python3-pip curl
systemctl enable --now docker
# For a short-lived single-user hackathon VM only: access to Docker is effectively root access.
# Do not host unrelated workloads on this VM. Do not run public unauthenticated missions.
if ! id gotham &>/dev/null; then
  useradd --system --home-dir /opt/gotham --shell /usr/sbin/nologin --user-group gotham
fi
usermod -aG docker gotham
install -d -m 0755 -o root -g root /opt/gotham
install -d -m 0750 -o gotham -g gotham /var/lib/gotham
install -d -m 0755 -o gotham -g gotham /var/lib/gotham/work
cp -r "$ROOT/gotham" "$ROOT/requirements.txt" /opt/gotham/
python3 -m venv /opt/gotham/.venv
/opt/gotham/.venv/bin/pip install --disable-pip-version-check -r /opt/gotham/requirements.txt
# Pull once outside the untrusted execution path. Use pinned image digest in a longer-lived deployment.
docker pull python:3.12-alpine
cat >/etc/systemd/system/gotham.service <<'UNIT'
[Unit]
Description=Gotham Hackathon Agent Command Center
Requires=docker.service
After=network-online.target docker.service
Wants=network-online.target
[Service]
Type=simple
User=gotham
Group=gotham
SupplementaryGroups=docker
WorkingDirectory=/opt/gotham
EnvironmentFile=/etc/gotham.env
Environment=GOTHAM_LEDGER_PATH=/var/lib/gotham/missions.sqlite3
Environment=GOTHAM_SPECTER_DB=/var/lib/gotham/specter.sqlite3
Environment=GOTHAM_SPECTER_EXTERNAL=1
Environment=GOTHAM_SANDBOX_TMPDIR=/var/lib/gotham/work
ExecStart=/opt/gotham/.venv/bin/uvicorn gotham.app:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/gotham
# PrivateTmp must remain off so the Docker daemon can see bind-mounted task directories.
[Install]
WantedBy=multi-user.target
UNIT
cat >/etc/systemd/system/gotham-specter.service <<'UNIT'
[Unit]
Description=Gotham Specter independent audit watcher
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=gotham
Group=gotham
WorkingDirectory=/opt/gotham
EnvironmentFile=/etc/gotham.env
Environment=GOTHAM_SPECTER_DB=/var/lib/gotham/specter.sqlite3
ExecStart=/opt/gotham/.venv/bin/python -m gotham.specter_service
Restart=always
RestartSec=2
UMask=0077
NoNewPrivileges=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/gotham
[Install]
WantedBy=multi-user.target
UNIT
DOMAIN="${GOTHAM_PUBLIC_IP}.sslip.io"
cat >/etc/caddy/Caddyfile <<EOF
${DOMAIN} {
    encode gzip
    header {
       X-Content-Type-Options nosniff
       Referrer-Policy strict-origin-when-cross-origin
       X-Frame-Options DENY
       -Server
    }
    reverse_proxy 127.0.0.1:8000
}
EOF
caddy fmt --overwrite /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable --now gotham-specter.service
systemctl enable --now gotham.service
systemctl enable --now caddy.service
systemctl restart gotham-specter.service gotham.service caddy.service
sleep 2
curl -fsS --max-time 10 http://127.0.0.1:8000/health || fail 'Local health check failed. See: journalctl -u gotham --no-pager -n 50'
printf '\nGotham service installed on this Vultr VM.\nTentative public URL: https://%s/\n' "$DOMAIN"
printf 'Public HTTPS is not verified by this script. DNS, inbound 80/443, and Caddy ACME must succeed.\n'
printf 'Run: bash scripts/verify_live.sh https://%s\n' "$DOMAIN"
printf 'Caution: Docker-group service user is root-equivalent on this dedicated VM.\n'
printf 'Specter audit watcher is installed as its own auto-restarting systemd service.\n'
printf 'Check with: systemctl is-active gotham-specter.service\n'
