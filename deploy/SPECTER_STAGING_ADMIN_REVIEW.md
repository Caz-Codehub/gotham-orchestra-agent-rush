# Specter staging sidecar: ADMINISTRATOR-REVIEW ONLY

This manifest is an installation proposal, NOT a self-executing deployment.
Do not copy it onto the production service or invoke as root automatically.

## Required identities and permissions
- `gothamspecter`: independent non-root auditor owner. Owns private journal and HMAC key, and both Unix socket directories.
- `gothamdeploy`: restricted, **model-only** orchestra worker. May connect only to `/run/gotham-specter/write/record.sock`.
- `gothambatmanapi`: separate Batman-authenticated API identity. May connect only to `/run/gotham-specter/verify/verify.sock`. **Must not** be in worker's OS group or share its UID.
- Host administrator: installs the service and allocates UIDs but does not inject auditor credentials into agent prompts.

Each socket parent directory must be pre-provisioned with auditor ownership and a group allowing only the corresponding client identity to traverse and connect. Private HMAC key and SQLite journal are owned by the auditor and inaccessible to both clients. Group memberships must be tested with `stat`, `id` and negative access checks on the real host.

## Example service configuration
The administrator must replace the paths and numeric UIDs with verified staging-only values. The process refuses to start if the three UIDs are not distinct or if directories have not been provisioned.

```ini
[Unit]
Description=Gotham Specter staging audit boundary (writer + Batman verifier)
After=network.target

[Service]
Type=simple
User=gothamspecter
Group=gothamspecter
WorkingDirectory=/opt/gotham-specter-staging/current
ExecStart=/opt/gotham-specter-staging/current/.venv/bin/python -m gotham.core.specter_service --journal /var/lib/gotham-specter-staging/specter.sqlite3 --record-socket /run/gotham-specter/write/record.sock --verify-socket /run/gotham-specter/verify/verify.sock --worker-uid WORKER_UID_HERE --batman-api-uid BATMAN_API_UID_HERE
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/gotham-specter-staging /run/gotham-specter
CapabilityBoundingSet=
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryMax=192M
TasksMax=48
UMask=0077
Environment=GOTHAM_REQUIRE_INDEPENDENT_SPECTER=1

[Install]
WantedBy=multi-user.target
```

**Important:** the `write` and `verify` socket directories need an actual permission design. A socket's 0660 mode is not enough if the client cannot traverse the parent directory. Verify ownership, group isolation and file key visibility on-host. The existing `gothamdeploy` API and worker currently share an OS identity, so enabling the write sidecar **without splitting the Batman API** would fail the required separation. No automatic attempt should be made.

## User-facing service configuration (once accepted)
- Worker: `GOTHAM_SPECTER_RECORD_SOCKET=/run/gotham-specter/write/record.sock`, `GOTHAM_REQUIRE_INDEPENDENT_SPECTER=1`; no journal/key access.
- Batman API: `GOTHAM_SPECTER_VERIFY_SOCKET=/run/gotham-specter/verify/verify.sock`, `GOTHAM_REQUIRE_INDEPENDENT_SPECTER=1`. If this API still creates a mission via Alfred, it also needs a permitted **record-only** socket for its own audit events, while remaining unable to read the journal directly.
- Auditor: owns journal/key and both sockets; the service refuses connection to itself as a client.

## Acceptance and rollback
1. CI must pass all unit, Docker, audit and negative tests for the exact source SHA.
2. Stage three distinct Unix identities; prove worker cannot read auditor key/journal or connect verifier, and Batman API cannot modify private journal or impersonate the worker.
3. Attempt model/tool calls with the auditor stopped. **Zero inference/tool execution is allowed** without a committed acknowledgment.
4. Start a synthetic 21-task real-Qwen mission and verify Batman-only chain integrity plus off-host head checkpoint.
5. Roll back only the staging sidecar, preserving the journal and audit key. Never revert to local same-UID auditing while strict mode is enabled.
6. Production promotion remains separately owner-approved.

This document is an installation review plan. **No privileged host changes have been authorized or performed.**
