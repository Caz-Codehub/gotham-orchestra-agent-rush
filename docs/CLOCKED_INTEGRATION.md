# Clocked integration — Gotham Orchestra

## Scope
This branch adds a **preflight gateway** to Gotham's existing Batman -> Alfred ->
five worker architecture. This is not a new orchestra. It is intended to be called
before Alfred/worker context ingestion and prior to any proposed script execution.
It does not change the four orchestra interfaces, Vultr deployment, or Specter.

**State: integration component, not yet wired into the live FastAPI routes.**
Do not claim live Clocked operation until a key is installed, the app routes call
`preflight`, and a live execution receipt is captured.

## Install and configure
- Install `clocked-sdk>=0.7,<1` in the production Python environment.
- Redeem `CLOCKEDHACKATHON` on the Clocked challenge account for the
  advertised credits, subject to organizer terms.
- Set `CLOCKED_API_KEY` on the server (systemd environment file or secret
  manager). **Never** place it in GitHub, frontend JavaScript, demo screenshots,
  logs, or any client-side environment.
- Import `from clocked_gateway import preflight`.
- For **untrusted external content**: `receipt = preflight(raw_text, source="tool")`.
  If `receipt.allowed` is false, do not route it into any worker.
  If true, pass only `receipt.sanitized_text` to the worker.
- For proposed scripts: `receipt = preflight(context, script=proposed_script)`.
  Continue only on `receipt.allowed`, *and* after Gotham's normal mission
  authorization, explicit execution approvals, and sandbox policy have passed.
  This gateway never executes scripts.

## Security boundary
- Clocked verdicts are advisory classification, not proof of safety.
- A positive Clocked verdict does not override user/mission authorization.
- Fail closed when the API is down, the response is ambiguous, or the key is absent.
- Do not log unredacted raw requests; persist only minimal receipts.
- Never let workers invoke the gateway to grant themselves more privileges.

## Offline tests
```bash
python -m unittest discover -s tests -p 'test_clocked_gateway.py'
```

## Live acceptance criteria (not yet met)
1. A legitimate request reaches the intended worker using sanitized text.
2. Malicious injected tool text is blocked and the worker is not invoked.
3. A risky script is blocked before Docker or any local runner is invoked.
4. A synthetic email/phone is masked before reaching the model.
5. Missing API key, timeout, malformed verdict, and provider outage fail closed.
6. Compare local receipts to the real Clocked API responses and expand the
   verdict parser if the real schema differs; never weaken fail-closed defaults
   without evidence.

## Challenge description
Gotham Orchestra is a human-directed agent command center: Batman assigns
missions to Captain Alfred, who coordinates five specialized workers. Clocked
Guard/Protect/Inspect are integrated as preflight controls so untrusted context,
personal data and scripts can change whether a task proceeds. The Clocked
functions must be called in the live app before this description is used as
a claim of completed functionality.

**Eligibility:** preserve the existing Git history and disclose prior
frameworks/other challenge work accurately. The first visible repository
commit is November 8, 2026; that alone does not prove no development predates
the challenge.
