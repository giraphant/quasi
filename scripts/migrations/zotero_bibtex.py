#!/usr/bin/env python3
"""One-shot Zotero BibTeX inventory and BTS migration."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.customization import getnames
from pydantic import ValidationError

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN_ROOT))

from core import atomic_write_text, read_frontmatter, write_frontmatter, write_json  # noqa: E402
from scripts.citation.slug import parse_author_token  # noqa: E402
from scripts.localise.localise import normalise_isbn  # noqa: E402
from scripts.schemas import __version__ as SCHEMA_VERSION, canonical_type  # noqa: E402
from scripts.schemas.body import BOOK_BODY, PAPER_BODY  # noqa: E402
from scripts.schemas.book import BookSchema  # noqa: E402
from scripts.schemas.paper import PaperSchema  # noqa: E402
from scripts.typecheck.typecheck import check_body, check_file  # noqa: E402
from scripts.vault.resolve import normalise_doi, surnames, title_keys  # noqa: E402


SUPPORTED_TYPES = {"article", "book"}


def clean_text(raw: Any) -> str | None:
    if raw in (None, "", [], {}):
        return None
    text = re.sub(r"\s+", " ", str(raw)).strip()
    # ponytail: limited unescape of Zotero's 7 common LaTeX punctuation escapes only; not a general LaTeX parser
    text = re.sub(r"\\([#&%$_{}])", r"\1", text)
    text = text.replace("{", "").replace("}", "").strip()
    return text or None


def display_person(raw: Any) -> str | None:
    if raw in (None, "", [], {}):
        return None
    text = str(raw).strip()
    if text.startswith("{") and text.endswith("}"):
        return clean_text(text)
    comma_parts = [part.strip() for part in text.split(",")]
    if len(comma_parts) >= 3:
        family, suffix = comma_parts[:2]
        given = " ".join(comma_parts[2:])
        return clean_text(" ".join(part for part in (given, family, suffix) if part))
    tidy = getnames([text])
    if not tidy:
        return None
    family, separator, given = tidy[0].partition(",")
    return clean_text(f"{given.strip()} {family.strip()}" if separator else family)


def _split_people_text(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for token in re.split(r"(\{|\}|\s+and\s+)", text):
        if token == "{":
            depth += 1
            current.append(token)
        elif token == "}":
            depth = max(0, depth - 1)
            current.append(token)
        elif depth == 0 and re.fullmatch(r"\s+and\s+", token):
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(token)
    parts.append("".join(current).strip())
    return [part for part in parts if part]


def split_people(raw: Any) -> list[str]:
    if raw in (None, "", [], {}):
        return []
    values = raw if isinstance(raw, list) else _split_people_text(str(raw).strip())
    return [name for value in values if (name := display_person(value))]


def _split_bibtex_blocks(text: str) -> list[str]:
    starts = list(re.finditer(r"(?m)^[ \t]*@[A-Za-z]+\s*[({]", text))
    return [
        text[match.start():(starts[index + 1].start() if index + 1 < len(starts) else len(text))].strip()
        for index, match in enumerate(starts)
    ]


def _block_identity(block: str, index: int) -> tuple[str, str]:
    match = re.match(
        r"\s*@(?P<type>[A-Za-z]+)\s*[({]\s*(?P<key>[^,\s}\)]+)",
        block,
    )
    if not match:
        return "unknown", f"__parse_error_{index:06d}"
    return match.group("type").lower(), match.group("key")


def _parse_bibtex_block(block: str, directives: list[str]) -> dict[str, Any]:
    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    database = bibtexparser.loads("\n".join([*directives, block]), parser=parser)
    if len(database.entries) != 1:
        raise ValueError(f"expected one entry, found {len(database.entries)}")
    return database.entries[0]


def normalise_isbns(raw: Any) -> list[str]:
    if raw in (None, "", [], {}):
        return []
    if isinstance(raw, list):
        values = [isbn for item in raw for isbn in normalise_isbns(item)]
    else:
        direct = normalise_isbn(raw)
        if direct:
            values = [direct]
        else:
            pattern = re.compile(
                r"(?<!\d)(?:97[89](?:[-\s]?\d){10}|\d(?:[-\s]?\d){8}[-\s]?[\dXx])(?![\dXx])"
            )
            values = [
                isbn
                for match in pattern.finditer(str(raw))
                if (isbn := normalise_isbn(match.group(0)))
            ]
    return list(dict.fromkeys(values))


RATING_MAP = {"⭐": 1, "⭐⭐": 2, "⭐⭐⭐": 3, "⭐⭐⭐⭐": 4, "⭐⭐⭐⭐⭐": 5, "💖": 5}
TRANSLATION_MARKERS = ("zh-cn", "translation", "_dual", "-dual")
THEME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def map_rating(raw: Any) -> int | None:
    return RATING_MAP.get(clean_text(raw) or "")


def parse_file_refs(raw: str | None) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if not raw:
        return refs
    for segment in raw.split(";"):
        value = segment.strip()
        if not value:
            continue
        payload, mime = (value.rsplit(":", 1) if ":" in value else (value, None))
        marker = payload.find(":/")
        if marker < 0:
            refs.append({"raw": value, "label": None, "path": None, "mime": mime, "exists": False})
            continue
        label = payload[:marker] or None
        path = "/" + payload[marker + 2 :]
        refs.append({
            "raw": value,
            "label": label,
            "path": path,
            "mime": mime,
            "exists": Path(path).is_file(),
        })
    return refs


def is_readable_pdf(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 1024:
            return False
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def choose_local_pdf(refs: list[dict[str, Any]]) -> tuple[str | None, str]:
    pdfs = [
        ref for ref in refs
        if ref.get("mime") == "application/pdf"
        and ref.get("path")
        and is_readable_pdf(Path(str(ref["path"])))
    ]
    if not pdfs:
        return None, "no-readable-local-pdf"
    if len(pdfs) == 1:
        return str(pdfs[0]["path"]), "single-local-pdf"
    originals = [
        ref for ref in pdfs
        if not any(marker in Path(str(ref["path"])).name.lower() for marker in TRANSLATION_MARKERS)
    ]
    if len(originals) == 1:
        return str(originals[0]["path"]), "single-original-pdf"
    return None, "multiple-local-pdfs"


def _ascii_slug_tokens(text: str) -> list[str]:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", ascii_text)


def make_work_slug(title: str, authors: list[str], year: int) -> str:
    if not authors:
        raise ValueError("cannot make slug without authors")
    first = authors[0]
    parts = first.replace(",", " ").split()
    suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}
    surname = parts[-2] if len(parts) >= 2 and parts[-1].lower() in suffixes else parts[-1]
    author_slug = parse_author_token(surname).slug
    title_slug = "-".join(_ascii_slug_tokens(title)[:8])
    if not author_slug or not title_slug:
        raise ValueError("cannot make ASCII work slug")
    return f"{author_slug}-{title_slug}-{year}"


def render_stub(kind: str, title: str) -> str:
    marker = "待分析（由 Zotero 迁移创建）。"
    table = "| 概念 | 说明 |\n|---|---|\n| 待分析 | 待分析（由 Zotero 迁移创建）。 |"
    if kind == "book":
        return (
            f"\n# {title}\n\n## 核心论点\n\n{marker}\n\n"
            f"## 章节逻辑\n\n{marker}\n\n## 关键概念\n\n{table}\n\n"
            f"## 理论贡献\n\n{marker}\n\n## 精读章节\n\n1. {marker}\n"
        )
    if kind == "paper":
        return (
            f"\n# {title}\n\n## 核心论点\n\n{marker}\n\n"
            f"## 理论框架\n\n{marker}\n\n## 分节摘要\n\n### 待分析\n\n{marker}\n\n"
            f"## 关键概念\n\n{table}\n\n## 核心引用\n\n1. {marker}\n"
        )
    raise ValueError(f"unsupported stub kind: {kind}")


def collect_theme_catalog(project_root: Path) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for path in sorted((project_root / "vault").rglob("*.md")):
        fm = read_frontmatter(path).frontmatter or {}
        if canonical_type(fm.get("type")) not in {"paper", "book"}:
            continue
        title = clean_text(fm.get("title"))
        for theme in fm.get("themes") or []:
            if not isinstance(theme, str) or not THEME_RE.fullmatch(theme):
                continue
            item = catalog.setdefault(theme, {"count": 0, "examples": []})
            item["count"] += 1
            example = {"path": str(path.relative_to(project_root)), "title": title}
            if example not in item["examples"] and len(item["examples"]) < 5:
                item["examples"].append(example)
    return dict(sorted(catalog.items()))


def validate_theme_decision(
    decision: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
) -> tuple[list[str] | None, str | None]:
    required = {"entry_key", "themes", "confidence", "rationale"}
    allowed = required | {"validation_error"}
    if not required <= set(decision) or set(decision) - allowed:
        return None, "invalid-decision-shape"
    if decision.get("validation_error"):
        return None, str(decision["validation_error"])
    themes = decision.get("themes")
    if decision.get("confidence") != "high":
        return None, "low-confidence"
    if not isinstance(themes, list) or not 2 <= len(themes) <= 6:
        return None, "theme-count"
    if any(not isinstance(theme, str) for theme in themes):
        return None, "invalid-theme-value"
    if len(set(themes)) != len(themes):
        return None, "duplicate-theme"
    if any(theme not in catalog for theme in themes):
        return None, "unknown-theme"
    if "unclassified" in themes:
        return None, "forbidden-theme"
    if not clean_text(decision.get("rationale")):
        return None, "missing-rationale"
    return themes, None


def map_candidate(
    entry: dict[str, Any],
    themes: list[str] | None,
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    if entry["bibtex_type"] not in SUPPORTED_TYPES:
        return None, None, "deferred-type"
    title = entry.get("title")
    year = entry.get("year")
    if not title or not isinstance(year, int) or not 1500 <= year <= 2030:
        return None, None, "missing-title-or-year"

    if entry["bibtex_type"] == "article":
        if not entry["authors"] or not entry.get("journal"):
            return None, None, "missing-paper-authors-or-journal"
        if themes is None:
            return "paper", None, "theme-decision-missing"
        candidate = {
            "type": "paper",
            "title": title,
            "authors": entry["authors"],
            "year": year,
            "journal": entry["journal"],
            "themes": themes,
        }
        if entry.get("doi"):
            candidate["doi"] = entry["doi"]
        if entry.get("rating"):
            candidate["rating"] = entry["rating"]
        PaperSchema.model_validate(candidate)
        return "paper", candidate, None

    authors = entry["authors"] or entry["editors"]
    if not authors or not entry.get("publisher"):
        return None, None, "missing-book-authors-or-publisher"
    lower_title = title.lower()
    if "handbook" in lower_title:
        category = "handbook"
    elif not entry["authors"] and entry["editors"]:
        category = "edited-volume"
    else:
        category = "other"
    candidate = {
        "type": "book",
        "title": title,
        "authors": authors,
        "year": year,
        "publisher": entry["publisher"],
        "category": category,
    }
    if entry.get("isbn"):
        candidate["isbn"] = entry["isbn"]
    if entry.get("doi"):
        candidate["doi"] = entry["doi"]
    if entry.get("rating"):
        candidate["rating"] = entry["rating"]
    BookSchema.model_validate(candidate)
    return "book", candidate, None


def build_vault_index(project_root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in sorted((project_root / "vault").rglob("*.md")):
        doc = read_frontmatter(path)
        fm = doc.frontmatter
        if not fm:
            continue
        kind = canonical_type(fm.get("type"))
        if kind not in {"paper", "book"}:
            continue
        slug = path.stem if kind == "paper" else path.parent.name
        records.append({
            "kind": kind,
            "slug": slug,
            "path": str(path.relative_to(project_root)),
            "frontmatter": fm,
        })

    by_doi: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_isbn: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_title: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        fm = record["frontmatter"]
        if doi := normalise_doi(fm.get("doi")):
            by_doi[doi].append(record)
        if isbn := normalise_isbn(fm.get("isbn")):
            by_isbn[isbn].append(record)
        for key_index, key in enumerate(title_keys(fm.get("title"))):
            by_title[key].append({"record": record, "short": key_index > 0})
    return {
        "project_root": str(project_root.resolve()),
        "records": records,
        "by_doi": by_doi,
        "by_isbn": by_isbn,
        "by_title": by_title,
    }


def _record_candidates(
    entry: dict[str, Any],
    index: dict[str, Any],
) -> tuple[list[dict], str | None, str | None]:
    identifier_hits: dict[str, dict] = {}
    matched_by: list[str] = []
    doi_hits = index["by_doi"].get(entry.get("doi"), []) if entry.get("doi") else []
    isbn_hits_by_path: dict[str, dict] = {}
    for isbn in entry.get("isbns") or [entry.get("isbn")]:
        if not isbn:
            continue
        for record in index["by_isbn"].get(isbn, []):
            isbn_hits_by_path[record["path"]] = record
    isbn_hits = list(isbn_hits_by_path.values())
    if doi_hits:
        matched_by.append("doi")
        for record in doi_hits:
            identifier_hits[record["path"]] = record
    if isbn_hits:
        matched_by.append("isbn")
        for record in isbn_hits:
            identifier_hits[record["path"]] = record
    basis = "+".join(matched_by) or None
    if len(identifier_hits) > 1:
        return (
            list(identifier_hits.values()),
            "identifier-matches-multiple-objects",
            basis,
        )
    if len(identifier_hits) == 1:
        return list(identifier_hits.values()), None, basis

    who = surnames(entry.get("authors") or entry.get("editors"))
    title_hits: dict[str, dict] = {}
    for key_index, key in enumerate(title_keys(entry.get("title"))):
        for hit in index["by_title"].get(key, []):
            record = hit["record"]
            fm = record["frontmatter"]
            both_keys_are_short = key_index > 0 and hit["short"]
            if who & surnames(fm.get("authors")) and not both_keys_are_short:
                title_hits[record["path"]] = record
    if len(title_hits) > 1:
        return (
            list(title_hits.values()),
            "title-author-ambiguous",
            "title-author",
        )
    return (
        list(title_hits.values()),
        None,
        "title-author" if title_hits else None,
    )


def _titles_compatible(existing: Any, candidate: Any) -> bool:
    existing_keys = title_keys(existing)
    candidate_keys = title_keys(candidate)
    if not existing_keys or not candidate_keys:
        return False
    if existing_keys[0] == candidate_keys[0]:
        return True
    if len(existing_keys) == 1 and existing_keys[0] in candidate_keys:
        return True
    if len(candidate_keys) == 1 and candidate_keys[0] in existing_keys:
        return True
    return False


def _conflicting_fields(
    existing: dict[str, Any],
    candidate: dict[str, Any],
) -> list[str]:
    conflicts: list[str] = []
    for field in ("year", "journal", "publisher", "rating"):
        if (
            field in existing
            and field in candidate
            and existing[field] not in (None, "")
            and existing[field] != candidate[field]
        ):
            conflicts.append(field)
    if (
        existing.get("category")
        and candidate.get("category") not in (None, "other")
        and existing["category"] != candidate["category"]
    ):
        conflicts.append("category")
    if (
        existing.get("doi")
        and candidate.get("doi")
        and normalise_doi(existing["doi"]) != normalise_doi(candidate["doi"])
    ):
        conflicts.append("doi")
    if (
        existing.get("isbn")
        and candidate.get("isbn")
        and normalise_isbn(existing["isbn"]) != normalise_isbn(candidate["isbn"])
    ):
        conflicts.append("isbn")
    if existing.get("title") and candidate.get("title"):
        if not _titles_compatible(existing["title"], candidate["title"]):
            conflicts.append("title")
    if existing.get("authors") and candidate.get("authors"):
        existing_authors = [
            re.sub(r"\W+", " ", str(name), flags=re.UNICODE).strip().casefold()
            for name in existing["authors"]
        ]
        candidate_authors = [
            re.sub(r"\W+", " ", str(name), flags=re.UNICODE).strip().casefold()
            for name in candidate["authors"]
        ]
        if existing_authors != candidate_authors:
            conflicts.append("authors")
    return sorted(set(conflicts))


def _missing_fields(
    existing: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    return {
        field: value
        for field, value in candidate.items()
        if field not in existing or existing[field] in (None, "", [])
    }


def assess_entry(
    entry: dict[str, Any],
    index: dict[str, Any],
    theme_decisions: dict[str, dict[str, Any]],
    catalog: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    base = {
        "entry_key": entry["entry_key"],
        "bibtex_type": entry["bibtex_type"],
        "source_fields": {
            field: entry.get(field)
            for field in (
                "title",
                "authors",
                "editors",
                "year",
                "journal",
                "publisher",
                "doi",
                "isbn",
                "isbns",
                "abstract",
            )
        },
        "copyright_raw": entry.get("copyright_raw"),
        "rating": entry.get("rating"),
        "has_annote": entry.get("has_annote", False),
        "has_note": entry.get("has_note", False),
        "has_keywords": entry.get("has_keywords", False),
        "file_raw": entry.get("file_raw"),
        "file_refs": entry.get("file_refs", []),
        "attachment_review": [
            {"raw": ref.get("raw"), "reason": "unparsed-attachment-path"}
            for ref in entry.get("file_refs", [])
            if not ref.get("path")
        ],
        "status": None,
        "route": "manual-review",
        "reason": None,
        "target_path": None,
        "preferred_pdf": None,
        "preferred_pdf_reason": None,
        "theme_decision": theme_decisions.get(entry["entry_key"]),
        "canonical": None,
        "match": None,
        "match_basis": None,
        "parse_error": entry.get("parse_error"),
        "batch": None,
    }
    if entry.get("parse_error"):
        return {
            **base,
            "status": "invalid-source",
            "reason": "bibtex-parse-error",
        }

    preferred_pdf, pdf_reason = choose_local_pdf(entry.get("file_refs", []))
    base["preferred_pdf"] = preferred_pdf
    base["preferred_pdf_reason"] = pdf_reason
    if entry["bibtex_type"] not in SUPPORTED_TYPES:
        return {
            **base,
            "status": "deferred-type",
            "reason": "unsupported-first-round-type",
        }

    hits, match_error, match_basis = _record_candidates(entry, index)
    base["match_basis"] = match_basis
    expected_kind = "paper" if entry["bibtex_type"] == "article" else "book"
    if match_error:
        return {
            **base,
            "status": "review",
            "reason": match_error,
            "match": [record["path"] for record in hits],
        }

    existing = hits[0] if hits else None
    if existing and existing["kind"] != expected_kind:
        return {
            **base,
            "status": "review",
            "reason": "matched-wrong-kind",
            "match": existing["path"],
        }
    decision = theme_decisions.get(entry["entry_key"])
    themes: list[str] | None = None
    if expected_kind == "paper":
        if existing and existing["frontmatter"].get("themes"):
            themes = list(existing["frontmatter"]["themes"])
        elif decision:
            themes, theme_error = validate_theme_decision(decision, catalog)
            if theme_error:
                return {
                    **base,
                    "status": "review",
                    "reason": theme_error,
                    "preferred_pdf": preferred_pdf,
                    "theme_decision": decision,
                }

    try:
        kind, candidate, map_error = map_candidate(entry, themes)
    except ValidationError:
        return {
            **base,
            "status": "invalid-source",
            "reason": "schema-validation-error",
        }
    if map_error:
        invalid_reasons = {
            "missing-title-or-year",
            "missing-paper-authors-or-journal",
            "missing-book-authors-or-publisher",
        }
        status = "invalid-source" if map_error in invalid_reasons else "review"
        return {
            **base,
            "status": status,
            "reason": map_error,
            "preferred_pdf": preferred_pdf,
            "theme_decision": decision,
        }

    assert kind == expected_kind and candidate is not None
    if existing:
        conflicts = _conflicting_fields(existing["frontmatter"], candidate)
        existing_isbn = normalise_isbn(existing["frontmatter"].get("isbn"))
        if "isbn" in conflicts and existing_isbn in set(entry.get("isbns") or []):
            conflicts.remove("isbn")
        if conflicts:
            return {
                **base,
                "status": "review",
                "reason": "field-conflict",
                "conflicts": conflicts,
                "match": existing["path"],
                "target_path": existing["path"],
                "canonical": candidate,
            }
        missing = _missing_fields(existing["frontmatter"], candidate)
        if not missing:
            return {
                **base,
                "status": "exact-existing",
                "route": "exact-existing",
                "reason": "existing-object-complete",
                "match": existing["path"],
                "target_path": existing["path"],
                "canonical": candidate,
            }
        return {
            **base,
            "status": "safe-enrich",
            "route": "metadata-only",
            "reason": "existing-object-missing-fields",
            "match": existing["path"],
            "target_path": existing["path"],
            "canonical": candidate,
            "enrich_fields": missing,
        }

    try:
        slug = make_work_slug(
            candidate["title"],
            candidate["authors"],
            candidate["year"],
        )
    except ValueError as exc:
        return {**base, "status": "review", "reason": str(exc)}
    target = (
        f"vault/papers/{slug}.md"
        if expected_kind == "paper"
        else f"vault/books/{slug}/00-overview.md"
    )
    occupied = Path(index.get("project_root", ".")) / target
    if occupied.exists():
        return {
            **base,
            "status": "review",
            "reason": "target-slug-occupied",
            "target_path": target,
            "canonical": candidate,
        }
    if pdf_reason == "multiple-local-pdfs":
        return {
            **base,
            "status": "review",
            "route": "manual-review",
            "reason": pdf_reason,
            "target_path": target,
            "canonical": candidate,
            "preferred_pdf_reason": pdf_reason,
        }
    route = "process-local-pdf" if preferred_pdf else "metadata-only"
    return {
        **base,
        "status": "safe-create",
        "route": route,
        "reason": pdf_reason,
        "target_path": target,
        "preferred_pdf": preferred_pdf,
        "preferred_pdf_reason": pdf_reason,
        "canonical": candidate,
    }


def mark_source_collisions(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_identity: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in entries:
        if row.get("status") not in {"safe-create", "safe-enrich"}:
            continue
        key = row["entry_key"]
        source = row.get("source_fields") or {}
        if source.get("doi"):
            by_identity[("doi", source["doi"])].add(key)
        for isbn in source.get("isbns") or (
            [source.get("isbn")] if source.get("isbn") else []
        ):
            by_identity[("isbn", isbn)].add(key)
        if row.get("target_path"):
            by_identity[("target", row["target_path"])].add(key)

    collision_by_key: dict[str, set[str]] = defaultdict(set)
    peer_keys: dict[str, set[str]] = defaultdict(set)
    for (basis, _), keys in by_identity.items():
        if len(keys) < 2:
            continue
        for key in keys:
            collision_by_key[key].add(basis)
            peer_keys[key].update(keys - {key})

    return [
        {
            **row,
            "status": "review",
            "route": "manual-review",
            "reason": "source-entry-collision",
            "collision_basis": sorted(collision_by_key[row["entry_key"]]),
            "collision_entry_keys": sorted(peer_keys[row["entry_key"]]),
        }
        if row["entry_key"] in collision_by_key
        else row
        for row in entries
    ]


def assign_batches(
    entries: list[dict[str, Any]],
    pilot_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    supported = [
        entry for entry in entries if entry["bibtex_type"] in SUPPORTED_TYPES
    ]
    articles = [
        entry for entry in supported if entry["bibtex_type"] == "article"
    ]
    books = [entry for entry in supported if entry["bibtex_type"] == "book"]
    explicit_pilot = pilot_keys is not None
    if pilot_keys is None:
        pilot_keys = {
            entry["entry_key"]
            for entry in articles[:25] + books[:25]
        }
    pilot = [entry for entry in supported if entry["entry_key"] in pilot_keys]
    if explicit_pilot:
        if len(pilot_keys) != 50 or len(pilot) != 50:
            raise ValueError("pilot must contain 50 known supported entry keys")
        if sum(entry["bibtex_type"] == "article" for entry in pilot) != 25:
            raise ValueError("pilot must contain 25 articles")
        if sum(entry["bibtex_type"] == "book" for entry in pilot) != 25:
            raise ValueError("pilot must contain 25 books")
    remaining = [
        entry for entry in supported if entry["entry_key"] not in pilot_keys
    ]
    batch_by_key = {key: 1 for key in pilot_keys}
    for offset in range(0, len(remaining), 100):
        batch_number = 2 + offset // 100
        for entry in remaining[offset : offset + 100]:
            batch_by_key[entry["entry_key"]] = batch_number
    return [
        {**entry, "batch": batch_by_key.get(entry["entry_key"])}
        for entry in entries
    ]


def normalise_entry(raw: dict[str, Any]) -> dict[str, Any]:
    raw_year = clean_text(raw.get("year"))
    year = int(raw_year) if raw_year and raw_year.isdigit() else None
    isbns = normalise_isbns(raw.get("isbn"))
    return {
        "entry_key": raw["ID"],
        "bibtex_type": str(raw["ENTRYTYPE"]).lower(),
        "title": clean_text(raw.get("title")),
        "authors": split_people(raw.get("author")),
        "editors": split_people(raw.get("editor")),
        "year": year,
        "journal": clean_text(raw.get("journal")),
        "publisher": clean_text(raw.get("publisher")),
        "doi": normalise_doi(raw.get("doi")),
        "isbn": isbns[0] if isbns else None,
        "isbns": isbns,
        "abstract": clean_text(raw.get("abstract")),
        "copyright_raw": clean_text(raw.get("copyright")),
        "rating": map_rating(raw.get("copyright")),
        "file_raw": clean_text(raw.get("file")),
        "file_refs": parse_file_refs(clean_text(raw.get("file"))),
        "has_annote": bool(clean_text(raw.get("annote"))),
        "has_note": bool(clean_text(raw.get("note"))),
        "has_keywords": bool(clean_text(raw.get("keywords"))),
        "parse_error": None,
    }


def _invalid_parse_entry(
    block: str,
    index: int,
    exc: Exception,
) -> dict[str, Any]:
    bibtex_type, entry_key = _block_identity(block, index)
    return {
        "entry_key": entry_key,
        "bibtex_type": bibtex_type,
        "title": None,
        "authors": [],
        "editors": [],
        "year": None,
        "journal": None,
        "publisher": None,
        "doi": None,
        "isbn": None,
        "isbns": [],
        "abstract": None,
        "copyright_raw": None,
        "rating": None,
        "file_raw": None,
        "file_refs": [],
        "has_annote": False,
        "has_note": False,
        "has_keywords": False,
        "parse_error": f"{type(exc).__name__}: {exc}",
    }


def parse_bibtex(path: Path) -> list[dict[str, Any]]:
    blocks = _split_bibtex_blocks(path.read_text(encoding="utf-8"))
    directives = [
        block
        for index, block in enumerate(blocks, start=1)
        if _block_identity(block, index)[0] in {"comment", "preamble", "string"}
    ]
    seen: set[str] = set()
    entries: list[dict[str, Any]] = []

    for index, block in enumerate(blocks, start=1):
        bibtex_type, _ = _block_identity(block, index)
        if bibtex_type in {"comment", "preamble", "string"}:
            continue
        try:
            entry = normalise_entry(_parse_bibtex_block(block, directives))
        except Exception as exc:
            entry = _invalid_parse_entry(block, index, exc)
        key = entry["entry_key"]
        if key in seen:
            raise ValueError(f"duplicate BibTeX entry key: {key}")
        seen.add(key)
        entries.append(entry)

    return sorted(entries, key=lambda entry: entry["entry_key"])


TOOL_VERSION = "zotero-bibtex-migration.v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_jsonl_bytes(data: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def _parse_key_set_bytes(data: bytes) -> set[str]:
    parsed = json.loads(data)
    if not isinstance(parsed, list) or any(not isinstance(key, str) for key in parsed):
        raise ValueError("key file must be a JSON string array")
    if len(parsed) != len(set(parsed)):
        raise ValueError("key file contains duplicates")
    return set(parsed)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    atomic_write_text(path, text)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return _parse_jsonl_bytes(path.read_bytes())


def inventory_counts(entries: list[dict[str, Any]]) -> dict[str, Any]:
    refs = [ref for entry in entries for ref in entry.get("file_refs", [])]
    recognized = [ref for ref in refs if ref.get("path")]
    ratings = Counter(entry.get("copyright_raw") for entry in entries if entry.get("rating"))
    return {
        "entries": len(entries),
        "types": dict(sorted(Counter(entry["bibtex_type"] for entry in entries).items())),
        "ratings": dict(sorted(ratings.items())),
        "notes": {
            "annote": sum(bool(entry.get("has_annote")) for entry in entries),
            "note": sum(bool(entry.get("has_note")) for entry in entries),
        },
        "attachments": {
            "references": len(refs),
            "recognized_paths": len(recognized),
            "unparsed": len(refs) - len(recognized),
            "existing_paths": sum(bool(ref.get("exists")) for ref in recognized),
            "missing_paths": sum(not ref.get("exists") for ref in recognized),
        },
    }


def load_theme_decisions(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    rows = read_jsonl(path)
    decisions: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.get("entry_key")
        if not key or key in decisions:
            raise ValueError(f"duplicate or missing theme entry_key: {key}")
        decisions[key] = row
    return decisions


def load_key_set(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    return _parse_key_set_bytes(path.read_bytes())


def write_theme_work(
    temp_dir: Path,
    catalog: dict[str, dict[str, Any]],
    entries: list[dict[str, Any]],
) -> None:
    temp_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(temp_dir / "theme-catalog.jsonl", [
        {"theme": theme, **data} for theme, data in catalog.items()
    ])
    requests = [
        {
            "entry_key": entry["entry_key"],
            "title": entry.get("title"),
            "abstract": entry.get("abstract"),
        }
        for entry in entries
        if entry["bibtex_type"] == "article"
    ]
    write_jsonl(temp_dir / "theme-requests.jsonl", requests)


def run_inventory(
    source: Path,
    project_root: Path,
    output_dir: Path,
    theme_decisions_path: Path | None,
    pilot_keys_path: Path | None,
) -> dict[str, Any]:
    source = source.resolve()
    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    copied_source = output_dir / "source.bib"
    source_hash = sha256_file(source)
    if copied_source.exists() and sha256_file(copied_source) != source_hash:
        raise ValueError("source.bib hash mismatch")
    # ponytail: on first run parse the original and materialize source.bib only
    # after every fallible step succeeds, so a failed first run never leaves a
    # copy whose hash blocks a corrected retry; reruns parse the immutable copy.
    parse_source = copied_source if copied_source.exists() else source
    parsed = parse_bibtex(parse_source)
    catalog = collect_theme_catalog(project_root)
    decisions = load_theme_decisions(theme_decisions_path)
    pilot_keys = load_key_set(pilot_keys_path)
    index = build_vault_index(project_root)
    assessed = assign_batches(
        mark_source_collisions([
            assess_entry(entry, index, decisions, catalog)
            for entry in parsed
        ]),
        pilot_keys,
    )
    if not copied_source.exists():
        shutil.copy2(source, copied_source)

    temp_dir = project_root / ".quasi" / "temp" / "zotero-2026-07-27"
    assessed_by_key = {row["entry_key"]: row for row in assessed}
    write_theme_work(temp_dir, catalog, [
        entry for entry in parsed
        if assessed_by_key[entry["entry_key"]]["reason"] == "theme-decision-missing"
    ])
    write_jsonl(output_dir / "entries.jsonl", assessed)

    manifest_path = output_dir / "manifest.json"
    plugin_manifest = json.loads(
        (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    manifest = {
        "version": 1,
        "tool_version": TOOL_VERSION,
        "tool_path": str(Path(__file__).resolve()),
        "quasi_plugin_root": str(PLUGIN_ROOT),
        "quasi_version": plugin_manifest["version"],
        "source_original_path": str(source),
        "source_sha256": source_hash,
        "source_copy": str(copied_source.relative_to(project_root)),
        "bibtexparser_version": importlib.metadata.version("bibtexparser"),
        "schema_version": SCHEMA_VERSION,
        "counts": inventory_counts(parsed),
        "scope": {
            "supported": ["article", "book"],
            "deferred": ["incollection", "inproceedings", "misc", "phdthesis", "techreport"],
            "milestone_denominator": 2100,
            "milestone_target": 525,
            "excluded": ["collections", "note-conversion", "pdf-annotations", "full-attachment-sync"],
        },
    }
    write_json(manifest_path, manifest)
    return {"manifest": manifest, "entries": assessed, "temp_dir": str(temp_dir)}


def merge_theme_decisions(catalog_path: Path, input_dir: Path, output: Path) -> int:
    catalog = {
        row["theme"]: {"count": row["count"], "examples": row["examples"]}
        for row in read_jsonl(catalog_path)
    }
    merged: dict[str, dict[str, Any]] = {}
    for path in sorted(input_dir.glob("*.jsonl")):
        for row in read_jsonl(path):
            key = row.get("entry_key")
            if not key or key in merged:
                raise ValueError(f"duplicate or missing theme entry_key: {key}")
            _, error = validate_theme_decision(row, catalog)
            if error:
                row = {**row, "validation_error": error}
            merged[key] = row
    write_jsonl(output, [merged[key] for key in sorted(merged)])
    return len(merged)


def _resolve_vault_target(project_root: Path, target_path: str) -> Path:
    # Critical 2: single chokepoint for every inventory/changes target path.
    # Reject absolute, parent-traversal, symlink escape; enforce canonical shape.
    rel = Path(target_path)
    if not target_path or rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe target path: {target_path}")
    parts = rel.parts
    if not (
        (len(parts) == 3 and parts[0] == "vault" and parts[1] == "papers"
         and parts[2].endswith(".md") and parts[2] != ".md")
        or (len(parts) == 4 and parts[0] == "vault" and parts[1] == "books"
            and parts[2] and parts[3] == "00-overview.md")
    ):
        raise ValueError(f"unsupported target path: {target_path}")
    if not (project_root / rel).resolve(strict=False).is_relative_to(project_root):
        raise ValueError(f"target escapes project root: {target_path}")
    return project_root / rel


def slug_from_target(target_path: str) -> str:
    path = Path(target_path)
    if path.name == "00-overview.md":
        return path.parent.name
    if path.suffix == ".md":
        return path.stem
    raise ValueError(f"unsupported target path: {target_path}")


def _resolve_staged_pdf(project_root: Path, slug: str) -> Path:
    if not slug or "/" in slug or "\\" in slug or slug in {".", ".."} or slug.startswith("."):
        raise ValueError(f"unsafe staged slug: {slug}")
    staged = project_root / "sources" / f"{slug}.pdf"
    if not staged.resolve(strict=False).is_relative_to(project_root):
        raise ValueError(f"staged PDF escapes project root: {slug}")
    return staged


def collect_process_artifacts(project_root: Path, row: dict[str, Any]) -> list[str]:
    target = _resolve_vault_target(project_root, row["target_path"])
    slug = slug_from_target(row["target_path"])
    candidates = [target]
    if target.name == "00-overview.md":
        candidates.extend((project_root / "vault" / "books" / slug).glob("**/*"))
        candidates.extend((project_root / "processing" / "chapters" / slug).glob("**/*"))
    artifacts: list[str] = []
    for path in candidates:
        if not path.is_file() or path.suffix.lower() not in {".md", ".json", ".txt"}:
            continue
        if not path.resolve(strict=False).is_relative_to(project_root):
            continue
        artifacts.append(str(path.relative_to(project_root)))
    return sorted(set(artifacts))


def _body_sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _canonical_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _receipt_path(changes_path: Path) -> Path:
    name = changes_path.name
    match = re.fullmatch(r"batch-(\d{3})-changes\.json", name)
    if match is None:
        raise ValueError(f"unexpected changes filename: {name}")
    return changes_path.with_name(f"batch-{match.group(1)}-approved.json")


def _entry_provenance_stamp(entry: dict[str, Any], receipt_sha256: str) -> str:
    body = {key: value for key, value in entry.items() if key != "provenance"}
    return _canonical_sha256({"receipt_sha256": receipt_sha256, "entry": body})


def _row_stamp(row: dict[str, Any]) -> str:
    return _canonical_sha256({"row": row})


def _build_receipt(
    project_root: Path,
    inventory_path: Path,
    batch: int,
    approved: set[str],
    selected: list[dict[str, Any]],
    *,
    approved_input_sha256: str,
    inventory_sha256: str,
    row_snapshots: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "version": 1,
        "batch": batch,
        "project_root": str(project_root),
        "inventory_path": str(inventory_path.resolve()),
        "approved_input_sha256": approved_input_sha256,
        "approved_keys": sorted(approved),
        "inventory_sha256": inventory_sha256,
        "rows": {
            row["entry_key"]: {
                "row_sha256": _row_stamp(row),
                "row": row,
                **row_snapshots.get(row["entry_key"], {}),
            }
            for row in selected
        },
    }


def _load_receipt(
    changes_path: Path,
    expected_sha256: str | None,
) -> tuple[dict[str, Any], str]:
    # The apply receipt and inventory are the trust roots. Rewriting both is an
    # administrator action outside this migration's local tamper threat model.
    receipt_path = _receipt_path(changes_path)
    if not receipt_path.is_file():
        raise ValueError(f"missing apply receipt: {receipt_path}")
    receipt_bytes = receipt_path.read_bytes()
    receipt_sha256 = _sha256_bytes(receipt_bytes)
    if expected_sha256 is not None and receipt_sha256 != expected_sha256:
        raise ValueError(f"receipt hash mismatch: {receipt_path}")
    receipt = json.loads(receipt_bytes)
    if not isinstance(receipt, dict) \
            or type(receipt.get("version")) is not int \
            or receipt["version"] != 1:
        raise ValueError(f"invalid apply receipt: {receipt_path}")
    return receipt, receipt_sha256


def _validated_receipt_rows(
    receipt: dict[str, Any],
    *,
    inventory_path: Path | None,
    inventory_sha256: str | None,
    rows_by_key: dict[str, dict[str, Any]],
    project_root: Path | None,
    approved_input_sha256: str | None = None,
    approved_keys_input: set[str] | None = None,
) -> tuple[int, dict[str, dict[str, Any]], Path]:
    batch = receipt.get("batch")
    approved_keys = receipt.get("approved_keys")
    snapshots = receipt.get("rows")
    root_value = receipt.get("project_root")
    inventory_value = receipt.get("inventory_path")
    if type(batch) is not int \
            or not isinstance(approved_keys, list) \
            or not all(isinstance(key, str) for key in approved_keys) \
            or approved_keys != sorted(set(approved_keys)) \
            or not isinstance(receipt.get("approved_input_sha256"), str) \
            or not isinstance(receipt.get("inventory_sha256"), str) \
            or not isinstance(snapshots, dict) \
            or set(snapshots) != set(approved_keys) \
            or not isinstance(root_value, str) \
            or not Path(root_value).is_absolute() \
            or not isinstance(inventory_value, str) \
            or not Path(inventory_value).is_absolute():
        raise ValueError("invalid apply receipt")
    receipt_root = Path(root_value).resolve()
    receipt_inventory = Path(inventory_value).resolve()
    if project_root is not None and receipt_root != project_root.resolve():
        raise ValueError("apply receipt project root mismatch")
    if inventory_path is None:
        inventory_bytes = receipt_inventory.read_bytes()
        inventory_sha256 = _sha256_bytes(inventory_bytes)
        current_rows = {
            row["entry_key"]: row for row in _parse_jsonl_bytes(inventory_bytes)
        }
    else:
        if receipt_inventory != inventory_path.resolve():
            raise ValueError("apply receipt inventory path mismatch")
        if inventory_sha256 is None:
            raise ValueError("missing inventory snapshot")
        current_rows = rows_by_key
    if receipt["inventory_sha256"] != inventory_sha256:
        raise ValueError("inventory hash mismatch")
    if approved_input_sha256 is not None and (
        receipt["approved_input_sha256"] != approved_input_sha256
        or approved_keys_input is None
        or approved_keys != sorted(approved_keys_input)
    ):
        raise ValueError("apply receipt differs from approved inputs")

    receipt_rows: dict[str, dict[str, Any]] = {}
    for key in approved_keys:
        snapshot = snapshots[key]
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("row"), dict) \
                or snapshot.get("row_sha256") != _row_stamp(snapshot["row"]):
            raise ValueError(f"invalid receipt row: {key}")
        row = snapshot["row"]
        if row.get("entry_key") != key or row.get("batch") != batch \
                or row.get("status") not in {"safe-create", "safe-enrich"}:
            raise ValueError(f"invalid receipt row: {key}")
        if current_rows.get(key) != row:
            raise ValueError(f"receipt row does not match inventory: {key}")
        if row["route"] == "process-local-pdf":
            source_sha256 = snapshot.get("source_sha256")
            if not isinstance(source_sha256, str):
                raise ValueError(f"invalid receipt row: {key}")
            row = {**row, "_approved_source_sha256": source_sha256}
        elif row["status"] == "safe-enrich":
            target_before = snapshot.get("target_before")
            if not isinstance(target_before, dict) \
                    or not isinstance(target_before.get("frontmatter"), dict) \
                    or not isinstance(target_before.get("body_sha256"), str):
                raise ValueError(f"invalid receipt row: {key}")
            row = {**row, "_approved_target_before": target_before}
        receipt_rows[key] = row
    return batch, receipt_rows, receipt_root


def _build_review_rows(rows_by_key: dict[str, dict[str, Any]], batch: int) -> list[dict[str, Any]]:
    return sorted(
        (
            row for row in rows_by_key.values()
            if row.get("batch") == batch
            and (
                row.get("status") in {"review", "invalid-source"}
                or row.get("attachment_review")
            )
        ),
        key=lambda row: row["entry_key"],
    )


def _review_rows_with_failures(
    rows_by_key: dict[str, dict[str, Any]],
    batch: int,
    changes_by_key: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key = {row["entry_key"]: row for row in _build_review_rows(rows_by_key, batch)}
    for key, change in changes_by_key.items():
        if change.get("failed"):
            by_key[key] = {
                **rows_by_key[key],
                "execution_failure": change["failure_reason"],
                "partial_artifact_paths": change["partial_artifact_paths"],
            }
    return [by_key[key] for key in sorted(by_key)]


def _validate_review_payload(
    review: Any,
    batch: int,
    rows_by_key: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(review, dict) \
            or type(review.get("version")) is not int \
            or review["version"] != 1:
        raise ValueError("invalid review file: version")
    if type(review.get("batch")) is not int or review["batch"] != batch:
        raise ValueError("invalid review file: batch")
    entries = review.get("entries")
    if not isinstance(entries, list):
        raise ValueError("invalid review file: entries")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("entry_key"), str):
            raise ValueError("invalid review entry")
        key = entry["entry_key"]
        if key in seen or key not in rows_by_key:
            raise ValueError(f"invalid review entry: {key}")
        seen.add(key)
    return review


_PROCESS_ACTIONS = {"staged-local-pdf", "no-op", "processed-local-pdf"}


def _safe_enrich_state(
    row: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    target_before = row.get("_approved_target_before")
    if not isinstance(target_before, dict) \
            or not isinstance(target_before.get("frontmatter"), dict) \
            or not isinstance(target_before.get("body_sha256"), str):
        raise ValueError(f"invalid receipt row: {row['entry_key']}")
    before = dict(target_before["frontmatter"])
    after = dict(before)
    for field, value in row.get("enrich_fields", {}).items():
        existing = after.get(field)
        if existing in (None, "", []):
            after[field] = value
        elif existing != value:
            raise ValueError(f"invalid receipt row: {row['entry_key']}")
    if _conflicting_fields(after, row["canonical"]):
        raise ValueError(f"invalid receipt row: {row['entry_key']}")
    return before, after, target_before["body_sha256"]


def _require_apply_shape(
    project_root: Path,
    row: dict[str, Any],
    entry: dict[str, Any],
) -> None:
    key = row["entry_key"]
    route = row["route"]
    artifacts = entry.get("artifact_paths")
    if not isinstance(artifacts, list) or not all(isinstance(path, str) for path in artifacts):
        raise ValueError(f"invalid changes shape: {key}")
    if route == "metadata-only":
        before = entry.get("before")
        after = entry.get("after")
        if not (before is None or isinstance(before, dict)) \
                or not isinstance(after, dict) \
                or not isinstance(entry.get("body_sha256"), str) \
                or artifacts != [row["target_path"]]:
            raise ValueError(f"invalid changes shape: {key}")
        if row["status"] == "safe-create":
            expected_body = render_stub(row["canonical"]["type"], row["canonical"]["title"])
            if before is not None or after != row["canonical"] \
                    or entry["body_sha256"] != _body_sha256(expected_body):
                raise ValueError(f"invalid changes shape: {key}")
        else:
            expected_before, expected_after, expected_body_sha256 = _safe_enrich_state(row)
            expected_action = "enriched" if expected_after != expected_before else "no-op"
            if before != expected_before or after != expected_after \
                    or entry["body_sha256"] != expected_body_sha256 \
                    or entry.get("action") != expected_action:
                raise ValueError(f"invalid changes shape: {key}")
    elif route == "process-local-pdf":
        source_path = entry.get("source_path")
        staged_path = entry.get("staged_path")
        source_sha256 = entry.get("source_sha256")
        staged = _resolve_staged_pdf(project_root, slug_from_target(row["target_path"]))
        if source_path != row.get("preferred_pdf") \
                or staged_path != str(staged.relative_to(project_root)) \
                or source_sha256 != row.get("_approved_source_sha256"):
            raise ValueError(f"invalid changes shape: {key}")
        if entry.get("action") == "processed-local-pdf":
            finalize = entry.get("finalize")
            if not isinstance(finalize, dict) \
                    or not isinstance(finalize.get("before"), dict) \
                    or not isinstance(finalize.get("after"), dict) \
                    or not isinstance(finalize.get("body_sha256"), str):
                raise ValueError(f"invalid changes shape: {key}")
            canonical = row["canonical"]
            exact_fields = (
                ("title", "authors", "year", "journal", "doi", "rating")
                if canonical["type"] == "paper"
                else ("title", "authors", "year", "publisher", "isbn", "doi", "rating")
            )
            for field in exact_fields:
                value = canonical.get(field)
                if value not in (None, "", []) and finalize["after"].get(field) != value:
                    raise ValueError(f"invalid changes shape: {key}")
            controlled = "themes" if canonical["type"] == "paper" else "category"
            if finalize["after"].get(controlled) != canonical[controlled]:
                raise ValueError(f"invalid changes shape: {key}")
        elif entry.get("finalize") is not None:
            raise ValueError(f"invalid changes shape: {key}")
    else:
        raise ValueError(f"unsupported route: {route}")


def _validate_changes_entry(
    project_root: Path,
    row: dict[str, Any],
    entry: dict[str, Any],
    batch: int,
    receipt_sha256: str,
) -> None:
    key = row["entry_key"]
    if row.get("status") != entry.get("status") \
            or row.get("route") != entry.get("route") \
            or row.get("target_path") != entry.get("target_path") \
            or row.get("batch") != batch:
        raise ValueError(f"changes entry does not match inventory: {key}")
    allowed = (
        {"enriched", "no-op"}
        if row["status"] == "safe-enrich"
        else {"created", "no-op"}
        if row["route"] == "metadata-only"
        else _PROCESS_ACTIONS
    )
    if entry.get("action") not in allowed:
        raise ValueError(f"invalid changes action: {key}")
    if entry.get("reapply_action") not in (None, "no-op"):
        raise ValueError(f"invalid changes state: {key}")
    _require_apply_shape(project_root, row, entry)
    if entry.get("failed"):
        if entry.get("verified") \
                or not isinstance(entry.get("failure_reason"), str) \
                or not isinstance(entry.get("partial_artifact_paths"), list):
            raise ValueError(f"invalid failed changes entry: {key}")
    if entry.get("verified"):
        if row["route"] == "process-local-pdf" \
                and entry.get("action") != "processed-local-pdf":
            raise ValueError(f"verified-but-unfinalized changes entry: {key}")
        verification = entry.get("verification")
        if not isinstance(verification, dict) \
                or verification.get("frontmatter_errors") != [] \
                or verification.get("body_violations") != []:
            raise ValueError(f"verified entry lacks passing verification: {key}")
    if entry.get("provenance") != _entry_provenance_stamp(entry, receipt_sha256):
        raise ValueError(f"unprovenanced changes entry: {key}")


def _load_validated_payload(
    payload: dict[str, Any],
    rows_by_key: dict[str, dict[str, Any]],
    *,
    changes_path: Path,
    inventory_path: Path | None,
    inventory_sha256: str | None,
    project_root: Path | None,
    approved_input_sha256: str | None = None,
    approved_keys_input: set[str] | None = None,
) -> tuple[
    int,
    dict[str, dict[str, Any]],
    str,
    Path,
    dict[str, dict[str, Any]],
]:
    if not isinstance(payload, dict) \
            or type(payload.get("version")) is not int \
            or payload["version"] != 1:
        raise ValueError("unsupported changes version")
    batch = payload.get("batch")
    receipt_sha256 = payload.get("receipt_sha256")
    entries = payload.get("entries")
    if type(batch) is not int:
        raise ValueError("changes file missing batch")
    if changes_path.name != f"batch-{batch:03d}-changes.json":
        raise ValueError("changes filename does not match batch")
    if not isinstance(receipt_sha256, str):
        raise ValueError("changes file missing receipt_sha256")
    if not isinstance(entries, list):
        raise ValueError("changes file missing entries")
    receipt, _ = _load_receipt(changes_path, receipt_sha256)
    receipt_batch, receipt_rows, receipt_root = _validated_receipt_rows(
        receipt,
        inventory_path=inventory_path,
        inventory_sha256=inventory_sha256,
        rows_by_key=rows_by_key,
        project_root=project_root,
        approved_input_sha256=approved_input_sha256,
        approved_keys_input=approved_keys_input,
    )
    if receipt_batch != batch:
        raise ValueError("changes file batch differs from receipt")

    by_key: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("invalid changes entry")
        key = entry.get("entry_key")
        if not isinstance(key, str) or key in by_key:
            raise ValueError(f"invalid changes entry_key: {key}")
        by_key[key] = entry
    if set(by_key) != set(receipt_rows):
        raise ValueError("changes keys differ from apply receipt")
    for key, entry in by_key.items():
        _validate_changes_entry(receipt_root, receipt_rows[key], entry, batch, receipt_sha256)
    return batch, by_key, receipt_sha256, receipt_root, receipt_rows


def _copy_pdf_atomically(source: Path, staged: Path, expected_sha256: str) -> None:
    # ponytail: one batch writer; a sibling temp file is enough without a lock.
    temporary = staged.with_name(f".{staged.name}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        shutil.copy2(source, temporary)
        if sha256_file(source) != expected_sha256 \
                or sha256_file(temporary) != expected_sha256:
            raise ValueError(f"source PDF changed while staging: {source}")
        temporary.replace(staged)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def apply_batch(
    project_root: Path,
    inventory_path: Path,
    batch: int,
    approved_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    inventory_bytes = inventory_path.read_bytes()
    inventory_sha256 = _sha256_bytes(inventory_bytes)
    rows = {
        row["entry_key"]: row for row in _parse_jsonl_bytes(inventory_bytes)
    }
    approved_bytes = approved_path.read_bytes()
    approved_input_sha256 = _sha256_bytes(approved_bytes)
    approved = _parse_key_set_bytes(approved_bytes)
    selected: list[dict[str, Any]] = []
    for key in sorted(approved):
        row = rows.get(key)
        if row is None or row.get("batch") != batch:
            raise ValueError(f"approved key not in batch {batch}: {key}")
        if row.get("status") not in {"safe-create", "safe-enrich"}:
            raise ValueError(f"approved key is not safe: {key}")
        _resolve_vault_target(project_root, row["target_path"])
        selected.append(row)

    output_dir.mkdir(parents=True, exist_ok=True)
    changes_path = output_dir / f"batch-{batch:03d}-changes.json"
    review_path = output_dir / f"batch-{batch:03d}-review.json"
    receipt_path = _receipt_path(changes_path)
    if changes_path.exists():
        if not receipt_path.is_file():
            raise ValueError(f"missing apply receipt: {receipt_path}")
        prior_payload = json.loads(changes_path.read_bytes())
        _, prior_by_key, receipt_sha256, _, receipt_rows = _load_validated_payload(
            prior_payload,
            rows,
            changes_path=changes_path,
            inventory_path=inventory_path,
            inventory_sha256=inventory_sha256,
            project_root=project_root,
            approved_input_sha256=approved_input_sha256,
            approved_keys_input=approved,
        )
        if set(prior_by_key) != approved:
            raise ValueError("approved key set differs from existing changes file")

        for key in sorted(approved):
            row = receipt_rows[key]
            target = _resolve_vault_target(project_root, row["target_path"])
            prior = prior_by_key[key]
            if row["route"] == "process-local-pdf":
                if not _process_source_files_match(project_root, row, prior):
                    raise ValueError(f"reapply is not a no-op: {key}")
                if prior.get("action") == "processed-local-pdf":
                    if not target.is_file():
                        raise ValueError(f"reapply is not a no-op: {key}")
                    doc = read_frontmatter(target)
                    finalize = prior.get("finalize") or {}
                    if (
                        doc.frontmatter != finalize.get("after")
                        or _body_sha256(doc.body) != finalize.get("body_sha256")
                        or collect_process_artifacts(project_root, row)
                        != prior.get("artifact_paths")
                    ):
                        raise ValueError(f"reapply is not a no-op: {key}")
            elif row["status"] == "safe-enrich":
                if not target.is_file():
                    raise ValueError(f"reapply is not a no-op: {key}")
                doc = read_frontmatter(target)
                _, expected_after, expected_body_sha256 = _safe_enrich_state(row)
                if doc.frontmatter != expected_after \
                        or _body_sha256(doc.body) != expected_body_sha256:
                    raise ValueError(f"reapply is not a no-op: {key}")
            else:
                canonical = dict(row["canonical"])
                if not target.is_file():
                    raise ValueError(f"reapply is not a no-op: {key}")
                current = read_frontmatter(target)
                body = render_stub(canonical["type"], canonical["title"])
                if current.frontmatter != canonical or current.body != body:
                    raise ValueError(f"reapply is not a no-op: {key}")

        expected_review = {
            "version": 1,
            "batch": batch,
            "entries": _review_rows_with_failures(rows, batch, prior_by_key),
        }
        try:
            review_raw = json.loads(review_path.read_text(encoding="utf-8"))
            _validate_review_payload(review_raw, batch, rows)
            regenerate = review_raw != expected_review
        except (OSError, ValueError, json.JSONDecodeError):
            regenerate = True
        if regenerate:
            write_json(review_path, expected_review)

        for key in sorted(approved):
            prior = prior_by_key[key]
            prior["reapply_action"] = "no-op"
            prior["provenance"] = _entry_provenance_stamp(prior, receipt_sha256)
        prior_payload["entries"] = [prior_by_key[key] for key in sorted(approved)]
        write_json(changes_path, prior_payload)
        return prior_payload

    # Snapshot every trust-bound input before the first target/PDF write.
    target_docs: dict[str, Any] = {}
    row_snapshots: dict[str, dict[str, Any]] = {}
    receipt_is_new = not receipt_path.exists()
    if receipt_is_new:
        for row in selected:
            key = row["entry_key"]
            target = _resolve_vault_target(project_root, row["target_path"])
            if row["route"] == "process-local-pdf":
                source = Path(row["preferred_pdf"])
                staged = _resolve_staged_pdf(
                    project_root, slug_from_target(row["target_path"]),
                )
                if not is_readable_pdf(source):
                    raise ValueError(f"preferred PDF is no longer readable: {source}")
                if collect_process_artifacts(project_root, row):
                    raise ValueError(f"pre-existing process artifacts: {row['target_path']}")
                source_sha256 = sha256_file(source)
                if staged.exists() and sha256_file(staged) != source_sha256:
                    raise ValueError(f"staged PDF conflict: {staged}")
                row_snapshots[key] = {"source_sha256": source_sha256}
            elif row["route"] != "metadata-only":
                raise ValueError(f"unsupported route: {row['route']}")
            elif row["status"] == "safe-enrich":
                if not target.is_file():
                    raise ValueError(f"invalid frontmatter: {target}")
                current = read_frontmatter(target)
                if current.frontmatter is None:
                    raise ValueError(f"invalid frontmatter: {target}")
                conflicts = _conflicting_fields(current.frontmatter, row["canonical"])
                if conflicts:
                    raise ValueError(
                        f"enrichment conflict for {row['entry_key']}: "
                        f"{', '.join(conflicts)}"
                    )
                for field, value in row["enrich_fields"].items():
                    existing = current.frontmatter.get(field)
                    if existing not in (None, "", []) and existing != value:
                        raise ValueError(
                            f"enrichment conflict for {row['entry_key']}: {field}"
                        )
                target_docs[key] = current
                row_snapshots[key] = {
                    "target_before": {
                        "frontmatter": dict(current.frontmatter),
                        "body_sha256": _body_sha256(current.body),
                    },
                }
            else:
                canonical = dict(row["canonical"])
                if canonical["type"] == "paper":
                    PaperSchema.model_validate(canonical)
                else:
                    BookSchema.model_validate(canonical)
                if target.exists():
                    current = read_frontmatter(target)
                    body = render_stub(canonical["type"], canonical["title"])
                    if current.frontmatter != canonical or current.body != body:
                        raise ValueError(f"safe-create target conflict: {target}")
        receipt = _build_receipt(
            project_root,
            inventory_path,
            batch,
            approved,
            selected,
            approved_input_sha256=approved_input_sha256,
            inventory_sha256=inventory_sha256,
            row_snapshots=row_snapshots,
        )
        _, receipt_rows, _ = _validated_receipt_rows(
            receipt,
            inventory_path=inventory_path,
            inventory_sha256=inventory_sha256,
            rows_by_key=rows,
            project_root=project_root,
            approved_input_sha256=approved_input_sha256,
            approved_keys_input=approved,
        )
        receipt_text = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
        receipt_sha256 = _sha256_bytes(receipt_text.encode("utf-8"))
    else:
        receipt, receipt_sha256 = _load_receipt(changes_path, None)
        _, receipt_rows, _ = _validated_receipt_rows(
            receipt,
            inventory_path=inventory_path,
            inventory_sha256=inventory_sha256,
            rows_by_key=rows,
            project_root=project_root,
            approved_input_sha256=approved_input_sha256,
            approved_keys_input=approved,
        )

    expected_review = {
        "version": 1,
        "batch": batch,
        "entries": _build_review_rows(rows, batch),
    }
    try:
        review_raw = json.loads(review_path.read_bytes())
        _validate_review_payload(review_raw, batch, rows)
        regenerate_review = review_raw != expected_review
    except (OSError, ValueError, json.JSONDecodeError):
        regenerate_review = True
    if regenerate_review:
        write_json(review_path, expected_review)
    if receipt_is_new:
        atomic_write_text(receipt_path, receipt_text)

    # A receipt-only rerun is a safe interruption recovery. Disk state must still
    # be either the receipt baseline or its one permitted apply result.
    for key in sorted(approved):
        row = receipt_rows[key]
        target = _resolve_vault_target(project_root, row["target_path"])
        if row["route"] == "process-local-pdf":
            source = Path(row["preferred_pdf"])
            staged = _resolve_staged_pdf(
                project_root, slug_from_target(row["target_path"]),
            )
            expected_source_sha256 = row["_approved_source_sha256"]
            if not is_readable_pdf(source) \
                    or sha256_file(source) != expected_source_sha256:
                raise ValueError(f"source PDF changed while staging: {source}")
            if collect_process_artifacts(project_root, row):
                raise ValueError(f"pre-existing process artifacts: {row['target_path']}")
            if staged.exists() and sha256_file(staged) != expected_source_sha256:
                raise ValueError(f"staged PDF conflict: {staged}")
        elif row["status"] == "safe-enrich":
            if not target.is_file():
                raise ValueError(f"invalid frontmatter: {target}")
            current = read_frontmatter(target)
            target_docs[key] = current
            before, after, body_sha256 = _safe_enrich_state(row)
            if current.frontmatter not in (before, after) \
                    or _body_sha256(current.body) != body_sha256:
                raise ValueError(f"enrichment target changed after receipt: {key}")
        else:
            canonical = dict(row["canonical"])
            if canonical["type"] == "paper":
                PaperSchema.model_validate(canonical)
            else:
                BookSchema.model_validate(canonical)
            if target.exists():
                current = read_frontmatter(target)
                body = render_stub(canonical["type"], canonical["title"])
                if current.frontmatter != canonical or current.body != body:
                    raise ValueError(f"safe-create target conflict: {target}")

    changes: list[dict[str, Any]] = []
    created_staged: set[Path] = set()
    for key in sorted(approved):
        row = receipt_rows[key]
        target = _resolve_vault_target(project_root, row["target_path"])
        route = row["route"]
        if route == "process-local-pdf":
            source = Path(row["preferred_pdf"])
            staged = _resolve_staged_pdf(project_root, slug_from_target(row["target_path"]))
            source_sha256 = row["_approved_source_sha256"]
            if not staged.exists():
                staged.parent.mkdir(parents=True, exist_ok=True)
                _copy_pdf_atomically(source, staged, source_sha256)
                created_staged.add(staged)
                action = "staged-local-pdf"
            else:
                action = "no-op"
            entry = {
                "entry_key": key, "status": row["status"],
                "route": route, "action": action,
                "target_path": row["target_path"],
                "source_path": str(source),
                "staged_path": str(staged.relative_to(project_root)),
                "source_sha256": source_sha256,
                "artifact_paths": [], "verified": False,
            }
            changes.append(entry)
            continue

        if route != "metadata-only":
            raise ValueError(f"unsupported route: {route}")
        if row["status"] == "safe-enrich":
            doc = target_docs[key]
            before, after, body_sha256 = _safe_enrich_state(row)
            action = "enriched" if after != before else "no-op"
            if doc.frontmatter == before and after != before:
                write_frontmatter(target, after, doc.body)
            entry = {
                "entry_key": key, "status": row["status"],
                "route": route, "action": action,
                "target_path": row["target_path"], "before": before, "after": after,
                "body_sha256": body_sha256,
                "artifact_paths": [row["target_path"]], "verified": False,
            }
        else:
            canonical = dict(row["canonical"])
            if canonical["type"] == "paper":
                PaperSchema.model_validate(canonical)
            else:
                BookSchema.model_validate(canonical)
            body = render_stub(canonical["type"], canonical["title"])
            if target.exists():
                current = read_frontmatter(target)
                if current.frontmatter != canonical or current.body != body:
                    raise ValueError(f"safe-create target conflict: {target}")
                action = "no-op"
            else:
                write_frontmatter(target, canonical, body)
                action = "created"
            entry = {
                "entry_key": key, "status": row["status"],
                "route": route, "action": action,
                "target_path": row["target_path"], "before": None, "after": canonical,
                "body_sha256": _body_sha256(body),
                "artifact_paths": [row["target_path"]], "verified": False,
            }
        changes.append(entry)

    # Recheck every receipt-bound source immediately before changes is committed.
    for key in sorted(approved):
        row = receipt_rows[key]
        if row["route"] != "process-local-pdf":
            continue
        source = Path(row["preferred_pdf"])
        staged = _resolve_staged_pdf(project_root, slug_from_target(row["target_path"]))
        expected_source_sha256 = row["_approved_source_sha256"]
        try:
            matches_receipt = (
                is_readable_pdf(source)
                and is_readable_pdf(staged)
                and sha256_file(source) == expected_source_sha256
                and sha256_file(staged) == expected_source_sha256
            )
        except OSError:
            for created in created_staged:
                created.unlink(missing_ok=True)
            raise
        if not matches_receipt:
            for created in created_staged:
                created.unlink(missing_ok=True)
            raise ValueError(f"source PDF changed while staging: {source}")

    for entry in changes:
        entry["provenance"] = _entry_provenance_stamp(entry, receipt_sha256)
    payload = {
        "version": 1,
        "batch": batch,
        "receipt_sha256": receipt_sha256,
        "entries": changes,
    }
    write_json(changes_path, payload)
    return payload


def _process_after(doc: Any, canonical: dict[str, Any], entry_key: str) -> tuple[dict[str, Any], str]:
    exact_fields = (
        ("title", "authors", "year", "journal", "doi", "rating")
        if canonical["type"] == "paper"
        else ("title", "authors", "year", "publisher", "isbn", "doi", "rating")
    )
    after = dict(doc.frontmatter)
    for field in exact_fields:
        value = canonical.get(field)
        if value in (None, "", []):
            continue
        if after.get(field) in (None, "", []):
            after[field] = value
        elif after[field] != value:
            raise ValueError(f"finalize conflict for {entry_key}: {field}")
    if canonical["type"] == "paper":
        after["themes"] = canonical["themes"]
    else:
        after["category"] = canonical["category"]
    return after, _body_sha256(doc.body)


def _process_source_files_match(
    project_root: Path,
    row: dict[str, Any],
    entry: dict[str, Any],
) -> bool:
    source = Path(row["preferred_pdf"])
    staged = _resolve_staged_pdf(project_root, slug_from_target(row["target_path"]))
    expected = row["_approved_source_sha256"]
    return (
        is_readable_pdf(source)
        and is_readable_pdf(staged)
        and sha256_file(source) == expected
        and sha256_file(staged) == expected
    )


def finalize_entry(
    project_root: Path,
    inventory_path: Path,
    changes_path: Path,
    entry_key: str,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    inventory_bytes = inventory_path.read_bytes()
    inventory_sha256 = _sha256_bytes(inventory_bytes)
    rows_by_key = {
        row["entry_key"]: row for row in _parse_jsonl_bytes(inventory_bytes)
    }
    payload = json.loads(changes_path.read_bytes())
    _, by_key, receipt_sha256, _, receipt_rows = _load_validated_payload(
        payload,
        rows_by_key,
        changes_path=changes_path,
        inventory_path=inventory_path,
        inventory_sha256=inventory_sha256,
        project_root=project_root,
    )
    row = receipt_rows[entry_key]
    if row.get("route") != "process-local-pdf":
        raise ValueError(f"entry is not process-local-pdf: {entry_key}")
    change = by_key[entry_key]
    if change.get("failed"):
        raise ValueError(f"cannot finalize failed entry: {entry_key}")

    target = _resolve_vault_target(project_root, row["target_path"])
    if change.get("action") == "processed-local-pdf":
        # Compare raw disk state first. Missing/corrupt targets and staging drift
        # also invalidate a prior verification rather than leaving it cached true.
        try:
            doc = read_frontmatter(target) if target.is_file() else None
        except OSError:
            doc = None
        artifacts = collect_process_artifacts(project_root, row)
        prior = change["finalize"]
        body_sha256 = _body_sha256(doc.body) if doc is not None else None
        if not _process_source_files_match(project_root, row, change) \
                or doc is None \
                or doc.frontmatter != prior["after"] \
                or body_sha256 != prior["body_sha256"] \
                or row["target_path"] not in artifacts \
                or change["artifact_paths"] != artifacts:
            change["verified"] = False
            change["verification"] = {"path": str(target), "error": "finalize-drift"}
            change["provenance"] = _entry_provenance_stamp(change, receipt_sha256)
            write_json(changes_path, payload)
            raise ValueError(f"finalize drift, reapply is not a no-op: {entry_key}")
        return {
            "entry_key": entry_key,
            "target_path": row["target_path"],
            "artifact_paths": artifacts,
            "before": prior["before"],
            "after": prior["after"],
            "body_sha256": body_sha256,
        }

    if change.get("action") not in {"staged-local-pdf", "no-op"}:
        raise ValueError(f"cannot finalize from action {change.get('action')}: {entry_key}")
    if not _process_source_files_match(project_root, row, change):
        raise ValueError(f"staged PDF changed after apply: {entry_key}")
    if not target.is_file():
        raise ValueError(f"process product missing or invalid: {target}")
    doc = read_frontmatter(target)
    if doc.frontmatter is None:
        raise ValueError(f"process product missing or invalid: {target}")
    artifacts = collect_process_artifacts(project_root, row)
    if row["target_path"] not in artifacts:
        raise ValueError(f"process target missing from artifacts: {target}")

    before = dict(doc.frontmatter)
    after, body_sha256 = _process_after(doc, row["canonical"], entry_key)
    if after != before:
        write_frontmatter(target, after, doc.body)
    change["action"] = "processed-local-pdf"
    change["artifact_paths"] = artifacts
    change["finalize"] = {"before": before, "after": after, "body_sha256": body_sha256}
    change["verified"] = False
    change.pop("verification", None)
    change["provenance"] = _entry_provenance_stamp(change, receipt_sha256)
    write_json(changes_path, payload)
    return {
        "entry_key": entry_key,
        "target_path": row["target_path"],
        "artifact_paths": artifacts,
        "before": before,
        "after": after,
        "body_sha256": body_sha256,
    }


def _live_verification(
    project_root: Path,
    row: dict[str, Any],
    entry: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    target = _resolve_vault_target(project_root, row["target_path"])
    if entry.get("failed") or not target.is_file():
        return False, {"path": str(target), "error": "missing-or-failed"}
    if row["route"] == "process-local-pdf":
        if entry.get("action") != "processed-local-pdf":
            return False, {"path": str(target), "error": "not-finalized"}
        if not _process_source_files_match(project_root, row, entry):
            return False, {"path": str(target), "error": "staged-pdf-changed"}
        if collect_process_artifacts(project_root, row) != entry["artifact_paths"]:
            return False, {"path": str(target), "error": "process-artifacts-changed"}

    doc = read_frontmatter(target)
    if row["route"] == "metadata-only" and row["status"] == "safe-enrich":
        _, expected, body_sha256 = _safe_enrich_state(row)
    elif row["route"] == "metadata-only":
        expected = row["canonical"]
        body_sha256 = _body_sha256(
            render_stub(row["canonical"]["type"], row["canonical"]["title"])
        )
    else:
        finalize = entry["finalize"]
        expected = finalize["after"]
        body_sha256 = finalize["body_sha256"]
    if doc.frontmatter != expected:
        return False, {"path": str(target), "error": "frontmatter-changed"}
    if _body_sha256(doc.body) != body_sha256:
        return False, {"path": str(target), "error": "body-changed"}
    result = check_file(target)
    return (
        not result["frontmatter_errors"] and not result["body_violations"],
        result,
    )


def verify_changes(project_root: Path, changes_path: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    payload = json.loads(changes_path.read_bytes())
    _, by_key, receipt_sha256, _, receipt_rows = _load_validated_payload(
        payload,
        {},
        changes_path=changes_path,
        inventory_path=None,
        inventory_sha256=None,
        project_root=project_root,
    )
    for key, entry in by_key.items():
        entry["verified"], entry["verification"] = _live_verification(
            project_root, receipt_rows[key], entry,
        )
        entry["provenance"] = _entry_provenance_stamp(entry, receipt_sha256)
    write_json(changes_path, payload)
    return payload


def record_failure(
    project_root: Path,
    inventory_path: Path,
    changes_path: Path,
    review_path: Path,
    entry_key: str,
    reason: str,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    inventory_bytes = inventory_path.read_bytes()
    inventory_sha256 = _sha256_bytes(inventory_bytes)
    rows_by_key = {
        row["entry_key"]: row for row in _parse_jsonl_bytes(inventory_bytes)
    }
    payload = json.loads(changes_path.read_bytes())
    batch, by_key, receipt_sha256, _, receipt_rows = _load_validated_payload(
        payload,
        rows_by_key,
        changes_path=changes_path,
        inventory_path=inventory_path,
        inventory_sha256=inventory_sha256,
        project_root=project_root,
    )
    review = _validate_review_payload(
        json.loads(review_path.read_bytes()),
        batch,
        rows_by_key,
    )
    inventory_row = rows_by_key[entry_key]
    row = receipt_rows[entry_key]
    change = by_key[entry_key]
    if change.get("action") == "processed-local-pdf":
        raise ValueError(f"invalid failure change record: {entry_key}")

    if change.get("failed"):
        if change.get("failure_reason") != reason:
            raise ValueError(f"failure reason differs from existing record: {entry_key}")
        partial_artifact_paths = change["partial_artifact_paths"]
    else:
        partial_artifact_paths = collect_process_artifacts(project_root, row)
        change["failed"] = True
        change["failure_reason"] = reason
        change["partial_artifact_paths"] = partial_artifact_paths
        change["verified"] = False
        change.pop("verification", None)
        change["provenance"] = _entry_provenance_stamp(change, receipt_sha256)

    failure_row = {
        **inventory_row,
        "execution_failure": reason,
        "partial_artifact_paths": partial_artifact_paths,
    }
    review["entries"] = [
        item for item in review["entries"] if item["entry_key"] != entry_key
    ]
    review["entries"].append(failure_row)
    review["entries"].sort(key=lambda item: item["entry_key"])
    # Review is written first. If the changes write fails, the same-reason retry
    # replays this identical review row and converges without changing the reason.
    write_json(review_path, review)
    write_json(changes_path, payload)
    return {
        "entry_key": entry_key,
        "failed": True,
        "failure_reason": reason,
        "partial_artifact_paths": partial_artifact_paths,
    }


def _validated_change_entries(
    rows_by_key: dict[str, dict[str, Any]],
    inventory_path: Path,
    inventory_sha256: str,
    changes_dir: Path,
) -> tuple[list[tuple[dict[str, Any], dict[str, Any], Path]], list[int]]:
    entries: list[tuple[dict[str, Any], dict[str, Any], Path]] = []
    batches: list[int] = []
    seen: set[str] = set()
    for path in sorted(changes_dir.glob("batch-???-changes.json")):
        payload = json.loads(path.read_bytes())
        batch, by_key, _, project_root, receipt_rows = _load_validated_payload(
            payload,
            rows_by_key,
            changes_path=path,
            inventory_path=inventory_path,
            inventory_sha256=inventory_sha256,
            project_root=None,
        )
        batches.append(batch)
        for key, entry in by_key.items():
            if key in seen:
                raise ValueError(f"duplicate entry across changes files: {key}")
            seen.add(key)
            entries.append((entry, receipt_rows[key], project_root))
    return entries, sorted(set(batches))


def progress_summary(inventory_path: Path, changes_dir: Path) -> dict[str, Any]:
    inventory_bytes = inventory_path.read_bytes()
    inventory_sha256 = _sha256_bytes(inventory_bytes)
    rows = _parse_jsonl_bytes(inventory_bytes)
    rows_by_key = {row["entry_key"]: row for row in rows}
    completed = {row["entry_key"] for row in rows if row["status"] == "exact-existing"}
    changes, _ = _validated_change_entries(
        rows_by_key, inventory_path, inventory_sha256, changes_dir,
    )
    completed.update(
        entry["entry_key"]
        for entry, row, project_root in changes
        if entry.get("verified")
        and not entry.get("failed")
        and _live_verification(project_root, row, entry)[0]
    )
    return {
        "denominator": 2100,
        "target": 525,
        "completed": len(completed),
        "remaining_to_target": max(0, 525 - len(completed)),
        "milestone_reached": len(completed) >= 525,
    }


def milestone_report(
    inventory_path: Path,
    changes_dir: Path,
    output_path: Path,
) -> dict[str, Any]:
    output_resolved = output_path.resolve()
    changes_root = changes_dir.resolve()
    reserved_paths = [inventory_path, *changes_dir.glob("batch-*.json")]
    same_identity = output_path.exists() and any(
        path.exists() and output_path.samefile(path) for path in reserved_paths
    )
    reserved_names = output_resolved.parent == changes_root and re.fullmatch(
        r"batch-\d{3}-(?:changes|approved|review)\.json",
        output_resolved.name,
        flags=re.IGNORECASE,
    )
    if same_identity \
            or output_resolved in {path.resolve() for path in reserved_paths} \
            or reserved_names:
        raise ValueError("report output aliases migration input")
    # Invalidate a stale success before parsing any untrusted input.
    write_json(output_path, {
        "version": 1,
        "denominator": 2100,
        "target": 525,
        "completed": 0,
        "milestone_reached": False,
        "status": "validation-pending",
    })
    inventory_bytes = inventory_path.read_bytes()
    inventory_sha256 = _sha256_bytes(inventory_bytes)
    rows = _parse_jsonl_bytes(inventory_bytes)
    rows_by_key = {row["entry_key"]: row for row in rows}
    exact_keys = {row["entry_key"] for row in rows if row["status"] == "exact-existing"}
    metadata_keys: set[str] = set()
    pdf_keys: set[str] = set()
    failed_keys: set[str] = set()
    actions: Counter[str] = Counter()
    changes, batches = _validated_change_entries(
        rows_by_key, inventory_path, inventory_sha256, changes_dir,
    )
    for entry, row, project_root in changes:
        actions[entry.get("action", "missing")] += 1
        if entry.get("failed"):
            failed_keys.add(entry["entry_key"])
            continue
        live = entry.get("verified") and _live_verification(project_root, row, entry)[0]
        if live and entry["route"] == "metadata-only":
            metadata_keys.add(entry["entry_key"])
        elif live and entry["route"] == "process-local-pdf":
            pdf_keys.add(entry["entry_key"])
    completed_keys = exact_keys | metadata_keys | pdf_keys
    report = {
        "version": 1,
        "denominator": 2100,
        "target": 525,
        "completed": len(completed_keys),
        "exact_existing": len(exact_keys),
        "metadata_only_verified": len(metadata_keys),
        "process_local_pdf_verified": len(pdf_keys),
        "review_not_counted": sum(row["status"] in {"review", "invalid-source"} for row in rows),
        "attachment_review_fragments": sum(
            len(row.get("attachment_review", [])) for row in rows
        ),
        "failed_not_counted": len(failed_keys),
        "inventory_statuses": dict(sorted(Counter(row["status"] for row in rows).items())),
        "inventory_routes": dict(sorted(Counter(row["route"] for row in rows).items())),
        "change_actions": dict(sorted(actions.items())),
        "batches_completed": batches,
        "milestone_reached": len(completed_keys) >= 525,
    }
    write_json(output_path, report)
    if not report["milestone_reached"]:
        raise ValueError(f"milestone incomplete: {len(completed_keys)}/525")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zotero-bibtex-migration")
    sub = parser.add_subparsers(dest="command", required=True)

    inventory = sub.add_parser("inventory")
    inventory.add_argument("--source", type=Path, required=True)
    inventory.add_argument("--project-root", type=Path, required=True)
    inventory.add_argument("--output-dir", type=Path, required=True)
    inventory.add_argument("--theme-decisions", type=Path)
    inventory.add_argument("--pilot-keys", type=Path)

    merge = sub.add_parser("merge-themes")
    merge.add_argument("--catalog", type=Path, required=True)
    merge.add_argument("--input-dir", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)

    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("--project-root", type=Path, required=True)
    apply_cmd.add_argument("--inventory", type=Path, required=True)
    apply_cmd.add_argument("--batch", type=int, required=True)
    apply_cmd.add_argument("--approved-keys", type=Path, required=True)
    apply_cmd.add_argument("--output-dir", type=Path, required=True)

    finalize = sub.add_parser("finalize")
    finalize.add_argument("--project-root", type=Path, required=True)
    finalize.add_argument("--inventory", type=Path, required=True)
    finalize.add_argument("--changes", type=Path, required=True)
    finalize.add_argument("--entry-key", required=True)

    failure = sub.add_parser("record-failure")
    failure.add_argument("--project-root", type=Path, required=True)
    failure.add_argument("--inventory", type=Path, required=True)
    failure.add_argument("--changes", type=Path, required=True)
    failure.add_argument("--review", type=Path, required=True)
    failure.add_argument("--entry-key", required=True)
    failure.add_argument("--reason", required=True)

    verify = sub.add_parser("verify-batch")
    verify.add_argument("--project-root", type=Path, required=True)
    verify.add_argument("--changes", type=Path, required=True)

    progress = sub.add_parser("progress")
    progress.add_argument("--inventory", type=Path, required=True)
    progress.add_argument("--changes-dir", type=Path, required=True)

    report = sub.add_parser("report")
    report.add_argument("--inventory", type=Path, required=True)
    report.add_argument("--changes-dir", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "inventory":
            result = run_inventory(
                args.source, args.project_root, args.output_dir,
                args.theme_decisions, args.pilot_keys,
            )
            output = {
                "entries": len(result["entries"]),
                "statuses": dict(Counter(row["status"] for row in result["entries"])),
                "temp_dir": result["temp_dir"],
            }
        elif args.command == "merge-themes":
            count = merge_theme_decisions(args.catalog, args.input_dir, args.output)
            output = {"decisions": count, "output": str(args.output)}
        elif args.command == "apply":
            output = apply_batch(
                args.project_root, args.inventory, args.batch,
                args.approved_keys, args.output_dir,
            )
        elif args.command == "finalize":
            output = finalize_entry(
                args.project_root, args.inventory, args.changes, args.entry_key,
            )
        elif args.command == "record-failure":
            output = record_failure(
                args.project_root, args.inventory, args.changes,
                args.review, args.entry_key, args.reason,
            )
        elif args.command == "verify-batch":
            output = verify_changes(args.project_root, args.changes)
        elif args.command == "progress":
            output = progress_summary(args.inventory, args.changes_dir)
        else:
            output = milestone_report(args.inventory, args.changes_dir, args.output)
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, StopIteration, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
