# Gotham 2.1 — Zero-cloud-spend local operation

Batman owns all decisions. Alfred is Captain of Scout, Forge, Oracle, Sentinel,
and Cipher. Specter is an independent auditor; never a command layer.

## What "free local inference" means

- Ollama local inference uses your own CPU/GPU/RAM. It charges no cloud compute fee.
- Your electricity, existing internet and hardware are not free in an economic sense.
- The default application provider is `none`: no AI reasoning is performed.
- `ollama` connects only to `http://127.0.0.1:11434` with a downloaded model.
- Gotham refuses Ollama model names ending `:cloud` or `-cloud`, and its
  readiness check requires a model with positive downloaded size.
- A single process-wide inference gate prevents Gotham from flooding
  the laptop with five simultaneous model completions.
- Enable `disable_ollama_cloud` in Ollama's own server configuration for
  defense in depth; restarting Ollama is required. Documentation:
  https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features
- Vultr inference is never activated by the local launchers.

## Laptop-first sequence

1. Check hardware: `powershell -ExecutionPolicy Bypass -File .\scripts\check_windows_hardware.ps1`.
2. Install local Ollama from its official site; start Ollama.
3. Run `ollama pull qwen2.5:1.5b` once (approximately 986 MB download).
4. Run `powershell -ExecutionPolicy Bypass -File .\scripts\start_windows.ps1 -Mode ollama`.
5. Navigate to `http://127.0.0.1:8000`. Use Batman's private mission token.
6. General Objective mode conducts local model analysis; it does not yet
   browse the web or perform external operations.
7. Code Repair mode needs locally installed Docker Desktop with a cached
   sandbox image. Those real containment tests remain unverified here.

## What is not finished

This version has not been tested with real Ollama on your laptop or a live
Vultr instance. If the laptop shuts down, Gotham stops. GitHub-only hosting
cannot substitute for the Vultr VM requirement of the hackathon.

## 2.2 memory/resource controls

The Ollama local client uses the native loopback `/api/chat` API. It limits request context to 4096 tokens by default, model output tokens to a bounded amount, HTTP request duration to 90 seconds by default, and requested model keep-alive to 30 seconds (hard ceiling five minutes). Five worker tasks may be active, but their local model inferences are serialized through one process-wide lock. These are **not** a system-level RAM cap, nor a total mission deadline; external Ollama clients can still consume hardware resources. Use `ollama stop qwen2.5:1.5b` to manually release model RAM when studying.
