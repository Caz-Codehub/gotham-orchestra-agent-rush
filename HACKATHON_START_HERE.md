> **Nov 8 update:** screenshot verified $200 remaining Vultr credit. Earlier statements that the coupon was invalid are stale. Verify live balance before creating resources. See [ORCHESTRA_QUICK_START.md](ORCHESTRA_QUICK_START.md) for updated hackathon deployment steps.

# GOTHAM Agent Rush — last-mile operator guide (Nov 8, 2026)

**A separate, sanitized code-repair MVP intended for the hackathon.** The user's local Gotham v2.5 project studio, research projects, protected credentials, private repositories and unrelated CBTB files are not included here. Do NOT upload your Windows user profile or local machine's Gotham files to a public repository.

## Why this package

- Target: LabLab/Vultr Agent Rush C1 "Blast Radius Zero".
- Proof: Alfred coordinates five workers; Forge proposes a Python patch using Vultr Serverless Inference; Oracle verifies real failing baseline and passing patch inside temporary restricted Docker containers; Specter holds independent audit metadata.
- UI served publicly from Vultr VM through HTTPS proxy, but missions need a private token.
- This release is **Gotham v2.2 code-repair competition MVP**. The newer local Project Studio v2.5 is a separate branch not required for contest proof.

## Deadline

Official LabLab event page states submission cutoff **Nov 8, 2026, 23:00 UTC = 5:00 PM CST**. Submit on https://lablab.build/ai-hackathons/vultr-hackathon. Don't confuse optional Vultr Community showcase with the required LabLab submission.

## Step 0: credit safety

1. Open https://console.vultr.com/billing/ or use Vultr Billing in dashboard.
2. Verify **Remaining Credit** is a *positive numeric amount* after redeeming the hackathon gift code. Banner alone is not sufficient.
3. Keep budget alerts enabled and avoid adding any personal payment method if the provider doesn't require it. Monitor usage.
4. Vultr instances are hourly billed even while powered OFF; to stop billing, **destroy** the VM, not merely power it off.

## Step 1: create VM

Create **Shared CPU** (not Dedicated CPU), Ubuntu **24.04 LTS x64**, use a plan with preferably **2 vCPU / 4–8 GB RAM** and adequate storage. The inference runs on **Vultr Serverless Inference**, so no CPU-intensive Ollama model needs to load on the VM. Select a convenient US location, enable public IPv4, and deploy. Ensure inbound SSH 22 and HTTPS 443 (and 80 temporarily for Caddy TLS issuance) are allowed. Save root password securely / use SSH key. Record IP. Never paste password in AI chat.

## Step 2: get Vultr inference key (required C1)

Vultr Console > Compute > Serverless Inference. Provision or enable a subscription, create its API key, and select an available model. The default example `deepseek-v4.1-flash-1017` is documented by Vultr; check the live model catalog and pricing. Only perform charge-incurring actions after confirming your free credit and usage budget. Don't send API key to the chat.

## Step 3: upload and deploy

In a new **Windows PowerShell**, find the downloaded ZIP (this package must remain zipped for upload). Replace `YOUR_PUBLIC_IP`:

```powershell
scp "$env:USERPROFILE\Downloads\Gotham-Agent-Rush-Vultr-MVP.zip" root@YOUR_PUBLIC_IP:/root/
ssh root@YOUR_PUBLIC_IP
```

On the VM (Ubuntu terminal):

```bash
apt-get update && apt-get install -y unzip
cd /root
unzip -oq Gotham-Agent-Rush-Vultr-MVP.zip -d /root/gotham-hackathon
cd /root/gotham-hackathon
bash RUN_ON_VULTR_VM.sh
```

Follow prompts. Installer creates a private `/etc/gotham.env` with two distinct random mission/audit tokens, installs Docker/Python/Caddy, starts Gotham & Specter via systemd, and prints the public URL (which must be separately verified). **Do not paste tokens in a public chat or video.**

If root SSH login is disabled, connect with your chosen Ubuntu admin account and use sudo. If a problem occurs, use Vultr's web console and `journalctl -u gotham -n 60 --no-pager`.

## Step 4: verify live proof

1. Visit `https://PUBLIC_IP.sslip.io` in browser. DNS/HTTPS may take time. Verify after Caddy gets certificate.
2. Use Mission token. Code repair > Load sample > Run Code Repair. Look for real `inference: vultr-serverless-inference` and `candidate_source` likewise, and `baseline` with `sandbox: docker`, then passing `candidate_run`.
3. Run **Containment probe**, verify `timed_out: true`, `container_destroyed: true`, `network: none`. Do not claim this proves protection from kernel/container escapes.
4. Use audit token (kept private), show independent Specter receipt. Record sanitized video, hide all token fields.
5. Public URL verification: `bash scripts/verify_live.sh https://PUBLIC_IP.sslip.io` on VM. This tests HTTP health but not inference. 

## Step 5: public repository

Create a **new** public repository, e.g. `Caz-Codehub/gotham-agent-rush-2026` at https://github.com/new. Use only this clean folder; DO NOT upload credentials. `.gitignore` should exclude `.env`, venvs, logs and DBs. On Windows extract ZIP, open PowerShell at extracted folder and run (requires Git):

```powershell
git init
git branch -M main
git add .
git status
git commit -m "Hackathon Gotham: sandboxed agentic code repair on Vultr"
git remote add origin https://github.com/Caz-Codehub/gotham-agent-rush-2026.git
git push -u origin main
```

Review files listed by `git status` before committing. Keep audit DB, private research and credentials off GitHub. Follow current hackathon MIT/open-source requirements; the package contains LICENSE.

## Step 6: demo & submission

Submit **before 5 PM Central today** on https://lablab.build/ai-hackathons/vultr-hackathon : public repo; public HTTPS URL; title and descriptions; video showing baseline fail > patched pass > infinite-loop containment; slides/cover if requested. Official page lists these as deliverables. Actual deployment and LabLab submission remain user-controlled and are NOT performed by downloading this ZIP.

### Ready-to-use public pitch

**Gotham: Proof Before Permission** — A containment-first autonomous engineering team. Batman authorizes a repair mission. Captain Alfred delegates to five specialized Qwen/Vultr inference-supported roles, and independent Specter audits the execution trail. Forge's proposed patch runs only inside ephemeral Docker sandboxes with no network, limited resources and verified cleanup. Alfred withholds approval when tests or containment evidence are missing. A browser-based command center shows real results, event timeline and integrity hashes. Designed for auditable, human-governed agentic software maintenance.

### Known limitations

- Public unauthenticated browsers can inspect UI and health, but require a mission token to execute operations. Do not expose audit token or grant unrestricted public demo access.
- Docker daemon access is powerful; use a dedicated short-lived VM only. The demo does not establish comprehensive container-escape safety.
- Secret/API charges and security need attention; promotional credit covers only eligible charges up to provider terms.
- No local Qwen loads on the cloud VM; C1 inference uses Vultr Serverless Inference deliberately.
