# V3 demonstration verification (not proof of live deployment)

Current implementation: four separate logical orchestras with distinct captain and specialist reasoning calls; bounded deterministic export artifacts for each; narrow Docker-test route; Batman-only Specter audit dashboard, event timeline and question-to-evidence summaries. The demo does **not** implement unrestricted software code generation, unconstrained AI-directed malware, research on arbitrary datasets, or a provably hidden auditor.

### Required tests on Vultr

1. Confirm `/health` and four orchestra cards open over HTTPS.
2. In the orchestra UI, enter the **mission** token privately and select each domain. For the Lab domain, enter an explicit offline owned lab scope.
3. Choose **BUILD + DOCKER TEST DEMO ARTIFACT**. Save each ZIP, check `verified_execution=true`, `evidence.passed=true`, `evidence.container_destroyed=true` and `evidence.network=none`.
4. For Research, open the downloaded `.ipynb` notebook and distinguish its code cell from independently completed Docker tests. Notebook cells are *not* pre-executed in Jupyter.
5. From the original Code Repair & Containment interface, trigger the infinite-loop containment probe and verify its timeout and cleanup receipt.
6. Open `/specter` independently, enter the **Batman audit** token (not the mission token), click **Examine all missions**, inspect a mission and ask “What did each agent do?”. Check journal integrity and any findings.
7. Confirm that worker AI system prompts never contain the words `Specter`, its audit token or audit findings. This is application-level isolation, not a guarantee that a public codebase hides an auditor from adversarial inspection.
8. Confirm the live inference result includes successful hosted model calls (not just inference configured).
9. Upload the sanitized source publicly and verify GitHub Actions. Record a video with an actual containment moment; do not film secrets.

### Windows PowerShell to upload the V3 package

Download the V3 ZIP to your Downloads folder. From **Windows PowerShell**, not inside SSH:

```powershell
scp "$env:USERPROFILE\Downloads\Gotham-Orchestra-V3-Upgrade.zip" root@155.138.194.208:/root/
```

Then SSH to your VM and run:

```bash
mkdir -p /root/gotham-v3 && cd /root/gotham-v3
unzip -o /root/Gotham-Orchestra-V3-Upgrade.zip
bash scripts/apply_orchestra_v3_upgrade.sh
```

The patch creates a backup of `/opt/gotham/gotham`, does **not** overwrite `/etc/gotham.env`, and restarts only the Gotham services. If a health check fails, roll back using the created backup rather than rerunning the original installer.
