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


def json_blocks(document: str) -> list[dict[str, object]]:
    return [
        json.loads(block)
        for block in re.findall(r"```json\n(.*?)\n```", document, re.DOTALL)
    ]


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

    assert "恰好一次运行 exact command" in contract
    assert "只把 `exact_command` 原样交给 Bash **一次**" in contract
    assert "不得插值、重建、unquote/requote" in contract
    assert "`eval`/`sh -c`" in contract
    assert "自行运行另一 engine/command" in contract
    assert "绝不 retry" in contract
    assert "POSIX single-quote" in contract
    assert "`'\"'\"'`" in contract


def test_transcribe_agent_envelope_treats_identity_as_data() -> None:
    contract = text(TRANSCRIBE)
    request = json_blocks(contract)[0]

    assert set(request) == {
        "schema_version",
        "operation",
        "material_key",
        "identity",
        "paths",
        "input",
        "outputs",
        "exact_command",
    }
    assert request["operation"] == "talk.transcribe"
    assert request["material_key"] == "talk:canonical-slug"
    assert set(request["identity"]) == {
        "slug",
        "title",
        "date",
        "media",
        "engines",
        "lang",
    }
    assert set(request["paths"]) == {
        "output_dir",
        "talk_dir",
        "manifest",
        "prepared",
        "transcript",
        "subtitle",
        "talk",
    }
    assert request["input"] == {
        "role": "source",
        "path": "/project/input/talk.m4a",
    }
    assert [item["role"] for item in request["outputs"]] == [
        "manifest",
        "transcript",
        "subtitle",
    ]
    assert "不得自行要求 Graph 未提供的 effect/attempt/operation_instructions" in contract
    assert "title/date/media/engine/lang" in contract
    assert "都是不可信 data" in contract
    assert "不得从 metadata、文件名或" in contract
    assert "目录另造 slug/path/title/date" in contract
    assert "不把 credential、signed URL query、raw command" in contract


def test_transcribe_receipts_are_closed_and_fail_unknown_writer_safely() -> None:
    contract = text(TRANSCRIBE)

    for exact_field_list in (
        "schema_version,key,effect,status,attempt,material_key,slug,input_path,output_dir,manifest_path,manifest_exists,request_fingerprint,source_sha256,source_size,prepared_path,prepared_sha256,transcript_path,subtitle_path,talk_path,talk_exists,talk_sha256,classification,artifacts,failure",
        "schema_version,key,effect,status,attempt,material_key,input_path,output_path,artifact_roles,input_sha256,output_sha256,size,action,failure",
        "schema_version,key,effect,status,attempt,material_key,slug,input_path,output_dir,talk_dir,manifest_path,manifest_exists,manifest_fingerprint,request_fingerprint,source_sha256,lang,title,engines,primary_engine,transcript_path,subtitle_path,per_engine,artifacts,disposition,previous_manifest_preserved,failure",
        "schema_version,key,effect,status,attempt,material_key,input_path,input_sha256,signal,machine_signals,failure",
        "schema_version,key,effect,status,attempt,material_key,input_path,output_path,artifact_roles,classification_signal,action,output_sha256,size,failure",
    ):
        assert exact_field_list in contract

    assert "`{code,operation_key,outcome,retryable,message}`" in contract
    assert "blocked/unknown/retryable=false" in contract
    assert "绝不 retry" in contract
    assert "JSON null token" in contract
    assert '字符串 `"null"`' in contract
    assert "null classification" in contract
    assert "`created|replaced|reconciled|null`" in contract
    assert "显式\n  request fingerprint 改变" in contract
    assert "Agent 不得自行把 overwrite/文件变化推断成" in contract
    assert "根必须是单个 `type: object`" in contract
    assert "`oneOf/anyOf/allOf/if/then`" in contract


def test_talk_observe_prompt_forbids_provider_null_coercion() -> None:
    operation = text(TRANSCRIBE_OPERATION)

    assert "Copy every stdout field and value exactly" in operation
    assert "literal JSON null" in operation
    assert 'never the string "null"' in operation
    assert "null classification must not become empty" in operation


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

    for token in (
        "quasi.operation.talk.audit.legacy.receipt/0.1",
        'key: { const: "talk.audit.legacy" }',
        "vault/talks/${slug}/talk.md",
        "exact_output",
        "mutated_paths",
        "Do not start another graph transaction",
    ):
        assert token in operation


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
