# Failure-mode analysis (FMEA) — Gotham 4.0

Method: (1) walk every component boundary asking "what if this is slow, dead, hostile, duplicated, or full?"; (2) turn each suspicion into a
probe that runs the real code; (3) fix what the probe proves broken; (4) keep the probe as a regression test.
**Found-by** column: `probe` = hypothesis confirmed/refuted by running code; `incident` = actually happened in this build session; `review` = reasoning only.

## A. Bugs proven by probes and fixed
| ID | Failure | Found-by | Impact before fix | Fix | Regression test |
|---|---|---|---|---|---|
| FM-01 | Concurrent `advance()` finalized the same mission up to 10× | probe | duplicate `mission_finalized` audit events, report rewritten | compare-and-swap `begin_finalize`; stale `finalizing` reset by recovery | `test_concurrent_advance_finalizes_exactly_once`, `test_stale_finalizing_is_reset_by_recovery` |
| FM-03b | Cancel of a RUNNING task left its container running; mission stayed `running` until the sandbox timed out | probe | cancel looked ineffective; resources burned | `Alfred.cancel` kills task containers (labelled `gotham-task`) then advances | `test_cancelling_a_running_task_kills_its_container_and_cancels_mission` |
| FM-02b | A hung task thread kept renewing its lease forever | review → probe | task never recovered | heartbeat stops after `deadline + GOTHAM_HEARTBEAT_GRACE_SECONDS` | `test_hung_task_stops_renewing_lease_and_is_reclaimed` |
| FM-06a | `capture_output` buffered unlimited container output in worker RAM | review → probe | OOM of the worker host by a printing container | streamed, tail-only bounded drain | `test_output_flood_is_bounded…` (400 MB output, worker RSS growth < 150 MB) |
| FM-06b | Bind-mounted workspace let sandboxed code fill the host disk | review → probe | host disk exhaustion (DoS) | 0.5 s watchdog, `GOTHAM_WORKSPACE_LIMIT_MB` (256) → `docker kill`, `quota_killed` flag | `test_workspace_disk_quota_kills_runaway_writer` |
| FM-07 | Container image would crash at boot: default audit path `/data-audit` unwritable; compose used named volumes the host worker cannot share | review | API down / missions never executed | Dockerfile sets `GOTHAM_AUDIT_DB=/audit/…`; compose uses bind mounts + uid | image build/run check (below) |
| FM-08 | Image builds fail on transient registry errors (Docker Hub 429 was observed in this session) | incident | CI flake / first-run failure | `ensure_image` retries 3× with back-off on 429/timeouts/TLS | `test_image_build_retries_transient_registry_errors` |
| FM-09 | `docker build` could not verify the TLS-inspecting proxy; my `\|\| true` hid the failed `pip install` and produced an image without pytest | incident | silent broken image | build verifies imports (`python -c "import pytest"`), CA injected via optional `ca.crt` | `test_sandbox_*` use the image; build fails loudly |
| FM-10 | Docker daemon died between steps (ephemeral container) | incident | every sandbox task failed | tools fail **closed** (no host execution), bounded retry, clear error; CLAUDE.md says how to restart | `test_docker_down_fails_closed_without_host_execution` |

| FM-14 | `AuditWriter.__init__` chmod 0700'd a pre-existing shared audit dir; the root-owned host worker locked the uid-10001 container API out of the journal/key (HTTP 500 on `/audit/verify`, `/infra`) | incident (found by running the container + host-worker split) | audit unreadable to the API | only restrict directories we create; `preflight` checks (ownership/permissions with actionable text), `/api/v4/preflight`, worker **exits 3** on failed preflight, `/infra` degrades per-component | `test_audit_dir_permissions_are_not_clobbered…`, `test_worker_refuses_to_start…`, `test_preflight_endpoint_and_infra_degrade_gracefully` |
| FM-15 | Unreadable `GOTHAM_BUILD_CA_BUNDLE` (`/root/...` as a non-root user) raised `PermissionError` and broke every image build; tests also assumed images already existed | **REAL GitHub Actions failure** (my root-run simulation missed it) | 9 failing tests in `tests.yml` | `ca_bundle_bytes()/usable_ca_path()` swallow `OSError`; `sbx.run` builds managed images on demand; no machine-specific path in conftest | `test_unreadable_ca_bundle_path_is_not_fatal_for_unprivileged_user`, `test_sbx_run_builds_managed_images_on_demand` |
| FM-16 | Quality-gates workflow dropped the `docker pull python:3.12-alpine` step the legacy tests need | **REAL GitHub Actions failure** | 2 failing legacy tests | step restored in both workflows | CI |
| FM-17 | `pip-audit` failed on transitive deps (`mcp`, `opentelemetry-api`) of Semgrep; Semgrep hard-pins them so they cannot simply be upgraded | CI simulation | red CI | Semgrep isolated in `.scanners` venv; runtime requirements audit-clean (hard gate); time-boxed documented exceptions | CI `pip_audit_*` steps |
| FM-18 | Own Semgrep rule flagged 3 f-string SQL statements in `store.py`; `?1` named params mixed with sequences (error in Python 3.14) | CI simulation | red self-scan; future break | static statements + `json_each`, named params | CI `semgrep_selfscan`; suite run with `-W error::DeprecationWarning` |
| FM-19 | My simulation script was edited while bash was executing it → crash mid-run | incident (own mistake) | steps silently skipped | rule: never edit a running script; always read the final summary line | — |

