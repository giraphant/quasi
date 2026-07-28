from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "scripts" / "migrations" / "zotero_bibtex.py"


def load_module():
    spec = importlib.util.spec_from_file_location("zotero_bibtex", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_and_normalise_zotero_entries(tmp_path: Path) -> None:
    bib = tmp_path / "library.bib"
    bib.write_text(
        r'''@article{doe_example_2024,
  title = {An {Example}: Test},
  author = {Doe, Jane and Roe, Richard},
  year = {2024},
  journal = {Test Journal},
  doi = {https://doi.org/10.1000/ABC},
  abstract = {R\&D, 100\%, item\_1, item\#2},
  copyright = {⭐⭐⭐⭐},
  annote = {A personal note},
  file = {Full Text PDF:/tmp/example.pdf:application/pdf;\;snap},
}

@book{society_handbook_2017,
  title = {The Handbook of Things},
  editor = {{Research and Development Society}},
  year = {2017},
  publisher = {Test Press},
  isbn = {978-0-00-000000-2 978-0-00-000001-9},
}
''',
        encoding="utf-8",
    )

    migration = load_module()
    entries = migration.parse_bibtex(bib)

    assert [entry["entry_key"] for entry in entries] == [
        "doe_example_2024",
        "society_handbook_2017",
    ]
    assert entries[0]["bibtex_type"] == "article"
    assert entries[0]["title"] == "An Example: Test"
    assert entries[0]["authors"] == ["Jane Doe", "Richard Roe"]
    assert entries[0]["doi"] == "10.1000/abc"
    assert entries[0]["has_annote"] is True
    assert entries[0]["abstract"] == "R&D, 100%, item_1, item#2"
    assert entries[0]["parse_error"] is None
    assert entries[1]["authors"] == []
    assert entries[1]["editors"] == ["Research and Development Society"]
    assert entries[1]["isbn"] == "9780000000002"
    assert entries[1]["isbns"] == ["9780000000002", "9780000000019"]
    assert migration.display_person("van Dijck, José") == "José van Dijck"
    assert migration.display_person("{Research and Development Society}") == "Research and Development Society"
    assert migration.display_person("Smith, Jr, John") == "John Smith Jr"


def test_one_parse_failure_does_not_block_other_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bib = tmp_path / "partly-broken.bib"
    bib.write_text(
        "@article{good_one, title={One}}\n"
        "@article{broken, title={Broken}}\n"
        "@book{good_two, title={Two}}\n",
        encoding="utf-8",
    )
    migration = load_module()
    original = migration._parse_bibtex_block

    def fail_one(block: str, directives: list[str]):
        if "@article{broken," in block:
            raise ValueError("synthetic parser failure")
        return original(block, directives)

    monkeypatch.setattr(migration, "_parse_bibtex_block", fail_one)
    entries = migration.parse_bibtex(bib)

    assert [entry["entry_key"] for entry in entries] == [
        "broken",
        "good_one",
        "good_two",
    ]
    assert entries[0]["bibtex_type"] == "article"
    assert entries[0]["parse_error"] == "ValueError: synthetic parser failure"
    assert entries[1]["parse_error"] is None
    assert entries[2]["parse_error"] is None


def test_duplicate_entry_keys_are_rejected(tmp_path: Path) -> None:
    bib = tmp_path / "duplicates.bib"
    bib.write_text(
        "@book{same, title={One}}\n@book{same, title={Two}}\n",
        encoding="utf-8",
    )
    migration = load_module()
    with pytest.raises(ValueError, match="duplicate BibTeX entry key: same"):
        migration.parse_bibtex(bib)


def test_rating_mapping_is_exact() -> None:
    migration = load_module()
    assert migration.map_rating("⭐") == 1
    assert migration.map_rating("⭐⭐") == 2
    assert migration.map_rating("⭐⭐⭐") == 3
    assert migration.map_rating("⭐⭐⭐⭐") == 4
    assert migration.map_rating("⭐⭐⭐⭐⭐") == 5
    assert migration.map_rating("💖") == 5
    assert migration.map_rating("Copyright 2024") is None
    assert migration.map_rating("⭐⭐⭐⭐⭐ extra") is None


def test_attachment_parser_and_pdf_choice(tmp_path: Path) -> None:
    original = tmp_path / "Original.pdf"
    translated = tmp_path / "Original_zh-CN_translation.pdf"
    original.write_bytes(b"%PDF-1.7\n" + b"x" * 2048)
    translated.write_bytes(b"%PDF-1.7\n" + b"y" * 2048)
    raw = (
        f"Original:{original}:application/pdf;"
        f"Translation:{translated}:application/pdf;"
        "Snapshot:/missing/page.html:text/html;"
        "Relative:attachments/file.pdf:application/pdf"
    )
    migration = load_module()
    refs = migration.parse_file_refs(raw)
    path, reason = migration.choose_local_pdf(refs)
    assert path == str(original)
    assert reason == "single-original-pdf"
    assert refs[2]["exists"] is False
    assert refs[3]["path"] is None
    assert refs[3]["raw"] == "Relative:attachments/file.pdf:application/pdf"


def test_multiple_original_pdfs_require_review(tmp_path: Path) -> None:
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    first.write_bytes(b"%PDF-1.7\n" + b"a" * 2048)
    second.write_bytes(b"%PDF-1.7\n" + b"b" * 2048)
    migration = load_module()
    refs = migration.parse_file_refs(
        f"A:{first}:application/pdf;B:{second}:application/pdf"
    )
    assert migration.choose_local_pdf(refs) == (None, "multiple-local-pdfs")


def test_work_slug_and_stubs_pass_body_schema() -> None:
    migration = load_module()
    slug = migration.make_work_slug(
        "Code Ethnography and the Materiality of Power",
        ["Fernanda R. Rosa"],
        2022,
    )
    assert slug == "rosa-code-ethnography-and-the-materiality-of-power-2022"
    assert migration.make_work_slug("A Study", ["John Smith Jr"], 2024) == "smith-a-study-2024"
    assert migration.check_body(migration.render_stub("book", "A Book"), migration.BOOK_BODY) == []
    assert migration.check_body(migration.render_stub("paper", "A Paper"), migration.PAPER_BODY) == []


def test_theme_catalog_scans_all_canonical_books_and_papers(tmp_path: Path) -> None:
    migration = load_module()
    journal_paper = tmp_path / "vault" / "journals" / "journal" / "paper.md"
    chapter = tmp_path / "vault" / "books" / "book" / "ch01.md"
    journal_paper.parent.mkdir(parents=True)
    chapter.parent.mkdir(parents=True)
    journal_paper.write_text(
        "---\ntype: paper\ntitle: Journal Paper\nthemes:\n  - scoring\n---\n",
        encoding="utf-8",
    )
    chapter.write_text(
        "---\ntype: chapter\ntitle: Chapter\nthemes:\n  - chapter-only\n---\n",
        encoding="utf-8",
    )

    catalog = migration.collect_theme_catalog(tmp_path)

    assert catalog["scoring"]["examples"] == [{
        "path": "vault/journals/journal/paper.md",
        "title": "Journal Paper",
    }]
    assert "chapter-only" not in catalog


def test_theme_decision_must_use_existing_vocabulary() -> None:
    migration = load_module()
    catalog = {
        "infrastructure-studies": {
            "count": 4,
            "examples": [{"path": "vault/papers/a.md", "title": "A"}],
        },
        "materiality": {
            "count": 8,
            "examples": [{"path": "vault/books/b/00-overview.md", "title": "B"}],
        },
    }
    valid = {
        "entry_key": "x",
        "themes": ["infrastructure-studies", "materiality"],
        "confidence": "high",
        "rationale": "Both are explicit in the abstract.",
    }
    assert migration.validate_theme_decision(valid, catalog) == (
        ["infrastructure-studies", "materiality"],
        None,
    )
    invalid = {**valid, "themes": ["infrastructure-studies", "invented-theme"]}
    assert migration.validate_theme_decision(invalid, catalog)[1] == "unknown-theme"
    catalog["unclassified"] = {"count": 1, "examples": []}
    forbidden = {**valid, "themes": ["materiality", "unclassified"]}
    assert migration.validate_theme_decision(forbidden, catalog)[1] == "forbidden-theme"


def write_existing_paper(
    project: Path,
    slug: str,
    *,
    doi: str,
    rating: int | None = None,
) -> Path:
    migration = load_module()
    path = project / "vault" / "papers" / f"{slug}.md"
    fm = {
        "type": "paper",
        "title": "Existing Paper",
        "authors": ["Jane Doe"],
        "year": 2024,
        "journal": "Test Journal",
        "themes": ["materiality", "infrastructure-studies"],
        "doi": doi,
    }
    if rating is not None:
        fm["rating"] = rating
    migration.write_frontmatter(
        path,
        fm,
        migration.render_stub("paper", "Existing Paper"),
    )
    return path


def test_journal_paper_is_included_in_vault_index(tmp_path: Path) -> None:
    migration = load_module()
    path = tmp_path / "vault" / "journals" / "journal" / "10_1000_x.md"
    migration.write_frontmatter(
        path,
        {
            "type": "paper",
            "title": "Existing Paper",
            "authors": ["Jane Doe"],
            "year": 2024,
            "journal": "Test Journal",
            "themes": ["scoring"],
            "doi": "10.1000/x",
        },
        migration.render_stub("paper", "Existing Paper"),
    )

    index = migration.build_vault_index(tmp_path)

    assert index["by_doi"]["10.1000/x"][0]["path"] == (
        "vault/journals/journal/10_1000_x.md"
    )


def test_duplicate_identifier_is_review(tmp_path: Path) -> None:
    write_existing_paper(tmp_path, "first-2024", doi="10.1000/x")
    write_existing_paper(tmp_path, "second-2024", doi="10.1000/x")
    migration = load_module()
    entry = {
        "entry_key": "x",
        "bibtex_type": "article",
        "title": "Existing Paper",
        "authors": ["Jane Doe"],
        "editors": [],
        "year": 2024,
        "journal": "Test Journal",
        "doi": "10.1000/x",
        "isbn": None,
        "publisher": None,
        "rating": None,
        "abstract": "Material infrastructure.",
        "file_refs": [],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {"materiality": {"count": 1, "examples": []}},
    )
    assert assessed["status"] == "review"
    assert assessed["reason"] == "identifier-matches-multiple-objects"
    assert assessed["match_basis"] == "doi"


def test_new_paper_with_local_pdf_routes_to_process(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"p" * 2048)
    migration = load_module()
    entry = {
        "entry_key": "new",
        "bibtex_type": "article",
        "title": "A New Paper",
        "authors": ["Jane Doe"],
        "editors": [],
        "year": 2024,
        "journal": "Test Journal",
        "doi": "10.1000/new",
        "isbn": None,
        "publisher": None,
        "rating": 5,
        "abstract": "An abstract.",
        "file_refs": [
            {"path": str(pdf), "mime": "application/pdf", "exists": True}
        ],
        "has_annote": True,
        "has_note": False,
        "has_keywords": True,
    }
    catalog = {
        "materiality": {"count": 2, "examples": []},
        "infrastructure-studies": {"count": 2, "examples": []},
    }
    decisions = {
        "new": {
            "entry_key": "new",
            "themes": ["materiality", "infrastructure-studies"],
            "confidence": "high",
            "rationale": "Explicit in title and abstract.",
        }
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        decisions,
        catalog,
    )
    assert assessed["status"] == "safe-create"
    assert assessed["route"] == "process-local-pdf"
    assert assessed["preferred_pdf"] == str(pdf)
    assert assessed["canonical"]["themes"] == [
        "materiality",
        "infrastructure-studies",
    ]


def test_deferred_type_still_records_preferred_local_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "chapter.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"p" * 2048)
    migration = load_module()
    entry = {
        "entry_key": "chapter",
        "bibtex_type": "incollection",
        "file_refs": [
            {"path": str(pdf), "mime": "application/pdf", "exists": True},
            {
                "raw": "Relative:file.pdf:application/pdf",
                "path": None,
                "mime": "application/pdf",
                "exists": False,
            },
        ],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {},
    )
    assert assessed["status"] == "deferred-type"
    assert assessed["preferred_pdf"] == str(pdf)
    assert assessed["preferred_pdf_reason"] == "single-local-pdf"
    assert assessed["attachment_review"] == [
        {
            "raw": "Relative:file.pdf:application/pdf",
            "reason": "unparsed-attachment-path",
        }
    ]


def test_new_paper_without_pdf_needs_valid_theme_decision(tmp_path: Path) -> None:
    migration = load_module()
    entry = {
        "entry_key": "new",
        "bibtex_type": "article",
        "title": "A New Paper",
        "authors": ["Jane Doe"],
        "editors": [],
        "year": 2024,
        "journal": "Test Journal",
        "doi": "10.1000/new",
        "isbn": None,
        "publisher": None,
        "rating": None,
        "abstract": "Material infrastructure.",
        "file_refs": [],
        "has_annote": False,
        "has_note": False,
        "has_keywords": True,
    }
    catalog = {
        "materiality": {"count": 2, "examples": []},
        "infrastructure-studies": {"count": 2, "examples": []},
    }
    pending = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        catalog,
    )
    assert pending["status"] == "review"
    assert pending["reason"] == "theme-decision-missing"
    decided = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {
            "new": {
                "entry_key": "new",
                "themes": ["materiality", "infrastructure-studies"],
                "confidence": "high",
                "rationale": "Explicit in abstract.",
            }
        },
        catalog,
    )
    assert decided["status"] == "safe-create"
    assert decided["route"] == "metadata-only"


