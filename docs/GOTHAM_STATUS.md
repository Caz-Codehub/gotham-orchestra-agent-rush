# Gotham 4.0 development ledger

_Last updated: 2026-11-10 (session 1, hardening pass). Branch `claude/gotham-4-0-execution-8f66gu`._
**Real GitHub Actions on `adaf35b`: both workflows GREEN** — quality-gates run 42882583863 (**123 passed, 3 skipped**, runtime pip-audit clean, scanner audit clean with 5 documented
exceptions, Semgrep self-scan 0 findings, credential-file check) and `tests.yml` run 42882583986. History: the same branch at `643ee58` was **RED** on both workflows
(non-root runner exposed FM-15/16); fixed in `16a9099`…`adaf35b`. The 3 skips are tests that need root to simulate a second uid (they pass locally as root).

## Repository audit (starting point)
- `main` = Gotham 2.x/3.x demo: single-mission Docker code-repair, static agent labels, in-memory single-lock execution, SQLite ledger of receipts, rule-based Specter journal.
  50 tests passed (2 Docker tests pass when a daemon is present). Not a multi-agent platform; agents without a model were rule stubs.
- PR #2 (quality-gates workflow): validated and **incorporated** (cherry-picked `77ca1b6`, then extended to build images and run the full suite).
- PR #1 (Clocked gateway, draft): untouched; needs a real Clocked key (B8).
- Live site `https://155.138.194.208.sslip.io/`: unreachable from the build session (proxy 403) → **not verified**.

## Completed components (commits)
| Commit | What |
|---|---|
| `8fd0e57` | PR #2 CI quality gates |
| `9729271` | core: store, audit, auth, tools, sandbox, security + research + lab tools, Alfred, worker, 32 tests |
| `7368dac` | API v4, Command Center UI, agent runtime, deploy assets, docs, CLAUDE.md |
| `643ee58` | fuzzing tool, strict five-agent acceptance, research image fixes, acceptance + status docs |
| `0ac65ac` | failure-mode fixes (finalize race, cancel, hung lease, body limit, schema version), resilience tests, CD simulation |
| `c01f9e3` | audit-dir clobber fix, preflight, sandbox output/disk limits, scanner isolation, SQL hardening, container verification |
| `16a9099` | fixes for failures found by real CI; non-root CI simulation |
| `adaf35b` | hermetic legacy DB paths; CI pull retries — **real CI green** |

## Environment facts
Ephemeral container; Docker daemon started with `nohup dockerd &`; Docker-build TLS needs `GOTHAM_BUILD_CA_BUNDLE`; research image build ≈ 10 min over the proxy (922 MB);
sandbox image 197 MB. No GPU. No inference credentials. Egress blocked to Vultr.

## Resource usage
Spend: **$0** (no paid services activated, no cloud calls). Local images ≈ 1.2 GB.

## Known defects / limitations
- Audit writer shares a process with workers (B6). `install_deps` has open outbound network inside its container.
- Command-center UI verified manually with Playwright, not yet an automated test in CI.
- `dataset_validate` parses CSV with pandas on the host (small, size-capped); should move into the sandbox.
- Lab/probe catalogue is fixed and tiny; Sigma support covers selections with contains/startswith/endswith/re and and/or/not conditions only.
- Legacy 2.x routes (`/api/missions`, `/orchestra`, `/specter`) remain and use legacy tokens/single lock.

## Unresolved blockers
See `GOTHAM_BLOCKERS.md` (B1–B8).

## Next executable actions (in order)
1. Audit sink service on its own Unix user + off-host chain-head forwarding (B6).
2. Automate the Playwright UI checks in CI; move `dataset_validate` into the sandbox.
3. Egress allowlist (PyPI only) for `install_deps` via a proxy sidecar network.
4. Once B2 is cleared: run the Agent-mode acceptance checklist and model-assisted planning.
5. Once B1 is cleared: run `deploy/deploy.sh`, `deploy/smoke_test.sh` on the Vultr VM, verify credits, record in `GOTHAM_DEPLOYMENT.md`.
6. `git_push`/PR tool behind approval (B7); URR/Kaggle research backends (B4).
