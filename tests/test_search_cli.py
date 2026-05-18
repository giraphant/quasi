from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SEARCH = PLUGIN_ROOT / "scripts" / "search" / "search.py"


def run_search(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SEARCH), *args],
        cwd=PLUGIN_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )


def test_search_help_exposes_fixed_json_contract():
    top = run_search("--help")
    book = run_search("book", "--help")
    paper = run_search("paper", "--help")

    assert top.returncode == 0
    assert book.returncode == 0
    assert paper.returncode == 0
    assert "{book,paper}" in top.stdout
    assert "--top" in book.stdout
    assert "--json" in book.stdout
    assert "--shape" not in book.stdout
    assert "--output" not in book.stdout
    assert "--shape" not in paper.stdout
    assert "--output" not in paper.stdout


def test_legacy_shape_and_output_modes_are_removed():
    shape = run_search("paper", "--doi", "10.1/example", "--shape", "single")
    output = run_search("book", "--title", "Example", "--output", "out.json")

    assert shape.returncode == 2
    assert "unrecognized arguments" in shape.stderr
    assert output.returncode == 2
    assert "unrecognized arguments" in output.stderr
