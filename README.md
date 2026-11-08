# Gotham Orchestra — Vultr Agent Rush 2026

**Live application:** https://155.138.194.208.sslip.io/  
**Orchestra dashboard:** https://155.138.194.208.sslip.io/orchestra  
**Challenge:** Blast Radius Zero (sandboxed AI agent execution)

Gotham Orchestra is a human-directed, multi-agent command center. Batman (human) issues objectives to Captain Alfred. Alfred coordinates five specialist workers and four domain-specific orchestras: Software Engineering, Research, Cyber Defense, and Authorized Security Lab. Specter is an independent audit component.

## Architecture on Vultr

- **Vultr Cloud Compute:** Ubuntu 24.04 LTS VM (2 vCPUs, 4 GB RAM), running Python/FastAPI with Uvicorn as a systemd service.
- **Vultr Serverless Inference:** configured as the hosted model provider, with a per-request usage gate. Live inference behavior must be independently verified.
- **Caddy:** HTTPS reverse proxy with a hostname under `sslip.io`; the FastAPI backend listens on `127.0.0.1:8000`.
- **Docker:** `python:3.12-alpine` image for controlled Python code execution, with network disabled, resource limits and container cleanup.
- **Specter:** independently logs authorized mission evidence and audit status; Batman audit token is distinct from mission token.

```text
Batman (human) -> Captain Alfred -> Scout / Forge / Oracle / Sentinel / Cipher
                               |-> Software Engineering Orchestra
                               |-> Research Orchestra
                               |-> Cyber Defense Orchestra
                               |-> Authorized Security Lab Orchestra
Specter -> independent audit reports for Batman
Alfred -> vetted Docker execution -> test evidence -> review
```

## Current scope and honesty about verification

The public command center and four orchestra interfaces are deployed on Vultr. The VM health endpoint returned OK with the Vultr inference backend configured; that **does not prove successful hosted inference**. Multi-orchestra pages presently support orchestration and analysis; they are **not** full autonomous software factories or penetration-testing systems. Local automated tests reportedly passed, but the live Vultr code-repair and timeout-containment demonstrations still require evidence. These must not be described as passed until validated.

## Security and operating model

Administrative operations require a mission token, and sensitive audit reports require a distinct Batman token. Never commit API keys, token files, `.env` secrets, cloud credentials, or private client data. Authorized Security Lab remains scoped to approved targets and isolated testing. Network-facing offensive operations are not automatically enabled.

## Running and verification

The sanitized source package includes `requirements.txt`, `Dockerfile`, `RUN_ON_VULTR_VM.sh`, `scripts/deploy_vultr_ubuntu.sh`, `scripts/verify_live.sh`, and automated tests.

To validate after deployment, run the documented health, orchestration, code repair, containment, and Specter checks. Record the actual receipts and upload a public or unlisted demo video displaying a containment moment.

## Hackathon submission

Submission is incomplete until the public code, live application, full proof of execution and containment, demo video, required slides and team description have been verified and entered on lablab.ai.
