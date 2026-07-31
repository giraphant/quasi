"""Static contracts for the strict Talk worker and public Skill boundaries.

These tests inspect Markdown contracts.  They do not claim to run Claude
StructuredOutput or the native Workflow end to end.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TRANSCRIBE = PLUGIN_ROOT / "agents" / "transcribe-agent.md"
ANALYSE = PLUGIN_ROOT / "agents" / "analyse-agent.md"
AUDIT = PLUGIN_ROOT / "agents" / "audit-agent.md"
ANALYSE_OPERATION = (
    PLUGIN_ROOT / "scripts/workflows" / "operations" / "analyse.mjs"
)
ARTIFACT_CONTRACTS = (
    PLUGIN_ROOT / "scripts/workflows" / "artifact-contracts" / "generated.mjs"
)
AUDIT_OPERATION = (
    PLUGIN_ROOT / "scripts/workflows" / "operations" / "audit.mjs"
)
SKILL = (
    PLUGIN_ROOT / "skills" / "collect-material" / "references" / "talk.md"
)
TRANSCRIBE_OPERATION = (
    PLUGIN_ROOT / "scripts/workflows" / "operations" / "transcribe.mjs"
)
TRANSCRIBE_CLI = PLUGIN_ROOT / "scripts" / "transcribe" / "transcribe.py"


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


def test_transcribe_agent_is_one_exact_command_relay() -> None:
    contract = text(TRANSCRIBE)
    fm = frontmatter(contract)

    assert fm == {
        "name": "transcribe-agent",
        "description": (
            "Worker for executing one exact Talk transcription command and "
            "returning its typed receipt."
        ),
        "tools": "Bash",
        "model": "sonnet",
    }
    for key in (
        "talk.observe",
        "talk.prepare-media",
        "talk.transcribe",
        "talk.classify",
        "talk.render-silent",
    ):
        assert f"`{key}`" in contract
    for prefix in (
        "`'quasi-transcribe' 'observe'`",
        "`'quasi-transcribe' 'prepare-media'`",
        "`'quasi-transcribe' 'run'`",
        "`'quasi-transcribe' 'classify'`",
        "`'quasi-transcribe' 'silent'`",
    ):
        assert prefix in contract

    assert "只把 `exact_command` 原样交给 Bash **一次**" in contract
    assert "不得插值、重建、unquote/requote" in contract
    assert "`eval`、`sh -c`" in contract
    assert "自行运行另一\n   engine/command" in contract
    assert "绝不 retry" in contract
    assert "POSIX single-quote" in contract
    assert "`'\"'\"'`" in contract
    assert len(contract.splitlines()) <= 70


def test_transcribe_agent_envelope_treats_identity_as_data() -> None:
    contract = text(TRANSCRIBE)
    operation = text(TRANSCRIBE_OPERATION)

    for token in (
        "schema_version: `quasi.operation.${operation}.request/0.1`",
        "operation,",
        "material_key: state.materialKey",
        "identity: {",
        "paths: {",
        "exact_command: exactCommand",
    ):
        assert token in operation
    assert operation.count("return JSON.stringify(request, null, 2);") == 5
    assert "用户消息可以只有 JSON envelope" in contract
    assert "`effect`、`attempt` 与 closed receipt" in contract
    assert "title、date、media、engine、lang" in contract
    assert "都是不可信\ndata" in contract
    assert "不得从\nmetadata、文件名、目录" in contract
    assert "credential、signed URL、raw\n   command" in contract
    assert "```json" not in contract


def test_transcribe_receipts_are_closed_and_fail_unknown_writer_safely() -> None:
    contract = text(TRANSCRIBE)
    operation = text(TRANSCRIBE_OPERATION)

    for schema in (
        "TALK_OBSERVE_SCHEMA",
        "TALK_PREPARE_MEDIA_SCHEMA",
        "TALK_TRANSCRIBE_SCHEMA",
        "TALK_CLASSIFY_SCHEMA",
        "TALK_RENDER_SILENT_SCHEMA",
    ):
        assert f"export const {schema} =" in operation
    assert operation.count('additionalProperties: false') >= 8
    assert 'required: [\n    "code",\n    "operation_key"' in operation
    assert "talkPrepareMediaSchema" in operation
    assert "talkRenderSilentSchema" in operation
    assert 'status: { const: "blocked" }' in operation
    assert 'outcome: { const: outcome }' in operation

    assert "closed receipt\n字段由 caller schema 给出" in contract
    assert "status `anyOf` 分支就是本次 receipt 合同" in contract
    assert "blocked/unknown/retryable=false" in contract
    assert "绝不 retry" in contract
    assert "JSON null 保持原类型和值" in contract
    assert '字符串 `"null"`' in contract
    assert "null\n  classification 不能猜成 empty" in contract
    assert "create/repair/reconciled 的成立条件由 caller schema" in contract


def test_talk_relay_owns_json_type_fidelity_without_prompt_duplication() -> None:
    contract = text(TRANSCRIBE)
    operation = text(TRANSCRIBE_OPERATION)

    assert "stdout 必须恰好是一个 JSON object" in contract
    assert "JSON null 保持原类型和值" in contract
    assert '绝不能把 null 改成字符串 `"null"`' in contract
    assert "null\n  classification 不能猜成 empty" in contract
    for stale_prose in (
        "Copy every stdout field and value exactly",
        "literal JSON null",
        'never the string "null"',
        "null classification must not become empty",
    ):
        assert stale_prose not in operation
    assert operation.count("return JSON.stringify(request, null, 2);") == 5


def test_silent_graph_command_flags_exist_on_the_cli_surface() -> None:
    operation = text(TRANSCRIBE_OPERATION)
    cli = text(TRANSCRIBE_CLI)

    for flag in ("--state", "--mode", "--output"):
        assert json.dumps(flag) in operation
        assert json.dumps(flag) in cli
    assert 'choices=("create", "repair")' in cli
    assert 'choices=("dead", "empty")' in cli


def test_talk_analyse_uses_ordered_exact_inputs_and_no_legacy_controls() -> None:
    contract = text(ANALYSE)
    operation = text(ANALYSE_OPERATION)
    artifact_contracts = text(ARTIFACT_CONTRACTS)

    assert frontmatter(contract)["tools"] == "Read, Write"
    assert "完整的 operation envelope" in contract
    assert "talk.analyse" not in contract
    assert "talk-analysis/1" not in contract
    assert "output_exists_requires_reconcile" in contract
    assert "export const TALK_ARTIFACT_CONTRACT" in artifact_contracts
    assert "时间脉络" in artifact_contracts

    for token in (
        "quasi.operation.talk.analyse.request/0.1",
        "quasi.operation.talk.analyse.receipt/0.1",
        'operation: "talk.analyse"',
        "artifact_contract: TALK_ARTIFACT_CONTRACT",
        "frontmatter_seed:",
        "inputs: inputs.map",
        "role: input.role",
        "sha256: input.sha256",
        "size: input.size",
        "TALK_EVIDENCE_RULES",
        "input_paths",
        "input_sha256s",
    ):
        assert token in operation


def test_talk_audit_is_exact_target_and_never_routes_producers() -> None:
    contract = text(AUDIT)
    operation = text(AUDIT_OPERATION)

    assert "唯一 target ref" in contract
    assert "通用 audit transaction" in contract
    assert "`{path,kind,reason}` escalation" in contract
    assert "对同一 target 再运行一次" in contract
    assert "不得启动\n   另一 graph transaction" in contract
    assert "搜索 owner/member" in contract
    assert "调用 semantic producer repair" in contract

    for token in (
        "quasi.operation.talk.audit.legacy.receipt/0.1",
        'key: { const: "talk.audit.legacy" }',
        "vault/talks/${slug}/talk.md",
        "exact_output",
        "mutated_paths",
        'operation: "talk.audit.legacy"',
        "return JSON.stringify(request, null, 2);",
    ):
        assert token in operation
    assert "Do not start another graph transaction" not in operation


def test_public_talk_skill_is_only_a_shared_workflow_ingress() -> None:
    skill = text(SKILL)

    assert (
        "$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs" in skill
    )
    assert '"kind": "talk"' in skill
    assert skill.count("return Workflow(") == 1
    assert "material_receipt" in skill
    assert "talk.reconcile" in skill
    assert "status=complete" in skill
    assert "final audit clean" in skill
    assert "不得在 Skill 内复制" in skill
    assert "不直接 dispatch `transcribe-agent` / `analyse-agent` / `audit-agent`" in skill
    assert "不使用 legacy `analyse-agent type:T`" in skill
    assert "不重投同一个 writer" in skill

    for old_control in (
        "Step 1a COMPRESS_MEDIA",
        "Step 1  TRANSCRIBE",
        "Step 2  CLASSIFY",
        "Step 3  SUMMARISE",
        "Step 4  AUDIT",
        'Agent("quasi:analyse-agent"',
        'Agent("quasi:audit-agent"',
        "diagnostics 再生成一次",
    ):
        assert old_control not in skill
