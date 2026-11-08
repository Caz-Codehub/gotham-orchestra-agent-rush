# Gotham Orchestra — Hackathon pitch deck (slide content)

## 1. Gotham Orchestra: Containment-first AI work
A human-directed, multi-agent command center on Vultr. Software engineering, research and security teams under Captain Alfred, with independent Specter auditing.

## 2. The problem
AI can generate plausible code without safe execution or reliable evidence. Teams need authorization, isolation, reproducibility and accountability before accepting automated output.

## 3. The solution
Batman -> Alfred -> five workers and four role-oriented orchestras; a single supervised task interface, network-restricted Docker execution, evidence receipts, and independent audit.

## 4. Architecture
Vultr Ubuntu VM; Caddy HTTPS; FastAPI backend bound to localhost; Vultr Serverless Inference for LLM tasks; Docker sandboxes for code checks; systemd services for Gotham and Specter. No production access granted to agents by default.

## 5. Live demonstration
- Show the publicly reachable command center and four orchestras
- Run a real code repair and test it in Docker
- Execute infinite-loop containment and show a timeout/cleanup receipt
- Review independent audit evidence
Only include a feature as *verified* if the recording actually demonstrates it.

## 6. Business value
Developer platforms and security teams need safer AI-assisted code review, automated test evidence, and permission boundaries. The long-term cross-orchestra roadmap includes artifact-generating research notebooks and defensive security workflows; current demo scope is narrower.

## 7. Competitive distinction
Cross-domain orchestration, independent auditor separated from mission agents, human final authority and tangible test evidence together. Avoid claiming isolation/auditing alone is novel, as other tools and hackathon entrants already offer these.

## 8. Current scope and roadmap
**Deployed:** public control plane and orchestra interfaces; code execution infrastructure; configured inference. **Evidence pending:** live model mission, sandbox containment receipt, real independent audit. **Future:** larger autonomous software-building/research artifact workflows.

## 9. Links
Application: https://155.138.194.208.sslip.io/
Repository: https://github.com/Caz-Codehub/gotham-orchestra-agent-rush
Official event: https://lablab.ai/ai-hackathons/vultr-hackathon
