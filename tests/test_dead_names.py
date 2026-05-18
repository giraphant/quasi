from __future__ import annotations

from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]

DEAD_NAMES = [
    "discover-agent",
    "new-discover-agent",
    "quasi-search books",
    "quasi-synthesize-refs",
    "quasi-journal-fetch",
    "quasi-journal-report",
    "quasi-helpers citation render",
    "quasi-helpers proofread split",
    "quasi-helpers proofread init",
    "quasi-download book get",
    "quasi-download paper get",
    "quasi-download finalize",
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
    ".quasi/audit/translations.json",
]


def active_markdown_files() -> list[Path]:
    files: list[Path] = []
    files.extend((PLUGIN_ROOT / "agents").glob("*.md"))
    files.extend((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))
    return files


def test_active_agents_and_skills_do_not_reference_dead_names():
    offenders: list[str] = []
    for path in active_markdown_files():
        text = path.read_text(encoding="utf-8")
        for name in DEAD_NAMES:
            if name in text:
                offenders.append(f"{path.relative_to(PLUGIN_ROOT)}: {name}")

    assert offenders == []


def test_removed_legacy_bins_are_not_present():
    assert not (PLUGIN_ROOT / "bin" / "quasi-citation").exists()
    assert not (PLUGIN_ROOT / "bin" / "quasi-proofread").exists()
