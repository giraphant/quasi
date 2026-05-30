from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))

from schemas import __version__ as SCHEMA_VERSION  # noqa: E402
from scripts.audit.emit_schema import (  # noqa: E402
    SNAPSHOT_RELPATH,
    SNAPSHOT_VERSION,
    build_snapshot,
    write_snapshot,
)

# The required-field table the vault publishes for external readers (Marple).
# `type` is excluded as a tautological discriminator. This mirrors the schema
# models; if a model's required fields change, update this expectation too.
EXPECTED_REQUIRED = {
    "author": ["name"],
    "book": ["title", "authors", "year", "publisher"],
    "chapter": ["title", "authors", "year", "book"],
    "image": ["title"],
    "journal": ["title", "kind", "journal"],
    "note": ["title", "created"],
    "paper": ["title", "authors", "year", "journal", "themes"],
    "topic": ["title", "kind"],
}


def test_snapshot_has_stable_contract_fields() -> None:
    snap = build_snapshot()
    assert snap["version"] == SNAPSHOT_VERSION
    assert snap["schema_version"] == SCHEMA_VERSION
    assert "generated_at" not in snap  # volatile key lives only in the written file


def test_snapshot_required_fields_match_expected_table() -> None:
    snap = build_snapshot()
    got = {name: spec["required"] for name, spec in snap["types"].items()}
    assert got == EXPECTED_REQUIRED


def test_snapshot_excludes_type_discriminator() -> None:
    snap = build_snapshot()
    for spec in snap["types"].values():
        assert "type" not in spec["required"]


def test_write_snapshot_creates_file_with_generated_at(tmp_path: Path) -> None:
    path, changed = write_snapshot(tmp_path)
    assert changed is True
    assert path == (tmp_path / SNAPSHOT_RELPATH).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == SNAPSHOT_VERSION
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["generated_at"].endswith("Z")
    got = {name: spec["required"] for name, spec in payload["types"].items()}
    assert got == EXPECTED_REQUIRED


def test_write_snapshot_is_idempotent(tmp_path: Path) -> None:
    path1, changed1 = write_snapshot(tmp_path)
    assert changed1 is True
    first = path1.read_text(encoding="utf-8")

    path2, changed2 = write_snapshot(tmp_path)
    assert changed2 is False  # stable content unchanged → no rewrite
    assert path1 == path2
    assert path2.read_text(encoding="utf-8") == first  # byte-identical, no churn


def test_write_snapshot_rewrites_when_content_changes(tmp_path: Path) -> None:
    path, _ = write_snapshot(tmp_path)
    # Corrupt the stable content; the next run must detect the drift and rewrite.
    path.write_text(json.dumps({"version": "stale", "types": {}}), encoding="utf-8")
    _, changed = write_snapshot(tmp_path)
    assert changed is True
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == SNAPSHOT_VERSION
