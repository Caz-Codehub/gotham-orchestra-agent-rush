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


def test_service_refuses_inherited_audit_secret(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.setenv("GOTHAM_AUDIT_KEY", "never-share-a-private-specter-key")
    with pytest.raises(SystemExit) as error:
        main(_args(tmp_path, 1001, 1002))
    assert error.value.code == 2
    assert not (tmp_path / "audit").exists()


def test_service_refuses_world_accessible_audit_socket_directory(monkeypatch, tmp_path, capsys):
    if os.getuid() == 0:
        pytest.skip("directory-ownership test runs as non-root")
    for name in ("record", "verify", "audit"):
        (tmp_path / name).mkdir(mode=0o700)
    (tmp_path / "record").chmod(0o777)
    with pytest.raises(SystemExit) as err:
        main(_args(tmp_path, os.getuid() + 10001, os.getuid() + 10002))
    assert err.value.code == 2
    assert "deny access to other users" in capsys.readouterr().err


def test_service_refuses_group_readable_private_audit_key(monkeypatch, tmp_path, capsys):
    if os.getuid() == 0:
        pytest.skip("directory-ownership test runs as non-root")
    for name in ("record", "verify", "audit"):
        (tmp_path / name).mkdir(mode=0o700)
    for name in ("record", "verify"):
        (tmp_path / name).chmod(0o2700)
    key = tmp_path / "audit" / "specter.key"
    key.write_text("fake-test-only-key", encoding="utf-8")
    key.chmod(0o640)
    with pytest.raises(SystemExit) as err:
        main(_args(tmp_path, os.getuid() + 10001, os.getuid() + 10002))
    assert err.value.code == 2
    assert "must not be group/world readable" in capsys.readouterr().err


def test_service_requires_setgid_socket_directories(monkeypatch, tmp_path, capsys):
    if os.getuid() == 0:
        pytest.skip("directory owner test runs as non-root")
    for name in ("record", "verify", "audit"):
        (tmp_path / name).mkdir(mode=0o700)
    with pytest.raises(SystemExit) as err:
        main(_args(tmp_path, os.getuid() + 10001, os.getuid() + 10002))
    assert err.value.code == 2
    assert "setgid" in capsys.readouterr().err
