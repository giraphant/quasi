from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
AUDIT = PLUGIN_ROOT / "scripts" / "audit" / "audit.py"


def run_audit(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AUDIT), *args],
        cwd=project,
        text=True,
        capture_output=True,
        timeout=10,
    )


def write_paper(path: Path, frontmatter: str, key_concepts: str | None = None) -> None:
    key_concepts = key_concepts or """| 概念 | 英文 | 提出者 | 定义 |
|---|---|---|---|
| 概念A | Concept A | 作者 | 定义。 |"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
{frontmatter.rstrip()}
---

# 测试论文

## 核心论点

本段包含论点。

## 理论框架

本段包含框架。

## 分节摘要

### 1. 小节

本段包含摘要。

## 关键概念

{key_concepts}

## 核心引用

1. **作者 (2020)** — *Title* — 说明。
""",
        encoding="utf-8",
    )


def all_diagnostics(payload: dict) -> list[dict]:
    diagnostics: list[dict] = []
    for file_payload in payload["files"]:
        diagnostics.extend(file_payload["diagnostics"])
    return diagnostics


def test_audit_emits_diagnostic_first_contract_on_empty_vault(tmp_path: Path):
    project = tmp_path / "project"
    (project / "vault").mkdir(parents=True)

    result = run_audit(project, "--path", "vault")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["version"] == "quasi-audit.diagnostics.v1"
    assert payload["status"] == "clean"
    assert payload["target"]["requested"] == "vault"
    assert payload["target"]["exists"] is True
    assert payload["summary"]["files_checked"] == 0
    assert payload["summary"]["files_with_diagnostics"] == 0
    assert payload["summary"]["diagnostics_total"] == 0
    assert payload["summary"]["by_pass"] == {}
    assert payload["files"] == []
    assert "llm_editable" not in payload
    assert "escalated" not in payload


def test_audit_auto_fixes_frontmatter_flow_arrays_with_diagnostics(tmp_path: Path):
    project = tmp_path / "project"
    paper = project / "vault" / "papers" / "martin-test-2007.md"
    write_paper(
        paper,
        """type: paper
title: Test Paper
authors: [Aryn Martin]
year: 2007
journal: Endeavour
themes: [chimerism, feminist technoscience]""",
    )

    result = run_audit(project, "--path", str(paper))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    diagnostics = all_diagnostics(payload)
    assert payload["status"] == "clean"
    assert payload["summary"]["auto_fixed"] >= 2
    assert any(d["id"] == "frontmatter.authors.flow_array" for d in diagnostics)
    assert any(d["id"] == "frontmatter.themes.flow_array" for d in diagnostics)
    updated = paper.read_text(encoding="utf-8")
    assert "authors: [Aryn Martin]" not in updated
    assert "authors:\n- Aryn Martin" in updated
    assert "themes: [chimerism, feminist technoscience]" not in updated
    assert "themes:\n- chimerism\n- feminist technoscience" in updated


def test_audit_quote_style_fixes_body_and_skips_frontmatter_code_and_links(tmp_path: Path):
    project = tmp_path / "project"
    paper = project / "vault" / "papers" / "quote-test-2020.md"
    write_paper(
        paper,
        """type: paper
title: '\"中文标题\"'
authors:
- Aryn Martin
year: 2020
journal: Endeavour
themes:
- chimerism""",
    )
    original = paper.read_text(encoding="utf-8")
    paper.write_text(
        original.replace(
            "本段包含论点。",
            "本段包含\"摸索期\"。`\"代码\"` 不改。``\"多反引号代码\"`` 不改。[链接](https://example.com/\"中文\") 不改。[[target \"中文\"|别名]] 不改。\n\n    \"缩进代码里的中文\" 不改\n\n```\n\"代码块里的中文\" 不改\n```\n\n````\n\"四反引号代码块里的中文\" 不改\n```\n\"仍在四反引号代码块内\" 不改\n````",
        ),
        encoding="utf-8",
    )

    result = run_audit(project, "--path", str(paper))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    diagnostics = all_diagnostics(payload)
    updated = paper.read_text(encoding="utf-8")
    assert any(d["id"] == "quote.cjk_ascii_quote" for d in diagnostics)
    assert "本段包含「摸索期」。" in updated
    assert "title: '\"中文标题\"'" in updated
    assert "`\"代码\"`" in updated
    assert "``\"多反引号代码\"``" in updated
    assert "https://example.com/\"中文\"" in updated
    assert "[[target \"中文\"|别名]]" in updated
    assert "    \"缩进代码里的中文\" 不改" in updated
    assert "\"代码块里的中文\" 不改" in updated
    assert "\"四反引号代码块里的中文\" 不改" in updated
    assert "\"仍在四反引号代码块内\" 不改" in updated


def test_audit_body_schema_reports_agent_action_for_rewriteable_section(tmp_path: Path):
    project = tmp_path / "project"
    paper = project / "vault" / "papers" / "body-test-2020.md"
    write_paper(
        paper,
        """type: paper
title: Test Paper
authors:
- Aryn Martin
year: 2020
journal: Endeavour
themes:
- chimerism""",
        key_concepts="""**概念A**: 定义一。
**概念B**: 定义二。""",
    )

    result = run_audit(project, "--path", str(paper))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    diagnostics = all_diagnostics(payload)
    assert payload["version"] == "quasi-audit.diagnostics.v1"
    assert payload["status"] == "dirty"
    assert payload["summary"]["agent_fixable"] == 1
    assert payload["summary"]["human_required"] == 0
    assert payload["summary"]["by_pass"]["body_schema"] == 1
    assert payload["files"][0]["detected_type"] == "paper"
    assert any(
        d["id"] == "body.关键概念.block_kind_mismatch"
        and d["action"] == "rewrite_section_shape_preserving_content"
        and d["status"] == "agent_fixable"
        and d["location"] == {"h2": "关键概念"}
        for d in diagnostics
    )


def test_audit_rejects_removed_subcommands(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    result = run_audit(project, "run")

    assert result.returncode == 2
    assert "unrecognized arguments: run" in result.stderr
