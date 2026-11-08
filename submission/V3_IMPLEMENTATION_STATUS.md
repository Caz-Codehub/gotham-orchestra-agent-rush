# Gotham Orchestra V3 — execution upgrade

**Source package:** Gotham-Orchestra-V3-Full-GitHub-Source.zip (generated in ChatGPT); must still be uploaded to this repository. This document alone does not constitute a source-code release.

## Newly implemented locally (not yet deployed on Vultr)

- Four distinct logical orchestras with captain and 3 specialist AI calls per orchestra when Vultr inference succeeds.
- Qualified audit actor identities such as `research:captain`, `research:Methods Architect`, `software:Test Engineer`.
- Separate Batman-only Specter interface at `/specter` with protected mission list, per-agent event timelines, hash-chain integrity, policy findings and read-only question/explanation function.
- Boundaries: worker prompts do not disclose private Specter instructions or audit data; workers cannot call Batman-only audit APIs without distinct credentials. **This is not a cryptographic guarantee that Specter's existence is hidden from anyone inspecting a public repository.**
- Four constrained demonstration artifacts: a working static task-list page, a Python security-hardening example, a real Jupyter notebook file with synthetic computations, and a harmless lab-behavior emulator. All have Docker tests and downloadable ZIPs. These are deterministic task templates; **not unrestricted AI-coded applications or operational malware**.
- Existing dedicated containment-probe endpoint retained.
- Automated local regression suite: 50 passing, 2 skipped real-Docker tests; live cloud end-to-end verification pending.

## Deployment

The upgrade ZIP contains `scripts/apply_orchestra_v3_upgrade.sh`. On the existing Vultr VM, extract the ZIP and run the script as root, after backing up. The script backs up original application files, copies only edited Gotham files, leaves `/etc/gotham.env` untouched, restarts only Gotham + Specter, then checks local health.

## Live proof still required

1. Verify real Vultr Serverless Inference calls, not just configured keys.
2. Complete the four downloadable-artifact Docker demo missions through the public Windows browser UI.
3. Verify a timeout and cleanup from the infinite-loop containment probe.
4. Check the independent Specter mission report and findings.
5. Upload the complete sanitized source tree, then record the demo and submit.
