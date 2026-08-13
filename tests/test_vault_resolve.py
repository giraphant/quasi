from __future__ import annotations

import json
import plistlib
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


def write_book(project: Path, slug: str, isbn: str | None,
               title: str = "A Book", authors: list[str] | None = None) -> None:
    path = project / "vault" / "books" / slug / "00-overview.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    isbn_line = f"isbn: {isbn}\n" if isbn is not None else ""
    authors_line = "authors:\n" + "".join(f"  - {a}\n" for a in authors) if authors else ""
    path.write_text(
        f'---\ntype: book\ntitle: "{title}"\nyear: 2009\n{isbn_line}{authors_line}---\n\n',
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


def write_author(project: Path, slug: str) -> None:
    path = project / "vault" / "authors" / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\ntype: author\nname: Ada Example\nthemes:\n  - testing\n---\n\n",
        encoding="utf-8",
    )


def write_talk(project: Path, slug: str) -> None:
    path = project / "vault" / "talks" / slug / "talk.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\ntype: talk\ntitle: A Talk\ndate: 2026-07-30\n---\n\n",
        encoding="utf-8",
    )


def write_webarchive(project: Path, slug: str, url: str, title: str = "Saved title") -> Path:
    path = project / "vault" / "webpages" / slug / "snapshot.webarchive"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        plistlib.dumps(
            {
                "WebMainResource": {
                    "WebResourceData": f"<title>{title}</title>".encode("utf-8"),
                    "WebResourceURL": url,
                    "WebResourceMIMEType": "text/html",
                    "WebResourceTextEncodingName": "UTF-8",
                }
            },
            fmt=plistlib.FMT_BINARY,
        )
    )
    return path


def write_webpage(project: Path, slug: str, url: str) -> Path:
    path = project / "vault" / "webpages" / slug / "webpage.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntype: webpage\ntitle: Saved title\nurl: {url}\n"
        "captured_at: 2026-08-13T12:34:56Z\n---\n",
        encoding="utf-8",
    )
    return path


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


def test_title_and_surname_match_when_the_vault_entry_has_no_isbn(tmp_path: Path) -> None:
    """约 9% 的书 vault 里没有 isbn —— 前两级对它们必然 miss,于是每跑一次作者就多一条重复条目。"""
    write_book(tmp_path, "star-boundary-objects-2015", None,
               title="Boundary Objects and Beyond: Working with Leigh Star",
               authors=["Geoffrey C. Bowker", "Stefan Timmermans"])
    (item,) = run_resolve(tmp_path, [{
        "kind": "book", "slug": "bowker-boundary-objects-and-beyond-2016",
        "title": "Boundary Objects and Beyond: Working with Leigh Star",
        "authors": ["Bowker, Geoffrey C."],
    }])["resolved"]
    assert item["match"] == "title"
    assert item["vault_slug"] == "star-boundary-objects-2015"


def test_subtitle_drift_still_matches(tmp_path: Path) -> None:
    """副标题在候选侧和 vault 侧经常一有一无。"""
    write_book(tmp_path, "star-boundary-objects-2015", None,
               title="Boundary Objects and Beyond: Working with Leigh Star",
               authors=["Geoffrey C. Bowker"])
    (item,) = run_resolve(tmp_path, [{
        "kind": "book", "slug": "drifted", "title": "Boundary Objects and Beyond",
        "authors": ["Geoffrey C. Bowker"],
    }])["resolved"]
    assert item["match"] == "title"
    assert item["vault_slug"] == "star-boundary-objects-2015"


def test_ambiguous_title_key_refuses_to_match(tmp_path: Path) -> None:
    """误判会静默丢掉一部作品,漏判只是多一条看得见的重复条目 —— 撞键就拒绝,不猜。"""
    write_book(tmp_path, "bowker-essays-i-2001", None,
               title="Collected Essays: Part I", authors=["Geoffrey C. Bowker"])
    write_book(tmp_path, "bowker-essays-ii-2002", None,
               title="Collected Essays: Part II", authors=["Geoffrey C. Bowker"])
    out = run_resolve(tmp_path, [
        {"kind": "book", "slug": "drifted", "title": "Collected Essays",
         "authors": ["Geoffrey C. Bowker"]},
        {"kind": "book", "slug": "drifted-i", "title": "Collected Essays: Part I",
         "authors": ["Geoffrey C. Bowker"]},
    ])
    assert out["resolved"][0]["vault_slug"] is None          # 撞到两条 → 拒绝
    assert out["resolved"][1]["vault_slug"] == "bowker-essays-i-2001"  # 全标题唯一 → 命中


def test_title_hit_needs_an_author_surname_overlap(tmp_path: Path) -> None:
    write_book(tmp_path, "bowker-sorting-1999", None,
               title="Sorting Things Out", authors=["Geoffrey C. Bowker"])
    out = run_resolve(tmp_path, [
        {"kind": "book", "slug": "a", "title": "Sorting Things Out", "authors": ["Susan Leigh Star"]},
    ])
    assert out["resolved"][0]["vault_slug"] is None
    assert out["scanned"]["book"]["titles"] > 0  # 确实查了索引,是作者对不上才拒的


