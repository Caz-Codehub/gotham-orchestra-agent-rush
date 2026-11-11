# Gotham — 4-orchestra, 12-specialist architecture contract

**Authoritative target (2026-11-11).** Do not replace this with the five-worker legacy topology. This is an architectural specification, not proof that deployment has met it.

## Command hierarchy
- Batman (human, authorization and final oversight)
- Alfred (central coordinating captain; owns mission routing and verifies aggregated outcomes)
- FOUR distinct domain orchestra captains reporting directly to Alfred:
  1. **Forge Commander** — Software Engineering
  2. **Research Commander** — Research & Notebooks
  3. **Defense Commander** — Cyber Defense
  4. **Lab Commander** — Authorized Security Lab
- Each captain controls THREE logically distinct specialist positions; **12 specialist positions total**, 3 per orchestra. Names/labels currently supplied by `gotham/orchestras.py`.
- That is **12 specialists + four captains + Alfred**. Specter is a separate, independent audit system, not a subordinate specialist and not a captain.
- The five-worker compatibility API (Scout, Forge, Oracle, Sentinel, Cipher) is legacy/underlying shared tooling, **not** a substitute for the four orchestras or the 12 specialist identities.

## Audit architecture and pre-inference trust boundary
Specter is independent of the orchestra command chain. Agents/captains must not be told Specter's private architecture, identities, tokens, databases, endpoints or audit policy in prompts or tool results. Batman's separate authenticated interface can read audit evidence.

**Required flow for every proposed model call or tool action:**

Batman mission authorization -> central intake + authenticated scope -> policy / data classification -> prompt-injection and PII screening -> permit/deny/approval gateway -> independent append-only audit receipt -> minimal sanitized model input -> captain or specialist model invocation -> structured output validation -> tool permission/sandbox gate -> independent audit receipt -> evidence verification -> captain report -> Alfred synthesis -> Batman.

Specter's auditing layer receives event metadata through a separate protected path **before** model input is released. A failed, unavailable, or uncommitted audit gate must deny the call; do not continue silently. The hidden auditor must never enter the LLM prompt, tool registry, or untrusted workspace.

Clocked Guard/Protect/Inspect may be inserted as additional server-side security decisions only after real schemas/results and quotas are tested. No claims of live Clocked checks without receipts. Defensive scoped analysis only; no unapproved external targets or malicious deployment.

## Definition of DONE — evidence required
1. Inventory endpoint enumerates all four **distinct captains and 12 distinct orchestra-scoped specialists**; hierarchy and reporting links are correct.
2. An authenticated objective enters Alfred, is routed to the appropriate captain, and reaches three distinct specialists *within the selected orchestra*.
3. Model calls pass a pre-inference gateway, with fail-closed tests on denied/malformed inputs and audit sink outage; independent audit events commit before model invocation.
4. The model sees no Specter identity, credentials, or private audit metadata; an authorization test ensures only Batman can read audit evidence.
5. Specialist results produce real evidence: executable work in bounded Docker where authorized, notebook runs/checksums for research, defensive scanning receipts, and isolated/inert security-lab tests.
6. Each captain verifies specialist results and forwards an evidence-based report to Alfred. Alfred may not claim 12/12 complete based solely on static agent metadata or mock model calls.
7. Four-orchestra integration test covers all 12 specialist identities, four captains, Alfred, and hidden Specter audit for a bounded approved mission.
8. Infrastructure and release checks distinguish API smoke, local model status, live autonomous work, and full production release; no automatic production promotion.

## Current gaps at contract creation
- `gotham/orchestras.py` defines four captains and three roles per orchestra, but only performs analysis-only inference with five model calls per orchestra; it does not drive the separate `gotham/core/engine.py` durable tool-task execution.
- `/api/v4/agents` reports five shared workers; this endpoint **does not** yet prove 12 orchestra specialists are executing.
- The 2026-11-11 successful GitHub staging smoke proves localhost API startup and production isolation, **not** the four orchestras, hidden pre-inference gateway, or model-driven artifact execution.
- Independent Specter protections exist in `gotham/core/audit.py`, but the complete pre-model gateway semantics above are not yet enforced across every inference path.