def test_safe_enrich_never_routes_to_process_local_pdf(tmp_path: Path) -> None:
    path = write_existing_paper(tmp_path, "existing-2024", doi="10.1000/x")
    migration = load_module()
    fm = migration.read_frontmatter(path).frontmatter
    assert fm is not None
    fm.pop("rating", None)
    migration.write_frontmatter(path, fm, migration.read_frontmatter(path).body)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"p" * 2048)
    entry = {
        "entry_key": "x",
        "bibtex_type": "article",
        "title": "Existing Paper",
        "authors": ["Jane Doe"],
        "editors": [],
        "year": 2024,
        "journal": "Test Journal",
        "doi": "10.1000/x",
        "isbn": None,
        "publisher": None,
        "rating": 5,
        "abstract": None,
        "file_refs": [
            {"path": str(pdf), "mime": "application/pdf", "exists": True}
        ],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {},
    )
    assert assessed["status"] == "safe-enrich"
    assert assessed["route"] == "metadata-only"
    assert assessed["preferred_pdf"] == str(pdf)
    assert assessed["preferred_pdf_reason"] == "single-local-pdf"


def test_different_subtitles_do_not_match_on_two_short_title_keys(
    tmp_path: Path,
) -> None:
    path = write_existing_paper(
        tmp_path,
        "volume-eros-2024",
        doi="10.1000/existing",
    )
    migration = load_module()
    doc = migration.read_frontmatter(path)
    assert doc.frontmatter is not None
    doc.frontmatter["title"] = "Volume One: Eros"
    migration.write_frontmatter(path, doc.frontmatter, doc.body)
    entry = {
        "entry_key": "aphrodite",
        "bibtex_type": "article",
        "title": "Volume One: Aphrodite",
        "authors": ["Jane Doe"],
        "editors": [],
        "year": 2024,
        "journal": "Journal",
        "doi": None,
        "isbn": None,
        "publisher": None,
        "rating": None,
        "abstract": "Material infrastructure.",
        "file_refs": [],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }
    catalog = {
        "materiality": {"count": 1, "examples": []},
        "infrastructure-studies": {"count": 1, "examples": []},
    }
    decisions = {
        "aphrodite": {
            "entry_key": "aphrodite",
            "themes": ["materiality", "infrastructure-studies"],
            "confidence": "high",
            "rationale": "Explicit in abstract.",
        }
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        decisions,
        catalog,
    )
    assert assessed["status"] == "safe-create"
    assert assessed["match"] is None
    assert assessed["match_basis"] is None


