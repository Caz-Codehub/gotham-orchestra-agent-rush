# Gotham 4.0 — falsification-based orchestral acceptance standard

## What the hypotheses mean

For each contract below, **H0** is "the named component works according to its declared requirements"; **H1** is "there is at least one material violation of those requirements." Tests try to falsify H0 through deliberately adverse inputs, negative controls, fault injection and authentic sandbox execution.

* A failed requirement rejects H0 for that requirement.
* Passing a test **does not prove H0 or establish H1 is false**; it only means the exercised counterexamples did not falsify H0. Report the checked cases, coverage and residual risks.
* No p-values, significance levels, confidence intervals or statistical claims are warranted by deterministic unit tests alone. Those would require a sampling plan and an error model.
* No orchestral component can be called **operational** solely because its classes exist, its model replies, or unit tests pass.

## Per-orchestra hypothesis matrix

| Orchestra | H0 under challenge | H1 falsification targets | Minimum evidence for stage acceptance |
|---|---|---|---|
| Software / Forge Commander / three specialists | Supplied source can be built, changed, tested and committed in the sandbox | Failing tests, bad/missing source, nonexistent tool permissions, forged test pass, missing commit, container not destroyed | Real Docker test with failing **and** passing fixtures; verified before/after test receipts, commit hash, artifact integrity, no network privilege |
| Research / Research Commander / three specialists | Notebook name and cells are accepted, and all code cells execute in a bounded research sandbox | Wrong filename/cell schema, exception in cell, timeout, skipped execution, unsupported image, fake output | Real Jupyter execution receipt; code-cell count equals executed count; checksum of exported notebook, reproducibility rerun for deterministic fixtures |
| Cyber Defense / Defense Commander / three specialists | Authorized files are examined by the named scanners and expected weakness fixtures are detected | Empty input, scanner missing, missed seeded secret/config rule, false "clean" outcome, injection-laundered tool text | Semgrep, secret scanner and configuration scanner run; seeded expected findings detected; errors fail closed; output grounded to file paths and rules |
| Authorized Security Lab / Lab Commander / three specialists | A disposable lab can be started, probed *inside scope*, compared to expected vulnerability state and destroyed | Out-of-scope target accepted, container remains, fake vulnerability finding, unrestricted malware execution, missing authorization | Owner scope, Batman approval, real offline Docker lab, deliberate denied outside-scope probe, teardown proof and vulnerability/secure-fixture comparison |

## System-wide hypotheses

- **Hierarchy H0:** Batman → Alfred → four distinct captains → 12 scoped specialist identities; Specter is independent. H1: bypass, alias collision, unauthorized reporting or role confusion. Counterexample probes: missing specialist/captain, dependency skips, malformed report and unauthorized auditor reads.
- **Pre-model protection H0:** model requests are screened, private audit identity is not in prompts, and an append-only receipt commits before inference. H1: prompt/secret leak, model invoked when audit store unavailable, evidence silently bypasses the security boundary. Test with deliberate injection strings and simulated audit failure. Separate process isolation remains unverified.
- **Approval H0:** no high-risk execution launches without explicit Batman approval. H1: operator request alone runs sandbox/lab or an unapproved task is claimed. Test authorization and task lifecycle.
- **CI/CD H0:** no unvalidated commit reaches staging, no staging commit silently reaches production. H1: deployment from failed tests, wrong commit, credentials leaked, missing rollback, or accidental port-8000/Caddy modification. Require source SHA, GitHub CI receipts, staging API+worker checks and rollback.
- **Live inference H0:** bounded local-Qwen runs finish with structured evidence and all 21 tasks complete. H1: timeouts, invalid JSON, missing specialist reports, budget exhaustion. Current Vultr real-model acceptance **rejected H0** (timeouts and missing findings), so **production promotion is blocked**.

## CI/CD decision gates

1. **PR / pull-request check:** static compile and test imports; test four adapters and 12 role IDs; falsification tests including rejected inputs, denied approvals, audit outages, prompt injection and malformed model responses. Independent audit integrity tests. Do not claim real execution at this gate.
2. **Real Docker quality gate:** Forge code tests, Oracle executed notebook, Sentinel known-vulnerable fixtures and Cipher isolated lab scope/teardown. Zero unjustified failures. Root-only test skips must be accounted for.
3. **Immutable staging:** only exact commit that passed both GitHub checks may be uploaded with checksum; private localhost port 8001, rootless isolated user, separate persistent data/audit and rollback. Production service is not a deployment target.
4. **Real local-model acceptance:** actual 4 captain plans + 12 specialist completions + 4 captain reviews + Alfred synthesis; 21 durable task receipts and independent audit chain; no mock outputs. This is presently red.
5. **Permission-gated execution acceptance:** each selected orchestra needs a real approved tool/sandbox receipt. Source inspection, model statements, roster completeness, and synthetic fixture responses are **not equivalent** to autonomous execution.
6. **Promotion:** requires explicit owner approval, clean CI, latest staging+live-model+real-workload receipts, backups, monitoring, rollback and security review of Specter's process boundary. Never automatically promote from `main` or the development branch.

## Verified code-review findings (2026-11-11)

- **F-01: Research adapter mismatch, corrected.** Prior validation accepted `name="experiment.ipynb"` and `cell_type` cells; the actual `notebook_create` tool requires a bare `name` and `{type,source}` cells. Tests now reject incompatible schemas.
- **F-02: Lab wrong playbook, corrected.** Prior executor mapped the Authorized Lab to `malware_triage`. This did not test lab start, scope denial or teardown. It now maps to `Cipher/lab_validation`.
- **F-03: Empty and malformed execution payloads, corrected at plan time.** Empty source maps, invalid cell lists, and sample payloads injected into lab-validation are rejected before scheduling.
- **F-04: Missing real-model reliability, OPEN.** The last Vultr acceptance run failed because of Qwen timeouts and missing required structured findings. Reasoning-only audits cannot erase this failure.
- **F-05: Scoped evidence execution on staging, OPEN.** `gothamdeploy` deliberately does not have the Docker socket; four real orchestra tool executions need a separately hardened sandbox operator and Batman approvals.
- **F-06: Specter independent process isolation, OPEN.** Hidden audit metadata is protected by role and prompt boundaries, but same-process/audit-key authority has not been fully split.

## Status language

Use `defined`, `test-passing`, `staging-deployed`, `live-model-accepted`, `sandbox-workload-verified`, `production-ready`. These labels are **not interchangeable**. Any failed acceptance gate overrides optimistic estimates.
