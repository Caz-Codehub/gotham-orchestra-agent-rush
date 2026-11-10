#!/usr/bin/env bash
# CI simulation: replays .github/workflows/gotham-quality-gates.yml on a CLEAN CLONE of HEAD with a fresh venv,
# as a stand-in for the GitHub Actions runner. Usage: scripts/ci_local.sh [python-binary]   (default python3.12, matching CI)
# On a TLS-inspecting proxy export GOTHAM_BUILD_CA_BUNDLE; a real runner needs none.
set -uo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd); PYBIN=${1:-python3.12}
W=$(mktemp -d /tmp/gotham-ci-XXXX); T0=$(date +%s); R=0
step() { local n=$1; shift; local s=$(date +%s); echo "::group::$n"; if "$@" > "$W/$n.log" 2>&1; then echo "PASS  $n ($(( $(date +%s)-s ))s)"; else echo "FAIL  $n ($(( $(date +%s)-s ))s) -> $W/$n.log"; tail -15 "$W/$n.log"; R=1; fi; }
git clone -q --no-hardlinks "$HERE" "$W/repo" && cd "$W/repo" || exit 9
export GOTHAM_RUN_DOCKER_TESTS=1
step checkout        test -f .github/workflows/gotham-quality-gates.yml
step venv            $PYBIN -m venv "$W/venv"
step install         "$W/venv/bin/pip" install -q -r requirements.txt -r requirements-dev.txt
PY=$W/venv/bin/python
step scanner_venv    bash -c "$PYBIN -m venv .scanners && .scanners/bin/pip install -q -r requirements-scanners.txt"
step compile         $PY -m compileall -q gotham tests scripts
step build_images    $PY - <<'PY'
from gotham.core import sbx
for i in ('gotham-sandbox:latest', 'gotham-lab-target:latest', 'gotham-research:latest'):
    sbx.ensure_image(i); print('ready', i)
PY
step tests           $PY -m pytest -q -ra --maxfail=5 -p no:cacheprovider
step pip_audit_runtime  $PY -m pip_audit -r requirements.txt
step pip_audit_scanners $PY -m pip_audit -r requirements-scanners.txt --ignore-vuln CVE-2026-59951 --ignore-vuln CVE-2026-116685 --ignore-vuln CVE-2026-116684 --ignore-vuln CVE-2026-116686 --ignore-vuln CVE-2026-114603
step semgrep_selfscan .scanners/bin/semgrep scan --config rules/semgrep --metrics=off --error --severity ERROR gotham/core gotham/app.py
step credential_files $PY - <<'PY'
import subprocess,sys
tracked=subprocess.check_output(['git','ls-files'],text=True).splitlines()
bad=[p for p in tracked if p.split('/')[-1] in ('.env','id_rsa','id_ed25519','credentials.json','service-account.json') or p.endswith(('.pem','.key','.p12'))]
sys.exit(1 if bad else 0)
PY
echo "CI simulation finished in $(( $(date +%s)-T0 ))s, exit=$R (logs: $W)"; exit $R
