"""Small runtime foundation for quasi scripts.

Keep this file boring. It is shared plumbing for paths, frontmatter, JSON, and
dynamic script loading; domain policy belongs in scripts/* or scripts/schemas.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml


FM_RE = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$")


@dataclass(frozen=True)
class FrontmatterDoc:
    """Parsed markdown frontmatter plus remaining body."""

    frontmatter: dict[str, Any] | None
    body: str


def plugin_root(anchor: str | Path | None = None) -> Path:
    """Return the quasi plugin root.

    When `anchor` is provided, walk upward until `.claude-plugin/plugin.json` is
    found. Without an anchor, resolve from this package location.
    """

    if anchor is None:
        return Path(__file__).resolve().parents[1]

    path = Path(anchor).resolve()
    current = path if path.is_dir() else path.parent
    for candidate in (current, *current.parents):
        if (candidate / ".claude-plugin" / "plugin.json").exists():
            return candidate
    raise RuntimeError(f"cannot locate quasi plugin root from {path}")


def project_root() -> Path:
    """Return the caller's research project root."""

    return Path(
        os.environ.get("QUA_PROJECT_ROOT")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.getcwd()
    ).resolve()


def resolve_project_path(path_arg: str | Path, root: Path | None = None) -> Path:
    """Resolve `path_arg` relative to the project root when it is not absolute."""

    path = Path(path_arg).expanduser()
    if not path.is_absolute():
        path = (root or project_root()) / path
    return path.resolve()


def read_frontmatter(path: Path) -> FrontmatterDoc:
    """Read markdown frontmatter.

    Invalid or missing frontmatter is represented as `None`; the body is always
    returned so callers can decide whether that is fatal.
    """

    text = path.read_text(encoding="utf-8")
    match = FM_RE.match(text)
    if not match:
        return FrontmatterDoc(None, text)
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return FrontmatterDoc(None, match.group(2))
    if not isinstance(data, dict):
        return FrontmatterDoc(None, match.group(2))
    return FrontmatterDoc(data, match.group(2))


def dump_frontmatter(data: dict[str, Any]) -> str:
    """Serialize frontmatter with quasi's stable YAML style.

    `default_flow_style=False` is required by SPEC §5.2 (block-list arrays).
    Ulysses / Bear / iA Writer corrupt inline flow arrays (`[a, b]` → `[a, b](#)`);
    block lists have no `[` `]` for them to bite.
    """

    return yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()


def atomic_write_text(path: Path, text: str) -> None:
    """Atomically write UTF-8 text to `path`."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
    ) as handle:
        tmp = Path(handle.name)
        handle.write(text)
    tmp.replace(path)


def write_frontmatter(path: Path, data: dict[str, Any], body: str) -> None:
    """Write markdown with YAML frontmatter and body."""

    text = f"---\n{dump_frontmatter(data)}\n---\n{body}"
    atomic_write_text(path, text)


def write_json(path: Path, data: Any) -> None:
    """Write stable UTF-8 JSON."""

    atomic_write_text(
        path,
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
    )


def print_json(data: Any) -> None:
    """Print stable UTF-8 JSON to stdout."""

    print(json.dumps(data, ensure_ascii=False, indent=2))


def load_script_module(name: str, path: Path) -> ModuleType:
    """Load a script file as a module without relying on package layout."""

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
