# Specter write-only sidecar — prototype boundary (NOT deployed)

## Status
The experimental module `gotham/core/specter_transport.py` is **opt-in and not connected to live Gotham**. It provides a Unix-domain-socket record-only client and a server that checks Linux SO_PEERCRED UID before appending metadata to Specter's HMAC-chained journal. Unit tests must pass before integrating it with the inference and tool paths. The current Specter journal already provides append-only SQL triggers and HMAC chaining but remains within staging's shared-UID host boundary.

## Required trust boundary
- Dedicated `gothamspecter` OS UID owns the private journal and HMAC key (mode 0600) in a non-traversable directory (0700).
- A pre-provisioned IPC directory permits only the separate worker process identity to connect to the **record-only** socket. The client has no SQLite access, no audit key and no reader methods.
- The Batman-only audit reader must operate through a *separate authenticated verification IPC endpoint* and, critically, a different OS identity from the model worker. Do not expose verifier access through the record socket. **The reader IPC implementation is not yet built.**
- The auditor must not be in the worker's tool registry, prompts, container mounts or environment. The inference path must call the independent audit service *before* any HTTP/LLM transport, and errors must halt inference.
- Group permissions alone cannot separate an auditor from another process that shares its UID. Deploying server and client under the same identity is a test, not independent protection.
- User and group provisioning, service activation, runtime socket configuration and rollback require explicitly authorized host administration. Do not run these steps automatically from rootless staging CI.

## Fail-closed criteria
1. Wrong peer UID, malformed/oversized metadata, unknown operation and missing socket return an error with **no model or tool invocation**.
2. Socket acknowledgment is returned only after a successful HMAC-chained append to the private journal.
3. Concurrent writers preserve the chain, do not leak credentials and never expose the key.
4. An independent Batman-only reader validates the complete sequence and off-host checkpoint. An off-host GitHub artifact is a useful checkpoint, **not an immutable vault**; admins may delete artifacts.
5. Kill the auditor mid-mission; confirm no work proceeds, no fake task receipts and no unaudited fallback to the local keyfile.
6. Use a distinct staging canary with rollback and preserve the original production installation.

## Out of scope for this prototype
- Automatically changing Vultr Unix users, socket group or Docker permissions
- Creating an auditor read/verify service, or pretending the existing worker UID cannot read its current journal
- Enabling any paid inference, public listener, or production promotion

Production stays blocked until those controls are integrated and verified with real separate-UID tests.