## B. Hypotheses probed and found already safe
| ID | Hypothesis | Result | Test |
|---|---|---|---|
| FM-02 | `../` / absolute seed paths escape the workspace | denied, task fails, nothing written | `test_seed_path_traversal_and_absolute_paths_are_refused` |
| FM-02c | caller overrides `workdir` to escape | engine owns `workdir` | `test_malicious_params_cannot_override_workdir_or_escape` |
| FM-02d | giant payload | rejected pre-planning (400 KB) and at HTTP edge (413 at 1 MB) | `test_oversized_*` |
| FM-03 | audit journal unwritable ⇒ tools run unaudited | tools raise before executing (fail-closed) | `test_audit_journal_unwritable_blocks_tool_execution` |
| FM-04 | two worker processes double-execute a task | 24 missions × 2 processes: every task `attempts == 1`, both processes did work | `test_two_worker_processes_never_double_execute` |
| FM-04b | a task longer than its lease gets stolen | heartbeat keeps the lease; `attempts == 1` | `test_task_longer_than_lease_is_not_stolen…` |
| FM-05 | worker SIGTERM loses work | exits 0 after in-flight work | `test_sigterm_lets_worker_exit_cleanly` |
| FM-11 | retry loop spins forever | bounded (2 attempts) → task and mission `failed` | `test_retry_exhaustion_fails_mission_instead_of_hanging` |
| FM-12 | DB reopen after restart / schema drift | `PRAGMA user_version` migrations, reopen idempotent | `test_schema_version_is_set_and_reopen_is_idempotent` |
| FM-13 | `kill -9` mid-task | lease lapses → orphan container removed → retried → verified | `test_recovery_after_worker_is_killed_mid_task` |

## C. Deployment / CD failure modes (simulated by `scripts/cd_simulate.sh`, 17 checks)
| Scenario | Expected behaviour | Result |
|---|---|---|
| Release does not compile | rejected **before** the symlink switch; service untouched | PASS |
| Release compiles but crashes at import | restart → health fails → symlink restored → previous release healthy again | PASS |
| Release fails the functional smoke test | rolled back (same path) | covered by code path; smoke gate exercised on good releases |
| Clone/pip failure | exit before any change | by construction (`die` before switch) |
| Data across releases | missions and audit chain intact; pre-deploy backup written + checksummed | PASS |
| Rollback target also unhealthy | exit code 2 + "restore from backup" message | not simulated |

## D. CI failure modes
**Lesson from real CI:** simulation is only as faithful as its environment. My first simulation ran as **root** on a machine that has `/root/.ccr/`, so it hid FM-15; the real runner is
unprivileged. `scripts/ci_local.sh` now supports `CI_RUN_AS=runner`. Real runs on GitHub are the ground truth and are checked via the Actions API: RED on `643ee58` (runs 42868196053 / 42868196204), GREEN on `adaf35b` (42882583863 / 42882583986); after fixing, the non-root simulation and the real runner produced identical counts (123 passed / 3 skipped).
(simulated by `scripts/ci_local.sh`: clean clone, fresh Python 3.12 venv, same steps as the workflows)
| Risk | Contingency |
|---|---|
| Python 3.12 vs 3.13 differences | CI sim runs 3.12 (the version in the workflow) |
| Images absent on a fresh runner | workflow builds them first; `ensure_image` retries; research image ≈ 10 min here (CI timeout 40 min) |
| `pip-audit` flags a new CVE in a dependency → red CI | surfaces real risk; fix by bumping the pin (do not skip the gate) |
| Docker Hub rate limit on the runner | retry/back-off; base images are cached on GitHub-hosted runners |
| Timing-sensitive tests (lease 2–3 s) on a slow runner | generous waits (≥ 30 s) and explicit polling instead of fixed sleeps |

## E. Residual risks (not fixed — owner/next-session actions)
1. Audit writer shares a process with workers (GOTHAM_BLOCKERS B6). 2. `install_deps` has open outbound network inside its container.
3. Workspace quota is enforced by a 0.5 s watchdog, so a burst can overshoot the limit briefly (test bound: < 120 MB with a 20 MB limit). 4. A host-level disk-full
still blocks SQLite writes; monitor `/api/v4/infra` `disk.used_pct`. 5. Docker socket access for the worker is root-equivalent on the host; keep the worker host dedicated.
6. No automatic alerting (Batman is notified only by the UI/health checks). 7. All LLM-dependent failure modes (hallucinated tool args, looping, injection) are exercised only
with a scripted model until B2 is cleared. 8. Rolling back after a future *non-additive* schema migration needs the pre-deploy backup (`deploy/restore.sh`).
