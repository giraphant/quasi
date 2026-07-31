"""Static contracts for the Translation Prepare specialist and Skill edge."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
AGENT = PLUGIN_ROOT / "agents/translate-agent.md"
SKILL = PLUGIN_ROOT / "skills/collect-material/SKILL.md"
OPERATIONS = PLUGIN_ROOT / "scripts/workflows/operations/translate.mjs"
LOOP = PLUGIN_ROOT / "scripts/workflows/derivatives/translation.mjs"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def frontmatter(document: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", document, re.DOTALL)
    assert match
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator:
            result[key.strip()] = value.strip()
    return result


def test_translate_agent_owns_one_positive_prepare_goal() -> None:
    contract = text(AGENT)
    assert frontmatter(contract) == {
        "name": "translate-agent",
        "description": (
            "Translation preparation specialist that selects, produces, "
            "recovers, and validates one translated PDF generation."
        ),
        "tools": "Read, Bash",
        "model": "inherit",
    }
    for token in (
        "你负责 Translation 的 Prepare 阶段",
        "`quasi-translate observe`",
        "`quasi-translate run`",
        "`quasi-extract ocr --layout`",
        "coverage gate",
        "一个\n外观正常但正文大面积未翻译的 PDF 不算完成",
        "内部 observe/run/recovery 的实际结果",
    ):
        assert token in contract
    assert len(contract.splitlines()) < 80


def test_translation_prepare_envelope_names_goal_refs_and_capabilities() -> None:
    operations = text(OPERATIONS)
    for token in (
        'schema_version: "quasi.stage.translation-prepare.request/0.1"',
        'operation: "translation.prepare"',
        'stage: "Prepare"',
        "material_key: state.translationKey",
        "objective:",
        "source_request: {",
        "output: state.output",
        "manifest: state.manifest",
        "recovery_source: state.recoverySource",
        "capabilities: [",
        "quasi-translate observe ... --json",
        "quasi-translate run ... --json",
        "quasi-extract ocr INPUT OUTPUT --layout --no-clobber --json",
    ):
        assert token in operations
    for removed in (
        "TRANSLATION_RECONCILE_SCHEMA",
        "TRANSLATION_RUN_SCHEMA",
        "translationReconcilePrompt",
        "translationRunPrompt",
        "translationReocrPrompt",
    ):
        assert removed not in operations


def test_translation_prepare_schema_is_closed_and_provider_compatible() -> None:
    script = r"""
import { TRANSLATION_PREPARE_STAGE_CONTRACT } from "./scripts/workflows/operations/translate.mjs";
const schema = TRANSLATION_PREPARE_STAGE_CONTRACT.schema;
if (schema.type !== "object" || schema.additionalProperties !== false)
  throw new Error("stage root must be closed");
for (const key of ["schema_version", "operation", "stage", "material_key", "effect", "status", "attempt", "source", "validation", "gate", "steps", "issue"])
  if (!schema.required.includes(key)) throw new Error(`missing ${key}`);
for (const key of ["oneOf", "allOf", "anyOf", "if", "then"])
  if (Object.hasOwn(schema, key)) throw new Error(`top-level ${key}`);
if (schema.properties.operation.const !== "translation.prepare")
  throw new Error("wrong operation");
const issue = schema.properties.issue;
if (!Array.isArray(issue.type) || !issue.type.includes("object") || !issue.type.includes("null"))
  throw new Error("issue must be nullable object");
const median = schema.properties.validation.properties.coverage.properties.median;
if (!Array.isArray(median.anyOf) || !median.anyOf.some(row => row.type === "null"))
  throw new Error("coverage median must preserve explicit null");
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_translation_complete_contract_proves_one_coherent_generation() -> None:
    operations = text(OPERATIONS)
    for token in (
        "validRequestedSource(",
        "receipt.source.path === context.recoverySource",
        "receipt.validation.source_pages === receipt.source.pages",
        "receipt.validation.output_pages === receipt.source.pages * 2",
        "validCoverage(receipt.validation.coverage)",
        '"pass", "not_applicable", "insufficient_evidence"',
    ):
        assert token in operations
    assert "The configured backend reported by quasi-translate is authoritative" in operations


def test_translate_agent_explains_human_gates_and_unknown_writers() -> None:
    contract = text(AGENT)
    for token in (
        "多个候选",
        "配置缺失",
        "`needs_input`",
        "`blocked`",
        "writer durable outcome 不明",
        "新图从\nreconcile 观察",
        "凭据不进入 argv 或 receipt",
    ):
        assert token in contract


def test_translation_graph_has_one_prepare_stage_unit() -> None:
    loop = text(LOOP)
    assert 'runtime.phase("Prepare")' in loop
    assert "translationPrepareStagePrompt(state)" in loop
    assert 'agentType: "quasi:translate-agent"' in loop
    assert 'key: "translation.prepare"' in loop
    assert "retryNull(" not in loop
    for removed in (
        "translationReconcilePrompt",
        "translationRunPrompt",
        "translationReocrPrompt",
        'key: "translation.run"',
        'key: "translation.reocr"',
    ):
        assert removed not in loop


def test_collect_material_routes_translation_through_shared_workflow() -> None:
    skill = text(SKILL)
    assert "Translation：`slug`" in skill
    for field in (
        "source_file",
        "target_language",
        "toc_json",
        "toc_page_side",
    ):
        assert field in skill
    assert skill.count("return Workflow(") == 1
    assert "$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs" in skill
    assert "quasi.derivative.translation.receipt/0.1" in skill
    assert "`needs_input` 带一个用户可以回答" in skill
    assert "收到答案后构造一次新的 graph request" in skill
    assert 'Agent("quasi:translate-agent"' not in skill


def test_translation_secrets_stay_out_of_request_and_receipt() -> None:
    contract = text(AGENT)
    operations = text(OPERATIONS)
    assert "凭据不进入 argv 或 receipt" in contract
    for secret_field in (
        "translate_api_key",
        "immersive_auth_key",
        "authorization",
        "cookie",
    ):
        assert secret_field not in operations.lower()
