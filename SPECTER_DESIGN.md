# Specter — Batman's independent auditing position

**Reporting relationship:** Batman (human) only. Specter is not above Alfred and not under Alfred. Alfred commands five workers, while Specter independently audits Alfred and the five. The system therefore has **seven AI positions** but only **six operational agents** in the delegated chain.

## Currently implemented

- `team()` lists Alfred, Scout, Forge, Oracle, Sentinel, Cipher. Specter is not available as an Alfred tool or mentioned in operational worker prompts.
- The orchestrator sends sanitized metadata events to an independent SQLite journal. It does not pass prompts, code, bearer tokens or private objective context into that journal.
- A watchdog scans the journal approximately every second **while the app/service actually runs**. On the optional Vultr deployment, the watcher can run as a separate auto-restarting service.
- The rules flag unknown actors, disallowed tool selections, unexpected worker counts, sandbox network/cleanup violations, model errors, stalled missions and false verification approvals.
- `GOTHAM_BATMAN_TOKEN`, separate from the mission access token, gates `GET /api/batman/audit`.
- Internal hash chains detect accidental or naive tampering; no externally anchored or cryptographically signed attestation has been implemented.
- Optional `GOTHAM_BATMAN_ALERT_WEBHOOK` sends sanitized high/critical alerts to a chosen HTTPS URL. Without one, alerts are stored for Batman to read later.

## What is NOT yet implemented

Real-model validation of the optional locally hosted incident triage, kernel-level visibility into all agent activities, reliable 24/7 external alert delivery, off-host protected journaling, or automatic containment actions. Specter will not be able to detect every compromise and should not be sold as invisible or infallible. A privileged host operator can find or disable it.

## Future path

The optional `GOTHAM_SPECTER_LOCAL_AI=1` flag enables advisory incident reasoning through local Ollama only, never Vultr; its result is separate from rule evidence and may be absent. Create an independently permissioned Specter process and append-only off-host witness; feed auditable signed tool-call events, network metrics and Docker lifecycle records; add an optional **local-model** incident classifier restricted to event metadata; create heartbeat/alert failover; test with known malicious tool calls and realistic escape attempts inside a controlled lab. Never add unauthorized observation of other people's data.
