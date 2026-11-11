"""Transport-level fail-closed audit gateway tests."""
import json
import pytest

from gotham.inference import CompatibleInference


def test_transport_audit_failure_prevents_network(monkeypatch):
    from gotham.core import audit
    import gotham.inference as inference

    def fail(*args, **kwargs):
        raise OSError("independent journal unavailable")

    monkeypatch.setattr(audit, "AuditWriter", fail)

    def no_network(*args, **kwargs):
        raise AssertionError("network must not run before the audit sink commits")

    monkeypatch.setattr(inference.urllib.request, "urlopen", no_network)
    m = CompatibleInference(endpoint="http://127.0.0.1:11434/api/chat",
                            model="test-model", provider="ollama-local")
    with pytest.raises(OSError, match="journal unavailable"):
        m.chat("system", "synthetic input")


def test_transport_audit_commits_metadata_not_prompt(monkeypatch, env):
    from gotham.core import audit
    import gotham.inference as inference
    records = []

    class RecordingAudit:
        def __init__(self, path):
            pass

        def record(self, mid, tid, actor, action, detail):
            records.append((actor, action, detail))

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"message":{"content":"{\"ok\":true}"}}'

    monkeypatch.setattr(audit, "AuditWriter", RecordingAudit)
    monkeypatch.setattr(inference.urllib.request, "urlopen", lambda *a, **k: Reply())
    m = CompatibleInference(endpoint="http://127.0.0.1:11434/api/chat",
                            model="test-model", provider="ollama-local")
    # urllib's json.load calls response.read() and may call with chunk size.
    result = m.chat("hidden system instructions", "synthetic payload")
    assert result
    assert len(records) == 1
    actor, action, detail = records[0]
    assert actor == "InferenceGateway" and action == "pre_model_transport"
    assert detail["local"] is True
    assert "synthetic payload" not in str(detail)
    assert "hidden system instructions" not in str(detail)
