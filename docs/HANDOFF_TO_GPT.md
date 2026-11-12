# Gotham 4.0 — hand-off briefing (for GPT / any AI engineer continuing this work)

Prepared 2026-11-10 by Claude (Claude Code session). Read this first, then `docs/GOTHAM_STATUS.md`, `docs/GOTHAM_BLOCKERS.md`, `docs/GOTHAM_ACCEPTANCE.md`.
`CLAUDE.md` (Claude Code's convention) is duplicated as `AGENTS.md`; the instructions inside apply to you.

## 1. What this project is
Gotham = a multi-agent engineering / cyber-defense / research platform. Human authority is **Batman** → **Captain Alfred** (orchestrator) → five specialist workers
**Scout** (recon), **Forge** (software engineering), **Oracle** (research/notebooks/ML), **Sentinel** (defensive security), **Cipher** (security research, malware analysis, isolated lab);
plus **Specter**, an independent append-only audit journal. Owner: GitHub account `Caz-Codehub`, repo `gotham-orchestra-agent-rush`.

The Gotham **4.0** work is in `gotham/core/`. The older 2.x/3.x demo code (`gotham/app.py` legacy routes, `orchestras.py`, `specter.py`, …) is preserved but not extended.

## 2. Where everything is
- Branch: `claude/gotham-4-0-execution-8f66gu` (head = the tip of `gotham-4.0.bundle`). Draft PR **#3** into `main`: https://github.com/Caz-Codehub/gotham-orchestra-agent-rush/pull/3 . PR #1 (Clocked gateway, draft) untouched; PR #2 (quality gates) was incorporated.
- This package: `gotham-4.0-source/` (exact tree at HEAD), `gotham-4.0.bundle` (full git history; `git clone gotham-4.0.bundle gotham` then `git checkout claude/gotham-4-0-execution-8f66gu`), `MANIFEST.sha256`.

## 3. State of truth (verified, not aspirational)
| Claim | Evidence |
|---|---|
| Real GitHub Actions **green** on `adaf35b` | run 42882583863 (**123 passed, 3 skipped**, pip-audit runtime clean, scanner audit clean w/ 5 documented exceptions, Semgrep self-scan 0 findings) and 42882583986 (fast tier). Earlier `643ee58` was RED (unreadable CA path as non-root; missing docker pull) — fixed |
| Real execution, no mocked tools | `tests/test_v4_acceptance.py`: Forge repair+commit, Sentinel scans (Semgrep/secrets/config/pip-audit), Cipher YARA + sandboxed behaviour (approval-gated), scoped security lab, Oracle notebook + resumable training, five-agent mission, `kill -9` recovery, audit independence |
| 23 failure-injection tests | `tests/test_v4_resilience.py` (see `docs/GOTHAM_FAILURE_MODES.md`) |
| Local CD simulation 17/17 | `scripts/cd_simulate.sh` — releases, auto-rollback, data survival (local stand-in, **not** the Vultr host) |
| Command Center UI | `gotham/static/command.html`, verified manually in Chromium (desktop + 390 px). Not yet an automated test |

## 4. What is NOT done (do not claim otherwise)
1. **No LLM-driven agent mode has been run.** No model credential existed. `gotham/core/runtime.py` (tool-calling loop) is exercised only with a *scripted* decision source
   (`tests/test_v4_agent_runtime.py`, labelled). Alfred's planner is rule-based. `objective` missions fail closed ("BLOCKED"). To unblock: set
   `GOTHAM_INFERENCE_PROVIDER` (+ `GOTHAM_ALLOW_PAID_INFERENCE=I_ACCEPT_POTENTIAL_CHARGES` for Vultr, `VULTR_INFERENCE_API_KEY`, `VULTR_INFERENCE_MODEL`) then run the checklist at the end of `docs/GOTHAM_ACCEPTANCE.md`.
2. **Never deployed to Vultr.** The build sandbox's proxy returned 403 for `*.vultr.com`, `api.vultrinference.com`, and the earlier live host `https://155.138.194.208.sslip.io/`. The ~$198 Vultr credit / ~28k dev-platform credits are **unverified**. `deploy/deploy.sh` is verified only on a local stand-in.
3. Trivy container scanning (`container_scan`) — implemented, untestable (Docker Hub 429 / no DB mirror). GPU runs, URR Alpha/3.0, Kaggle backends — not integrated/tested. Forge `git push`/PR creation — not implemented. Disassembly/RE of non-Python binaries — not implemented.
4. Audit isolation limit: the audit **writer shares a process with workers** (agents/sandboxes cannot reach it, but a compromised worker process or host-root with the HMAC key could forge the chain). Planned fix: separate Unix-user audit service + off-host chain-head forwarding.
5. `install_deps` has open outbound network inside its container (needs an egress allowlist).

## 5. Run it
```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt
python3 -m venv .scanners && .scanners/bin/pip install -r requirements-scanners.txt     # Semgrep, isolated on purpose
docker info                                  # a Docker daemon is REQUIRED for sandboxed execution; images build on demand
GOTHAM_RUN_DOCKER_TESTS=1 python -m pytest -q -ra                    # ~1-2 min; research image build adds minutes first time
# product:
export GOTHAM_BATMAN_TOKEN=<>=20 chars> GOTHAM_OPERATOR_TOKEN=<>=20 chars> GOTHAM_DATA_DIR=./data GOTHAM_AUDIT_DB=./data-audit/specter.sqlite3
python -m gotham.core.worker &               # executes tasks (needs Docker)
uvicorn gotham.app:app --port 8000           # UI at /command, API at /api/v4
scripts/cd_simulate.sh                       # CD simulation;  scripts/ci_local.sh  (CI_RUN_AS=<user> for non-root parity)
```
Behind a TLS-inspecting proxy: export `GOTHAM_BUILD_CA_BUNDLE=/path/ca.pem` (readable by the running user). Run the API and worker as the **same uid** (FM-14; `/api/v4/preflight` diagnoses).

## 6. Architecture in 8 lines
`core/store.py` durable SQLite (leases, deps, retries, approvals) · `core/engine.py` Alfred (plan → dispatch → atomic finalize → evidence-based verify) · `core/worker.py` service ·
`core/tools.py` registry (allowlist, validation, approval gate, quota, audit) · `core/sbx.py` hardened Docker runner (no network, read-only, cap-drop, limits, output/disk caps) ·
`core/sectools.py`, `research.py`, `lab.py` capabilities · `core/audit.py` Specter (HMAC hash chain, UPDATE/DELETE blocked) · `core/api.py` + `static/command.html` control plane/UI.
Rule of the house: **verification re-checks tool evidence; agent prose is never trusted.**

## 7. Lessons that cost time (avoid repeating)
- A simulation is only as good as its environment: my CI simulation ran as root and missed bugs real (non-root) GitHub runners caught. Use `CI_RUN_AS`, and check real runs via the Actions API.
- Never edit a script while bash is executing it (crashed a long simulation silently). Always read the final summary line.
- `|| true` in a Dockerfile hid a failed `pip install`; builds now verify imports.
- SQLite WAL + two uids = permission traps; don't `chmod` directories you didn't create.
- Docker daemon in the Claude cloud container dies between steps: restart with `nohup dockerd &`.

## 8. Ground rules the owner set (keep following them)
Execute, don't plan. Never mock agents/tools in acceptance evidence; report PASS/FAIL/BLOCKED/NOT TESTED honestly. No unauthorised spend; paid inference needs the double opt-in. No secrets in the repo or in logs.
Active security testing only against the local lab, approval-gated and scope-checked. No malware generation, persistence, stealth or unauthorised targets. Ask Batman only for new permissions, spending, irreversible deletion, or security-sensitive access.
Dummy values in `scripts/cd_simulate.sh` (`batman-token-0123456789abcdef`, …) are simulation-only; real tokens must come from the environment.

## 9. Suggested next actions (priority order)
1. Obtain a model credential → run agent-mode acceptance; add model-assisted planning to `Engine._plan`.
2. Unblock Vultr egress → verify credits, run `deploy/deploy.sh` + `deploy/smoke_test.sh` on the VM, record in `docs/GOTHAM_DEPLOYMENT.md`.
3. Audit sink as a separate service (B6); egress allowlist for `install_deps`.
4. Automate the Playwright UI checks in CI; move `dataset_validate` into the sandbox.
5. `git_push`/PR tool behind approval; URR/Kaggle backends; Trivy once a DB mirror exists.
