# Gotham 2.2 — Quick Launch without Cloud Charges

**Windows:** Extract the ZIP and open PowerShell in the project folder.
Before installing anything, you can inspect the laptop's CPU/RAM/GPU/storage without sending details to the cloud:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check_windows_hardware.ps1
```

Launch the offline dashboard:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_windows.ps1 -Mode offline
```

Open `http://127.0.0.1:8000`. The terminal displays a **mission token** and a different **Batman audit token**. Keep both private. Offline mode is useful for inspecting the app and verifying the architecture, but doesn't produce actual model reasoning.

For locally hosted AI (free local compute, normal electricity use), install/start [Ollama](https://ollama.com/) and run `ollama pull qwen2.5:1.5b`, then:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_windows.ps1 -Mode ollama
```

**Laptop safety:** By default, workers share **one** Ollama model and local inference is serialized to limit memory pressure. Five agents produce five distinct analyses, but do not require five models loaded at once. Ollama cloud-model names ending in `-cloud` or `:cloud` are rejected in local mode. For stronger assurance, disable Ollama cloud features in Ollama server settings and restart Ollama. Consult https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features . This does not make Gotham an always-on service after the laptop shuts down.

**Linux/macOS:** `bash scripts/start_unix.sh offline` or `bash scripts/start_unix.sh ollama` (with Ollama running and model downloaded).

**For code repair:** Docker Desktop/Engine must be running. Cache the Python sandbox image once using `docker pull python:3.12-alpine`. `General Objective` does not require Docker; `Code Repair` does. Never install a cloud or paid inference provider just to try the local version.

**Tests:** `python -m pytest -q -m "not docker"`. Real Docker integration tests need a daemon and `GOTHAM_RUN_DOCKER_TESTS=1` and have not been validated in this build environment.


**First actual local-model proof:** With Ollama and `qwen2.5:1.5b` ready, open a second PowerShell window in the extracted project folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\prove_local_windows.ps1
```

This produces actual Qwen requests through Alfred and the five workers and a local Specter receipt; it cannot prove accuracy or external tool execution. Read `LOCAL_LAUNCH_CARD.md` for the full sequence. Native Ollama limits: default 4K context, model unload after 30s idle, and one request at a time within Gotham.
