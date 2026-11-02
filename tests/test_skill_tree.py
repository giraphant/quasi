"""Keep the quasi skill tree coherent: every page it routes to and every CLI command it names exists."""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "quasi"
PAGES = sorted(SKILL.rglob("*.md"))
SKILL_DIRS = {path.name for path in SKILL.iterdir() if path.is_dir()}

# Backticked skill-relative page paths, e.g. `collect/paper/README.md` or `本目录/writing.md`.
PAGE_REF = re.compile(r"`((?:本目录/)?[A-Za-z0-9_./-]+\.md)`")
# CLI calls such as `quasi status ...` inside backticks or code blocks.
COMMAND_REF = re.compile(r"(?<![\w/.-])quasi ([a-z][a-z-]*)\b")


def _page_refs(page: Path) -> list[tuple[str, Path]]:
    refs = []
    for raw in PAGE_REF.findall(page.read_text(encoding="utf-8")):
        if raw.startswith("本目录/"):
            target = page.parent / raw.removeprefix("本目录/")
        elif raw == "SKILL.md" or raw.split("/", 1)[0] in SKILL_DIRS:
            target = SKILL / raw
        else:
            continue  # artifact names such as `archive.md` or `vault/...` paths
        refs.append((raw, target))
    return refs


def test_skill_tree_has_pages():
    assert (SKILL / "SKILL.md").is_file()
    assert len(PAGES) > 10


def test_every_routed_page_exists():
    missing = [
        f"{page.relative_to(SKILL)} -> {raw}"
        for page in PAGES
        for raw, target in _page_refs(page)
        if not target.is_file()
    ]
    assert missing == []


def test_every_named_quasi_command_exists():
    commands = {
        command
        for page in PAGES
        for command in COMMAND_REF.findall(page.read_text(encoding="utf-8"))
    }
    assert commands, "expected the skill to name quasi commands"
    missing = sorted(c for c in commands if not (ROOT / "bin" / f"quasi-{c}").is_file())
    assert missing == []


def test_cli_entry_is_executable():
    entry = SKILL / "scripts" / "quasi"
    assert entry.is_file() and os.access(entry, os.X_OK)


def test_claude_md_only_imports_agents_md():
    assert (ROOT / "CLAUDE.md").read_text(encoding="utf-8").strip() == "@AGENTS.md"


def test_workflow_orchestration_does_not_return():
    for relative in ("workflows", "agents", "scripts/workflows", "skills/collect-material", "skills/research-topic"):
        assert not (ROOT / relative).exists(), relative
