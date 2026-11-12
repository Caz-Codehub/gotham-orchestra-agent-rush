# Accepted dependency risks (time-boxed)

`pip-audit` is a **hard gate** for `requirements.txt` (the API/worker runtime): it must be clean.
`requirements-scanners.txt` (Semgrep, isolated in `.scanners`) carries pinned transitive dependencies that cannot be upgraded without breaking Semgrep
(verified 2026-11-10: forcing `mcp 2.x` / `opentelemetry-api 1.45` makes `semgrep` fail at import). The following advisories are therefore **explicitly ignored for that
file only**, each reviewed against its description:

| Advisory | Package | Why not reachable in Gotham | Review by |
|---|---|---|---|
| CVE-2026-59951 / GHSA-84m7-p3x7-pcfv | mcp 1.29.0 | Streamable-HTTP **server** session leak; Gotham never runs `semgrep mcp` | 2026-12-10 |
| CVE-2026-116685 / GHSA-5h93-6whr-6q8j | mcp 1.29.0 | MCP **client** follows cross-origin redirects; no MCP client use | 2026-12-10 |
| CVE-2026-116684 / GHSA-w4fh-qvv9-3v23 | mcp 1.29.0 | MCP server bearer-audience check; no MCP server run | 2026-12-10 |
| CVE-2026-116686 / GHSA-rwrf-2pqf-9j8j | mcp 1.29.0 | MCP client `$ref` fetching; no MCP client use | 2026-12-10 |
| CVE-2026-114603 / GHSA-xcq7-p3pf-p88h | opentelemetry-api 1.37.0 | ReDoS parsing inbound `tracestate` HTTP header; Semgrep exposes no HTTP listener | 2026-12-10 |

Mitigations: Semgrep lives in its own venv (not importable by the API/worker); it runs `scan` only, over files the worker already confined to a task workspace;
`--metrics=off`. **Owner action:** re-check on the review date; when Semgrep ships updated pins, delete the ignores. The descriptions were read, but exploitability analysis
beyond "feature not used" was not performed.
