#!/usr/bin/env python3
"""One-shot Zotero BibTeX inventory and BTS migration."""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.customization import getnames

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN_ROOT))

from core import read_frontmatter  # noqa: E402
from scripts.citation.slug import parse_author_token  # noqa: E402
from scripts.localise.localise import normalise_isbn  # noqa: E402
from scripts.schemas import canonical_type  # noqa: E402
from scripts.schemas.body import BOOK_BODY, PAPER_BODY  # noqa: E402
from scripts.typecheck.typecheck import check_body  # noqa: E402
from scripts.vault.resolve import normalise_doi  # noqa: E402


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
