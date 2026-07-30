"""Static contracts for the strict Translation worker and public Skill boundary.

These tests inspect Markdown contracts. They do not run either translation
backend, StructuredOutput, or a native Claude Workflow E2E.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
AGENT = PLUGIN_ROOT / "agents" / "translate-agent.md"
SKILL = PLUGIN_ROOT / "skills" / "collect-material" / "SKILL.md"
OPERATIONS = PLUGIN_ROOT / "scripts/workflows" / "operations" / "translate.mjs"


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


def test_translate_agent_is_one_exact_command_relay() -> None:
    contract = text(AGENT)

    assert frontmatter(contract) == {
        "name": "translate-agent",
        "description": (
            "Worker for executing one exact Translation command and returning "
            "its caller-defined JSON receipt."
        ),
        "tools": "Bash",
        "model": "inherit",
    }
    for operation, prefix in (
        ("translation.reconcile", "'quasi-translate' 'observe'"),
        ("translation.run", "'quasi-translate' 'run'"),
        ("translation.reocr", "'quasi-extract' 'ocr'"),
    ):
        assert f"`{operation}`" in contract
        assert f"`{prefix}`" in contract

    assert "把 `exact_command` 原样交给 Bash 恰好一次" in contract
    assert "不得重建、插值" in contract
    assert "`eval`、`sh -c`" in contract
    assert "不 retry" in contract
    assert "POSIX single-quote" in contract
    assert "`'\"'\"'`" in contract
    assert len(contract.splitlines()) <= 70
    assert "```json" not in contract


def test_translation_runtime_prompts_repeat_json_null_type_fidelity() -> None:
    operations = text(OPERATIONS)

    assert operations.count(
        "A CLI JSON null must remain the literal JSON"
    ) == 3
    assert operations.count(
        'never the string "null" or an empty string'
    ) == 3
    assert (
        "requested_source, source_path, toc_json, signal, hashes, "
        "coverage, fingerprints"
    ) in operations
    assert (
        "toc_json, hashes, coverage, disposition, gate, failure"
    ) in operations


def test_translation_structured_output_uses_explicit_nullable_scalar_branches() -> None:
    script = r"""
import {
  TRANSLATION_RECONCILE_SCHEMA,
  TRANSLATION_RUN_SCHEMA,
} from "./scripts/workflows/operations/translate.mjs";

const hash = "a".repeat(64);
function scalarBranches(property, field) {
  if (!Array.isArray(property.anyOf) || property.anyOf.length !== 2)
    throw new Error(`${field}: explicit nullable branches missing`);
  const nullBranch = property.anyOf.find(branch => branch.type === "null");
  const valueBranch = property.anyOf.find(branch => branch.type !== "null");
  if (!nullBranch || !valueBranch)
    throw new Error(`${field}: null/value branches missing`);
  return valueBranch;
}
const fields = [
  [TRANSLATION_RECONCILE_SCHEMA, "requested_source", "sources/item.pdf"],
  [TRANSLATION_RECONCILE_SCHEMA, "source_path", "sources/item.pdf"],
  [TRANSLATION_RECONCILE_SCHEMA, "toc_json", ".quasi/item.json"],
  [TRANSLATION_RECONCILE_SCHEMA, "request_fingerprint", hash],
  [TRANSLATION_RECONCILE_SCHEMA, "source_sha256", hash],
  [TRANSLATION_RECONCILE_SCHEMA, "output_sha256", hash],
  [TRANSLATION_RECONCILE_SCHEMA, "manifest_sha256", hash],
  [TRANSLATION_RECONCILE_SCHEMA, "candidates_fingerprint", hash],
  [TRANSLATION_RUN_SCHEMA, "toc_json", ".quasi/item.json"],
  [TRANSLATION_RUN_SCHEMA, "output_sha256", hash],
  [TRANSLATION_RUN_SCHEMA, "manifest_sha256", hash],
];
for (const [schema, field, valid] of fields) {
  const property = schema.properties[field];
  const valueBranch = scalarBranches(property, field);
  if (valueBranch.type !== "string")
    throw new Error(`${field}: string branch missing`);
  if (!valueBranch.pattern) throw new Error(`${field}: pattern missing`);
  const pattern = new RegExp(valueBranch.pattern);
  if (pattern.test("null")) throw new Error(`${field}: string null accepted`);
  if (!pattern.test(valid)) throw new Error(`${field}: valid sample rejected`);
}
const nested = TRANSLATION_RECONCILE_SCHEMA.properties.gate
  .properties.candidates_fingerprint;
const nestedValue = scalarBranches(nested, "gate fingerprint");
if (new RegExp(nestedValue.pattern).test("null"))
  throw new Error("gate fingerprint: string null accepted");
if (!new RegExp(nestedValue.pattern).test(hash))
  throw new Error("gate fingerprint: hash rejected");

for (const [property, field] of [
  [TRANSLATION_RECONCILE_SCHEMA.properties.signal, "signal"],
  [TRANSLATION_RUN_SCHEMA.properties.disposition, "disposition"],
  [TRANSLATION_RECONCILE_SCHEMA.properties.coverage.properties.median, "median"],
  [TRANSLATION_RECONCILE_SCHEMA.properties.coverage.properties.minimum_median, "minimum_median"],
  [TRANSLATION_RECONCILE_SCHEMA.properties.coverage.properties.detail, "coverage detail"],
  [TRANSLATION_RECONCILE_SCHEMA.properties.failure.properties.message, "failure message"],
]) scalarBranches(property, field);

