from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SEARCH = PLUGIN_ROOT / "scripts" / "search" / "search.py"
SEARCH_DIR = PLUGIN_ROOT / "scripts" / "search"


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


def load_search_module():
    sys.path.insert(0, str(SEARCH_DIR))
    spec = importlib.util.spec_from_file_location("quasi_search_for_tests", SEARCH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_book_localisation_sidecar_uses_douban_even_when_source_is_limited():
    search = load_search_module()
    calls: list[tuple[str, object]] = []

    def fake_adapter(source_id, query):
        calls.append((source_id, query))
        if source_id == "openlibrary":
            return search.AdapterResult(source=source_id, success=True, entries=[])
        if source_id == "douban_cn":
            return search.AdapterResult(
                source=source_id,
                success=True,
                entries=[{
                    "title": "与麻烦同在",
                    "authors": ["[美] 唐娜·哈拉维"],
                    "translators": ["赵文"],
                    "publisher": "华东师范大学出版社",
                    "year": 2024,
                    "isbn_13": "9787576048971",
                    "source_ids": {"douban_cn": "36500000"},
                    "language": "zh",
                }],
            )
        raise AssertionError(source_id)

    with patch.object(search, "_adapter_search_book", side_effect=fake_adapter):
        resp = search.book_search(
            search.BookQuery(title="Staying with the Trouble", author="Donna Haraway"),
            sources=["openlibrary"],
        )

    assert [source for source, _ in calls] == ["openlibrary", "douban_cn"]
    assert resp.diagnostics["sources_attempted"] == ["openlibrary"]
    assert resp.localisations["zh"]["status"] == "found"
    assert resp.localisations["zh"]["candidates"][0]["douban_id"] == "36500000"
