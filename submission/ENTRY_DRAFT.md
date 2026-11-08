# Agent Rush Entry Draft — Gotham Project: Proof Before Permission

**Draft only. Not submitted, not publicly hosted, no prize claims.**

**Challenge target:** Blast Radius Zero, Pattern A (sandboxed code execution).

**Pitch:** Batman gives Captain Alfred a code-repair objective. Alfred coordinates five concurrent specialist workers—Scout, Forge, Oracle, Sentinel, and Cipher—and tests each candidate within an ephemeral, network-isolated Docker container. Approval requires actual evidence of successful tests, source hash consistency, and confirmed container cleanup. An independent auditor, Specter, watches command-team telemetry and alerts Batman to violations without being part of the workers' prompts or command chain.

**Business case:** Engineering organizations need agents that actually validate code under a restricted execution boundary, not assistants that merely assert a fix is safe. Gotham emphasizes auditable, constrained execution and human decision authority.

**Gotham 2.0 enhancement:** Generic objectives are decomposed by Alfred into five specialized model analyses; this route is clearly labeled analysis-only and cannot be used as proof of code execution. A zero-paid-cloud mode supports local Ollama model inference; it does not satisfy the event's Vultr inference requirement.

**Competition-specific requirements still missing:** Vultr VM backend, actual Vultr Serverless Inference calls, live Docker executions on Vultr, a public HTTPS app URL, a public repository, recorded demo, presentation and formal LabLab submission.

**Demo sequence (only after actual Vultr activation):**
1. Batman enters a broken addition function and assertions.
2. Alfred delegates to the five workers in parallel.
3. Oracle records a failing baseline Docker run.
4. Forge proposes a patch using Vultr Serverless Inference.
5. Alfred tests patch in a separate temporary Docker sandbox, confirms checksum and cleanup.
6. A containment probe intentionally spins forever, is timed out and removed.
7. Batman opens the protected Specter audit to see boundary events and an unauthorized-tool alert.
8. Present application URL, repository and a recorded screen capture of actual work.

**Important integrity rule:** Never imply local mock tests prove Vultr deployment or real model execution. The hackathon gift code was accepted in the owner's Vultr UI; a Remaining Credit balance and deployed VM are still unverified.
