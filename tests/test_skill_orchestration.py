"""Maintainer-facing static contracts for quasi's orchestration layers.

These checks intentionally assert ownership and public boundaries rather than
freezing sentence-level prompt wording or a specialist's internal method.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "scripts" / "workflows"


def source_file(relative: str) -> str:
    return (WORKFLOWS / relative).read_text(encoding="utf-8")


def active_skill_files() -> list[Path]:
    return sorted((ROOT / "skills").glob("*/SKILL.md"))


def active_agent_files() -> list[Path]:
    return sorted((ROOT / "agents").glob("*-agent.md"))


def description(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
    assert match, path
    return match.group(1).strip()


def run_node(body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    proc = subprocess.run(
        [node, "--input-type=module", "-e", body],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_mirrored_maintainer_guides_are_identical() -> None:
    assert (ROOT / "AGENTS.md").read_bytes() == (ROOT / "CLAUDE.md").read_bytes()


def test_skill_orchestration_guide_describes_the_three_owners() -> None:
    text = (ROOT / "docs" / "SKILL_ORCHESTRATION.md").read_text(encoding="utf-8")
    assert "The Workflow is a stage board" in text
    assert "An Agent is a goal-owning specialist" in text
    assert "deterministic CLI remains responsible" in text
    assert "quasi.stage.receipt/0.2" in text
    assert "complete" in text and "needs_input" in text


def test_active_skills_keep_the_runtime_landmarks() -> None:
    required = (
        "## 任务",
        "## 输入",
        "## 硬约束",
        "## 状态",
        "## Agent / Helper 合同",
        "## 工作流",
        "## 执行流程",
        "## 断点续跑",
        "## 输出",
    )
    offenders: list[str] = []
    for path in active_skill_files():
        text = path.read_text(encoding="utf-8")
        for heading in required:
            if heading not in text:
                offenders.append(f"{path.relative_to(ROOT)} missing {heading}")
        if "docs/SKILL_ORCHESTRATION.md" in text:
            offenders.append(f"{path.relative_to(ROOT)} cites maintainer docs")
    assert offenders == []


def test_frontmatter_descriptions_are_short_routing_hints() -> None:
    for path in active_skill_files():
        value = description(path)
        assert value.startswith("Use when the user wants to "), path
        assert len(value) <= 220, path
    for path in active_agent_files():
        value = description(path)
        assert 20 <= len(value) <= 220, path
        assert "Phase" not in value and "→" not in value, path


def test_collect_material_starts_one_graph_and_does_not_shadow_ingress() -> None:
    skill = (ROOT / "skills" / "collect-material" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs" in skill
    assert '"kind": "batch"' in skill
    assert "2–32" in skill
    assert "quasi.collection.material-batch.receipt/0.1" in skill
    assert "material.recall" not in skill
    assert "quasi-search book" not in skill
    assert "quasi-helpers vault resolve" not in skill
    assert "collect_needs_input" in skill
    assert "report_blocked_and_failed_items" in skill


def test_collect_material_keeps_host_adapters_and_large_receipts_out_of_pty() -> None:
    skill = (ROOT / "skills" / "collect-material" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    reference = (
        ROOT / "skills" / "collect-material" / "references" / "codex-native-driver.md"
    ).read_text(encoding="utf-8")
    for name in ("quasi-pi-runner", "quasi-codex-driver", "quasi-codex-runner"):
        assert name in skill
    assert "request_path" in reference
    assert "receipt_path" in reference
    assert "result_path" in reference


def test_metadata_agent_is_a_goal_owning_investigator() -> None:
    text = (ROOT / "agents" / "metadata-agent.md").read_text(encoding="utf-8")
    assert "书目" in text and "规范身份" in text
    assert "quasi-search book|paper ... --json" in text
    assert "quasi-search kagi search --format json" in text
    assert "quasi-helpers vault resolve --items-file -" in text
    assert "只要还有一条有意义的证据路径，就继续调查" in text
    assert "查询次数和顺序由你" in text
    assert "complete" in text and "needs_input" in text
    assert "attempt:1" in text


def test_material_search_failure_shape_does_not_require_a_fake_identity() -> None:
    acquire = (WORKFLOWS / "operations" / "acquire.mjs").as_uri()
    result = run_node(
        f"""