def test_title_author_match_with_different_given_name_is_review(
    tmp_path: Path,
) -> None:
    write_existing_paper(tmp_path, "existing-2024", doi="10.1000/existing")
    migration = load_module()
    entry = {
        "entry_key": "other-doe",
        "bibtex_type": "article",
        "title": "Existing Paper",
        "authors": ["John Doe"],
        "editors": [],
        "year": 2024,
        "journal": "Test Journal",
        "doi": None,
        "isbn": None,
        "isbns": [],
        "publisher": None,
        "rating": None,
        "abstract": None,
        "file_refs": [],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {},
    )
    assert assessed["status"] == "review"
    assert assessed["match_basis"] == "title-author"
    assert assessed["conflicts"] == ["authors"]


def test_identifier_match_with_different_subtitle_is_review(
    tmp_path: Path,
) -> None:
    path = write_existing_paper(
        tmp_path,
        "volume-eros-2024",
        doi="10.1000/same",
    )
    migration = load_module()
    doc = migration.read_frontmatter(path)
    assert doc.frontmatter is not None
    doc.frontmatter["title"] = "Volume One: Eros"
    migration.write_frontmatter(path, doc.frontmatter, doc.body)
    entry = {
        "entry_key": "aphrodite",
        "bibtex_type": "article",
        "title": "Volume One: Aphrodite",
        "authors": ["Jane Doe"],
        "editors": [],
        "year": 2024,
        "journal": "Test Journal",
        "doi": "10.1000/same",
        "isbn": None,
        "isbns": [],
        "publisher": None,
        "rating": None,
        "abstract": None,
        "file_refs": [],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {},
    )
    assert assessed["status"] == "review"
    assert assessed["reason"] == "field-conflict"
    assert assessed["conflicts"] == ["title"]


