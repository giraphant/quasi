from __future__ import annotations

from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]

DEAD_NAMES = [
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
]


def active_markdown_files() -> list[Path]:
    files: list[Path] = []
    files.extend((PLUGIN_ROOT / "agents").glob("*.md"))
    files.extend((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))
    return files


def active_contract_files() -> list[Path]:
    files = active_markdown_files()
    files.extend((PLUGIN_ROOT / "bin").glob("quasi-*"))
    files.extend([
        PLUGIN_ROOT / "README.md",
        PLUGIN_ROOT / "docs" / "ARCHITECTURE.md",
    ])
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
    assert not (PLUGIN_ROOT / "bin" / "quasi-citation").exists()
    assert not (PLUGIN_ROOT / "bin" / "quasi-proofread").exists()
