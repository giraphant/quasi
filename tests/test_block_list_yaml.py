"""Capability tests for block-list YAML frontmatter normalization."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
AUTOFIX = PLUGIN_ROOT / "scripts" / "typecheck" / "autofix_mechanical.py"
SWEEP_CLEAN = PLUGIN_ROOT / "scripts" / "audit" / "sweep" / "sweep-book-fm-clean.py"


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


def test_autofix_omits_empty_optional_list(tmp_path: Path) -> None:
    """Per SPEC §5.2: empty list value → omit field entirely."""
    fp = tmp_path / "vault" / "papers" / "no-themes.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(
        "---\n"
        "type: chapter\n"
        "title: Empty themes paper\n"
        "authors: [Foo]\n"
        "year: 2020\n"
        "book: foo-bar-2020\n"
        "themes: []\n"
        "---\n"
        "\n"
        "## 核心论点\n"
        "body.\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(AUTOFIX), "--path", str(fp), "--write"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr

    after = fp.read_text(encoding="utf-8")
    assert "themes:" not in after, f"Empty themes should be dropped:\n{after}"
    assert "themes: []" not in after, after


def test_autofix_keeps_topics_drops_singular_topic(tmp_path: Path) -> None:
    """Regression for QUA-36: `topics` became a real schema support field on
    book/paper/chapter/author, but was left in autofix's ORPHAN_FIELDS, so
    mechanical autofix stripped it. The plural `topics` must survive; the
    legacy singular `topic` must still be dropped."""
    fp = tmp_path / "vault" / "papers" / "topics-keep.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(
        "---\n"
        "type: paper\n"
        "title: Membership Test\n"
        "authors: [Foo]\n"
        "year: 2020\n"
        "journal: Some Journal\n"
        "topic: legacy-singular\n"
        "topics: [feminist-sts, infrastructure]\n"
        "---\n"
        "\n"
        "## 核心论点\n"
        "body.\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(AUTOFIX), "--path", str(fp), "--write"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr

    after = fp.read_text(encoding="utf-8")
    assert "topics:" in after, f"plural topics was dropped:\n{after}"
    assert "feminist-sts" in after, after
    assert "infrastructure" in after, after
    # legacy singular topic stays an orphan and is removed
    assert "topic: legacy-singular" not in after, f"singular topic survived:\n{after}"


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


def test_sweep_clean_consumes_unindented_block_list_remnant(tmp_path: Path) -> None:
    """Pre-existing block-list authors written at column 0 must be fully
    consumed when replaced — no stale `- ...` line should leak below the new
    authors block."""
    project = tmp_path / "project"
    fp = project / "vault" / "books" / "test-book-2020" / "00-overview.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(
        "---\n"
        "type: book\n"
        "title: Test Book\n"
        "authors:\n"
        "- '[[test-slug|Real Name]]'\n"
        "- '[[other-slug|Other Name]]'\n"
        "year: 2020\n"
        "publisher: Test Press\n"
        "category: monograph\n"
        "---\n"
        "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SWEEP_CLEAN), "--write"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr

    after = fp.read_text(encoding="utf-8")
    # The old wikilinks should be fully consumed and replaced.
    assert "[[test-slug" not in after, f"Old wikilink leaked:\n{after}"
    assert "[[other-slug" not in after, f"Old wikilink leaked:\n{after}"
    # The new block list should appear, no stale unindented items below it.
    assert "authors:\n  - Real Name\n  - Other Name\nyear: 2020" in after, after