import {{ materialSearchStageSchema }} from {json.dumps(acquire)}
const schema = materialSearchStageSchema({{
  request_key: 'paper:example', kind: 'paper'
}})
console.log(JSON.stringify({{
  root: schema.type,
  identity: schema.properties.identity.type,
  terminalBranches: schema.properties.terminal.anyOf.map(branch => ({{
    status: branch.properties.status.const,
    issue: branch.properties.issue.type,
    required: branch.required,
  }})),
  required: schema.required,
}}))
"""
    )
    assert result["root"] == "object"
    assert result["identity"] == ["object", "null"]
    assert [branch["status"] for branch in result["terminalBranches"]] == [
        "complete",
        "needs_input",
        "blocked",
        "failed",
    ]
    assert result["terminalBranches"][0]["issue"] == "null"
    needs_input = result["terminalBranches"][1]
    assert {"candidates", "conflicts"} <= set(needs_input["required"])
    assert "identity" in result["required"]
    assert "terminal" in result["required"]


def test_ingress_uses_one_search_stage_for_identity_and_local_owner() -> None:
    ingress = source_file("materials/ingress.mjs")
    acquire = source_file("operations/acquire.mjs")
    assert "materialSearchPrompt" in ingress
    assert "MATERIAL_SEARCH_STAGE_CONTRACT" in ingress
    assert 'operation: "material.search"' in acquire
    assert "local_owner" in acquire
    assert "materialResolvePrompt" not in ingress
    assert "materialRecallPrompt" not in ingress
    assert "MATERIAL_RECALL_SCHEMA" not in acquire
    assert ":recall" not in ingress
    assert 'label: `${request.requestedSlug}:search`' in ingress


@pytest.mark.parametrize(
    ("module", "operation", "agent_type"),
    [
        ("materials/paper.mjs", "paper.prepare", "quasi:extract-agent"),
        ("materials/book.mjs", "book.prepare", "quasi:extract-agent"),
        ("materials/talk.mjs", "talk.prepare", "quasi:transcribe-agent"),
        ("derivatives/translation.mjs", "translation.prepare", "quasi:translate-agent"),
    ],
)
def test_prepare_flows_are_one_specialist_stage(
    module: str,
    operation: str,
    agent_type: str,
) -> None:
    text = source_file(module)
    assert f'key: "{operation}"' in text
    assert f'agentType: "{agent_type}"' in text
    assert 'phase: "Prepare"' in text
    assert 'retry: "forbidden"' in text


def test_stage_contract_validates_terminals_not_internal_methods() -> None:
    stage = source_file("stage.mjs")
    assert "STAGE_STATUSES" in stage
    assert '"complete"' in stage
    assert '"needs_input"' in stage
    assert "complete(receipt, context)" in stage
    for forbidden in ("query_budget", "retry_count", "ocr_rounds", "fallback_method"):
        assert forbidden not in stage


def test_prepare_agents_own_local_judgement_while_cli_owns_transactions() -> None:
    extract = (ROOT / "agents" / "extract-agent.md").read_text(encoding="utf-8")
    transcribe = (ROOT / "agents" / "transcribe-agent.md").read_text(encoding="utf-8")
    translate = (ROOT / "agents" / "translate-agent.md").read_text(encoding="utf-8")
    assert "语义" in extract and "章节" in extract
    assert "锁、staging、原子发布" in extract
    assert "live|dead|empty" in transcribe
    assert "engine" in transcribe and "generation" in transcribe
    assert "coverage" in translate and "ToUnicode" in translate
    assert "writer durable outcome" in translate


def test_analyse_and_synthesis_consume_schema_and_exact_refs() -> None:
    analyse = (ROOT / "agents" / "analyse-agent.md").read_text(encoding="utf-8")
    synthesis = (ROOT / "agents" / "synthesis-agent.md").read_text(encoding="utf-8")
    for text in (analyse, synthesis):
        assert "artifact_contract" in text
        assert "exact" in text
        assert "create" in text and "repair" in text and "reconciled" in text
    assert "不自行扩充 corpus" in synthesis
    assert "Glob" not in synthesis


def test_download_receipt_keeps_actionable_acquisition_evidence() -> None:
    text = (ROOT / "agents" / "download-agent.md").read_text(encoding="utf-8")
    acquire = source_file("operations/acquire.mjs")
    assert "failure reason" in text and "attempts" in text
    assert "POSIX single quoting" in text
    assert "source:\"existing_file\"" in text
    assert "preserve_attempt_rows: true" in acquire
    assert "min_independent_supports: 2" in acquire


def test_audit_agent_has_one_local_fix_then_validation_transaction() -> None:
    text = (ROOT / "agents" / "audit-agent.md").read_text(encoding="utf-8")
    assert "quasi-audit --path" in text
    assert "发生 Edit 后，再对同一 target 跑一次 audit" in text
    assert "mutated_paths" in text
    assert "{path,kind,reason}" in text
    assert "Target 之外" in text


def test_shared_ui_phases_are_progress_stages_not_router_branches() -> None:
    entry = (WORKFLOWS / "process-material.entry.mjs").as_uri()
    result = run_node(
        f"""
import {{ workflowMeta }} from {json.dumps(entry)}
console.log(JSON.stringify(workflowMeta))
"""
    )
    assert [row["title"] for row in result["phases"]] == [
        "Recall", "Search", "Acquire", "Prepare", "Analyse", "Synthesise", "Audit"
    ]
    assert not {"Paper", "Book", "Talk", "Translation", "Author", "Topic"}.intersection(
        row["title"] for row in result["phases"]
    )


def test_agent_labels_are_material_first_and_every_call_has_a_phase() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in WORKFLOWS.rglob("*.mjs")
    )
    calls = re.findall(r"agent\([^;]+?\{([^;]+?)\}\s*\)", sources, re.DOTALL)
    # Runtime owns the sole raw agent call; material Operations use operate or
    # runOperation with opts that always carry phase and label.
    assert sources.count("agent(prompt, opts)") == 1
    for module in (
        "materials/ingress.mjs", "materials/paper.mjs", "materials/book.mjs",
        "materials/talk.mjs", "derivatives/translation.mjs",
    ):
        text = source_file(module)
        assert "phase:" in text and "label:" in text


def test_artifact_structure_has_one_schema_owner() -> None:
    guide = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "scripts/schemas/" in guide
    assert "single source of truth" in guide
    assert "artifact-contracts/generated.mjs" in guide
    assert "never hand-edit" in guide


def test_removed_legacy_bins_do_not_reappear_in_active_prompts() -> None:
    active = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [*active_skill_files(), *active_agent_files()]
    )
    for removed in ("quasi-citation ", "quasi-proofread ", "quasi-download batch"):
        assert removed not in active


def test_topic_remains_a_separate_public_research_skill() -> None:
    collect = description(ROOT / "skills" / "collect-material" / "SKILL.md")
    topic = description(ROOT / "skills" / "precise-topic" / "SKILL.md")
    assert "topic" not in collect.lower()
    assert "topic" in topic.lower()
    graph = source_file("process-material.entry.mjs")
    assert 'case "topic"' in graph
    assert "processTopic" in graph
