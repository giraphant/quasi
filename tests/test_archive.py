"""Archive metadata, freeform audit, and exact-path discovery contracts."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.schemas.archive import ArchiveSchema
from scripts.schemas.note import NoteSchema
from scripts.status.status import archive_status, scan_status
from scripts.vault.resolve import resolve
from scripts.typecheck.typecheck import check_file


MINIMAL = {"type": "archive", "title": "评论截图", "kind": "thread", "created": "2026-09-20"}


def write_archive(root: Path, body: str = "") -> Path:
    path = root / "vault/archives/discussion/archive.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\ntype: archive\ntitle: 评论截图\nkind: thread\ncreated: 2026-09-20\n---\n" + body)
    return path


@pytest.mark.parametrize("kind", ["patent", "thread", "post", "video", "image", "webpage", "document"])
def test_archive_kinds_and_optional_metadata(kind):
    record = ArchiveSchema.model_validate({**MINIMAL, "kind": kind})
    assert record.model_dump(exclude_unset=True).keys() == MINIMAL.keys()
    full = ArchiveSchema.model_validate({**MINIMAL, "kind": kind, "creator": ["某用户"],
        "date": "2025-08-30", "source": "论坛截图", "url": "https://example.com/123",
        "themes": ["感官判断"], "topics": ["second-hand"], "rating": 4})
    assert full.topics == ["second-hand"]


@pytest.mark.parametrize("patch", [{"kind": "pdf"}, {"kind": "audio"}, {"created": "2026"},
    {"date": "2025-08"}, {"date": 0}, {"created": "2026-09-20T00:00:00"}, {"creator": "某用户"}, {"rating": 6}, {"original": "original.pdf"}])
def test_archive_rejects_invalid_metadata(patch):
    with pytest.raises(ValidationError):
        ArchiveSchema.model_validate({**MINIMAL, **patch})


@pytest.mark.parametrize("field", ["type", "title", "kind", "created"])
def test_archive_required_fields(field):
    with pytest.raises(ValidationError):
        ArchiveSchema.model_validate({k: v for k, v in MINIMAL.items() if k != field})


@pytest.mark.parametrize("body", ["", "简短说明。\n", "# 评论截图\n\n## 自定义栏目\n\n[来源](https://example.com)\n"])
def test_archive_audit_and_discovery_without_attachments(tmp_path, body):
    path = write_archive(tmp_path, body)
    result = check_file(path)
    assert result["frontmatter_errors"] == []
    assert result["body_violations"] == []
    assert result["body_warnings"] == []
    status = archive_status(tmp_path, "discussion")
    assert status["facts"] == {"kind": "archive", "canonical": {
        "path": "vault/archives/discussion/archive.md", "present": True, "usable": True}}
    assert status["identity"]["created"] == "2026-09-20"
    assert {"kind": "archive", "slug": "discussion"} in scan_status(tmp_path)["items"]
    resolved = resolve(tmp_path, [{"kind": "archive", "slug": "discussion"}])["resolved"][0]
    assert resolved["path"] == "vault/archives/discussion/archive.md"
    assert resolved["match"] == "slug"
    NoteSchema.model_validate({"type": "note", "title": "个人思考", "created": "2026-09-21", "annotates": resolved["path"]})


def test_archive_missing_invalid_and_unsafe(tmp_path):
    assert not archive_status(tmp_path, "discussion")["facts"]["canonical"]["usable"]
    assert resolve(tmp_path, [{"kind": "archive", "slug": "absent", "doi": "10.1234/test"}])["scanned"] == {}
    path = write_archive(tmp_path)
    path.write_text(path.read_text().replace("kind: thread", "kind: pdf"))
    assert not archive_status(tmp_path, "discussion")["facts"]["canonical"]["usable"]
    path.unlink()
    target = tmp_path / "outside.md"
    target.write_text("secret")
    path.symlink_to(target)
    assert not archive_status(tmp_path, "discussion")["facts"]["canonical"]["usable"]
    assert scan_status(tmp_path)["items"] == []
    assert resolve(tmp_path, [{"kind": "archive", "slug": "discussion"}])["resolved"][0]["error"]
    assert resolve(tmp_path, [{"kind": "archive", "slug": "../outside"}])["resolved"][0]["error"]


def test_archive_audit_cli_preserves_lightweight_record(tmp_path):
    path = write_archive(tmp_path, "## 自定义\n\n[附件](saved-screenshot.png)\n")
    run = subprocess.run([sys.executable, str(ROOT / "scripts/audit/audit.py"), "--path", str(path)],
                         cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "## 自定义" in path.read_text()
    assert "saved-screenshot.png" in path.read_text()
    snapshot = json.loads((tmp_path / ".quasi/schema.json").read_text())
    assert snapshot["types"]["archive"]["required"] == ["title", "kind", "created"]
    status = subprocess.run([sys.executable, str(ROOT / "scripts/status/status.py"),
        "--kind", "archive", "--slug", "discussion", "--json"], cwd=tmp_path, capture_output=True, text=True)
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["facts"]["canonical"]["usable"]


def test_archive_scan_requires_canonical_entry(tmp_path):
    directory = tmp_path / "vault/archives/attachment-only"
    directory.mkdir(parents=True)
    (directory / "saved.pdf").write_bytes(b"placeholder")
    (directory / "notes.md").write_text("not an object entry")
    assert scan_status(tmp_path)["items"] == []
    assert resolve(tmp_path, [{"kind": "archive", "slug": "attachment-only"}])["resolved"][0]["path"] is None


def test_archive_discovery_rejects_symlinked_ancestor(tmp_path):
    path = write_archive(tmp_path)
    directory = path.parent
    moved = tmp_path / "saved-discussion"
    directory.rename(moved)
    directory.symlink_to(moved, target_is_directory=True)
    assert not archive_status(tmp_path, "discussion")["facts"]["canonical"]["usable"]
    assert scan_status(tmp_path)["items"] == []
    assert resolve(tmp_path, [{"kind": "archive", "slug": "discussion"}])["resolved"][0]["error"]
