# Gotham 4.0 acceptance record

Legend: **PASS** executed for real and asserted · **FAIL** · **BLOCKED** needs an owner action (see GOTHAM_BLOCKERS.md) · **NOT TESTED**.
Environment of record: Claude cloud container (Linux, 4 vCPU, 16 GB, no GPU), Docker 29.9 daemon started in-session, Python 3.13, 2026-11-10.
Reproduce: `GOTHAM_RUN_DOCKER_TESTS=1 python -m pytest -q -ra` → **124 tests (≈90 s)**; on 2026-11-10 a clean-clone Python 3.12 run reported 122 passed + 2 skipped-by-environment (see FAILURE_MODES FM-14 note).
**Real GitHub Actions status: FAILED on `643ee58`, fixes pending a re-run** — do not treat this document as CI-green evidence until the Actions run is green. No mocked tools; one scripted-model suite is labelled below.

| # | Acceptance item | Result | Evidence (test) |
|---|---|---|---|
| 1 | **Software engineering**: Forge creates/modifies a real project, runs tests in a sandbox, sees 1 failing test, applies a supplied repair, re-runs (2 pass), commits on a branch, exports a patch artifact | **PASS** | `test_forge_repairs_defect_tests_pass_and_commit_is_real` (checks real `git log`, file content, container destroyed) |
| 1b | Forge without any repair source fails closed (no pretend repair) | **PASS** | `test_forge_without_repair_source_fails_closed` |
| 1c | **Autonomous (LLM) defect repair** | **BLOCKED (B2)** | No model credential. Loop plumbing verified with a *scripted* decision source only (`test_forge_agent_mode_repair_is_reverified_by_real_tests`, `test_lying_model_claim_does_not_verify`) — not evidence of model capability |
| 2 | **Cyber defense**: Sentinel scans an authorized project; detects 5 planted weakness classes (eval, shell=True, SQLi, hard-coded secret, MD5) with Semgrep, a committed key, Docker misconfig, and a vulnerable pinned dependency via pip-audit; hash-verified report; findings identical on re-run | **PASS** | `test_sentinel_detects_introduced_weaknesses_with_reproducible_report` |
| 2b | Log correlation (brute-force → success-after-failures), Sigma-compatible rule evaluation, secrets/config audit | **PASS** | `test_log_*`, `test_sigma_*`, `test_secrets_and_config_scanners`, API `test_log_analysis_mission…` |
| 2c | Container image scanning (Trivy) | **BLOCKED (B3)** | tool implemented, fails closed without Trivy |
| 3 | **Malware analysis**: Cipher analyses an approved inert sample: hashes, IOCs, entropy, YARA rule generated and validated (positive+negative), dynamic behaviour in an isolated container (socket.connect, file open captured) — only after Batman approval | **PASS** | `test_cipher_malware_analysis_static_and_isolated_behavior_with_approval` (asserts nothing ran before approval; sample marker not on host) |
| 3b | Controlled fuzzing finds planted crashes, reproducible by seed | **PASS** | `test_fuzzer_finds_planted_crash_in_sandbox_reproducibly` |
| 3c | Disassembly / binary reverse engineering of non-Python samples; Windows/PE dynamic analysis | **NOT TESTED / not implemented** | static ELF/PE header parsing only |
| 4 | **Security lab**: scoped validation of a deliberately vulnerable local target on an internal-only network: detects SQLi-bypass, path traversal, reflected XSS, missing headers; hardened build verified clean; out-of-scope target refused and audited; containers cleaned | **PASS** | `test_security_lab_scoped_validation_and_remediation_check` |
| 5 | **Research**: Oracle creates a notebook, executes it in the sandboxed kernel, saves executed notebook/metrics, training interrupted then resumed from checkpoint; failing notebook never marked complete | **PASS** | `test_oracle_notebook_executes_and_training_resumes_from_checkpoint`, `test_failing_notebook_is_never_marked_complete` |
| 5b | GPU experiments; URR Alpha/3.0, Kaggle, GitHub-Actions research backends | **BLOCKED (B4, B5)** | |
| 6 | **Orchestration**: Alfred delegates real work to all five specialists, dependency order + concurrency respected, structured task messages, per-agent receipts, Specter shows tool calls from all five, mission verified from evidence | **PASS** | `test_alfred_delegates_real_work_to_all_five_agents` |
| 6b | Mission planning/decomposition by a model | **BLOCKED (B2)** | planner is rule-based and labelled so in `/api/v4/agents` |
| 7 | **Recovery**: worker process SIGKILLed mid-task; lease expires; restarted worker recovers, removes orphan container, retries, mission verified; audit shows `recovery_requeued` | **PASS** | `test_recovery_after_worker_is_killed_mid_task` (real subprocess) |
| 7b | Store/lease semantics: expired lease re-queue, retry budget, stale-worker overwrite refused, cancel, idempotent submit, approval finality | **PASS** | `test_store_*` group in `test_v4_core.py` |
| 8 | **Audit**: Specter records authorization→finalization independently; UPDATE/DELETE rejected; out-of-band edit/deletion detected; tools cannot reach the journal; sandboxes cannot see it; writer has no read surface; Batman-only API | **PASS** | `test_audit_*`, `test_agent_cannot_touch_audit_journal_via_tools`, `test_specter_independently_records…`, API `test_audit_endpoints_are_batman_only` |
| 8b | Audit isolation against a compromised worker *process* / host root | **NOT ACHIEVED (B6)** | documented limitation |
| 9 | **Sandbox containment**: no network, read-only root, uid 65534, infinite loop killed at timeout and container destroyed | **PASS** | `test_sandbox_containment_flags_and_timeout_kill` |
| 10 | **Security governance**: role separation (viewer/operator/batman), weak-token rejection, lockout, approval gates Batman-only, high-risk tools denied without approval, quotas, cancellation, path-traversal/symlink denial, prompt-injection flagging | **PASS** | `test_roles_*`, `test_failed_auth_lockout`, `test_high_risk_*`, `test_tool_call_quota_*`, `test_path_traversal_*`, `test_prompt_injection_*`, API tests |
| 11 | **Command Center**: chat, mission submit/history/detail, agents, engineering/research/cyber/lab workspaces, approvals, artifacts (hash-verified preview/download), audit, budget, infra, recovery, error log; desktop + 390 px mobile, no horizontal scroll, no JS errors | **PASS** (manual Playwright run; not yet an automated test) | session log: cyber audit → verified in UI, approval cards shown, audit chain VALID (39 entries), operator denied audit |
| 12 | **Deployment (local staging)**: health, unauthenticated rejected, operator cannot read audit, worker executes mission, artifact retrieval with integrity check, audit valid, 404 handling | **PASS** 7/7 | `deploy/smoke_test.sh` against local API+worker |
| 12b | **Deployment (Vultr production)**, systemd units, `deploy.sh` rollback on a real host, backups on schedule | **BLOCKED (B1)** | scripts written, `bash -n` only; backup/restore executed locally (PASS) |
| 12c | **CD simulation** (`scripts/cd_simulate.sh`): good release, non-compiling release refused, import-crash release auto-rolled-back, smoke-gated release, data + audit chain survive, pre-deploy backup | **PASS** 17/17 (local stand-in; not the Vultr host) | |
| 12d | **Container deployment**: hardened API image (non-root, read-only root, no caps) + host worker sharing bind mounts runs a mission to `verified`; audit chain valid; preflight endpoint | **PASS** (local Docker) | |
| 12e | **Resilience suite**: 23 failure-injection tests (concurrent finalize, cancel-running, hung lease, double-worker, long task vs lease, SIGTERM, docker-down, audit-down, oversized body/output/disk, mixed-uid, schema reopen) | **PASS** | `tests/test_v4_resilience.py` |
| 13 | Vultr credit verification (~$198) / dev-platform credits (~28k) | **BLOCKED (B1)** | |
| 14 | Git push / PR creation by Forge | **NOT IMPLEMENTED (B7)** | |

## Agent mode (needs B2 resolved) — checklist to run once a model is configured
1. `GOTHAM_INFERENCE_PROVIDER=…` set; `/api/v4/agents` shows `model_configured: true`.
2. Submit `engineering` mission *without* `patch`: Forge must repair via `run_agent`; `repaired_by` must read `model:<provider>` and `tests_after.ok` must be true.
3. Submit `objective` mission; verify Specter shows `model_decision` events and tool calls by the chosen agent.
4. Re-run injection test files through a real model and confirm no unpermitted tool executes.
