# Gotham 4 — Four-orchestra implementation status (2026-11-11)

This is an evidence-oriented engineering report, not a claim of production readiness.

## Built in the GitHub development branch
- Durable Alfred DAG: four captain planning tasks, 12 scoped specialist tasks, four captain review tasks and one Alfred synthesis task (21 tasks, five model calls per orchestra plus Alfred).
- Authenticated `GET /api/v4/orchestras` returns the four captain chains, 12 specialist identities and their reporting lines.
- Restricted, non-root `gotham.core.orchestra_worker`: processes only orchestra DAG kinds; cannot take unrelated sandbox/security work.
- Every real `CompatibleInference.chat` transport commits an independently journaled metadata-only `pre_model_transport` event before sending inputs. Core agent loops and orchestra DAGs also add scoped `pre_model_gate` events; model prompts do not include the private auditor.
- Orchestral analysis returns `completed_unverified`, never the misleading `verified` status. Synthetic test evidence and model reasoning are not substitutes for real artifact execution.
- Optional `execute=true` workloads add a separate, Batman-approved evidence stage per selected orchestra using existing registered tool/playbook capabilities. Model synthesis references tool receipt digests, and `verified` can only be issued if the existing artifact-verification checks pass.
- GitHub Actions runs CI, auto-stages to existing Vultr VM via the dedicated `gothamdeploy` key after tests, and may publish `deployments/staging-status.json` only if staging reports four captains, 12 defined specialists, a live restricted worker, and API health.
- A separate manual workflow tests a real Qwen 21-task synthetic mission and the Batman-only audit chain.

## What remains unverified
1. **Staging deployment receipt**: `deployments/staging-status.json` not yet observed for this branch; do not claim the auto-staging action succeeded.
2. **Real Qwen inference**: API/worker tests currently use fake models. The explicit 12-specialist acceptance workflow must run and pass using local Ollama. Qwen2.5 1.5B may fail structured JSON or exceed CPU budgets.
3. **Sandbox execution**: the safe rootless orchestra worker intentionally lacks Docker access. Real code/notebook/defensive scanner/authorized-lab workloads need the separately supervised, least-privileged sandbox worker, working images, permissions and Batman approvals.
4. **Independent Specter process isolation**: journal is stored separately with HMAC and Batman-only API, but full physically isolated auditor process and an external write-only audit transport are not proven. Do not call Specter hidden from host administrators.
5. **Clocked service**: not connected to Gotham's gateway; no unverified endpoint results or credits should be presented as operational.
6. **Production release**: no Caddy change, no port 8000 cutover. Original Gotham remains running.

## Safe activation order
- GitHub CI green on exact HEAD -> staging receipt pinned to exact commit -> real 12-specialist Qwen acceptance -> remote audit integrity -> scoped tool/sandbox execution acceptance -> independent auditor process boundary -> optional Clocked middleware with schema/quotas and fail-closed behavior -> owner-approved promotion with backup, canary and rollback.
- All staging routes bind localhost. Never promote automatically; preserve production data, audit journal, versioned history and cost ceilings.

## Credits
User-reported approximately $199 Vultr promotional credits and 20,000 Clocked included credits. Direct balance checks unavailable. Staging remains on the existing VM, uses local Ollama and explicitly disables paid inference. No new VM or Clocked API charges are required for these tests.
