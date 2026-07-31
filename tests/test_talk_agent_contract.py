"""Static contracts for the Talk Stage specialist and public Skill boundary.

These tests protect the current architectural boundary: one goal-owning
Prepare Stage, exact producer/audit operations, and one shared Workflow.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TRANSCRIBE = PLUGIN_ROOT / "agents" / "transcribe-agent.md"
ANALYSE = PLUGIN_ROOT / "agents" / "analyse-agent.md"
AUDIT = PLUGIN_ROOT / "agents" / "audit-agent.md"
ANALYSE_OPERATION = PLUGIN_ROOT / "scripts/workflows/operations/analyse.mjs"
ARTIFACT_CONTRACTS = (
    PLUGIN_ROOT / "scripts/workflows/artifact-contracts/generated.mjs"
)
AUDIT_OPERATION = PLUGIN_ROOT / "scripts/workflows/operations/audit.mjs"
SKILL = PLUGIN_ROOT / "skills/collect-material/references/talk.md"
TRANSCRIBE_OPERATION = (
    PLUGIN_ROOT / "scripts/workflows/operations/transcribe.mjs"
)
TALK_LOOP = PLUGIN_ROOT / "scripts/workflows/materials/talk.mjs"


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


def test_transcribe_agent_owns_one_positive_prepare_goal() -> None:
    contract = text(TRANSCRIBE)
    assert frontmatter(contract) == {
        "name": "transcribe-agent",
        "description": (
            "Talk preparation specialist that reconciles media, builds a "
            "transcript generation, and classifies its content."
        ),
        "tools": "Read, Bash",
        "model": "sonnet",
    }
    for capability in (
        "`observe`",
        "`prepare-media`",
        "`run`",
        "`classify`",
        "committed primary transcript",
        "`live|dead|empty`",
    ):
        assert capability in contract
    assert "你负责 Talk 的 Prepare 阶段" in contract
    assert "机器阈值是证据" in contract
    assert "内部可以依材料状态调用多项能力" in contract
    assert len(contract.splitlines()) < 70


def test_talk_prepare_envelope_names_goal_capabilities_and_exact_refs() -> None:
    operation = text(TRANSCRIBE_OPERATION)
    for token in (
        'schema_version: "quasi.stage.talk-prepare.request/0.1"',
        'operation: "talk.prepare"',
        'stage: "Prepare"',
        "material_key: state.materialKey",
        "objective:",
        "refs: {",
        "media: state.media",
        "manifest: state.manifest",
        "transcript: state.transcript",
        "engines: state.engines",
        "capabilities: [",
        "Read exact transcript artifacts",
    ):
        assert token in operation
    for removed in (
        "TALK_OBSERVE_SCHEMA",
        "TALK_PREPARE_MEDIA_SCHEMA",
        "TALK_TRANSCRIBE_SCHEMA",
        "TALK_CLASSIFY_SCHEMA",
    ):
        assert removed not in operation


def test_talk_prepare_receipt_is_closed_stage_contract() -> None:
    script = r"""
import { TALK_PREPARE_STAGE_CONTRACT } from "./scripts/workflows/operations/transcribe.mjs";
const schema = TALK_PREPARE_STAGE_CONTRACT.schema;
if (schema.type !== "object" || schema.additionalProperties !== false)
  throw new Error("stage root must be closed");
for (const key of ["schema_version", "operation", "stage", "material_key", "effect", "attempt", "artifacts", "steps", "diagnostics", "terminal"])
  if (!schema.required.includes(key)) throw new Error(`missing ${key}`);
for (const key of ["oneOf", "allOf", "anyOf", "if", "then"])
  if (Object.hasOwn(schema, key)) throw new Error(`top-level ${key}`);
const branches = schema.properties.terminal.anyOf;
if (branches.length !== 4) throw new Error("wrong terminal branch count");
if (branches[0].properties.status.const !== "complete")
  throw new Error("missing complete terminal");
if (branches[0].properties.issue.type !== "null")
  throw new Error("complete must carry issue:null");
if (schema.properties.operation.const !== "talk.prepare")
  throw new Error("wrong operation");
if (schema.properties.stage.const !== "Prepare")
  throw new Error("wrong stage");
const source = schema.properties.source_observation;
if (!Array.isArray(source.type) || source.type.join(",") !== "object,null")
  throw new Error("source observation must be object|null");
