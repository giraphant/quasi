from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN_ROOT))

from core import (  # noqa: E402
    dump_frontmatter,
    plugin_root,
    project_root,
    read_frontmatter,
    resolve_project_path,
    write_frontmatter,
    write_json,
)


def test_project_root_precedence(monkeypatch, tmp_path):
    qua = tmp_path / "qua"
    claude = tmp_path / "claude"
    monkeypatch.setenv("QUA_PROJECT_ROOT", str(qua))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(claude))

    assert project_root() == qua.resolve()


def test_plugin_root_from_anchor():
    assert plugin_root(__file__) == PLUGIN_ROOT


def test_resolve_project_path(monkeypatch, tmp_path):
    monkeypatch.setenv("QUA_PROJECT_ROOT", str(tmp_path))

    assert resolve_project_path("vault/books") == (tmp_path / "vault/books").resolve()


def test_frontmatter_roundtrip(tmp_path):
    path = tmp_path / "doc.md"
    write_frontmatter(path, {"type": "book", "title": "A Book"}, "# A Book\n")

    doc = read_frontmatter(path)

    assert doc.frontmatter == {"type": "book", "title": "A Book"}
    assert doc.body == "# A Book\n"
    assert "title: A Book" in dump_frontmatter(doc.frontmatter)


def test_write_json(tmp_path):
    path = tmp_path / "out" / "data.json"
    write_json(path, {"title": "差异", "items": [1]})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "title": "差异",
        "items": [1],
    }
