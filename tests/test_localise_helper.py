from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
LOCALISE = PLUGIN_ROOT / "scripts" / "localise" / "localise.py"


def run_localise(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LOCALISE), *args],
        cwd=project,
        text=True,
        capture_output=True,
        timeout=10,
    )


def write_overview(project: Path, slug: str, isbn: str | None = "978-0-8223-7378-0") -> Path:
    path = project / "vault" / "books" / slug / "00-overview.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    isbn_line = f"isbn: {isbn}\n" if isbn is not None else ""
    path.write_text(
        "---\n"
        "type: book\n"
        "title: Staying with the Trouble\n"
        "authors:\n"
        "  - Donna Haraway\n"
        "year: 2016\n"
        "publisher: Duke University Press\n"
        f"{isbn_line}"
        "category: monograph\n"
        "---\n"
        "\n",
        encoding="utf-8",
    )
    return path


def test_scan_reports_isbn_keyed_pending_books(tmp_path: Path):
    project = tmp_path / "project"
    write_overview(project, "haraway-staying-with-the-trouble-2016")
    write_overview(project, "missing-isbn-2024", isbn=None)

    result = run_localise(project, "scan", "--path", "vault/books", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["total"] == 2
    assert payload["with_isbn"] == 1
    assert payload["missing_isbn"] == 1
    assert payload["pending"] == 1
    assert payload["books"][0]["isbn"] == "9780822373780"


def test_write_merges_search_localisations_by_isbn(tmp_path: Path):
    project = tmp_path / "project"
    overview = write_overview(project, "haraway-staying-with-the-trouble-2016")
    search_result = project / "search.json"
    search_result.write_text(
        json.dumps({
            "kind": "book",
            "localisations": {
                "zh": {
                    "status": "found",
                    "candidates": [
                        {
                            "douban_id": "1234567",
                            "title": "与麻烦共处",
                            "author": "唐娜·哈拉维",
                            "translator": "译者甲",
                            "publisher": "某出版社",
                            "year": 2024,
                            "isbn": "978-7-0000-0000-1",
                            "original_title": "Staying with the Trouble",
                            "ratings_count": 100,
                            "douban_url": "https://book.douban.com/subject/1234567/",
                        }
                    ],
                }
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    result = run_localise(
        project,
        "write",
        "--book-path",
        str(overview),
        "--search-result-file",
        str(search_result),
        "--checked-at",
        "2026-05-18",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["isbn"] == "9780822373780"
    assert payload["status"] == "found"
    cache = json.loads((project / ".quasi" / "localise" / "cndouban.json").read_text(encoding="utf-8"))
    record = cache["by_isbn"]["9780822373780"]
    assert record["cndouban_ids"] == ["1234567"]
    assert record["books"][0]["slug"] == "haraway-staying-with-the-trouble-2016"
    assert cache["by_douban_id"]["1234567"]["title"] == "与麻烦共处"
