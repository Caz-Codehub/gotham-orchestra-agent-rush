# Deployment

Status: **local staging verified; Vultr production deployment BLOCKED from the build session** (egress proxy returns 403 for the Vultr
API, the previously deployed host `155.138.194.208.sslip.io`, and `api.vultrinference.com`). Nothing below was run against a remote host.

## Layout (single VM, recommended)
- `/opt/gotham/releases/<ref>` + `/opt/gotham/current` symlink; venv `/opt/gotham/venv`.
- `/etc/gotham/gotham.env` (0600) with `GOTHAM_BATMAN_TOKEN`, `GOTHAM_OPERATOR_TOKEN`, `GOTHAM_DATA_DIR=/var/lib/gotham`,
  `GOTHAM_AUDIT_DB=/var/lib/gotham-audit/specter.sqlite3` (owner-only dir, outside the data dir), optional inference settings.
- Units: `deploy/gotham-api.service`, `deploy/gotham-worker.service` (worker needs the Docker daemon; run it on the host, not in a container).
- Reverse proxy with TLS (Caddy/nginx; the earlier sslip.io host used Caddy-style HTTPS) in front of `127.0.0.1:8000`.
- Separation: **dev** = laptop/CI; **staging** = same VM, second data dir + port; **production** = the VM's `current` release. Use distinct tokens per tier.

## Same-uid rule (verified failure mode FM-14)
SQLite WAL files are shared between the API (container) and the worker (host). Both must run as the **same uid**: create a host user `gotham`, `chown -R gotham /var/lib/gotham /var/lib/gotham-audit`,
and start compose with `GOTHAM_UID=$(id -u gotham) GOTHAM_GID=$(id -g gotham)`. `GET /api/v4/preflight` (and the worker's startup check, exit code 3) names any permission/ownership problem.

## Procedures (scripts in `deploy/`)
| Step | Command | Verified here |
|---|---|---|
| Release + compile gate + backup + health/smoke gate + auto-rollback | `deploy/deploy.sh <git-ref>` | **yes, via `scripts/cd_simulate.sh` (17/17) on a local stand-in** |
| Backup (store + audit + key + artifacts, checksummed, 7 kept) | `deploy/backup.sh DATA AUDIT OUT` | **yes** (restored audit chain verified) |
| Restore | `deploy/restore.sh BACKUP DATA AUDIT` | **yes** |
| Deployment acceptance | `deploy/smoke_test.sh URL OPERATOR_TOKEN BATMAN_TOKEN` | **yes, against local API+worker (7/7 PASS)** |
| Cron backup | `0 * * * * root /opt/gotham/current/deploy/backup.sh ...` | not installed (no host) |

## Cost control
Default inference provider is `none`; paid inference needs both `GOTHAM_INFERENCE_PROVIDER=vultr` and `GOTHAM_ALLOW_PAID_INFERENCE=I_ACCEPT_POTENTIAL_CHARGES`.
Vultr credit balance (~$198 reported) and the ~28k development credits are **unverified** — no cloud API could be reached.
