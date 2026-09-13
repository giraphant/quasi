from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
AUDIT = PLUGIN_ROOT / "scripts" / "audit" / "audit.py"
SCRIPTS_ROOT = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from schemas import TYPE_REGISTRY  # noqa: E402


def run_audit(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AUDIT), *args],
        cwd=project,
        text=True,
        capture_output=True,
        timeout=10,
    )


def write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def tree_digest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def valid_paper(*, extra_h2: str = "") -> str:
    return f"""---
type: paper
title: Audit Contract Paper
authors:
- Aryn Martin
year: 2020
journal: Endeavour
themes:
- audit-contract
---

# Audit Contract Paper

## 核心论点

One argument.

## 理论框架

One framework.

## 分节摘要

### Opening

One section.

## 关键概念

| 概念 | 英文 | 提出者 | 定义 |
|---|---|---|---|
| 契约 | Contract | Aryn Martin | A stable interface. |

## 核心引用

1. **Martin (2020)** — *Audit Contract Paper* — Source.
{extra_h2}"""


def test_all_report_modes_are_stdout_only_and_byte_stable(tmp_path: Path) -> None:
    project = tmp_path / "project"
    write_markdown(
        project / "vault" / "images" / "artifact" / "image.md",
        "---\ntype: image\ntitle: Artifact\n---\n\n# Artifact\n",
    )
    before = tree_digest(project)

    invocations = [
        ("fields",),
        ("toc", "--format", "json"),
        ("typecheck", "--format", "json"),
    ]
    for invocation in invocations:
        first = run_audit(project, "--path", "vault", "--report", *invocation)
        second = run_audit(project, "--path", "vault", "--report", *invocation)
        assert first.returncode == 0, first.stderr
        assert second.returncode == 0, second.stderr
        assert first.stdout == second.stdout
        assert first.stderr == second.stderr == ""
        assert tree_digest(project) == before

    assert not (project / ".quasi").exists()


def test_typecheck_report_json_covers_registry_and_separates_warnings(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    write_markdown(
        project / "vault" / "papers" / "paper.md",
        valid_paper(extra_h2="\n## Extra\n\nAdvisory text.\n"),
    )

    result = run_audit(
        project,
        "--path",
        "vault",
        "--report",
        "typecheck",
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["version"] == "quasi-typecheck.results.v1"
    assert payload["status"] == "clean"
    assert list(payload["types"]) == [*TYPE_REGISTRY, "unknown"]
    assert payload["summary"]["body_violations"] == 0
    assert payload["summary"]["body_warnings"] == 1
    assert payload["files"][0]["body_warnings"] == [
        {"kind": "unknown_h2", "h2": "Extra"}
    ]
    assert not (project / ".quasi").exists()


def test_typecheck_report_missing_path_returns_two_without_writing(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    before = tree_digest(project)

    result = run_audit(
        project,
        "--path",
        "vault",
        "--report",
        "typecheck",
        "--format",
        "json",
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["version"] == "quasi-typecheck.results.v1"
    assert payload["target"]["exists"] is False
    assert tree_digest(project) == before
    assert not (project / ".quasi").exists()


def test_toc_report_excludes_every_dot_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    visible = project / "vault" / "books" / "visible" / "ch01-visible.md"
    hidden = project / "vault" / "books" / ".trash" / "hidden" / "ch01-hidden.md"
    write_markdown(visible, "---\ntype: chapter\ntitle: Visible\n---\n\nBody.\n")
    write_markdown(hidden, "---\ntype: chapter\ntitle: Hidden\n---\n\nBody.\n")

    result = run_audit(
        project,
        "--path",
        "vault",
        "--report",
        "toc",
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"] == {"books": 1, "chapters": 1}
    assert [book["path"] for book in payload["books"]] == ["vault/books/visible"]
    assert "Hidden" not in result.stdout
    assert not (project / ".quasi").exists()


def test_default_audit_keeps_nonstrict_unknown_h2_advisory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    write_markdown(
        project / "vault" / "papers" / "paper.md",
        valid_paper(extra_h2="\n## Extra\n\nAdvisory text.\n"),
    )

    result = run_audit(project, "--path", "vault")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    diagnostics = [
        diagnostic
        for file_payload in payload["files"]
        for diagnostic in file_payload["diagnostics"]
    ]
    assert payload["status"] == "clean"
    assert payload["summary"]["advisory"] == 1
    assert any(
        diagnostic["id"] == "body.Extra.unknown_h2"
        and diagnostic["status"] == "advisory"
        and diagnostic["action"] == "none"
        for diagnostic in diagnostics
    )
