from __future__ import annotations

import json
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))

from schemas import TYPE_REGISTRY, __version__ as SCHEMA_VERSION  # noqa: E402
from scripts.audit import emit_schema  # noqa: E402


def test_snapshot_payload_covers_every_registered_type() -> None:
    payload = emit_schema.build_snapshot()

    assert payload["version"] == "quasi-schema-snapshot.v1"
    assert payload["schema_version"] == SCHEMA_VERSION
    assert list(payload["types"]) == sorted(TYPE_REGISTRY)
    assert set(payload["types"]) == set(TYPE_REGISTRY)
    assert all(set(entry) == {"required"} for entry in payload["types"].values())


def test_snapshot_write_is_atomic_and_idempotent(tmp_path: Path) -> None:
    path, changed = emit_schema.write_snapshot(tmp_path)

    assert changed is True
    assert path == (tmp_path / ".quasi" / "schema.json").resolve()
    first_bytes = path.read_bytes()
    first_payload = json.loads(first_bytes)
    assert first_payload["version"] == "quasi-schema-snapshot.v1"
    assert "generated_at" in first_payload

    same_path, changed_again = emit_schema.write_snapshot(tmp_path)

    assert same_path == path
    assert changed_again is False
    assert path.read_bytes() == first_bytes
