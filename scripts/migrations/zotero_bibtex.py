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
from scripts.typecheck.typecheck import check_body  # noqa: E402
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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    atomic_write_text(path, text)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or any(not isinstance(key, str) for key in data):
        raise ValueError("key file must be a JSON string array")
    if len(data) != len(set(data)):
        raise ValueError("key file contains duplicates")
    return set(data)


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

    args = parser.parse_args(argv)
    try:
        if args.command == "inventory":
            result = run_inventory(
                args.source, args.project_root, args.output_dir,
                args.theme_decisions, args.pilot_keys,
            )
            print(json.dumps({
                "entries": len(result["entries"]),
                "statuses": dict(Counter(row["status"] for row in result["entries"])),
                "temp_dir": result["temp_dir"],
            }, ensure_ascii=False, indent=2))
            return 0
        count = merge_theme_decisions(args.catalog, args.input_dir, args.output)
        print(json.dumps({"decisions": count, "output": str(args.output)}, indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
