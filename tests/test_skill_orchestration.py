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


def run_stage_registry() -> dict[str, dict[str, str]]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    entry = ROOT / "scripts" / "workflows" / "run-stage.entry.mjs"
    script = (
        f"import {{ RUN_STAGE_REGISTRY }} from {json.dumps(entry.as_uri())};"
        "process.stdout.write(JSON.stringify(RUN_STAGE_REGISTRY));"
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


def test_receipt_version_is_synced_between_stage_module_and_guide() -> None:
    version = "quasi.stage.receipt/0.2"
    stage = (ROOT / "scripts" / "workflows" / "stage.mjs").read_text(
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
    registry = run_stage_registry()
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
        ROOT / "scripts" / "workflows" / "operations" / "rows" / "book.mjs"
    ).read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "collect-material" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    for token in ("accept-current", "use-recommended-year"):
        assert token in row
        assert token in skill


def test_collection_container_route_exists_in_search_contract() -> None:
    row = (ROOT / "scripts" / "workflows" / "operations" / "rows" / "search.mjs").read_text(
        encoding="utf-8"
    )
    agent = (ROOT / "agents" / "metadata-agent.md").read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "collect-material" / "SKILL.md").read_text(encoding="utf-8")
    # The conflict vocabulary lives in the row; the method and the routing must
    # both be able to name it, or a container-only work has no honest exit.
    assert '"publication_type"' in row
    assert "publication_type" in agent
    assert "publication_type" in skill


def test_removed_legacy_bins_do_not_reappear_in_active_prompts() -> None:
    active = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [*active_skill_files(), *active_agent_files()]
    )
    for removed in ("quasi-citation ", "quasi-proofread ", "quasi-download batch"):
        assert removed not in active
