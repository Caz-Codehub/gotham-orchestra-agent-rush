# Blockers and owner actions

| # | Blocker | Impact | Exact action needed |
|---|---|---|---|
| B1 | Build-session egress proxy denies `*.vultr.com`, `api.vultrinference.com`, `155.138.194.208.sslip.io` (HTTP 403 CONNECT) | Cannot verify credits, deploy, or call Vultr inference | Allow those hosts for the environment (Claude cloud environment network settings) or run `deploy/deploy.sh` from a machine with access; supply `VULTR_*` keys via the environment's secret store (never chat) |
| B2 | No inference credential/model in the session | **Agent-mode (LLM-driven) tasks, model decomposition and `objective` missions are BLOCKED**; playbooks work without a model | Provide Vultr inference key + model id (`GOTHAM_INFERENCE_PROVIDER=vultr`, `GOTHAM_ALLOW_PAID_INFERENCE=I_ACCEPT_POTENTIAL_CHARGES`) or a local Ollama model; then run the model-driven acceptance (see ACCEPTANCE §Agent mode) |
| B3 | Docker Hub rate-limit (429) and no `ghcr.io` DB path for Trivy | Container-image vulnerability scanning (`container_scan`) NOT TESTED | Provide a Trivy binary/DB mirror or allow `ghcr.io`; tool is implemented and fails closed when Trivy is absent |
| B4 | URR Alpha / URR 3.0 / Kaggle: `URR3_Google_Cloud` MCP tools exist but were not invoked (job submission needs `urr3.submit`, Kaggle needs credentials) | External research backends not integrated | Confirm URR 3.0 notebook-submission policy and provide Kaggle credentials if desired |
| B5 | GPU not present in session | GPU experiments NOT TESTED (`compute_info` reports `gpu: none detected`) | Run worker on a GPU host/backend |
| B6 | Audit writer shares a process with workers | Host-root compromise could forge the chain | Next action: split audit into its own Unix-user service (unix-socket append API) and forward chain head off-host |
| B7 | PR creation/`git push` from Forge | Not implemented (commits are local to the task workspace; artifacts export a patch) | Provide a scoped GitHub credential to a high-risk, approval-gated `git_push` tool (new account permission → needs Batman) |
| B8 | Pre-existing PR #1 (Clocked gateway, draft) | Not merged; needs real Clocked API key & contest-eligibility check | Batman decision |
