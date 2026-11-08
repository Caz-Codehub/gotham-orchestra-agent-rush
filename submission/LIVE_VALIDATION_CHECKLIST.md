# Live Vultr validation checklist

- [x] VM deployed with Ubuntu 24.04
- [x] HTTPS War Room page loads
- [x] Four domain-orchestra pages display
- [x] FastAPI /health returned status ok
- [x] Gotham and Specter systemd services active
- [ ] Confirm a live Vultr Serverless Inference request and model/usage evidence
- [ ] Run actual Docker code-repair test and save output
- [ ] Run infinite-loop containment probe and record timeout, exit code, network isolation, and cleanup
- [ ] Retrieve Specter independent audit and document findings (redact secrets)
- [ ] Public repository contains the full sanitized source tree
- [ ] GitHub Actions checks pass, including any Docker integration checks
- [ ] Record public or unlisted demo video with visible containment moment
- [ ] Prepare cover image and slide presentation
- [ ] Enter final submission on lablab.ai before deadline

Do not check boxes without evidence. Do not disclose access credentials in recordings.
