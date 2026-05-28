#!/usr/bin/env python3
"""Emit a machine-readable schema snapshot into the vault (QUA-97).

The vault becomes self-describing: instead of reaching into this plugin's Python
models, an external reader (Marple) loads
`$CLAUDE_PROJECT_DIR/.quasi/schema.json` to learn which frontmatter fields each
canonical type requires, then checks conformance natively — no Python at
runtime, no vault mutation.

Contract: `quasi-schema-snapshot.v1`.

`required` lists the fields Pydantic marks required (no default / default_factory),
excluding the tautological `type` discriminator. Field names are the *schema's*
names (e.g. `authors`, `name`); the reader maps them onto its own model.

Note on emptiness — a reader may treat "required" as "present AND non-empty":
that stays faithful to the schema because every required field in these models is
also value-constrained non-empty (Title/Name/ShortString are `min_length>=2`;
required list fields such as `paper.authors` / `paper.themes` are `min_length=1`).
The non-empty interpretation is the reader's presentation policy layered on
quasi's required-presence; it is documented here so the two cannot silently
diverge.

Usage (standalone, from inside a vault project):
  python "$CLAUDE_PLUGIN_ROOT/scripts/audit/emit_schema.py"
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

# Locate roots (this script lives at quasi/scripts/audit/emit_schema.py).
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))

from core import project_root, write_json  # noqa: E402
from schemas import TYPE_REGISTRY, __version__ as SCHEMA_VERSION  # noqa: E402

SNAPSHOT_VERSION = "quasi-schema-snapshot.v1"
SNAPSHOT_RELPATH = Path(".quasi") / "schema.json"

# Keys that make up the stable content. `generated_at` is intentionally excluded
# so an unchanged schema does not rewrite the file (avoids FSEvents churn for
# watchers like Marple).
_STABLE_KEYS = ("version", "schema_version", "types")


def _required_fields(model: Any) -> list[str]:
    """Required frontmatter field names for one Pydantic model, sans `type`."""
    return [
        name
        for name, field in model.model_fields.items()
        if field.is_required() and name != "type"
    ]


def build_snapshot() -> dict[str, Any]:
    """Build the stable snapshot payload (no volatile timestamp)."""
    types = {
        type_name: {"required": _required_fields(model)}
        for type_name, (model, _body) in sorted(TYPE_REGISTRY.items())
    }
    return {
        "version": SNAPSHOT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "types": types,
    }


def write_snapshot(root: Path | None = None) -> tuple[Path, bool]:
    """Write the snapshot to `$ROOT/.quasi/schema.json`, atomically + idempotently.

    Returns `(path, changed)`. When the stable content matches the existing file,
    the file is left untouched so filesystem watchers don't churn.
    """
    root = root or project_root()
    path = (root / SNAPSHOT_RELPATH).resolve()
    stable = build_snapshot()

    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            existing = None
        if isinstance(existing, dict):
            if {k: existing.get(k) for k in _STABLE_KEYS} == stable:
                return path, False

    generated_at = (
        _dt.datetime.now(_dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    # generated_at sits right after version so the file reads top-down.
    payload = {
        "version": stable["version"],
        "generated_at": generated_at,
        "schema_version": stable["schema_version"],
        "types": stable["types"],
    }
    write_json(path, payload)  # core.write_json is temp-file + atomic rename
    return path, True


def main(argv: list[str] | None = None) -> int:
    path, changed = write_snapshot()
    state = "wrote" if changed else "unchanged"
    print(f"[quasi] schema snapshot {state}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