def test_title_without_authors_skips_the_vault_scan(tmp_path: Path) -> None:
    """只有标题没有作者时匹配条件永不成立,不值得为它扫一遍全库。"""
    write_book(tmp_path, "bowker-sorting-1999", None,
               title="Sorting Things Out", authors=["Geoffrey C. Bowker"])
    out = run_resolve(tmp_path, [{"kind": "book", "slug": "b", "title": "Sorting Things Out"}])
    assert out["resolved"][0]["vault_slug"] is None
    assert out["scanned"] == {}


def test_differing_subtitles_never_match_on_the_stem_alone(tmp_path: Path) -> None:
    """多卷本:vault 只有 Band 1 时,Band 2 必须判成"没做过"——认成同一部会静默丢掉一卷。"""
    write_book(tmp_path, "kittler-musik-mathematik-1-2006", None,
               title="Musik und Mathematik Band 1: Aphrodite", authors=["Friedrich Kittler"])
    (item,) = run_resolve(tmp_path, [{
        "kind": "book", "slug": "kittler-musik-mathematik-2-2009",
        "title": "Musik und Mathematik Band 1: Eros", "authors": ["Friedrich Kittler"],
    }])["resolved"]
    assert item["vault_slug"] is None


def test_identifier_wins_over_title(vault: Path) -> None:
    """ISBN 是硬身份,标题只是兜底 —— 有 ISBN 就不该退到模糊匹配。"""
    (item,) = run_resolve(vault, [{
        "kind": "book", "slug": "drifted", "isbn": "9781400833139",
        "title": "Something Else Entirely", "authors": ["Marion Fourcade"],
    }])["resolved"]
    assert item["match"] == "isbn"
    assert item["vault_slug"] == "fourcade-economists-societies-2009"


def test_bad_kind_is_reported_not_crashed(vault: Path) -> None:
    (item,) = run_resolve(vault, [{"kind": "image", "slug": "whatever"}])["resolved"]
    assert item["vault_slug"] is None
    assert "error" in item


def test_talk_exact_path_is_observed_without_work_indexes(tmp_path: Path) -> None:
    write_talk(tmp_path, "ada-keynote-2026")

    out = run_resolve(
        tmp_path,
        [
            {"kind": "talk", "slug": "ada-keynote-2026"},
            {"kind": "talk", "slug": "missing-talk"},
        ],
    )

    assert out == {
        "resolved": [
            {
                "kind": "talk",
                "slug": "ada-keynote-2026",
                "vault_slug": "ada-keynote-2026",
                "path": "vault/talks/ada-keynote-2026/talk.md",
                "match": "slug",
            },
            {
                "kind": "talk",
                "slug": "missing-talk",
                "vault_slug": None,
                "path": None,
                "match": None,
            },
        ],
        "scanned": {},
    }


def test_author_exact_path_is_observed_without_work_indexes(tmp_path: Path) -> None:
    write_author(tmp_path, "ada-example")

    out = run_resolve(
        tmp_path,
        [
            {"kind": "author", "slug": "ada-example"},
            {"kind": "author", "slug": "missing-author"},
        ],
    )

    assert out == {
        "resolved": [
            {
                "kind": "author",
                "slug": "ada-example",
                "vault_slug": "ada-example",
                "path": "vault/authors/ada-example.md",
                "match": "slug",
            },
            {
                "kind": "author",
                "slug": "missing-author",
                "vault_slug": None,
                "path": None,
                "match": None,
            },
        ],
        "scanned": {},
    }


def test_author_exact_file_symlink_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    path = tmp_path / "vault" / "authors" / "ada-example.md"
    path.parent.mkdir(parents=True)
    path.symlink_to(outside)

    (item,) = run_resolve(
        tmp_path,
        [{"kind": "author", "slug": "ada-example"}],
    )["resolved"]

    assert item["vault_slug"] is None
    assert item["path"] is None
    assert item["match"] is None
    assert "error" in item


