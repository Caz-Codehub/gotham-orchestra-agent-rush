# Specter staged UID separation — administrator-reviewed deployment plan

**Status:** proposed only. The sidecar must not deploy from normal GitHub Actions or change the existing Gotham production service.

## Isolation model

Use three non-root identities with mutually exclusive permissions:

| Identity | Responsibilities | Direct access |
| --- | --- | --- |
| `gothamspecter` | Private HMAC key, append-only audit journal, record and verify sockets | Own journal/key, neither application nor Docker |
| `gothamworker` | Model inference and bounded orchestral analysis | Connect to record-only socket; no journal/key or verification socket |
| `gothambatmanapi` | Authenticated Batman-only audit verification API | Connect to verify-only socket; no journal/key or record socket |

The current all-in-one `gothamdeploy` staging service **does not meet this isolation model**. First prove the identities in a separate canary; do not rename a service account and assume separation exists.

## Preconditions (human host administrator review)

1. Confirm available Vultr CPU, disk, account quotas and existing service map. Snapshot/audit-copy existing staging and note a rollback commit. Do not expose secrets in GitHub summaries.
2. Administrator creates the three OS users (with no shell login and no Docker group membership) and tightly separated socket/journal directories. Restrict `gothamspecter` HMAC key and SQLite files to the Specter service identity. Configure per-socket group permissions so **only** the corresponding peer can connect, and use Linux `SO_PEERCRED` checks as a second layer.
3. Use separate process supervisors, with dedicated `WorkingDirectory`, `User`, `Group`, `NoNewPrivileges`, `ProtectSystem`, `PrivateTmp`, and read/write paths limited to each role's own files. Avoid host Docker socket access, world-readable socket directories and public listeners.
4. The sidecar service starts as `gothamspecter` with explicit `--worker-uid` and `--batman-api-uid`. Both are mandatory. The service refuses root and shared UIDs, and does not create privileged directories.
5. Configure `GOTHAM_SPECTER_RECORD_SOCKET` **only** for the model worker, `GOTHAM_SPECTER_VERIFY_SOCKET` **only** for Batman API; both set `GOTHAM_REQUIRE_INDEPENDENT_SPECTER=1`. The auditor has neither socket env var. Do not copy `GOTHAM_AUDIT_DB` or an HMAC key into the worker/reader environment.
6. Keep the legacy rootless staging release available for rollback. Never modify `gotham.service`, port 8000, Caddy or the original journal in this phase.

## Mandatory acceptance challenges

- Wrong peer UID cannot write or read; the worker cannot inspect the verifier socket, and the Batman API cannot write via record socket.
- Auditor is killed during a mission: no new model HTTP call, tool invocation, or successful mission receipt after the failed audit acknowledgment.
- Concurrent write receipts remain HMAC-chain valid; no private event payload/HMAC key reaches specialist prompts or GitHub artifacts.
- A complete 21-task live local-Qwen mission succeeds with the sidecar, while its reader verifies the chain and compares the external chain-head checkpoint.
- All four real sandbox tool paths remain approval-gated and must be verified separately.
- An audit transport timeout, malformed event, journal outage, or reader outage fails closed. No automatic fallback to local `AuditWriter` or `AuditReader`.
- Reboot behavior, service restart and rollback restore an intact, verifiable audit chain.
- The exact staging release commit and SHA-256 evidence are captured. No production promotion without Batman's explicit approval.

## Rollback

Stop only canary worker/API services; preserve and hash the Specter journal and key in private ownership. Revert canary environment and service units to the last verified staging release, confirm staging health and production service untouched. Do not delete the audit journal or reuse a corrupted key. A failed canary blocks promotion rather than becoming a silent downgrade.

## Blockers to full operational claim

The repository provides socket transports and a runnable auditor entrypoint, but **there is no approved distinct-UID Vultr canary** yet. Only a host administrator can authorize and provision the OS-level separation. The normal GitHub staging deployer runs without elevated privileges by design; its inability to create these identities is a security feature, not a defect.
