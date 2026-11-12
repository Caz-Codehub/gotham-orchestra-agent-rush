# Gotham 4.0 — Simplified deployment handoff

**Created:** 2026-11-11. **Status:** GitHub automation prepared; remote server access NOT CONNECTED.

## What is actually verified
- Existing Vultr VM runs Ubuntu, Docker, Caddy, legacy Gotham, Specter and local Ollama; previous server receipts showed a 200 from legacy `/health`.
- The previous deployment responds 404 on `/api/v4/agents` and `/api/v4/preflight`. It is **not** Gotham 4.
- Gotham 4 source was cloned at `/opt/gotham-v4-staging/source`, ref `4f81fe7` at that time.
- The user's VM test results: **119 passed, 2 failed, 5 skipped** before Semgrep was installed. After isolated Semgrep installation, **both failed tests passed**. This does NOT prove the whole suite passed on the VM.
- GitHub's independent CI for commit `14533dd` completed its unit/Docker and quality-gate jobs successfully. Later commits require independent status review.

## One-click workflow structure
- `.github/workflows/gotham-staging-release.yml` lives on `main`, uses the Gotham 4 development branch for a test-gated *downloadable release*, and never connects to a host.
- `.github/workflows/gotham-staging-deploy.yml` lives on `main`; manual action only, explicit `STAGING_ONLY` confirmation, and requires the opt-in repository variable `GOTHAM_STAGING_DEPLOY_ENABLED=true`.
- `deploy/stage_side_by_side.sh` lives on the v4 development branch. It creates an isolated Linux service `gotham-v4-staging` listening **only** on `127.0.0.1:8001`, with separate storage, tokens and Ollama-only inference. It does not change production `gotham.service`, Caddy, or public routing.

## Exact remaining authorization boundary
Remote deployment is **not available** because there is no working authenticated SSH key from GitHub Actions to the user's Vultr VM. The user attempted to authorize a Windows key but SSH installation and root password authentication did not succeed; do not assume the VM trusts that key.

To activate GitHub staging deployment later, the repository needs ALL of:
1. An owner-approved dedicated SSH deployment credential installed on the Vultr VM, preferably belonging to a narrowly privileged deployment account (workflow currently expects `root`, so harden the account and update the workflow before production use).
2. GitHub repository Actions secret `GOTHAM_STAGING_SSH_KEY` containing the corresponding **dedicated** private key, which must be unencrypted for CI. Do not use or upload the user's personal Windows key.
3. GitHub repository Actions secret `GOTHAM_STAGING_KNOWN_HOSTS` with the verified Vultr **server host public key** (not the user's client key), using a trusted fingerprint comparison.
4. GitHub repository Actions variable `GOTHAM_STAGING_HOST=155.138.194.208` and `GOTHAM_STAGING_DEPLOY_ENABLED=true`.
5. Owner approval via workflow dispatch input `STAGING_ONLY`.

No secrets can be inferred or generated here for an account to which the assistant has no SSH/API access. Do not ask the user to paste secrets into chat.

## Safety gates and acceptance
- No automatic production cutover.
- `set -e` in scripts, versioned release archive checksum, isolated directory, API health check, production `systemctl is-active gotham` guard.
- No paid Vultr inference. Staging `GOTHAM_INFERENCE_PROVIDER=ollama` uses `qwen2.5:1.5b`. Clocked remains **unconfigured** for Gotham.
- **Important:** staging service presence and `/api/v4/health` do NOT prove that workers execute autonomous model-driven missions. That requires separately configured workers, audit/access checks, and full end-to-end acceptance.
- The user's reported $199 Vultr promotional balance and 20,000 Clocked credits have not been verified directly by these workflows. Existing VM rental continues to accrue charges.

## Simplified next user interaction
Do not make the user juggle PowerShell, Vultr's browser console, and Colab again just to run CI. Tests and artifacts run in GitHub. Pause at the deployment-authentication boundary; propose one short, secure, owner-approved connection/setup session. Then use GitHub Actions for repeated deployments and reports.
