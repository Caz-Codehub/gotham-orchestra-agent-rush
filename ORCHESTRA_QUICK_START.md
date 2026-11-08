# Gotham Orchestra — Agent Rush 2026 MVP

**Launch target:** Vultr Agent Rush / Blast Radius Zero. **Final submission deadline:** Nov 8, 2026, 23:00 UTC / 5:00 PM CST.

## What is working in this package

- `/` — existing Gotham code-repair control center, 5 dedicated worker roles, independent Specter audit, ephemeral no-network Docker Python sandbox, receipt export, infinite-loop containment probe.
- `/orchestra` — four domain-specialist AI orchestras: **Software Engineering**, **Research & Notebooks**, **Cyber Defense**, **Authorized Security Lab / Malware Analysis**. Each has a domain captain and three role-specific model analyses, then central Alfred synthesis. This runs through **Vultr Serverless Inference** when configured with an active key and explicit opt-in. Each generated report is labeled **analysis only**; it does not invent code execution or research citations.
- All non-read-only operations require a private mission token. Specter is separately supervised on the VM and has a different Batman audit token.
- Lab Orchestra requires an authorized lab scope and has **no attack execution or malware-deployment tools**.

## Important limitations

This is a **hackathon orchestration MVP**, not the finished Gotham v2.5 research/software studio: it does not yet provide separate full-time persistent agents, source-searching research, executable research notebooks, production security scanners, real live ethical-hacking actions, or software repository management. The *actual executed demonstration* is the existing authenticated code-repair + sandbox containment workflow. Do not claim the orchestra analysis itself executed external actions.

## FASTEST DEPLOYMENT

1. Verify remaining credit in Vultr Billing; screenshot currently showed $200 balance and $0 charges (verify again if necessary).
2. In Vultr create a **Shared CPU** instance in an available US region; use Ubuntu 24.04 LTS (x64), 2 vCPU and **4 GB RAM** if offered; enable IPv4. This is a metered instance, charged against promotional credit where eligible. Configure an SSH key (recommended) or strong root login. Ensure VM firewall allows TCP 22 to your IP, TCP 80/443 from the internet. Do not open port 8000 publicly.
3. In Vultr **Serverless Inference** create a service API key and choose a model from the official live catalog. Never share key in chat, recordings, screenshots or GitHub.
4. Download this ZIP on Windows and open PowerShell (replace IP):

```powershell
scp "$env:USERPROFILE\Downloads\Gotham-Orchestra-Agent-Rush-2026.zip" root@YOUR_PUBLIC_IP:/root/
ssh root@YOUR_PUBLIC_IP
```

5. On the Ubuntu VM:

```bash
sudo apt-get update && sudo apt-get install -y unzip
cd /root
unzip -oq Gotham-Orchestra-Agent-Rush-2026.zip -d /root/gotham-orchestra
cd /root/gotham-orchestra
sudo bash RUN_ON_VULTR_VM.sh
```

The guided script asks for verified credit, the VM IPv4, serverless model ID, key (hidden), and explicit consent for metered inference. It creates separate random tokens, installs Docker, Caddy TLS reverse proxy, Gotham and the independent Specter watchdog as services. Keep terminal tokens private. **Cloud deployment is NOT complete until `/health`, a Vultr inference repair, and a real containment run are verified.**

6. Verify public URL `https://PUBLIC_IP.sslip.io/` and `https://PUBLIC_IP.sslip.io/orchestra`. Certificates/DNS may require 80/443 to be reachable. In Gotham Mission Control: Code Repair → Load sample → Run Repair; then Containment probe. In the Orchestra page: select Research and dispatch a low-cost example. Include `model_backend:vultr-serverless-inference` in sanitized receipt, and never publish actual tokens.

## Hackathon submission

- Create a new public GitHub repository using only this sanitized ZIP's extracted files. NEVER upload `/etc/gotham.env`, database files, Windows profile, Ollama model files, private notebooks, or Git credentials.
- Record a ~90-second screen capture: four orchestra cards → Software orchestra analysis → actual failed baseline/passing patch → containment probe → Specter audit → architecture description. Blur credentials and hidden input values.
- Submit public repo, real Vultr-hosted HTTPS demo URL, and demo video to https://lablab.build/ai-hackathons/vultr-hackathon **before 5 PM CST**. This package is not automatically submitted.

## Budget safety

Vultr is **metered** even if the promotional credit is $200. Keep account alerts on, check credit expiry and eligibility, never assume a coupon covers all charges. Turn off billable inference when not needed. Destroy the VM when done if you want instance billing to stop (a powered-off VM can still incur charges). There is no automatic spending kill switch in this package.