def test_book_matches_any_source_isbn_without_false_conflict(
    tmp_path: Path,
) -> None:
    migration = load_module()
    path = tmp_path / "vault" / "books" / "doe-book-2024" / "00-overview.md"
    migration.write_frontmatter(
        path,
        {
            "type": "book",
            "title": "Book",
            "authors": ["Jane Doe"],
            "year": 2024,
            "publisher": "Press",
            "isbn": "9780000000019",
            "category": "monograph",
            "themes": [],
        },
        migration.render_stub("book", "Book"),
    )
    entry = {
        "entry_key": "book",
        "bibtex_type": "book",
        "title": "Book",
        "authors": ["Jane Doe"],
        "editors": [],
        "year": 2024,
        "publisher": "Press",
        "isbn": "9780000000002",
        "isbns": ["9780000000002", "9780000000019"],
        "doi": None,
        "journal": None,
        "rating": None,
        "abstract": None,
        "file_refs": [],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {},
    )
    assert assessed["status"] == "exact-existing"
    assert assessed["match_basis"] == "isbn"
    assert assessed.get("conflicts") is None


def test_missing_required_metadata_is_invalid_source(tmp_path: Path) -> None:
    migration = load_module()
    entry = {
        "entry_key": "broken",
        "bibtex_type": "article",
        "title": "Broken",
        "authors": [],
        "editors": [],
        "year": 2024,
        "journal": None,
        "doi": None,
        "isbn": None,
        "publisher": None,
        "rating": None,
        "abstract": None,
        "file_refs": [],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
    }
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {},
    )
    assert assessed["status"] == "invalid-source"
    assert assessed["reason"] == "missing-paper-authors-or-journal"


