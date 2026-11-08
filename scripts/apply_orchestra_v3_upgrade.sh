#!/usr/bin/env bash
# Run as root inside an extracted GOTHAM ORCHESTRA V3 package, on the existing Vultr VM.
# Does NOT regenerate credentials, re-run installation, or change billing settings.
set -Eeuo pipefail
[[ "$(id -u)" == 0 ]] || { echo 'Must run as root'; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[[ -f "$ROOT/gotham/demo_artifacts.py" && -f "$ROOT/gotham/static/specter.html" ]] || { echo 'V3 source missing'; exit 1; }
[[ -f /etc/gotham.env && -d /opt/gotham/gotham && -x /opt/gotham/.venv/bin/python ]] || { echo 'Existing Gotham install missing; refusing destructive changes'; exit 1; }
backup="/root/gotham-pre-v3-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
tar -czf "$backup" -C /opt/gotham gotham
# Only replace app source and HTML. Preserve existing runtime state and private env file.
cp -a "$ROOT/gotham/app.py" "$ROOT/gotham/orchestras.py" "$ROOT/gotham/specter.py" "$ROOT/gotham/demo_artifacts.py" /opt/gotham/gotham/
cp -a "$ROOT/gotham/static/orchestra.html" "$ROOT/gotham/static/specter.html" /opt/gotham/gotham/static/
chmod -R a+rX /opt/gotham/gotham
systemctl restart gotham-specter gotham
sleep 2
systemctl is-active --quiet gotham && systemctl is-active --quiet gotham-specter || { echo 'Service failed; inspect journalctl -u gotham'; exit 1; }
curl -fsS --max-time 10 http://127.0.0.1:8000/health > /dev/null
printf 'V3 service upgrade healthy. Backup: %s\n' "$backup"
printf 'Open https://155.138.194.208.sslip.io/orchestra and https://155.138.194.208.sslip.io/specter\n'
printf 'Do not share audit token, mission token or API key. Real model and Docker demonstration still required.\n'
