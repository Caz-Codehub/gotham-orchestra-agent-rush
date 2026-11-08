# Security policy

Gotham Orchestra is a hackathon prototype. Do not submit private data, production credentials, or client secrets. The public demo is not a production penetration-testing service.

- Keep `/etc/gotham.env`, API keys, mission tokens, audit tokens, private SSH keys and `.env` files out of Git.
- Only the server-side service should read inference credentials.
- Use separate mission and Batman audit credentials. Never publish either to judges.
- Execute generated code in constrained Docker sandboxes without network, with resource and time limits and cleanup. Docker isolation is defense in depth, not proof against all escapes.
- Authorization and scope are required for security-lab work. Remote offensive testing is not enabled by default.
- Confirm container cleanup and stopped infinite-loop evidence in a live demonstration.
- Rotate any credentials accidentally exposed.
