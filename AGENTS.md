# CLAUDE.md — Gotham 4.0 resumption guide

Gotham = Batman (human) → Captain Alfred → Scout/Forge/Oracle/Sentinel/Cipher, with an independent audit component (Specter).
Gotham 4.0 lives in `gotham/core/`; the older 2.x/3.x demo code (`gotham/app.py` legacy routes, `orchestras.py`, …) is preserved, not extended.

## Resume procedure (do this first in a new session)
1. `git fetch && git checkout claude/gotham-4-0-execution-8f66gu` (or its successor); read `docs/GOTHAM_STATUS.md` (ledger), then `docs/GOTHAM_BLOCKERS.md`.
2. Environment: `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt`.
3. Docker: `docker info` must work (in the Claude cloud container start it with `nohup dockerd &`). Images build on demand
   (`gotham.core.sbx.ensure_image`). Behind a TLS-inspecting proxy export `GOTHAM_BUILD_CA_BUNDLE=/root/.ccr/ca-bundle.crt`.
4. Run everything: `GOTHAM_RUN_DOCKER_TESTS=1 python -m pytest -q -ra` (≈40 s with images present). Record results in `docs/GOTHAM_ACCEPTANCE.md`.
5. Run the product: worker `python -m gotham.core.worker` + API `uvicorn gotham.app:app`; UI at `/command`. Env: `GOTHAM_BATMAN_TOKEN`,
   `GOTHAM_OPERATOR_TOKEN` (≥20 chars), `GOTHAM_DATA_DIR`, `GOTHAM_AUDIT_DB` (keep OUTSIDE the data dir).

## Architecture in one paragraph
`Store` (SQLite WAL) holds missions/tasks/approvals/artifacts/usage. `Alfred.submit` plans tasks; workers `claim_next` with leases;
`Alfred.execute_task` runs a playbook (deterministic tool sequence) or, in agent mode, `runtime.run_agent` (needs a real model).
Every capability is a tool in `tools.REGISTRY` with per-agent allowlists, approval gating, quotas and audit; untrusted code only runs through
`sbx.run` (Docker: no network, read-only, cap-drop, limits). `AuditWriter/AuditReader` = Specter's append-only HMAC chain (separate file).
`Alfred.finalize` re-verifies structured evidence (`verify_tasks`) — never trust agent prose.

## Rules for contributors (human or AI)
- Never mock tools in acceptance tests. A scripted model is allowed ONLY to test loop plumbing (`tests/test_v4_agent_runtime.py`) and must be labelled.
- Mark results PASS / FAIL / BLOCKED / NOT TESTED honestly. No model configured ⇒ agent-mode is BLOCKED, never simulated.
- Never commit secrets; tokens come from env. Never give agents the audit handle, credentials, or paths outside their workspace.
- Active security testing only against the local lab (`gotham/core/lab.py`), always approval-gated and scope-checked.
- Keep milestones small: implement → execute → test → commit → push → update `docs/GOTHAM_STATUS.md`.
