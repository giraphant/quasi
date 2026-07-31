"""Static ownership tests for the shared analyse Agent and artifact schemas.

These tests deliberately separate the stable Agent role from operation-specific
contracts owned by scripts/workflows/operations/analyse.mjs.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from scripts.schemas.contracts import artifact_contract_for_type


AGENT = PLUGIN_ROOT / "agents" / "analyse-agent.md"
OPERATIONS = PLUGIN_ROOT / "scripts/workflows" / "operations" / "analyse.mjs"
GENERATED_CONTRACTS = (
    PLUGIN_ROOT / "scripts/workflows" / "artifact-contracts" / "generated.mjs"
)


def agent_text() -> str:
    return AGENT.read_text(encoding="utf-8")


def operation_text() -> str:
    return OPERATIONS.read_text(encoding="utf-8")


def frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator:
            result[key.strip()] = value.strip()
    return result


def test_common_role_is_small_and_least_privilege() -> None:
    text = agent_text()
    metadata = frontmatter(text)

    assert metadata["name"] == "analyse-agent"
    assert metadata["tools"] == "Read, Write"
    assert len(text.splitlines()) < 50
    assert "Caller\n提供材料身份、exact input refs、唯一 output" in text
    assert "artifact_contract" in text
    assert "frontmatter_seed" in text
    assert "关键判断回到实际\ninput" in text
    assert "Create 先观察 exact output" in text
    assert "reconciled collision" in text
    assert "caller StructuredOutput schema" in text


def test_common_role_does_not_duplicate_operation_catalog_or_migration_history() -> None:
    text = agent_text()

    for operation_specific in (
        "paper.analyse",
        "chapter.analyse",
        "talk.analyse",
        "paper-analysis/1",
        "chapter-analysis/1",
        "talk-analysis/1",
        "type: A|B|T",
        "needs_ocr",
        "pdftotext",
        "retryable=false",
    ):
        assert operation_specific not in text


def test_operation_module_injects_artifact_contracts() -> None:
    text = operation_text()

    for key, contract in (
        ("paper.analyse", "PAPER_ARTIFACT_CONTRACT"),
        ("chapter.analyse", "CHAPTER_ARTIFACT_CONTRACT"),
        ("talk.analyse", "TALK_ARTIFACT_CONTRACT"),
    ):
        assert key in text
        assert contract in text

    assert text.count("artifact_contract:") == 3
    assert text.count("frontmatter_seed:") == 3
    assert "operation_instructions:" not in text
    assert "TALK_EVIDENCE_RULES" in text


def test_canonical_schemas_own_product_structure_without_audit_aliases() -> None:
    paper = artifact_contract_for_type("paper")
    chapter = artifact_contract_for_type("chapter")
    talk = artifact_contract_for_type("talk")

    assert paper["schema_version"] == "quasi.artifact.paper/0.1"
    assert paper["frontmatter"]["field_order"] == [
        "type",
        "title",
        "authors",
        "year",
        "journal",
        "themes",
        "doi",
        "topics",
        "rating",
    ]
    assert paper["document"]["section_order"][:5] == [
        "核心论点",
        "理论框架",
        "分节摘要",
        "关键概念",
        "核心引用",
    ]
    paper_text = str(paper)
    assert "核心引用文献" not in paper_text
    assert next(
        section
        for section in paper["document"]["sections"]
        if section["h2"] == "关键概念"
    )["columns"] == ["概念", "英文", "提出者", "定义"]

    assert chapter["frontmatter"]["json_schema"]["properties"]["book"]
    assert "分节摘要" in chapter["document"]["section_order"]
    assert talk["document"]["section_order"][-1] == "时间脉络"

    generated = GENERATED_CONTRACTS.read_text(encoding="utf-8")
    for export_name in (
        "PAPER_ARTIFACT_CONTRACT",
        "CHAPTER_ARTIFACT_CONTRACT",
        "TALK_ARTIFACT_CONTRACT",
    ):
        assert f"export const {export_name}" in generated


def test_removed_dispatcher_and_old_prompt_exports_do_not_return() -> None:
    agent = agent_text()
    operations = operation_text()

    for dead in (
        "export const AN_SCHEMA",
        "noopIfExists",
        "analyseChapterPrompt",
        "type: A\n",
        "type: B\n",
        "Legacy A/B/T",
        "pdftotext \"{input}\"",
        "{preamble}",
    ):
        assert dead not in operations
        assert dead not in agent


def test_operation_prompts_keep_exact_refs_and_no_flow_control() -> None:
    text = operation_text()

    for token in (
        'role: "normalized_text"',
        'role: "normalized_chapter"',
        "inputs: inputs.map",
        "role: input.role",
        "artifact_contract",
        "frontmatter_seed",
        "repair_diagnostics",
        "Do not reinterpret it as another operation",
    ):
        assert token in text

    assert "已经存在时返回 reconciled collision" in agent_text()
    assert "needs_ocr" not in text