if (source.properties.path.const !== "input.wav" ||
    source.properties.sha256.pattern !== "^[a-f0-9]{64}$")
  throw new Error("source observation must bind the exact artifact");
const generation = schema.properties.generation_observation;
if (!Array.isArray(generation.type) ||
    generation.type.join(",") !== "object,null")
  throw new Error("generation observation must be object|null");
if (generation.properties.manifest_path.const !==
      "processing/talks/placeholder/manifest.json" ||
    generation.properties.request_fingerprint.pattern !== "^[a-f0-9]{64}$")
  throw new Error("generation observation must bind the exact manifest");
const canonical = schema.properties.canonical_observation;
if (!Array.isArray(canonical.type) ||
    canonical.type.join(",") !== "object,null")
  throw new Error("canonical observation must be object|null");
if (canonical.properties.path.const !== "vault/talks/placeholder/talk.md")
  throw new Error("canonical observation must echo the exact path");
if (canonical.properties.sha256.pattern !== "^[a-f0-9]{64}$")
  throw new Error("canonical observation must carry a digest");
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_transcribe_agent_reports_only_real_canonical_hashes() -> None:
    contract = text(TRANSCRIBE)
    assert "`canonical_observation:null`" in contract
    assert "exact path 与实际 SHA-256" in contract


def test_silent_product_remains_one_exact_writer_operation() -> None:
    operation = text(TRANSCRIBE_OPERATION)
    for token in (
        "export const TALK_RENDER_SILENT_SCHEMA",
        'operation: "talk.render-silent"',
        '"quasi-transcribe"',
        '"silent"',
        '"--state"',
        '"--mode"',
        '"--output"',
        '"--json"',
    ):
        assert token in operation
    assert "failureSchema(\"talk.render-silent\")" in operation


def test_talk_analyse_gets_schema_and_ordered_exact_inputs() -> None:
    contract = text(ANALYSE)
    operation = text(ANALYSE_OPERATION)
    artifact_contracts = text(ARTIFACT_CONTRACTS)
    assert frontmatter(contract)["tools"] == "Read, Write"
    assert "Caller\n提供材料身份、exact input refs、唯一 output" in contract
    assert "Talk 使用有序 transcripts" in contract
    assert "export const TALK_ARTIFACT_CONTRACT" in artifact_contracts
    assert "时间脉络" in artifact_contracts
    for token in (
        "quasi.operation.talk.analyse.request/0.1",
        "quasi.operation.talk.analyse.receipt/0.1",
        'operation: "talk.analyse"',
        "artifact_contract: TALK_ARTIFACT_CONTRACT",
        "frontmatter_seed:",
        "inputs: inputs.map",
        "sha256: input.sha256",
        "TALK_EVIDENCE_RULES",
    ):
        assert token in operation


def test_talk_graph_exposes_prepare_analyse_audit_phases() -> None:
    loop = text(TALK_LOOP)
    assert 'runtime.phase("Prepare")' in loop
    assert 'runtime.phase("Analyse")' in loop
    assert 'runtime.phase("Audit")' in loop
    assert "talkPrepareStagePrompt(state)" in loop
    assert 'agentType: "quasi:transcribe-agent"' in loop
    assert "retryNull(" not in loop


def test_talk_audit_stays_on_exact_canonical_target() -> None:
    contract = text(AUDIT)
    operation = text(AUDIT_OPERATION)
    assert "一个 exact vault target" in contract
    assert "对同一 target 跑一次 audit" in contract
    assert "Workflow 按 exact\nowner 路由回 producer" in contract
    for token in (
        "quasi.operation.talk.audit.legacy.receipt/0.1",
        'key: { const: "talk.audit.legacy" }',
        "vault/talks/${slug}/talk.md",
        "exact_output",
        "mutated_paths",
        'operation: "talk.audit.legacy"',
    ):
        assert token in operation


def test_public_talk_skill_is_one_shared_workflow_ingress() -> None:
    skill = text(SKILL)
    assert "$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs" in skill
    assert '"kind": "talk"' in skill
    assert skill.count("return Workflow(") == 1
    assert "quasi.stage.receipt/0.2" in skill
    assert "Talk Prepare specialist" in skill
    assert "typed MaterialReceipt" in skill
    assert 'Agent("quasi:analyse-agent"' not in skill
    assert 'Agent("quasi:audit-agent"' not in skill
