"""Artifact-integrity falsification tests for Alfred's final mission gate."""
import hashlib

from gotham.core.engine import verify_artifact_integrity


def _receipt(path, **overrides):
    data = path.read_bytes()
    return {"id": "artifact-1", "name": path.name, "path": str(path),
            "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), **overrides}


def test_finalization_rehashes_actual_file(tmp_path):
    root = tmp_path / "mission"
    root.mkdir()
    file = root / "evidence.json"
    file.write_text('{"checked":true}', encoding="utf-8")
    r = _receipt(file)
    assert verify_artifact_integrity([r], root)[0]["pass"] is True
    file.write_text('{"checked":fals}', encoding="utf-8")  # identical size, altered content
    result = verify_artifact_integrity([r], root)[0]
    assert result["pass"] is False
    assert result["reason"] == "content_or_size_mismatch"


def test_missing_file_fails_verification(tmp_path):
    root = tmp_path / "mission"
    root.mkdir()
    p = root / "report.txt"
    p.write_text("test", encoding="utf-8")
    receipt = _receipt(p)
    p.unlink()
    assert verify_artifact_integrity([receipt], root)[0]["pass"] is False


def test_outside_file_and_symlink_are_rejected(tmp_path):
    root = tmp_path / "mission"
    root.mkdir()
    external = tmp_path / "outside"
    external.write_text("not in the mission", encoding="utf-8")
    link = root / "alias"
    link.symlink_to(external)
    receipts = [_receipt(external), {**_receipt(external), "path": str(link), "id": "alias"}]
    results = verify_artifact_integrity(receipts, root)
    assert [r["pass"] for r in results] == [False, False]


def test_empty_artifacts_is_not_a_failure(tmp_path):
    assert verify_artifact_integrity([], tmp_path) == []
