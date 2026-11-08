# Live Vultr verification evidence — 2026-11-08

**Status:** Results transcribed from owner-provided terminal evidence, not independently fetched from Vultr by GitHub.

## Deployed infrastructure
- Vultr Ubuntu 24.04 VM at `155.138.194.208`.
- Public HTTPS site: https://155.138.194.208.sslip.io/
- Orchestra interface: https://155.138.194.208.sslip.io/orchestra
- Specter interface: https://155.138.194.208.sslip.io/specter
- Backend health returned `{"status":"ok"}`; configured hosted model `qwen3.8-flash-next`.
- A direct Vultr Serverless Inference request returned **HTTP 200** and response `{"status":"online"}`.

## Real containment probe
The live `POST /api/containment-probe` returned:

```json
{
  "probe": "cpu_infinite_loop",
  "contained": true,
  "evidence": {
    "passed": false,
    "timed_out": true,
    "exit_code": 124,
    "output": "Sandbox stopped at execution time limit",
    "sandbox": "docker",
    "network": "none",
    "container_destroyed": true,
    "code_sha256": "d8b5c4b6751d495e5ffef53e4af21891adb500da0df28dc19727ca0cda213d8b"
  }
}
```

`evidence.passed=false` is the expected result of the *infinite-loop program*, not failure of containment: the protected runtime stopped it at the time limit.

## Four-orchestra hosted-model demonstration after AI hotfix

| Orchestra | Mission ID | Specialist reports | Docker test | Container cleanup |
| --- | --- | --- | --- | --- |
| Software | `728421ec-90cd-4d28-be26-3b4941a19f18` | 3 of 3 `analysis_ready` | true | true |
| Defense | `df97feb9-03e4-4d83-92bc-1cc81080aaa3` | 3 of 3 `analysis_ready` | true | true |
| Research | `5bdcfd36-b30e-45c6-95a7-40f22b67c109` | 3 of 3 `analysis_ready` | true | true |
| Lab | `b08279f5-141a-41eb-8296-845c0c508a37` | 3 of 3 `analysis_ready` | true | true |

The demo artifacts are deterministic bounded templates with model-powered **analysis**; they must not be described as arbitrary applications written autonomously by the specialists.

## Specter audit

For each of the four missions, Specter returned **11 recorded events** and internally valid audit-chain integrity. On the Research mission, **one finding** was returned:

`Captain planning incomplete; deterministic roles retained`

This demonstrates recorded policy findings, but not tamperproof external attestation. Workers do not have Batman-only API access; no guarantee is claimed that workers cannot learn Specter exists by inspecting open-source project materials.

## Remaining work for final submission
- Automated GitHub workflow conclusion has not been confirmed.
- Demo video evidence reel has been generated separately from screenshots and logs, but has **not yet been hosted on a public/unlisted video service**.
- Required final lablab.ai entry has **not yet been submitted**.

**Product and security scope:** Controlled sandboxed Python/code-repair demonstrations, four AI analysis orchestras, independent audit trails, downloadable bounded example artifacts. Not unrestricted full software factories, external research agents, or deployable malware.
