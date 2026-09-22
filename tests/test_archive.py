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
    assert all(w["kind"] == "unknown_h2" for w in result["body_warnings"])
    status = archive_status(tmp_path, "discussion")
    assert status["facts"]["canonical"] == {
        "path": "vault/archives/discussion/archive.md", "present": True, "usable": True}
    assert not status["facts"]["collection"]["present"]
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


def test_archive_url_resolution_reuses_owner_and_rejects_duplicates(tmp_path):
    path = write_archive(tmp_path)
    path.write_text(path.read_text().replace("created:", "url: https://example.org/manual\ncreated:"))
    row = resolve(tmp_path, [{"kind": "archive", "slug": "new-topic-title", "url": "https://example.org/manual#section"}])["resolved"][0]
    assert row["vault_slug"] == "discussion"
    assert row["match"] == "url"
    assert resolve(tmp_path, [{"kind": "archive", "slug": "discussion", "url": "https://other.org/manual"}])["resolved"][0]["error"]
    other = tmp_path / "vault/archives/duplicate/archive.md"
    other.parent.mkdir()
    other.write_bytes(path.read_bytes())
    row = resolve(tmp_path, [{"kind": "archive", "slug": "new", "url": "https://example.org/manual"}])["resolved"][0]
    assert "multiple" in row["error"]


def test_topic_archive_links_validate_and_track_membership(tmp_path):
    from scripts.schemas.topic import TopicSchema
    from scripts.status.status import topic_status
    archive = write_archive(tmp_path)
    archive.write_text(archive.read_text().replace("created:", "topics:\n  - repair\ncreated:"))
    topic = tmp_path / "vault/topics/repair"
    (topic / "cards").mkdir(parents=True)
    (topic / "02-outline.md").write_text("---\ntype: topic\nkind: outline\ntitle: Repair research\nsubquestions:\n  - id: scope\n    question: What does the manual cover?\n    coverage: covered\n    cards:\n      - manual\n---\n")
    card = topic / "cards/manual.md"
    card.write_text("---\ntype: topic\nkind: card\ntitle: Repair evidence\narchives:\n  - vault/archives/discussion/archive.md\n---\nEvidence from [manual](../../../archives/discussion/archive.md).\n")
    status = topic_status(tmp_path, "repair")
    assert status["facts"]["outline"]["projection"]["cards"][0]["artifact"]["usable"]
    archive.write_text(archive.read_text().replace("  - repair", "  - different-topic"))
    status = topic_status(tmp_path, "repair")
    assert not status["facts"]["outline"]["projection"]["cards"][0]["artifact"]["usable"]
    with pytest.raises(ValidationError):
        TopicSchema.model_validate({"type": "topic", "kind": "card", "title": "Invalid link", "archives": ["vault/webpages/x/webpage.md"]})
    with pytest.raises(ValidationError):
        TopicSchema.model_validate({"type": "topic", "kind": "overview", "title": "Invalid kind", "archives": ["vault/archives/x/archive.md"]})
