# Gotham 4.0 architecture

```
Batman ──(Bearer token, role=batman)──► Command Center (/command) ──► /api/v4  (FastAPI, gotham/core/api.py)
                                              │                          │ submit / approve / cancel / retry / audit
                                              ▼                          ▼
                                   Store (SQLite WAL, gotham/core/store.py)  ◄──── Alfred (engine.py): plan, verify
                                     missions · tasks(leases, deps) · approvals · artifacts · usage · messages
                                              ▲ claim_next / heartbeat / finish
                                   Worker service (worker.py, N threads) ──► playbooks / runtime.run_agent
                                              │ every action
                                              ▼
                                   tools.call()  ─ allowlist ─ validate ─ approval gate ─ quota ─ deadline ─►  tool
                                              │                                                              │
                                              ▼                                                              ▼
                                   AuditWriter (record-only) ──► Specter journal (separate file, HMAC chain)   sbx.run → Docker sandbox
```

## Components
| Concern | Where | Notes |
|---|---|---|
| Durable state | `core/store.py` | Leases (default 30 s), bounded retries (2), dependency blocking, idempotency keys, cancel flag, approvals, usage metering |
| Orchestration | `core/engine.py` | Mission kinds: engineering, security_audit, log_analysis, malware_analysis, research, lab_validation, full_spectrum, objective (model-only) |
| Execution | `core/playbooks`, `core/runtime.py` | Playbooks = fixed audited tool sequences (no model). Agent mode = JSON tool-calling loop, needs a configured model |
| Tools | `core/tools.py`, `sectools.py`, `research.py`, `lab.py` | 34 tools; per-agent allowlists; `risk=high` needs Batman approval |
| Sandbox | `core/sbx.py` | `--network none --read-only --cap-drop ALL --security-opt no-new-privileges --user 65534 --pids/mem/cpu limits`, destroyed-container proof, task labels for orphan cleanup |
| Specter | `core/audit.py` | Separate SQLite file+key; UPDATE/DELETE triggers abort; HMAC chain; writer/reader split; secret redaction |
| Auth | `core/auth.py` | Roles batman/operator/viewer; tokens ≥20 chars from env; constant-time compare; lockout after 10 failures/5 min/IP |
| UI | `static/command.html` | Single responsive page; every control calls `/api/v4` |

## Security properties and their limits
- Untrusted code/samples never execute on the host: only inside `sbx.run`. Static analysis (Semgrep, YARA, file triage) reads files on the host.
- Workers' playbook code is trusted and shares a process with the `AuditWriter`; **agents (models) and sandboxes cannot reach the audit file**
  (tool confinement + not mounted). A host-root attacker with the HMAC key can rewrite history → forward the chain head off-host (next action, see BLOCKERS).
- Approval gates: `sandbox_behavior`, `lab_start/probe/stop`. One approval authorises exactly the tools shown to Batman for that task.
- Lab: Docker `--internal` network `gotham-lab`; probes limited to a fixed benign catalogue; out-of-scope target ⇒ `scope_violation` + denial.
- Prompt injection: tool output is delimited as untrusted and scanned; permissions are enforced outside the model so an obeyed injection still cannot escalate.
- `install_deps` needs outbound network (pip); egress filtering to PyPI is a deployment-level control, not enforced by Docker alone.
