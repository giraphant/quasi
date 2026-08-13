"""Maintainer-facing static contracts for quasi's orchestration layers.

These tests assert cross-file coherence (shared names, stages, schema versions)
and public boundaries — never the presence of specific prose sentences.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re

import yaml

from scripts.status import status as status_module
from workflow_test_support import run_workflow_export


ROOT = Path(__file__).resolve().parents[1]


def active_skill_files() -> list[Path]:
    return sorted((ROOT / "skills").glob("*/SKILL.md"))


def active_agent_files() -> list[Path]:
    return sorted((ROOT / "agents").glob("*-agent.md"))


def frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, path
    value = yaml.safe_load(match.group(1))
    assert isinstance(value, dict), path
    return value


def markdown_table_row(path: Path, label: str) -> str:
    match = re.search(
        rf"^\|\s*{re.escape(label)}\s*\|\s*(.*?)\s*\|$",
        path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match, f"{path} has no table row for {label}"
    return match.group(1)


def collect_material_leaf_workflow_manifest() -> dict[str, dict[str, object]]:
    path = ROOT / "skills" / "collect-material" / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    for source in re.findall(r"```json\n(.*?)\n```", text, re.DOTALL):
        try:
            value = json.loads(source)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(value, dict)
            and set(value) == {"workflow_inputs"}
            and isinstance(value["workflow_inputs"], dict)
        ):
            return value["workflow_inputs"]
    raise AssertionError("collect-material has no closed leaf invocation manifest")


def test_collect_material_has_generic_user_decision_envelope() -> None:
    path = ROOT / "skills" / "collect-material" / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    assignments: list[ast.Assign] = []
    for source in re.findall(r"```python\n(.*?)\n```", text, re.DOTALL):
        tree = ast.parse(source)
        assignments.extend(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "user_decision"
                for target in node.targets
            )
        )

    assert len(assignments) == 1
    value = assignments[0].value
    assert isinstance(value, ast.Dict)
    assert len(value.keys) == 3
    assert all(
        isinstance(key, ast.Constant) and isinstance(key.value, str)
        for key in value.keys
    )
    assert {
        key.value
        for key in value.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    } == {"material_key", "operation", "value"}


def research_topic_workflow_manifest() -> dict[str, object]:
    path = ROOT / "skills" / "research-topic" / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    for source in re.findall(r"```json\n(.*?)\n```", text, re.DOTALL):
        try:
            value = json.loads(source)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and set(value) == {"workflow_input"}:
            contract = value["workflow_input"]
            if isinstance(contract, dict):
                return contract
    raise AssertionError("research-topic has no closed invocation manifest")


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


def test_frontmatter_descriptions_are_nonempty_single_line_strings() -> None:
    skill_files = active_skill_files()
    for path in skill_files:
        metadata = frontmatter(path)
        assert isinstance(metadata.get("name"), str), path
    for path in [*skill_files, *active_agent_files()]:
        value = frontmatter(path).get("description")
        assert isinstance(value, str), path
        assert value.strip(), path
        assert "\n" not in value and "\r" not in value, path


def test_webpage_agent_exposes_only_read_and_bash() -> None:
    path = ROOT / "agents" / "webpage-agent.md"
    assert path.is_file()
    assert frontmatter(path)["tools"] == "Read, Bash"


def test_webpage_public_documentation_limits_capture_to_macos_11_or_newer() -> None:
    capability = markdown_table_row(ROOT / "README.md", "`collect-material`")
    assert "公共网页" in capability
    assert re.search(r"macOS\s+11\+", capability)

    cli = markdown_table_row(ROOT / "docs" / "ARCHITECTURE.md", "`quasi-webpage`")
    assert "capture" in cli
    assert re.search(r"macOS\s+11\+", cli)


def test_collect_material_routes_leaf_kinds_to_generated_named_entries() -> None:
    manifest = collect_material_leaf_workflow_manifest()
    assert manifest == {
        "paper": {
            "entry": "$CLAUDE_PLUGIN_ROOT/workflows/paper.mjs",
            "required": ["seed", "observation", "options"],
            "optional": ["userDecision"],
            "seed_keys": ["state", "requested_slug", "hints"],
            "hint_keys": [
                "title", "doi", "authors", "year", "journal", "oa_url", "url"
            ],
            "option_keys": [],
        },
        "book": {
            "entry": "$CLAUDE_PLUGIN_ROOT/workflows/book.mjs",
            "required": ["seed", "observation", "options"],
            "optional": ["userDecision"],
            "seed_keys": ["state", "requested_slug", "hints"],
            "hint_keys": [
                "title", "isbn", "authors", "year", "publisher", "category"
            ],
            "option_keys": ["allowed_formats"],
        },
        "talk": {
            "entry": "$CLAUDE_PLUGIN_ROOT/workflows/talk.mjs",
            "required": ["seed", "observation", "options"],
            "optional": [],
            "seed_keys": ["state", "material_slug", "identity"],
            "identity_keys": ["title", "date", "media"],
            "option_keys": ["engines", "lang", "prepare_media"],
        },
        "translation": {
            "entry": "$CLAUDE_PLUGIN_ROOT/workflows/translation.mjs",
            "required": ["seed", "target_language", "observation", "options"],
            "optional": ["userDecision"],
            "seed_keys": ["state", "material_slug"],
            "option_keys": ["source_file", "toc_json", "toc_page_side"],
        },
        "author": {
            "entry": "$CLAUDE_PLUGIN_ROOT/workflows/author.mjs",
            "required": ["seed", "observation", "options"],
            "optional": [],
            "seed_keys": ["slug", "full_name", "topic"],
            "option_keys": ["maxBooks", "maxPapers"],
            "resume_required": [
                "observation", "resume_seed", "child_observations"
            ],
            "resume_optional": ["userDecision"],
        },
        "webpage": {
            "entry": "$CLAUDE_PLUGIN_ROOT/workflows/webpage.mjs",
            "required": ["seed", "observation", "options"],
            "optional": [],
            "seed_keys": ["state", "url"],
            "option_keys": [],
            "initial_observation": None,
        },
    }
    for contract in manifest.values():
        entry = contract["entry"]
        assert isinstance(entry, str)
        relative = entry.removeprefix("$CLAUDE_PLUGIN_ROOT/")
        assert relative != entry
        assert (ROOT / relative).is_file(), entry


def test_collect_material_transports_a_webpage_url_without_an_initial_observation() -> None:
    path = ROOT / "skills" / "collect-material" / "SKILL.md"
    assignments: list[ast.Assign] = []
    for source in re.findall(r"```python\n(.*?)\n```", path.read_text(encoding="utf-8"), re.DOTALL):
        tree = ast.parse(source)
        assignments.extend(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "workflow_input"
                for target in node.targets
            )
        )

    envelopes = [
        assignment.value
        for assignment in assignments
        if isinstance(assignment.value, ast.Dict)
        and any(
            isinstance(key, ast.Constant) and key.value == "seed"
            and isinstance(value, ast.Dict)
            and any(
                isinstance(seed_key, ast.Constant) and seed_key.value == "url"
                for seed_key in value.keys
            )
            for key, value in zip(assignment.value.keys, assignment.value.values)
        )
    ]
    assert len(envelopes) == 1

    envelope = envelopes[0]
    assert isinstance(envelope, ast.Dict)
    fields = {
        key.value: value
        for key, value in zip(envelope.keys, envelope.values)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    assert set(fields) == {"seed", "observation", "options"}
    assert isinstance(fields["seed"], ast.Dict)
    seed = {
        key.value: value
        for key, value in zip(fields["seed"].keys, fields["seed"].values)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    assert isinstance(seed.get("state"), ast.Constant)
    assert seed["state"].value == "provisional"
    assert isinstance(seed.get("url"), ast.Name)
    assert seed["url"].id == "exact_url"
    assert isinstance(fields["observation"], ast.Constant)
    assert fields["observation"].value is None
    assert isinstance(fields["options"], ast.Dict)
    assert fields["options"].keys == []


def test_research_topic_routes_to_its_generated_named_entry() -> None:
    manifest = research_topic_workflow_manifest()
    assert manifest == {
        "entry": "$CLAUDE_PLUGIN_ROOT/workflows/topic.mjs",
        "required": [
            "query", "observation", "options", "seed_materials",
            "child_observations",
        ],
        "optional": ["resume"],
        "query_keys": ["slug", "description"],
        "option_keys": ["maxRounds", "maxCardsPerRound"],
        "seed_kinds": ["paper", "book", "talk"],
        "resume_required": ["resume_seed"],
        "resume_optional": ["userDecision"],
    }
    entry = str(manifest["entry"]).removeprefix("$CLAUDE_PLUGIN_ROOT/")
    assert (ROOT / entry).is_file()
    text = (ROOT / "skills" / "research-topic" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "quasi-status --kind topic" in text
    assert "--scan" not in text
    assert 'stage:"' not in text


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


def test_removed_legacy_bins_do_not_reappear_in_active_prompts() -> None:
    active = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [*active_skill_files(), *active_agent_files()]
    )
    for removed in ("quasi-citation ", "quasi-proofread ", "quasi-download batch"):
        assert removed not in active
