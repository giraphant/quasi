"""Maintainer-facing static contracts for quasi's orchestration layers.

These checks intentionally assert ownership and public boundaries rather than
freezing sentence-level prompt wording or a specialist's internal method.
"""

from __future__ import annotations

from pathlib import Path
import re


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
    assert "quasi.collection.material-batch.receipt/0.2" in skill
    assert "material.recall" not in skill
    assert "quasi-search book" not in skill
    assert "quasi-helpers vault resolve" not in skill
    assert "collect_needs_input" in skill
    assert "report_blocked_and_failed_items" in skill


def test_collect_material_uses_native_claude_workflow_only() -> None:
    skill = (ROOT / "skills" / "collect-material" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "Workflow(" in skill
    assert 'scriptPath="$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs"' in skill
    for name in ("quasi-pi-runner", "quasi-codex-driver", "quasi-codex-runner"):
        assert name not in skill


def test_research_topic_starts_the_shared_topic_graph() -> None:
    skill = (ROOT / "skills" / "research-topic" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "name: research-topic" in skill
    assert "$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs" in skill
    assert '{"kind":"topic","slug":slug,"meta":meta}' in skill
    assert "needs_seeds" in skill


























def test_removed_legacy_bins_do_not_reappear_in_active_prompts() -> None:
    active = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [*active_skill_files(), *active_agent_files()]
    )
    for removed in ("quasi-citation ", "quasi-proofread ", "quasi-download batch"):
        assert removed not in active
