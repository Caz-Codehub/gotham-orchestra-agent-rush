> **Nov 8 update:** screenshot verified $200 remaining Vultr credit. Earlier statements that the coupon was invalid are stale. Verify live balance before creating resources. See [ORCHESTRA_QUICK_START.md](ORCHESTRA_QUICK_START.md) for updated hackathon deployment steps.

# Gotham 2.0 Deployment — Zero-Dollar First

## Stage 1 — Local, private development ($0 cloud infrastructure)

Use `scripts/start_windows.ps1` or `scripts/start_unix.sh` in `offline` or `ollama` mode. This binds to `127.0.0.1`; it does not provide a public Internet link. Ollama performs on-device model inference when installed and loaded. The application is usable for general objective analysis without Docker; contained code-repair validation requires Docker.

## Stage 2 — Repeatable, free CI validation

Publish only this sanitized Gotham source to a dedicated repository. The `.github/workflows/tests.yml` workflow runs unit tests and genuine Docker containment tests using GitHub-hosted runners, subject to GitHub's plan and usage limits. This is a test runner, not public production hosting and not evidence of Vultr integration.

## Stage 3 — Vultr hackathon deployment, ONLY after credit restoration

The organizer's $200 coupon was not redeemed in the user's account at the latest known check. The previous Vultr screenshot showed $0 remaining credit and the message "Gift code is no longer valid." **Do not create a charged VM or add billing details solely for Gotham** until the account can guarantee an acceptable funding source. If credits become available, verify them in the Vultr console and independently confirm potential charges, then run the deployment script on an already provisioned dedicated Ubuntu VM with explicit budget approval. The script itself does not create the VM or manage billing.

Required file `/etc/gotham.env` with `chmod 600`:

```env
GOTHAM_ACCESS_TOKEN=<generate-strong-secret>
GOTHAM_BATMAN_TOKEN=<generate-A-DIFFERENT-strong-secret>
GOTHAM_INFERENCE_PROVIDER=vultr
GOTHAM_ALLOW_PAID_INFERENCE=I_ACCEPT_POTENTIAL_CHARGES
VULTR_INFERENCE_API_KEY=<private-inference-key>
VULTR_INFERENCE_MODEL=<verified-supported-model>
```

Once credits and billing authorization have been verified, run as root on the *existing* instance:

```bash
export GOTHAM_CREDITS_VERIFIED=YES
export GOTHAM_PUBLIC_IP=<public-ip-from-console>
bash scripts/deploy_vultr_ubuntu.sh
```

This requires real owner approval for any billable inference; an assumed promotional credit is not a guarantee. It installs Docker, a FastAPI service, a separately supervised Specter watcher and a Caddy reverse proxy. `GOTHAM_PUBLIC_IP.sslip.io` is a **tentative**, not verified, HTTPS hostname. Check it with `scripts/verify_live.sh` and genuine end-to-end tests before claiming successful deployment. The service account's Docker-group membership is root-equivalent and acceptable only for an isolated, dedicated hackathon VM with no other user data; it is not a production security design.

## What remains unverified

No public URL, Vultr instance, inference request, real Docker runtime in this environment, browser-recorded video, or submitted hackathon entry has been established. The local system is functional at the API and mocked-boundary test level, not proven in live Vultr infrastructure.
