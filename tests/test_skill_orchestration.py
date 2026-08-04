"""Maintainer-facing static contracts for quasi's orchestration layers.

These tests assert cross-file coherence (shared names, stages, schema versions)
and public boundaries — never the presence of specific prose sentences.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from scripts.status import status as status_module
from workflow_test_support import run_workflow_export


ROOT = Path(__file__).resolve().parents[1]


def active_skill_files() -> list[Path]:
    return sorted((ROOT / "skills").glob("*/SKILL.md"))


def active_agent_files() -> list[Path]:
    return sorted((ROOT / "agents").glob("*-agent.md"))


def description(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
    assert match, path
    return match.group(1).strip()


def generated_pipeline_registry() -> dict[str, dict[str, str]]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    entry = ROOT / "scripts" / "workflows" / "artifact-contracts" / "generated.mjs"
    script = (
        f"import {{ PIPELINE }} from {json.dumps(entry.as_uri())};"
        "const registry = Object.fromEntries("
        "Object.entries(PIPELINE).map(([kind, definition]) => ["
        "kind, Object.fromEntries(definition.stages.map("
        "({ stage, operation }) => [stage, operation]"
        "))]));"
        "process.stdout.write(JSON.stringify(registry));"
    )
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_mirrored_maintainer_guides_are_identical() -> None:
    assert (ROOT / "AGENTS.md").read_bytes() == (ROOT / "CLAUDE.md").read_bytes()


def test_status_producer_and_workflow_consumer_share_the_factual_envelope(
    tmp_path: Path,
) -> None:
    payload = status_module.paper_status(tmp_path, "exact-paper")

    observation = run_workflow_export(
        "scripts/workflows/contracts/paper.mts",
        "parsePaperStatusObservation",
        payload,
    )
    assert observation == payload

    parsed = run_workflow_export(
        "scripts/workflows/shared/material-input.mts",
        "sparseObservations",
        [
            {
                "route": {"kind": "paper", "slug": "exact-paper"},
                "observation": observation,
            }
        ],
    )

    assert parsed == {"__map_entries__": [["paper:exact-paper", payload]]}


def test_receipt_version_is_synced_between_stage_module_and_guide() -> None:
    version = "quasi.stage.receipt/0.3"
    stage = (ROOT / "scripts" / "workflows" / "stage.mts").read_text(
        encoding="utf-8"
    )
    guide = (ROOT / "docs" / "SKILL_ORCHESTRATION.md").read_text(encoding="utf-8")
    assert version in stage
    assert version in guide


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


def test_every_skill_dispatched_stage_resolves_in_the_registry() -> None:
    registry = generated_pipeline_registry()
    registry_stages = {
        stage for stages_by_kind in registry.values() for stage in stages_by_kind
    }
    for path in active_skill_files():
        text = path.read_text(encoding="utf-8")
        kinds = set(re.findall(r'"?kind"?\s*:\s*"([a-z]+)"', text))
        stages = set(re.findall(r'"?stage"?\s*:\s*"([a-z-]+)"', text))
        for kind in kinds:
            assert kind in registry, f"{path.relative_to(ROOT)}: unknown kind {kind}"
        for stage in stages:
            assert stage in registry_stages, (
                f"{path.relative_to(ROOT)}: unknown stage {stage}"
            )


def test_dispatching_skills_use_only_the_public_workflow_entry() -> None:
    for path in active_skill_files():
        text = path.read_text(encoding="utf-8")
        if "Workflow(" not in text:
            continue
        assert (
            'scriptPath="$CLAUDE_PLUGIN_ROOT/workflows/run-stage.mjs"' in text
        ), path
        assert "quasi-status" in text, path
        mjs_names = set(re.findall(r"[A-Za-z0-9_-]+\.mjs", text))
        assert mjs_names == {"run-stage.mjs"}, path


def test_skills_never_invoke_agent_owned_capabilities() -> None:
    capabilities = (
        "quasi-search",
        "quasi-download",
        "quasi-extract",
        "quasi-transcribe",
        "quasi-translate",
        "quasi-audit",
    )
    for path in active_skill_files():
        text = path.read_text(encoding="utf-8")
        referenced = [capability for capability in capabilities if capability in text]
        assert referenced == [], path


def test_gate_decision_tokens_shared_between_row_and_skill() -> None:
    row = (
        ROOT / "scripts" / "workflows" / "operations" / "rows" / "book.mts"
    ).read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "collect-material" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    for token in ("accept-current", "use-recommended-year"):
        assert token in row
        assert token in skill


def test_removed_legacy_bins_do_not_reappear_in_active_prompts() -> None:
    active = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [*active_skill_files(), *active_agent_files()]
    )
    for removed in ("quasi-citation ", "quasi-proofread ", "quasi-download batch"):
        assert removed not in active
