"""Specter service configuration refuses unsafe identities and unprovisioned paths."""
import os

import pytest

from gotham.core.specter_service import main


def _args(tmp_path, worker, batman):
    return ["--journal", str(tmp_path / "audit" / "specter.sqlite3"),
            "--record-socket", str(tmp_path / "record" / "record.sock"),
            "--verify-socket", str(tmp_path / "verify" / "verify.sock"),
            "--worker-uid", str(worker), "--batman-api-uid", str(batman)]


def test_service_rejects_root_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    with pytest.raises(SystemExit, match="2"):
        main(_args(tmp_path, 1001, 1002))


def test_service_rejects_same_worker_and_batman_uid(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    with pytest.raises(SystemExit) as error:
        main(_args(tmp_path, 1001, 1001))
    assert error.value.code == 2


def test_service_rejects_auditor_sharing_worker_or_batman_uid(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    for worker, batman in ((1000, 1001), (1001, 1000)):
        with pytest.raises(SystemExit) as error:
            main(_args(tmp_path, worker, batman))
        assert error.value.code == 2


def test_service_never_auto_creates_privileged_socket_directories(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    with pytest.raises(SystemExit) as error:
        main(_args(tmp_path, 1001, 1002))
    assert error.value.code == 2
    assert not (tmp_path / "record").exists()
    assert not (tmp_path / "verify").exists()
    assert not (tmp_path / "audit").exists()
