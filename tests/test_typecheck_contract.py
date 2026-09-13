from __future__ import annotations

import hashlib
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))

from schemas import TYPE_REGISTRY, BodySchema, BodySection  # noqa: E402
from scripts.typecheck import typecheck  # noqa: E402


def write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def paper_markdown(*, extra_h2: str = "") -> str:
    return f"""---
type: paper
title: Contract Paper
authors:
- Aryn Martin
year: 2020
journal: Endeavour
themes:
- audit-contract
---

# Contract Paper

## 核心论点

The paper makes one argument.

## 理论框架

The paper uses one framework.

## 分节摘要

### Opening

The opening establishes the question.

## 关键概念

| 概念 | 英文 | 提出者 | 定义 |
|---|---|---|---|
| 契约 | Contract | Aryn Martin | A stable interface. |

## 核心引用

1. **Martin (2020)** — *Contract Paper* — Source.
{extra_h2}"""


def tree_digest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_frontmatter_failures_remain_distinct(tmp_path: Path) -> None:
    cases = {
        "missing.md": ("Plain body.\n", "missing_frontmatter"),
        "invalid.md": ("---\ntitle: [unclosed\n---\nBody.\n", "invalid_yaml"),
        "not-mapping.md": ("---\n- one\n- two\n---\nBody.\n", "frontmatter_not_mapping"),
        "missing-type.md": ("---\ntitle: Missing Type\n---\nBody.\n", "missing_type"),
        "unknown-type.md": ("---\ntype: mystery\ntitle: Mystery\n---\nBody.\n", "unknown_type"),
        "list-type.md": ("---\ntype:\n- paper\ntitle: List Type\n---\nBody.\n", "unknown_type"),
    }

    for filename, (text, expected) in cases.items():
        path = tmp_path / filename
        write_markdown(path, text)
        result = typecheck.check_file(path)
        assert [error["type"] for error in result["frontmatter_errors"]] == [expected]
        assert result["body_violations"] == []
        assert result["body_warnings"] == []


def test_unknown_h2_obeys_body_schema_strictness() -> None:
    section = BodySection(h2="Canonical", kind="paragraph", required=True)
    body = "## Canonical\n\nBody.\n\n## Extra\n\nMore.\n"

    loose = BodySchema(type_name="fixture", sections=[section], strict=False)
    strict = BodySchema(type_name="fixture", sections=[section], strict=True)

    loose_violations, loose_warnings = typecheck.check_body(body, loose)
    strict_violations, strict_warnings = typecheck.check_body(body, strict)

    assert loose_violations == []
    assert loose_warnings == [{"kind": "unknown_h2", "h2": "Extra"}]
    assert strict_violations == [{"kind": "unknown_h2", "h2": "Extra"}]
    assert strict_warnings == []


def test_alias_resolves_before_required_section_check() -> None:
    schema = BodySchema(
        type_name="fixture",
        sections=[
            BodySection(
                h2="Canonical",
                kind="paragraph",
                required=True,
                aliases=["Legacy"],
            )
        ],
    )

    violations, warnings = typecheck.check_body("## Legacy\n\nBody.\n", schema)

    assert violations == [{"kind": "h2_alias", "from": "Legacy", "to": "Canonical"}]
    assert warnings == []
    assert not any(item["kind"] == "missing_required_h2" for item in violations)


def test_run_typecheck_no_write_keeps_project_tree_unchanged(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    vault = project / "vault"
    write_markdown(
        vault / "papers" / "contract-paper.md",
        paper_markdown(extra_h2="\n## Extra\n\nAdvisory text.\n"),
    )
    monkeypatch.setattr(typecheck, "PROJECT_ROOT", project)
    monkeypatch.setattr(typecheck, "OUT_DIR", project / ".quasi" / "audit")
    before = tree_digest(project)

    exit_code = typecheck.run_typecheck(
        vault,
        quiet=True,
        write_report=False,
        results_path=None,
    )

    assert exit_code == 0
    assert tree_digest(project) == before
    assert not (project / ".quasi").exists()


def test_results_payload_is_stable_and_registry_driven(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_markdown(vault / "papers" / "contract-paper.md", paper_markdown())

    evaluation = typecheck.evaluate_typecheck(vault)
    first = typecheck.build_results_payload(evaluation, requested_path="vault")
    second = typecheck.build_results_payload(evaluation, requested_path="vault")

    assert first == second
    assert first["version"] == "quasi-typecheck.results.v1"
    assert first["status"] == "clean"
    assert list(first["types"]) == [*TYPE_REGISTRY, "unknown"]
    assert first["summary"] == {
        "files_checked": 1,
        "files_clean": 1,
        "files_with_errors": 0,
        "frontmatter_errors": 0,
        "body_violations": 0,
        "body_warnings": 0,
    }