def test_author_symlinked_parent_directory_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside-authors"
    outside.mkdir()
    (outside / "ada-example.md").write_text("outside\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "authors").symlink_to(outside, target_is_directory=True)

    (item,) = run_resolve(
        tmp_path,
        [{"kind": "author", "slug": "ada-example"}],
    )["resolved"]

    assert item["vault_slug"] is None
    assert item["path"] is None
    assert item["match"] is None
    assert "error" in item


def test_paper_identifier_index_skips_symlinked_product(tmp_path: Path) -> None:
    outside = tmp_path / "outside-paper.md"
    outside.write_text(
        "---\ntype: paper\ntitle: Outside\nauthors:\n  - Ada Example\n"
        "doi: 10.5555/outside\n---\n",
        encoding="utf-8",
    )
    paper = tmp_path / "vault" / "papers" / "evil.md"
    paper.parent.mkdir(parents=True)
    paper.symlink_to(outside)

    (item,) = run_resolve(
        tmp_path,
        [
            {
                "kind": "paper",
                "slug": "requested-paper",
                "doi": "10.5555/outside",
                "title": "Outside",
                "authors": ["Ada Example"],
            }
        ],
    )["resolved"]

    assert item["vault_slug"] is None
    assert item["path"] is None
    assert item["match"] is None


def test_book_identifier_index_skips_symlinked_book_directory(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-book"
    outside.mkdir()
    (outside / "00-overview.md").write_text(
        "---\ntype: book\ntitle: Outside\nauthors:\n  - Ada Example\n"
        "isbn: 9780000000002\n---\n",
        encoding="utf-8",
    )
    books = tmp_path / "vault" / "books"
    books.mkdir(parents=True)
    (books / "evil").symlink_to(outside, target_is_directory=True)

    (item,) = run_resolve(
        tmp_path,
        [
            {
                "kind": "book",
                "slug": "requested-book",
                "isbn": "9780000000002",
                "title": "Outside",
                "authors": ["Ada Example"],
            }
        ],
    )["resolved"]

    assert item["vault_slug"] is None
    assert item["path"] is None
    assert item["match"] is None


def test_book_identifier_index_skips_symlinked_overview(tmp_path: Path) -> None:
    outside = tmp_path / "outside-overview.md"
    outside.write_text(
        "---\ntype: book\ntitle: Outside\nauthors:\n  - Ada Example\n"
        "isbn: 9780000000002\n---\n",
        encoding="utf-8",
    )
    overview = tmp_path / "vault" / "books" / "evil" / "00-overview.md"
    overview.parent.mkdir(parents=True)
    overview.symlink_to(outside)

    (item,) = run_resolve(
        tmp_path,
        [
            {
                "kind": "book",
                "slug": "requested-book",
                "isbn": "9780000000002",
                "title": "Outside",
                "authors": ["Ada Example"],
            }
        ],
    )["resolved"]

    assert item["vault_slug"] is None
    assert item["path"] is None
    assert item["match"] is None


def test_webpage_resolver_observes_no_url_owner(tmp_path: Path) -> None:
    (row,) = run_resolve(
        tmp_path,
        [{"kind": "webpage", "slug": "proposed-slug", "url": "https://example.org/page"}],
    )["resolved"]

    assert row == {
        "kind": "webpage",
        "slug": "proposed-slug",
        "vault_slug": None,
        "path": None,
        "match": None,
        "suggested_slug": "proposed-slug",
    }


def test_webpage_resolver_uses_canonical_url_owner(tmp_path: Path) -> None:
    write_webpage(tmp_path, "existing-owner", "https://EXAMPLE.org:443/page#fragment")

    (row,) = run_resolve(
        tmp_path,
        [{"kind": "webpage", "slug": "proposed-slug", "url": "https://example.org/page"}],
    )["resolved"]

    assert row == {
        "kind": "webpage",
        "slug": "proposed-slug",
        "vault_slug": "existing-owner",
        "path": "vault/webpages/existing-owner/webpage.md",
        "match": "url",
        "suggested_slug": "existing-owner",
    }


def test_webpage_resolver_uses_snapshot_only_url_owner(tmp_path: Path) -> None:
    write_webarchive(tmp_path, "existing-owner", "https://example.org/page")

    (row,) = run_resolve(
        tmp_path,
        [{"kind": "webpage", "slug": "proposed-slug", "url": "https://example.org/page"}],
    )["resolved"]

    assert row == {
        "kind": "webpage",
        "slug": "proposed-slug",
        "vault_slug": "existing-owner",
        "path": "vault/webpages/existing-owner/snapshot.webarchive",
        "match": "url",
        "suggested_slug": "existing-owner",
    }


def test_webpage_resolver_refuses_duplicate_url_owners(tmp_path: Path) -> None:
    write_webpage(tmp_path, "first-owner", "https://example.org/page")
    write_webarchive(tmp_path, "second-owner", "https://example.org/page")

    (row,) = run_resolve(
        tmp_path,
        [{"kind": "webpage", "slug": "proposed-slug", "url": "https://example.org/page"}],
    )["resolved"]

    assert row["vault_slug"] is None
    assert row["path"] is None
    assert row["suggested_slug"] is None
    assert "error" in row


def test_webpage_resolver_suggests_deterministic_slug_for_different_owner(tmp_path: Path) -> None:
    write_webpage(tmp_path, "proposed-slug", "https://example.org/other")

    (row,) = run_resolve(
        tmp_path,
        [{"kind": "webpage", "slug": "proposed-slug", "url": "https://example.org/page"}],
    )["resolved"]

    assert row["vault_slug"] is None
    assert row["suggested_slug"] == "proposed-slug-2476c9de"
