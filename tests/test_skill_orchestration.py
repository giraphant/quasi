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


def test_collect_material_main_thread_drives_run_stage_from_disk_observations() -> None:
    skill = (ROOT / "skills" / "collect-material" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "$CLAUDE_PLUGIN_ROOT/workflows/run-stage.mjs" in skill
    assert "$CLAUDE_PLUGIN_ROOT/workflows/process-material.mjs" not in skill
    assert '"stage": "search"' in skill
    assert "quasi-status --kind K --slug S --json" in skill
    assert "next_stage" in skill and "绝不能当作" in skill
    assert "WRITER-AMBIGUITY RULE" in skill
    assert "不得 blind redispatch" in skill
    assert "2–32" in skill
    assert "material.recall" not in skill
    assert "quasi-search book" not in skill
    assert "quasi-helpers vault resolve" not in skill
    assert "quasi-status --identity" in skill
    assert "member/admission-probe" not in skill


def test_collect_material_pins_main_thread_gates_repair_and_author_rows() -> None:
    skill = (ROOT / "skills" / "collect-material" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "Workflow(" in skill
    assert 'scriptPath="$CLAUDE_PLUGIN_ROOT/workflows/run-stage.mjs"' in skill
    # No intermediate driver layer: the main thread drives every material.
    assert "driver" not in skill.lower()
    assert "主线程" in skill
    assert "same identity" in skill or "same-identity" in skill
    assert "accept-current" in skill
    assert "use-recommended-year" in skill
    assert 'mode:"repair"' in skill
    assert "discover-books" in skill
    assert "discover-papers" in skill
    assert "resolve-membership" in skill
    assert 'stage:"synthesise"' in skill
    assert "--identity" in skill
    for name in ("quasi-pi-runner", "quasi-codex-driver", "quasi-codex-runner"):
        assert name not in skill


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


def test_research_topic_main_thread_drives_bounded_run_stage_rounds() -> None:
    skill = (ROOT / "skills" / "research-topic" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "name: research-topic" in skill
    assert "$CLAUDE_PLUGIN_ROOT/workflows/run-stage.mjs" in skill
    assert "process-material.mjs" not in skill
    assert 'scriptPath="$CLAUDE_PLUGIN_ROOT/workflows/run-stage.mjs"' in skill
    assert "主线程" in skill
    assert "driver" not in skill.lower()
    assert "Agent(" not in skill
    assert "至多保持五个" in skill
    assert "逐个受理" in skill
    assert "maxRounds" in skill and "recall-only" in skill
    assert "maxCardsPerRound" in skill and "共享资源" in skill
    assert "process-now" in skill and "proceed-without" in skill


def test_research_topic_pins_round_convergence_channels_and_repair() -> None:
    skill = (ROOT / "skills" / "research-topic" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    for stage in (
        'stage:"recall"',
        'stage:"steer"',
        'stage:"webcard"',
        'stage:"synthesise-overview"',
        'stage:"synthesise-resources"',
        'stage:"audit"',
    ):
        assert stage in skill
    assert "seen_demand_fingerprints" in skill
    assert "[kind,query,subq,role,reason]" in skill
    assert "seen_identities" in skill
    assert 'signal:"saturated"' in skill
    assert "没有 unseen demand/card" in skill
    assert "hard bound" in skill
    assert 'card_status:"empty"' in skill
    assert "独立 evidence-card channel" in skill
    assert "quasi-status --kind K --slug S --json --identity" in skill
    assert "WRITER-AMBIGUITY RULE" in skill
    assert 'mode:"repair"' in skill
    assert "pass:2" in skill


























def test_removed_legacy_bins_do_not_reappear_in_active_prompts() -> None:
    active = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [*active_skill_files(), *active_agent_files()]
    )
    for removed in ("quasi-citation ", "quasi-proofread ", "quasi-download batch"):
        assert removed not in active
