from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RESOLVE = PLUGIN_ROOT / "scripts" / "vault" / "resolve.py"


def run_resolve(project: Path, items: list[dict]) -> dict:
    proc = subprocess.run(
        [sys.executable, str(RESOLVE), "--items-json", json.dumps(items)],
        cwd=project,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def write_book(project: Path, slug: str, isbn: str | None) -> None:
    path = project / "vault" / "books" / slug / "00-overview.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    isbn_line = f"isbn: {isbn}\n" if isbn is not None else ""
    path.write_text(
        f"---\ntype: book\ntitle: A Book\nyear: 2009\n{isbn_line}---\n\n",
        encoding="utf-8",
    )


def write_paper(project: Path, slug: str, doi: str | None) -> None:
    path = project / "vault" / "papers" / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    doi_line = f"doi: {doi}\n" if doi is not None else ""
    path.write_text(
        f"---\ntype: paper\ntitle: A Paper\nyear: 2013\n{doi_line}---\n\n",
        encoding="utf-8",
    )


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    write_book(tmp_path, "fourcade-economists-societies-2009", "9781400833139")
    write_paper(tmp_path, "fourcade-classification-situations-2013", "10.1016/j.aos.2013.11.002")
    return tmp_path


def test_exact_slug_match(vault: Path) -> None:
    (item,) = run_resolve(vault, [{"kind": "book", "slug": "fourcade-economists-societies-2009"}])["resolved"]
    assert item["match"] == "slug"
    assert item["vault_slug"] == "fourcade-economists-societies-2009"
    assert item["path"] == "vault/books/fourcade-economists-societies-2009/00-overview.md"


def test_isbn_matches_across_slug_drift(vault: Path) -> None:
    """The 0.44.3 backlog case: same book, connector-word + year drift in the slug."""
    (item,) = run_resolve(vault, [
        {"kind": "book", "slug": "fourcade-economists-and-societies-2010", "isbn": "978-1-4008-3313-9"},
    ])["resolved"]
    assert item["match"] == "isbn"
    assert item["vault_slug"] == "fourcade-economists-societies-2009"


def test_isbn10_normalises_to_isbn13(tmp_path: Path) -> None:
    write_book(tmp_path, "haraway-staying-2016", "9780822373780")
    (item,) = run_resolve(tmp_path, [{"kind": "book", "slug": "drifted", "isbn": "0822373785"}])["resolved"]
    assert item["match"] == "isbn"
    assert item["vault_slug"] == "haraway-staying-2016"


def test_doi_normalises_prefix_and_case(vault: Path) -> None:
    (item,) = run_resolve(vault, [
        {"kind": "paper", "slug": "drifted-2014", "doi": "https://doi.org/10.1016/J.AOS.2013.11.002"},
    ])["resolved"]
    assert item["match"] == "doi"
    assert item["vault_slug"] == "fourcade-classification-situations-2013"


def test_unknown_identifier_is_not_a_match(vault: Path) -> None:
    out = run_resolve(vault, [
        {"kind": "book", "slug": "nope-2011", "isbn": "9780000000000"},
        {"kind": "paper", "slug": "nope-2099", "doi": "10.9999/nope"},
    ])
    assert [i["vault_slug"] for i in out["resolved"]] == [None, None]
    assert [i["match"] for i in out["resolved"]] == [None, None]


def test_no_identifier_skips_the_vault_scan(vault: Path) -> None:
    """A candidate with neither ISBN nor DOI must not trigger a full-vault index build."""
    out = run_resolve(vault, [{"kind": "book", "slug": "unknown-book-2020"}])
    assert out["resolved"][0]["vault_slug"] is None
    assert out["scanned"] == {}


def test_book_and_paper_indexes_stay_separate(vault: Path) -> None:
    """A book DOI must not resolve against the paper index (and vice versa)."""
    out = run_resolve(vault, [
        {"kind": "book", "slug": "x-2013", "doi": "10.1016/j.aos.2013.11.002"},
        {"kind": "paper", "slug": "y-2009", "isbn": "9781400833139"},
    ])
    assert [i["vault_slug"] for i in out["resolved"]] == [None, None]


def test_bad_kind_is_reported_not_crashed(vault: Path) -> None:
    (item,) = run_resolve(vault, [{"kind": "talk", "slug": "whatever"}])["resolved"]
    assert item["vault_slug"] is None
    assert "error" in item
