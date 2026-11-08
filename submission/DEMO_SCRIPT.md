# Gotham Orchestra hackathon demo script

**Length target:** approximately 2–3 minutes, adjusted to official event rules.

1. **Problem (20 seconds):** AI agents can produce code that is wrong or unsafe; businesses need execution evidence and narrow authorization.
2. **Architecture (25 seconds):** Show Batman -> Alfred -> workers and four domain orchestras on Vultr VM, with hosted Vultr inference and independent Specter.
3. **Real agent work (40 seconds):** Issue a small code-repair mission. Show the model proposal, isolated execution, assertions, and returned evidence. Do not claim an unexecuted task passed.
4. **Containment moment (40 seconds):** Run an isolated infinite-loop test. Show the enforced timeout, nonzero exit/timeout status, no host damage, and container cleanup.
5. **Independent audit (20 seconds):** Show Specter findings without disclosing Batman audit token.
6. **Business use case (25 seconds):** Demonstrate how the same control plane helps a software team safely review AI-generated code; note research and security orchestras are currently planning modules unless execution features are validated.
7. **Close (10 seconds):** Show GitHub source, architecture README, live URL, and status of verified vs planned features.

Never record private API keys, cloud passwords, mission tokens, or audit tokens.
