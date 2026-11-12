# Gotham 4.0 — Vultr + Clocked rollout (2026-11-11)

## Scope and evidence
The owner reports **$199 remaining Vultr promotional credits** and **20,000 Clocked included API credits**. Neither balance has been independently verified here. This is a staged operating budget, **not an authorization to start billable infrastructure** or proof of resource availability.

SignalForge is a separate submitted hackathon demo. Do **not** turn SignalForge into the Gotham control plane or claim Clocked security verdicts are live without request receipts. Its production Netlify secret is separate from Gotham's server-side secret.

## Rollout phases and gates

### Gate 0 — Verify live baseline at $0 incremental cost
- Pin Gotham deployment to branch and commit; record release SHA.
- Obtain read-only verification of Vultr credit balance, running instances and billing rates.
- Run existing Vultr host health/preflight; verify app and worker versions match, API authenticates, Batman audit permission separation works.
- Record screenshots and redacted receipts for endpoints and current GitHub Actions.
- Inspect existing host rather than creating a duplicate VM.

### Gate 1 — Enable actual model-driven Gotham
- Configure the Vultr inference key and model **only** in the server's secret store or owner-controlled deployment environment. Never in Git history, PR, chat, browser bundles, or audit payloads.
- Require explicit paid-inference opt-in and hard ceilings before requests.
- Validate `/api/v4/agents` shows a real configured model, then run one bounded engineering mission **without a supplied patch**. Evidence must show genuine model/tool decisions, real sandbox tests, verification and Specter events. Scripted-model fixtures are not proof.
- Stop rather than silently downgrade to pretend autonomy if inference is unavailable.

### Gate 2 — Clocked security middleware
- Add server-only `CLOCKED_API_KEY`; preserve Netlify's existing secret separately.
- Put Guard (`/injection`) before ingesting untrusted tool output / external text into an agent; block or require approval on risky or unparseable responses.
- Put Protect (`/pii`) before forwarding sensitive text into inference or report output; verify redaction with synthetic fixtures.
- Put Inspect (`/script`) before any agent-generated script goes into a sandbox; **never** treat a positive verdict as authority to execute without Gotham approvals and containment checks.
- Check actual response schemas against Clocked documentation/real sanitized receipts before wiring verdict parsing. Fail closed on missing key, timeout, malformed responses or HTTP failure.
- Set app-level request/time/credit quotas: at most four concurrent calls; no retry storms; stop when included credits run out; no Clocked paid plan/overage.
- Prove allowed, blocked, redacted and outage paths with real endpoint responses, then capture a redacted audit ledger.

### Gate 3 — Research and security tasks
- Run CPU notebook execution through existing approved URR/worker backend; prove artifact checksums and resume from checkpoint.
- Run defensive code/config scanning, approved inert malware analysis, and authorized local-lab security tests only.
- Keep the audit sink and workspace rights separate; do not activate unrestricted outbound scans or malware deployment.

## Initial caps (proposed until owner-approved)
- Keep Vultr paid resources limited to **one existing VM**, no new GPU instances, no auto-scaling, no automatic credit top-ups.
- Proposed reserve: $100 of the reported $199 unused until the first live acceptance passes; staged deployment spending allowance max $25, then review measured cost. No new resource creation without billing-rate inspection.
- Clocked: initially use <= 1,000 included credits for end-to-end tests, with <= 4 requests in flight, then review actual usage. Preserve the remainder for Gotham security workflows.
- Stop on failed provider/billing inspection, budget check, verification gate, authorization, or evidence receipt. These caps are a desired policy only, **not enforced yet**.

## Blockers and owner actions
- Existing build-session egress blocked Vultr. Do not assert reachability has been fixed.
- Read-only access to Vultr billing and permissions for deployment are needed to verify credits and host release. Keep credentials out of chat.
- Gotham-specific server-side Clocked key and real Vultr inference credentials are needed for live acceptance.
- Until those requirements are met, make offline code/test improvements without billable actions.

## Acceptance
Each milestone must produce: exact code ref, executed command/endpoint, actual timestamp, PASS/FAIL/BLOCKED result, redacted source receipts, measured requests/credits where available, and rollback plan.
