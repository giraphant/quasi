"""Source-bound MinerU provenance and disagreement evidence carried by the PDF.

Agreement with an old OCR layer is not ground truth. Keep the new recognition,
record disagreements for inspection, and never call an unavailable baseline a
successful check. This metadata travels with the only CLI-owned output path.
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

import pymupdf

if __package__:
    from . import layout_evidence
else:
    import layout_evidence

KEY = "QuasiOCR"
SCHEMA = "quasi.ocr.evidence/0.1"
PROFILE = "mineru25-pro-2605-text/1"
MODEL = "opendatalab/MinerU2.5-Pro-2605-1.2B"
THRESHOLD = 0.85
REFERENCE_TYPES = {"ref_text", "page_footnote", "table_footnote"}


def words(text: str) -> list[str]:
    # Compare discretionary and compound hyphens alike in both layers. Only
    # the comparison changes: the recognized text retains its original spelling.
    text = re.sub(r"(?<=\w)[-‐‑\u00ad]\s*(?=\w)", "", text)
    return re.findall(r"[a-zA-ZÀ-ÖØ-öø-ÿ]+|[\u3400-\u9fff]", text.casefold())


def reference_heading(page, blocks: list[dict]) -> bool:
    headings = {"notes", "endnotes", "references", "bibliography", "works cited"}
    reported = {b["content"].strip().casefold() for b in blocks
                if b["type"] in {"header", "title", "paragraph_title"} and b["bbox"][1] < .15}
    top = page.rect
    top.y1 = top.y0 + top.height * .15
    existing = {line.strip().casefold() for line in page.get_text(clip=top).splitlines()}
    return bool(headings & reported & existing)


def empty_quality() -> dict:
    return {"threshold": THRESHOLD, "policy": "retain-new-and-report",
            "checked_blocks": 0, "reference_blocks": 0,
            "unavailable_pages": [], "empty_pages": [], "suspects": []}


def check_page(page, blocks: list[dict], page_number: int, quality: dict) -> None:
    if not blocks:
        quality["empty_pages"].append(page_number)
    baseline = words(page.get_text())
    if len(baseline) < 50:
        quality["unavailable_pages"].append(page_number)
        return
    reference_section = reference_heading(page, blocks)
    for index, block in enumerate(blocks):
        kind, text = block["type"], block["content"]
        dense_reference = reference_section and len(re.findall(r"\b\d{1,4}\s*[-–]\s*\d{1,4}\b", text)) >= 3
        if kind in REFERENCE_TYPES or (kind == "text" and dense_reference):
            quality["reference_blocks"] += 1
            continue
        if kind != "text":
            continue
        tokens = words(text)
        if len(tokens) < 10:
            continue
        quality["checked_blocks"] += 1
        match = difflib.SequenceMatcher(None, tokens, baseline, autojunk=False)
        agreement = sum(item.size for item in match.get_matching_blocks()) / len(tokens)
        if agreement < THRESHOLD:
            w, h = page.rect.width, page.rect.height
            rect = pymupdf.Rect(*(v * (w if i % 2 == 0 else h) for i, v in enumerate(block["bbox"])))
            quality["suspects"].append({
                "page": page_number, "block": index, "type": kind,
                "bbox": block["bbox"], "agreement": round(agreement, 6),
                "new_excerpt": text[:500], "old_excerpt": page.get_text(clip=rect)[:500],
            })


def valid_quality(value: object, pages: int) -> bool:
    if not isinstance(value, dict) or set(value) != set(empty_quality()):
        return False
    if value["threshold"] != THRESHOLD or value["policy"] != "retain-new-and-report":
        return False
    if any(type(value[k]) is not int or value[k] < 0 for k in ("checked_blocks", "reference_blocks")):
        return False
    for key in ("unavailable_pages", "empty_pages"):
        rows = value[key]
        if (not isinstance(rows, list) or any(type(p) is not int or not 1 <= p <= pages for p in rows)
                or len(set(rows)) != len(rows)):
            return False
    suspects = value["suspects"]
    if not isinstance(suspects, list):
        return False
    for row in suspects:
        if not isinstance(row, dict) or set(row) != {
            "page", "block", "type", "bbox", "agreement", "new_excerpt", "old_excerpt"
        }:
            return False
        if (type(row["page"]) is not int or not 1 <= row["page"] <= pages
                or type(row["block"]) is not int or row["block"] < 0 or row["type"] != "text"
                or not isinstance(row["agreement"], (int, float)) or not 0 <= row["agreement"] < THRESHOLD
                or not all(isinstance(row[k], str) for k in ("new_excerpt", "old_excerpt"))):
            return False
        box = row["bbox"]
        if (not isinstance(box, list) or len(box) != 4
                or any(type(v) not in (int, float) or not 0 <= v <= 1 for v in box)
                or box[0] >= box[2] or box[1] >= box[3]):
            return False
    return len(suspects) <= value["checked_blocks"]


def stamp(document, *, source_sha256: str, quality: dict, model: str) -> None:
    assert valid_quality(quality, len(document))
    evidence = {"schema_version": SCHEMA, "profile": PROFILE,
                "source_sha256": source_sha256, "model": model,
                "pages": len(document), "text_sha256": layout_evidence.text_sha256(document),
                "quality": quality}
    document.xref_set_key(document.pdf_catalog(), KEY, pymupdf.get_pdf_str(json.dumps(evidence, ensure_ascii=False)))


def read(document) -> dict | None:
    kind, raw = document.xref_get_key(document.pdf_catalog(), KEY)
    try:
        value = json.loads(raw) if kind == "string" else None
    except (ValueError, TypeError):
        return None
    if (not isinstance(value, dict) or value.get("schema_version") != SCHEMA
            or value.get("profile") != PROFILE or value.get("pages") != len(document)
            or value.get("model") != MODEL
            or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("source_sha256", "")))
            or value.get("text_sha256") != layout_evidence.text_sha256(document)
            or not valid_quality(value.get("quality"), len(document))):
        return None
    return value


def inspect(path: Path) -> dict | None:
    with pymupdf.open(path) as document:
        return read(document)


def combine(rows: list[tuple[int, dict]]) -> dict:
    quality = empty_quality()
    for offset, part in rows:
        quality["checked_blocks"] += part["checked_blocks"]
        quality["reference_blocks"] += part["reference_blocks"]
        quality["unavailable_pages"].extend(p + offset for p in part["unavailable_pages"])
        quality["empty_pages"].extend(p + offset for p in part["empty_pages"])
        quality["suspects"].extend({**row, "page": row["page"] + offset} for row in part["suspects"])
    return quality