def test_parse_error_is_invalid_source(tmp_path: Path) -> None:
    migration = load_module()
    entry = migration._invalid_parse_entry(
        "@article{broken, title={Broken}}",
        1,
        ValueError("bad entry"),
    )
    assessed = migration.assess_entry(
        entry,
        migration.build_vault_index(tmp_path),
        {},
        {},
    )
    assert assessed["status"] == "invalid-source"
    assert assessed["reason"] == "bibtex-parse-error"
    assert assessed["parse_error"] == "ValueError: bad entry"


def test_book_authors_take_precedence_over_editors() -> None:
    migration = load_module()
    kind, candidate, error = migration.map_candidate(
        {
            "entry_key": "book",
            "bibtex_type": "book",
            "title": "A Book",
            "authors": ["Jane Doe"],
            "editors": ["Richard Roe"],
            "year": 2024,
            "publisher": "Press",
            "isbn": None,
            "doi": None,
            "rating": None,
        },
        None,
    )
    assert error is None
    assert kind == "book"
    assert candidate["authors"] == ["Jane Doe"]
    assert candidate["category"] == "other"


def test_batch_one_contains_25_articles_and_25_books() -> None:
    migration = load_module()
    rows = [
        {"entry_key": f"a-{i:02d}", "bibtex_type": "article"}
        for i in range(30)
    ] + [
        {"entry_key": f"b-{i:02d}", "bibtex_type": "book"}
        for i in range(30)
    ]
    assigned = migration.assign_batches(rows)
    pilot = [row for row in assigned if row["batch"] == 1]
    assert sum(row["bibtex_type"] == "article" for row in pilot) == 25
    assert sum(row["bibtex_type"] == "book" for row in pilot) == 25


def test_source_entries_with_same_identifier_are_both_review() -> None:
    migration = load_module()
    rows = [
        {
            "entry_key": key,
            "bibtex_type": "article",
            "status": "safe-create",
            "route": "metadata-only",
            "target_path": f"vault/papers/{key}.md",
            "source_fields": {
                "doi": "10.1000/same",
                "isbn": None,
                "isbns": [],
            },
        }
        for key in ("first", "second")
    ]
    collided = migration.mark_source_collisions(rows)
    assert [row["status"] for row in collided] == ["review", "review"]
    assert all(row["reason"] == "source-entry-collision" for row in collided)
    assert all(row["collision_basis"] == ["doi"] for row in collided)
