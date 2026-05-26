"""Guard tests for SPEC §5.2 (block-list YAML for vault frontmatter arrays).

Two layers:

1. **Production code**: feed flow-form fixtures to `autofix_mechanical.py` and
   `sweep-book-fm-clean.py`; assert the on-disk result is block-form.

2. **Source-tree grep**: ensure no canonical frontmatter examples in agent
   templates or the schema spec leak flow-form arrays for known list keys
   (`themes`, `authors`, `tags`, `keywords`). Negative examples inside
   "禁用" / "❌" / "wrong" blocks are exempt.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
AUTOFIX = PLUGIN_ROOT / "scripts" / "typecheck" / "autofix_mechanical.py"
SWEEP_CLEAN = PLUGIN_ROOT / "scripts" / "audit" / "sweep" / "sweep-book-fm-clean.py"

LIST_KEYS = ("themes", "authors", "tags", "keywords")
FLOW_ARRAY_RE = re.compile(
    rf"^[ \t]*(?:{'|'.join(LIST_KEYS)}):[ \t]*\[",
    re.MULTILINE,
)
NEGATIVE_MARKERS = ("❌", "禁用", "wrong", "错误", "incorrect")


# ─── production code smoke tests ──────────────────────────────────────────


def _write_paper_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "type: paper\n"
        "title: Happy Objects\n"
        "authors: [Sara Ahmed]\n"
        "year: 2010\n"
        "journal: The Affect Theory Reader\n"
        "themes: [affect-theory, happiness]\n"
        "---\n"
        "\n"
        "## 核心论点\n"
        "body.\n",
        encoding="utf-8",
    )


def test_autofix_emits_block_lists(tmp_path: Path) -> None:
    vault = tmp_path / "vault" / "papers"
    fp = vault / "ahmed-happy-objects.md"
    _write_paper_fixture(fp)

    result = subprocess.run(
        [sys.executable, str(AUTOFIX), "--path", str(fp), "--write"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr

    after = fp.read_text(encoding="utf-8")
    assert "authors:\n- Sara Ahmed" in after or "authors:\n  - Sara Ahmed" in after, after
    assert "themes:\n- affect-theory" in after or "themes:\n  - affect-theory" in after, after
    # No flow arrays survived.
    assert "[Sara Ahmed]" not in after, after
    assert "[affect-theory" not in after, after


def _write_book_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "type: book\n"
        "title: Nightwork\n"
        'authors: ["[[allison-nightwork-1994|Anne Allison]]"]\n'
        "year: 1994\n"
        "publisher: University of Chicago Press\n"
        "category: monograph\n"
        "---\n"
        "\n",
        encoding="utf-8",
    )


def test_sweep_clean_emits_block_lists(tmp_path: Path) -> None:
    project = tmp_path / "project"
    fp = project / "vault" / "books" / "allison-nightwork-1994" / "00-overview.md"
    _write_book_fixture(fp)

    result = subprocess.run(
        [sys.executable, str(SWEEP_CLEAN), "--write"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr

    after = fp.read_text(encoding="utf-8")
    assert "authors:\n  - Anne Allison" in after, after
    assert "[Anne Allison]" not in after, after


# ─── source-tree grep guard ───────────────────────────────────────────────


def _flow_array_violations_in(text: str) -> list[tuple[int, str]]:
    """Return (line_number, line_text) for flow-array hits not preceded by a
    negative marker within the prior 6 lines (the marker convention in our
    SPEC / agent files)."""
    lines = text.splitlines()
    out: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        if not FLOW_ARRAY_RE.match(line):
            continue
        window = "\n".join(lines[max(0, idx - 6) : idx])
        if any(marker in window for marker in NEGATIVE_MARKERS):
            continue
        out.append((idx + 1, line))
    return out


def test_no_flow_arrays_in_agent_templates() -> None:
    scan_files = [
        PLUGIN_ROOT / "agents" / "analyse-agent.md",
        PLUGIN_ROOT / "agents" / "synthesis-agent.md",
        PLUGIN_ROOT / "agents" / "audit-agent.md",
        PLUGIN_ROOT / "scripts" / "schemas" / "SPEC.md",
    ]
    violations: list[str] = []
    for path in scan_files:
        text = path.read_text(encoding="utf-8")
        for lineno, line in _flow_array_violations_in(text):
            violations.append(f"{path.relative_to(PLUGIN_ROOT)}:{lineno}: {line}")
    assert not violations, (
        "Flow-form arrays found outside ❌/禁用/wrong/错误 blocks "
        "(SPEC §5.2 requires block lists):\n  " + "\n  ".join(violations)
    )
