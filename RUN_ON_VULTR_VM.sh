#!/usr/bin/env bash
# Assisted deployment of the isolated Gotham hackathon MVP on fresh Ubuntu 24.04 Vultr VM.
# Never run on the user's laptop. Doesn't create a server or install paid Vultr services.
set -Eeuo pipefail
if [[ "$(id -u)" != 0 ]]; then echo 'Run: sudo bash RUN_ON_VULTR_VM.sh' >&2; exit 1; fi
cd "$(dirname "$0")"
[[ -f scripts/deploy_vultr_ubuntu.sh ]] || { echo 'Missing deployment script' >&2; exit 1; }
echo 'GOTHAM: Agent Rush C1 Deployment on Vultr Ubuntu 24.04'
echo 'IMPORTANT: A successful gift code is NOT proof of remaining credit.'
echo 'Check Vultr Billing > Remaining Credit before proceeding.'
printf 'Confirm your Vultr Remaining Credit is positive (type YES): '
read -r confirm
[[ "$confirm" == YES ]] || { echo 'STOP: Credit not confirmed'; exit 2; }
printf 'Public IPv4 address shown on the Vultr VM page: '
read -r public_ip
python3 - "$public_ip" <<'PYIP'
import sys,ipaddress
try: ip=ipaddress.ip_address(sys.argv[1]); assert isinstance(ip,ipaddress.IPv4Address) and ip.is_global
except Exception: raise SystemExit('Invalid public IPv4')
PYIP
printf 'Serverless Inference model ID [deepseek-v4.1-flash-1017]: '
read -r model
model=${model:-deepseek-v4.1-flash-1017}
[[ "$model" =~ ^[a-zA-Z0-9._:/-]+$ ]] || { echo 'Unexpected model id characters'; exit 2; }
echo 'Paste Vultr SERVERLESS INFERENCE API key (hidden); do not use the general Vultr API key.'
read -rs -p 'Vultr Serverless Inference key: ' api_key; echo
[[ -n "$api_key" ]] || { echo 'Key is empty'; exit 2; }
[[ "$api_key" =~ ^[a-zA-Z0-9._:-]+$ ]] || { echo 'Key has unexpected characters. Use the raw API key, no quotation marks.'; exit 2; }
read -r -p 'Allow metered serverless inference usage against credits? Type YES: ' optin
[[ "$optin" == YES ]] || { echo 'STOP: no inference authorization'; exit 2; }
if ! command -v openssl >/dev/null; then
  apt-get update && apt-get install -y openssl
fi
mission=$(openssl rand -hex 32)
audit=$(openssl rand -hex 32)
if [[ -e /etc/gotham.env ]]; then
  echo '/etc/gotham.env already exists. Refusing to overwrite live credentials.' >&2
  exit 3
fi
umask 077
cat > /etc/gotham.env <<EOF
GOTHAM_ACCESS_TOKEN=$mission
GOTHAM_BATMAN_TOKEN=$audit
GOTHAM_INFERENCE_PROVIDER=vultr
GOTHAM_ALLOW_PAID_INFERENCE=I_ACCEPT_POTENTIAL_CHARGES
VULTR_INFERENCE_API_KEY=$api_key
VULTR_INFERENCE_MODEL=$model
GOTHAM_MAX_MODEL_CALLS=12
GOTHAM_SANDBOX_IMAGE=python:3.12-alpine
GOTHAM_SPECTER_STALE_SECONDS=90
EOF
chmod 600 /etc/gotham.env
unset api_key
export GOTHAM_CREDITS_VERIFIED=YES GOTHAM_PUBLIC_IP="$public_ip"
echo 'Starting system installation...'
bash scripts/deploy_vultr_ubuntu.sh
printf '\nMISSION TOKEN: %s\nBATMAN AUDIT TOKEN: %s\n' "$mission" "$audit"
echo 'Store both tokens in a password manager, never in GitHub or screenshots.'
echo 'Do not type them in this chat. They are not stored in your local Gotham Windows credential store.'
echo 'If you want judges to interact, provide a demonstration account with narrow permissions; NEVER share Batman audit token.'
echo 'IMPORTANT: Stopping/turning off a Vultr VM does not stop billing. DESTROY VM after event if not needed.'
