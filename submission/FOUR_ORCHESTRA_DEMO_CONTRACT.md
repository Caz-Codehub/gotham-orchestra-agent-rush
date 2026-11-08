# GOTHAM FOUR-ORCHESTRA DEMONSTRATION CONTRACT — 2026-11-08

**Status:** Product requirement. This document defines what Gotham MUST demonstrate; it does **not** claim features have been built or verified.

## Human command
Batman remains final human authority. Alfred coordinates the four orchestrated workstreams. Specter independently audits the evidence. No orchestra is a grant of unrestricted shell, network, or other system access.

## 1. Software Development Orchestra
- Input: Batman's request for a small functioning web application.
- Required work: produce actual source files (HTML/CSS/JavaScript or Python service), tests, and an artifact ZIP; execute appropriate test commands inside constrained Docker.
- Observable Windows demo: download the generated artifact, run or preview the app, and display passing test receipts.
- Pass condition: working output and reproducible tests, not an essay outlining the solution.

## 2. Ethical Hacking / Authorized Security Lab Orchestra
- Input: explicit authorized lab scope and test objective.
- Required work: generate an **inert, non-propagating malware-behavior emulator** (e.g., simulated suspicious file modification in a disposable test directory, with no persistence, exfiltration or live attacker infrastructure) and run it in isolated Docker with network disabled. Collect findings and verified containment results.
- Observable Windows demo: show test creation, isolated execution, safety boundary, container timeout/cleanup, and audit report.
- Pass condition: no production host or third-party impact. Actual deployable malware, credential theft, propagation, or evasion functionality is not part of this hackathon demo.

## 3. Research & Notebooks Orchestra
- Input: a research question and permitted dataset.
- Required work: generate a real Jupyter `.ipynb` file with code and markdown, run notebook cells or equivalent approved experiment in Docker, preserve generated results, and package the notebook.
- Observable Windows demo: download notebook, inspect executed cells, charts/data (if relevant), and reproducibility receipt.
- Pass condition: executable notebook with genuine outputs; no fabricated measurements, results or citations.

## 4. Cyber Defense Orchestra
- Input: source from software orchestra plus a specified threat model.
- Required work: add real security hardening to a sample website (e.g., secure headers, input validation, rate-limiting design, auth checks) and produce test cases proving controls reject malicious input while preserving legitimate flows.
- Observable Windows demo: run before/after safe tests, view a functioning hardened website, and display defensive evidence.
- Pass condition: verified security control behavior, not a recommended-controls list.

## Shared mandatory success criteria
1. All four demonstrations operable from **Windows via the HTTPS web interface**, with a clear generated artifact or execution receipt for each.
2. Vultr Serverless Inference request verified with real API success (configured != invoked).
3. Code execution isolated on Vultr with resource/time limits; demonstrate a safely stopped infinite loop and cleanup.
4. Evidence includes mission ID, role responsible, artifact hash, test outcome, and independently readable Specter audit trail.
5. Auth tokens never appear in screenshots, recording, logs committed to Git, or downloads; avoid exposing sensitive routes in public demo.
6. Public GitHub repository contains runnable sanitized source, an architectural README and documented validation instructions.
7. Demo video and slide deck accurately identify current implementation and limitations; do not call mock output a verified run.

## Deployment reminder
The current public version implements orchestral **analysis** for Research, Defense and Lab, and a limited Docker code-repair path for Software. These execution and artifact requirements are a **change request**, NOT verified existing features. A demo must not claim them complete unless implementation and live checks succeed.

## Suggested demonstration sequence
1. Windows browser: Software makes a tiny website and test receipt.
2. Windows browser: Defense hardens that website; before/after tests.
3. Windows browser: Research generates and runs a minimal deterministic notebook and exports `.ipynb`.
4. Windows browser: Authorized Lab tests harmless suspicious behavior in a constrained container, then triggers and contains a deliberately infinite loop.
5. Windows browser: Batman reviews Specter receipts, mission status and hashes.
