"""Image-page classification and in-PDF evidence for layout OCR outputs."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pymupdf

KEY = "QuasiLayout"
SCHEMA = "quasi.ocr.layout/0.2"
PROFILE = "mineru25-pro-2605-layout/1"


def has_page_image(page) -> bool:
    # ABBYY scans can name their text font TimesNewRomanPSMT. Font names do
    # not tell us whether the visible page is an image.
    return bool(page.get_images())


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_sha256(document) -> str:
    digest = hashlib.sha256()
    for page in document:
        data = page.get_text().encode("utf-8")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def stamp(document, *, source_sha256: str, grouped_pages: int, paragraphs: int) -> None:
    evidence = {
        "schema_version": SCHEMA,
        "profile": PROFILE,
        "source_sha256": source_sha256,
        "pages": len(document),
        "image_pages": sum(has_page_image(page) for page in document),
        "grouped_pages": grouped_pages,
        "paragraphs": paragraphs,
        "text_sha256": text_sha256(document),
    }
    document.xref_set_key(document.pdf_catalog(), KEY, pymupdf.get_pdf_str(json.dumps(evidence)))


def inspect(path: Path, *, source_sha256: str | None = None) -> dict:
    """Read exact PDF evidence; a recovery filename alone never proves layout."""
    with pymupdf.open(path) as document:
        image_pages = sum(has_page_image(page) for page in document)
        kind, raw = document.xref_get_key(document.pdf_catalog(), KEY)
        try:
            evidence = json.loads(raw) if kind == "string" else None
        except (TypeError, ValueError):
            evidence = None
        prepared = (
            isinstance(evidence, dict)
            and evidence.get("schema_version") == SCHEMA
            and evidence.get("profile") == PROFILE
            and isinstance(evidence.get("source_sha256"), str)
            and re.fullmatch(r"[a-f0-9]{64}", evidence["source_sha256"]) is not None
            and (source_sha256 is None or evidence["source_sha256"] == source_sha256)
            and evidence.get("pages") == len(document)
            and evidence.get("image_pages") == image_pages
            and type(evidence.get("grouped_pages")) is int
            and type(evidence.get("paragraphs")) is int
            and 0 <= evidence["grouped_pages"] <= image_pages
            and evidence["paragraphs"] >= evidence["grouped_pages"]
            and (image_pages == 0 or evidence["grouped_pages"] > 0)
            and evidence.get("text_sha256") == text_sha256(document)
        )
        return {"pages": len(document), "image_pages": image_pages, "prepared": bool(prepared)}
