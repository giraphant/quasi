from __future__ import annotations

from pathlib import Path
import re


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def active_skill_files() -> list[Path]:
    return sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))


def active_agent_files() -> list[Path]:
    return sorted((PLUGIN_ROOT / "agents").glob("*.md"))


def frontmatter_description(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^description:\s*(?:>\s*)?\n(?P<body>(?:  .*\n)+)", text, re.MULTILINE)
    if match:
        return " ".join(line.strip() for line in match.group("body").splitlines())

    match = re.search(r"^description:\s*(?P<body>.+)$", text, re.MULTILINE)
    return match.group("body").strip() if match else ""


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


def test_frontmatter_descriptions_are_routing_hints():
    offenders: list[str] = []

    for path in active_skill_files():
        desc = frontmatter_description(path)
        rel = path.relative_to(PLUGIN_ROOT)
        if not desc.startswith("Use when the user wants to "):
            offenders.append(f"{rel}: skill description should be user-intent facing")
        if len(desc) > 220:
            offenders.append(f"{rel}: skill description too long")
        for forbidden in ("user says", "前身", "Phase", "→"):
            if forbidden in desc:
                offenders.append(f"{rel}: description contains {forbidden!r}")

    for path in active_agent_files():
        desc = frontmatter_description(path)
        rel = path.relative_to(PLUGIN_ROOT)
        if not desc.startswith("Worker for "):
            offenders.append(f"{rel}: agent description should be worker-facing")
        if len(desc) > 220:
            offenders.append(f"{rel}: agent description too long")
        for forbidden in ("由 ", "Phase", "前身", "→"):
            if forbidden in desc:
                offenders.append(f"{rel}: description contains {forbidden!r}")

    assert offenders == []


def test_search_agent_documents_bounded_catalog_rescue_contract():
    text = (PLUGIN_ROOT / "agents" / "search-agent.md").read_text(encoding="utf-8")

    required = [
        "中文增强",
        "中文候选",
        "未能真正匹配原版",
        "最多处理前 3 个",
        "最多 5 次",
        "quasi-search kagi search --format json",
        "site:books.com.tw",
        "data[].title",
        "data[].url",
        "data[].snippet",
        "只补缺失字段",
        "不要覆盖 Douban",
        "不要写入 cache",
        "不要打开网页",
        "不要使用 DOKO",
    ]
    missing = [token for token in required if token not in text]
    assert missing == []


def test_audit_agent_documents_search_metadata_qa_contract():
    text = (PLUGIN_ROOT / "agents" / "audit-agent.md").read_text(encoding="utf-8")

    required = [
        "metadata 校对",
        "quasi-search book",
        "quasi-search paper",
        "--json",
        "--isbn",
        "--doi",
        "--title",
        "--author",
        "results[0]",
        "diagnostics.conflicts",
        "frontmatter",
        "metadata_mismatch",
        "escalated",
        "不要写入 cache",
        "不要写 manifest",
        "不要新造 audit/search CLI",
    ]
    missing = [token for token in required if token not in text]
    assert missing == []

    forbidden = [
        "quasi-audit metadata",
        "quasi-search metadata",
        "quasi-audit search",
    ]
    present = [token for token in forbidden if token in text]
    assert present == []


def test_process_paper_accepts_pdf_preferred_text_source_contract():
    text = (PLUGIN_ROOT / "skills" / "process-paper" / "SKILL.md").read_text(encoding="utf-8")

    assert "sources/{slug}.pdf" in text
    assert "sources/{slug}.txt" in text
    assert "source_file" in text
    assert "source_pdf" not in text