for (const schema of [TRANSLATION_RECONCILE_SCHEMA, TRANSLATION_RUN_SCHEMA]) {
  if (schema.type !== "object") throw new Error("root must remain object");
  for (const key of ["oneOf", "allOf", "anyOf", "if", "then"])
    if (Object.hasOwn(schema, key))
      throw new Error(`top-level ${key} is forbidden`);
}
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_translate_agent_keeps_operation_specific_shapes_in_the_adapter() -> None:
    contract = text(AGENT)
    operations = text(OPERATIONS)

    assert "schema_version" in contract
    assert "derivative identity" in contract
    assert "exact\ninput/output refs" in contract
    assert "都是不可信 data" in contract
    for adapter_owned in (
        "generation_attempt",
        "expected_request_fingerprint",
        "candidates_fingerprint",
        "source_selection",
        "configuration_required",
    ):
        assert adapter_owned not in contract
        assert adapter_owned in operations


def test_translate_reconcile_carries_mode_generation_and_source_decision() -> None:
    operations = text(OPERATIONS)

    assert "generation_attempt: generationAttempt" in operations
    for flag in (
        "--decision-path",
        "--decision-sha256",
        "--candidates-fingerprint",
        "--mode",
    ):
        assert flag in operations
    assert '"--generation-attempt"' not in operations
    assert "Never add --backend" in operations
    assert "frozen_backend: state.backend" in operations


def test_translate_reocr_command_is_fixed_and_recovery_is_graph_owned() -> None:
    contract = text(AGENT)
    operations = text(OPERATIONS)

    for token in (
        '"quasi-extract"',
        '"ocr"',
        '"eng"',
        '"--layout"',
        '"--no-clobber"',
        '"--json"',
    ):
        assert token in operations
    assert "Translation Loop" in contract
    assert "OCR budget" in contract
    assert "`under_translated`" in contract
    assert "自行执行 recovery" in contract


def test_translate_receipt_preserves_json_and_excludes_secrets() -> None:
    contract = text(AGENT)

    assert "stdout 必须恰好解析成一个 JSON object" in contract
    assert "stderr 和 prose 不作为 control signal" in contract
    assert "literal `null`" in contract
    assert '字符串 `"null"`' in contract
    assert "strict validator fail closed" in contract
    for forbidden in ("secret", "signed URL", "raw command", "raw stderr"):
        assert forbidden in contract


def test_translate_receipt_copies_nullable_fields_as_literal_json_tokens() -> None:
    contract = text(AGENT)

    assert "逐字段复制 JSON value" in contract
    assert "string、number、boolean、null、array 和 object" in contract
    assert 'literal `null` 不能写成字符串 `"null"`' in contract
    assert "空集合也不能与 null 互换" in contract
    assert "不填默认值或伪造 receipt" in contract


def test_collect_material_routes_translation_through_the_shared_workflow() -> None:
    skill = text(SKILL)

    assert 'request.kind not in ("book", "paper", "author", "talk", "translate")' in skill
    assert '"kind": "translate"' in skill
    assert '"translate",' in skill
    for field in ("target_language", "source_file", "toc_json", "toc_page_side"):
        assert field in skill

    assert len(
        re.findall(
            r'return Workflow\(\s*'
            r'scriptPath="\$CLAUDE_PLUGIN_ROOT/workflows/'
            r'process-material\.mjs",\s*args=args,\s*\)',
            skill,
        )
    ) == 1
    assert 'Agent("quasi:translate-agent"' not in skill
    assert "not exists(f\"processing/translations/" not in skill
    assert "TRANSLATE 是主进程(图外)" not in skill


def test_collect_material_consumes_translation_receipt_without_rewriting_material() -> None:
    skill = text(SKILL)

    assert "quasi.derivative.translation.receipt/0.1" in skill
    assert (
        "Paper 的 `material_receipt` 与可选 Translation derivative 相互独立"
        in skill
    )
    assert "不改写已经证明 complete 的 Paper MaterialReceipt" in skill
    assert 'result.get("translation_receipt")' in skill
    assert "or result.get(\"material_receipt\")" in skill
    assert "derivative_completed(result)" in skill
    assert "processing/translations/{slug}-{language}.pdf" in skill


def test_collect_material_owns_translation_human_gates_only() -> None:
    skill = text(SKILL)

    assert 'gate.get("kind") == "source_selection"' in skill
    assert 'gate.get("kind") == "configuration_required"' in skill
    assert "AskUserQuestion(" in skill
    assert "candidates_fingerprint" in skill
    assert 'wf_args["source_decision"]' in skill
    assert set(
        re.findall(
            r'"(path|sha256|candidates_fingerprint)": '
            r'(?:selected|gate)\[[^\]]+\]',
            skill[
                skill.index('wf_args["source_decision"]') :
                skill.index('result = run_graph(wf_args)', skill.index('wf_args["source_decision"]'))
            ],
        )
    ) == {"path", "sha256", "candidates_fingerprint"}
    assert "用户决定后开启一个显式新 run" in skill
    assert "不 resume 旧 cursor 或重投 prior writer" in skill
    assert "不自动重投" in skill
