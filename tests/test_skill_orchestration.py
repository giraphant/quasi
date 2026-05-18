from __future__ import annotations

from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def active_skill_files() -> list[Path]:
    return sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))


def test_skill_orchestration_contract_doc_exists():
    doc = PLUGIN_ROOT / "docs" / "SKILL_ORCHESTRATION.md"

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    assert "## Runtime vs Maintainer" in text
    assert "## Skill File Schema" in text
    assert "## Ownership" in text
    assert "## Phase Contract" in text
    assert "## State" in text
    assert "输出" in text


def test_active_skills_follow_runtime_schema():
    required_sections = [
        "## 任务",
        "## 输入",
        "## 硬约束",
        "## 状态",
        "## Agent / Helper 合同",
        "## 工作流",
        "## 执行流程",
        "## 断点续跑",
        "## 输出",
    ]
    offenders: list[str] = []
    for path in active_skill_files():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(PLUGIN_ROOT)
        for section in required_sections:
            if section not in text:
                offenders.append(f"{rel}: missing {section}")
        for forbidden in ("## 调用方式", "## 编排契约", "docs/SKILL_ORCHESTRATION.md"):
            if forbidden in text:
                offenders.append(f"{rel}: runtime skill contains maintainer-only text {forbidden!r}")

    assert offenders == []
