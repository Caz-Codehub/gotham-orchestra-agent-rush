#!/usr/bin/env bash
# Linux/macOS zero-cloud-cost launcher; run from extracted project root.
set -euo pipefail
cd "$(dirname "$0")/.."
MODE="${1:-offline}"
if [[ "$MODE" != 'offline' && "$MODE" != 'ollama' ]]; then
  printf 'Usage: bash scripts/start_unix.sh [offline|ollama]\n' >&2; exit 2
fi
export GOTHAM_INFERENCE_PROVIDER="${MODE/offline/none}"
export GOTHAM_ALLOW_PAID_INFERENCE=''
export GOTHAM_OLLAMA_MODEL="${GOTHAM_OLLAMA_MODEL:-qwen2.5:1.5b}"
export GOTHAM_ACCESS_TOKEN="${GOTHAM_ACCESS_TOKEN:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')}"
export GOTHAM_BATMAN_TOKEN="${GOTHAM_BATMAN_TOKEN:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/gotham"
mkdir -p "$DATA"; chmod 700 "$DATA"
export GOTHAM_LEDGER_PATH="${GOTHAM_LEDGER_PATH:-$DATA/missions.sqlite3}"
export GOTHAM_SPECTER_DB="${GOTHAM_SPECTER_DB:-$DATA/specter.sqlite3}"
if [[ ! -x .venv/bin/python ]]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
.venv/bin/python scripts/preflight.py --mode objective
printf '\nGOTHAM 2.1 | LOCAL $0 CLOUD CHARGES\nURL: http://127.0.0.1:8000\nMission token: %s\nBatman audit token: %s\n' "$GOTHAM_ACCESS_TOKEN" "$GOTHAM_BATMAN_TOKEN"
printf 'Treat tokens like passwords. Local AI requires Ollama installed and running. Code execution requires Docker.\n'
exec .venv/bin/python -m uvicorn gotham.app:app --host 127.0.0.1 --port 8000 --workers 1
