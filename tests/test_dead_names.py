from __future__ import annotations

from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]

DEAD_NAMES = [
    "search-agent",
    "discover-agent",
    "new-discover-agent",
    "quasi-search books",
    "--shape single",
    "--shape raw",
    "quasi-search --output",
    "quasi-synthesize-refs",
    "quasi-journal-fetch",
    "quasi-journal-report",
    "quasi-helpers citation render",
    "citation-agent",
    "quasi-helpers proofread split",
    "quasi-helpers proofread init",
    "quasi-download book get",
    "quasi-download paper get",
    "quasi-download finalize",
    "quasi-download batch",
    "mode: papers",
    "--finalize-book",
    "localisation-agent",
    "quasi:localisation-agent",
    "quasi:local-agent",
    "local-agent",
    "quasi-audit localise",
    "quasi-audit run",
    "quasi-audit emit-bib",
    "quasi-audit backfill",
    "--mode check",
    "--mode fix",
    "write_policy",
    "output_schema",
    ".quasi/audit/translations.json",
    "quasi:process-book",
    "quasi:process-paper",
    "quasi:process-author",
    "quasi:process-topic",
    "process-talk",
    "process-draft",
    "precise-topic",
    "quasi:process-material",
    "organise-topic",
    "finalize-draft",
    "kb-update",
    "mode: journal",
    "profile-agent",
    "overview-agent",
    "quasi-pi-runner",
    "quasi-codex-runner",
    "quasi-codex-driver",
    "quasi-codex-agents",
    "member.admission-probe",
    "process-material.mjs",
    "materials/interpreter.mjs",
    "materials/paper.mjs",
    "materials/book.mjs",
    "materials/talk.mjs",
    "materials/route.mjs",
    "materials/ingress.mjs",
    "materials/batch.mjs",
    "materials/dispatch.mjs",
    "materials/member.mjs",
    "materials/receipt.mjs",
    "derivatives/translation.mjs",
    "collections/author.mjs",
    "research/topic-recall.mjs",
    "operations/chains.mjs",
    "run-stage-context.mjs",
    "workflows/run-stage.mjs",
    "quasi.run-stage.chain",
    "quasi.run-stage.batch",
    "quasi.run-stage.error",
    "RUN_STAGE_REGISTRY",
    "STAGE_CHAINS",
    '"until":',
    '"units":',
]

DEAD_GRAPH_PATHS = [
    "workflows/run-stage.mjs",
    "scripts/workflows/run-stage.entry.mts",
    "scripts/workflows/shared/dispatch.mts",
    "scripts/workflows/operations/catalog.mts",
    "workflows/process-material.mjs",
    "scripts/workflows/process-material.entry.mjs",
    "scripts/workflows/materials/interpreter.mjs",
    "scripts/workflows/materials/paper.mjs",
    "scripts/workflows/materials/book.mjs",
    "scripts/workflows/materials/talk.mjs",
    "scripts/workflows/materials/route.mjs",
    "scripts/workflows/materials/ingress.mjs",
    "scripts/workflows/materials/batch.mjs",
    "scripts/workflows/materials/dispatch.mjs",
    "scripts/workflows/materials/member.mjs",
    "scripts/workflows/materials/receipt.mjs",
    "scripts/workflows/derivatives/translation.mjs",
    "scripts/workflows/collections/author.mjs",
    "scripts/workflows/research/topic-recall.mjs",
    "scripts/workflows/operations/acquire.mjs",
    "scripts/workflows/operations/audit.mjs",
    "scripts/workflows/operations/synthesise.mjs",
]

def active_markdown_files() -> list[Path]:
    files: list[Path] = []
    files.extend((PLUGIN_ROOT / "agents").glob("*.md"))
    files.extend((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))
    return files


def active_contract_files() -> list[Path]:
    files = active_markdown_files()
    files.extend((PLUGIN_ROOT / "bin").glob("quasi-*"))
    files.extend(
        [
            PLUGIN_ROOT / "README.md",
            PLUGIN_ROOT / "docs" / "ARCHITECTURE.md",
        ]
    )
    return [path for path in files if path.exists()]


def test_active_agents_and_skills_do_not_reference_dead_names():
    offenders: list[str] = []
    for path in active_contract_files():
        text = path.read_text(encoding="utf-8")
        for name in DEAD_NAMES:
            if name in text:
                offenders.append(f"{path.relative_to(PLUGIN_ROOT)}: {name}")

    assert offenders == []


def test_removed_legacy_bins_are_not_present():
    for name in (
        "quasi-citation",
        "quasi-proofread",
        "quasi-pi-runner",
        "quasi-codex-runner",
        "quasi-codex-driver",
        "quasi-codex-agents",
    ):
        assert not (PLUGIN_ROOT / "bin" / name).exists()


def test_removed_public_skill_directories_are_not_present():
    for name in (
        "process-material",
        "organise-topic",
        "finalize-draft",
        "process-talk",
        "process-draft",
        "precise-topic",
    ):
        assert not (PLUGIN_ROOT / "skills" / name).exists()


def test_removed_graph_driver_paths_are_not_present():
    for relative in DEAD_GRAPH_PATHS:
        assert not (PLUGIN_ROOT / relative).exists()
