#!/usr/bin/env python3
"""Build an aligned original-side text layer from MinerU paragraph and line evidence.

The translation provider must see the paragraph-flow PDF.  This module builds
a second, locally staged version for the original side of a dual PDF only.
"""
from __future__ import annotations

import difflib
import hashlib
import importlib
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pymupdf as fitz

# Some other command entry points import scripts/extract/extract.py as the
# top-level ``extract`` module.  It is not a package, so never rely on that
# name to resolve the OCR sibling modules in a long-lived interpreter.
if __package__ == "scripts.translate":
    from scripts.extract import layout_evidence, ocr_mineru
else:
    _extract_dir = Path(__file__).resolve().parents[1] / "extract"
    _extract_package = "quasi_selection_extract_" + hashlib.sha256(str(_extract_dir).encode()).hexdigest()[:16]
    if _extract_package not in sys.modules:
        _package = types.ModuleType(_extract_package)
        _package.__path__ = [str(_extract_dir)]
        sys.modules[_extract_package] = _package
    layout_evidence = importlib.import_module(f"{_extract_package}.layout_evidence")
    ocr_mineru = importlib.import_module(f"{_extract_package}.ocr_mineru")

MODEL_REVISION = "53ff4f970f0d0a9609da2018e9b015df5166cab8"
MODEL_REPO = "opendatalab/MinerU-4_models_onnx"
MODEL_FILES = {
    "OCR/paddleocr/ch_PP-OCRv6_tiny_det_infer.onnx": "193bab7a04fca699a6c82e6abb5b81bdb28177f0abd4062552b04908dafb19f8",
    "OCR/paddleocr/ch_PP-OCRv6_small_rec_infer.onnx": "5435fd747c9e0efe15a96d0b378d5bd157e9492ed8fd80edf08f30d02fa24634",
}
_OCR_COMMAND = ["uvx", "--python", "3.12", "--from", "mineru==4.2.0",
                "--with", "opencv-python-headless==5.0.0.93", "python", "-c"]

# This executes in uv's isolated MinerU environment, never in the main venv.
# Results use source-page normalized coordinates and retain text confidence.
_OCR_RUNNER = r'''
import hashlib, json, os, sys
import cv2
import numpy as np
from huggingface_hub import hf_hub_download
from mineru.model.ocr.pp_ocr_v6_onnx import PPOCRv6ONNX

request_path, result_path, cache_dir = sys.argv[1:]
request = json.load(open(request_path, encoding="utf-8"))
models = []
for name, expected in request["model_files"].items():
    path = hf_hub_download(repo_id=request["model_repo"], filename=name,
                           revision=request["model_revision"], cache_dir=cache_dir)
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("MinerU OCR model checksum mismatch: " + name)
    models.append(path)
ocr = PPOCRv6ONNX(det_model_path=models[0], rec_model_path=models[1],
                  det_db_box_thresh=0.3, drop_score=0.0, intra_op_num_threads=4)
pages = []
successful_blocks = failed_blocks = 0
for page_no, row in enumerate(request["pages"], 1):
    if row is None:
        pages.append([])
        continue
    if row.get("skip_reason"):
        pages.append(None)
        print(f"[selection] page {page_no}: {row['skip_reason']}", file=sys.stderr, flush=True)
        continue
    image = cv2.imread(row["image"], cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("could not read rendered page " + str(page_no))
    height, width = image.shape[:2]
    blocks = []
    for block in row["blocks"]:
        try:
            x0, y0, x1, y1 = block["bbox"]
            left, top = max(0, int(x0 * width)), max(0, int(y0 * height))
            right, bottom = min(width, int(np.ceil(x1 * width))), min(height, int(np.ceil(y1 * height)))
            if right <= left or bottom <= top:
                raise ValueError("empty OCR region on page " + str(page_no))
            crop = image[top:bottom, left:right]
            angle = block["angle"]
            if angle == 90:
                crop = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif angle == 180:
                crop = cv2.rotate(crop, cv2.ROTATE_180)
            elif angle == 270:
                crop = cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)
            elif angle != 0:
                raise ValueError("unsupported OCR text angle on page " + str(page_no))
            crop = cv2.copyMakeBorder(crop, 50, 50, 50, 50,
                                      cv2.BORDER_CONSTANT, value=(255, 255, 255))
            detected = ocr.ocr(crop, det=True, rec=True)[0] or []
            lines = []
            for corners, result in detected:
                points = np.asarray(corners, dtype=float) - 50
                px, py = points[:, 0].copy(), points[:, 1].copy()
                crop_width, crop_height = right - left, bottom - top
                if angle == 90:
                    points[:, 0], points[:, 1] = crop_width - py, px
                elif angle == 180:
                    points[:, 0], points[:, 1] = crop_width - px, crop_height - py
                elif angle == 270:
                    points[:, 0], points[:, 1] = py, crop_height - px
                px0 = max(left, left + points[:, 0].min())
                py0 = max(top, top + points[:, 1].min())
                px1 = min(right, left + points[:, 0].max())
                py1 = min(bottom, top + points[:, 1].max())
                if px0 < px1 and py0 < py1:
                    lines.append({"text": result[0], "confidence": float(result[1]),
                                  "bbox": [px0 / width, py0 / height, px1 / width, py1 / height]})
            blocks.append(lines)
            successful_blocks += 1
        except Exception as exc:
            failed_blocks += 1
            reason = f"native OCR block failed: {type(exc).__name__}: {exc}"
            print(f"[selection] page {page_no}: {reason}", file=sys.stderr, flush=True)
            blocks.append([{"error": reason}])
    pages.append(blocks)
    print(f"[selection] detected lines: page {page_no}/{len(request['pages'])}", file=sys.stderr, flush=True)
if failed_blocks and not successful_blocks:
    raise RuntimeError("native OCR failed on every attempted block")
with open(result_path, "w", encoding="utf-8") as handle:
    json.dump(pages, handle, ensure_ascii=False)
'''


class SelectionAlignmentError(ValueError):
    """Line evidence cannot safely place all recognized source text."""


def _compact_text(value: str) -> str:
    return "".join(ch for ch in value if not ch.isspace())


def _layout_characters(page: fitz.Page) -> list[tuple[str, float, float]]:
    """Source layout characters with ink centres in extraction order."""
    result = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for char in span.get("chars", []):
                    box = fitz.Rect(char["bbox"])
                    for value in _compact_text(char.get("c", "")):
                        result.append((value, (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2))
    return result


def read_bound_recognition(source: Path, recognition_path: Path) -> list[list[dict]]:
    """Match sidecar and embedded review to the exact layout preparation."""
    evidence = layout_evidence.inspect(source)
    if not evidence["prepared"]:
        raise SelectionAlignmentError("selection source lacks valid layout evidence")
    with fitz.open(source) as doc:
        kind, value = doc.xref_get_key(doc.pdf_catalog(), layout_evidence.KEY)
        if kind != "string":
            raise SelectionAlignmentError("selection source lacks embedded layout evidence")
        record = json.loads(value)
        original_sha = record["source_sha256"]
        try:
            pages = ocr_mineru.read_recognition(recognition_path, original_sha, len(doc))
        except (ValueError, OSError) as exc:
            raise SelectionAlignmentError(f"invalid source-bound recognition: {exc}") from exc
        if pages is None:
            raise SelectionAlignmentError(f"source-bound recognition is missing: {recognition_path}")
        pages = list(pages)
        review = record.get("review")
        if review is not None:
            if not isinstance(review, dict) or review.get("source_sha256") != original_sha:
                raise SelectionAlignmentError("embedded review does not match original source")
            seen = set()
            for row in review.get("pages", []):
                page_no = row.get("page") if isinstance(row, dict) else None
                if (type(page_no) is not int or page_no < 1 or page_no > len(doc) or page_no in seen
                        or not isinstance(row.get("blocks"), list)):
                    raise SelectionAlignmentError("invalid embedded review page")
                seen.add(page_no)
                pages[page_no - 1] = row["blocks"]
        for index, page in enumerate(doc):
            # A rotated page is retained unchanged, so no line coordinates
            # need to be derived from its layout text.
            if not layout_evidence.has_page_image(page) or page.rotation:
                continue
            blocks = [block for block in ocr_mineru.normalize_blocks(pages[index], layout=True)
                      if block["type"] in ocr_mineru.TEXT]
            if not blocks:
                if _compact_text(page.get_text()):
                    raise SelectionAlignmentError(f"page {index + 1}: recognition does not match layout text")
                continue
            _, _, texts = ocr_mineru.pick_font([block["content"] for block in blocks])
            expected_words = " ".join(" ".join(text.split()) for text in texts)
            actual_words = " ".join(page.get_text().split())
            if expected_words != actual_words:
                raise SelectionAlignmentError(f"page {index + 1}: recognition word boundaries do not match layout text")
            expected = _compact_text("".join(texts))
            characters = _layout_characters(page)
            actual = "".join(char for char, _, _ in characters)
            if expected != actual:
                raise SelectionAlignmentError(f"page {index + 1}: recognition does not match layout text")
            offset = 0
            for block, text in zip(blocks, texts):
                count = len(_compact_text(text))
                rect = ocr_mineru.rectangle(page, block)
                # Glyph centres can extend slightly outside the OCR box for
                # font ascenders/descenders; reject content elsewhere on page.
                rect += (-2, -2, 2, 2)
                for _, x, y in characters[offset:offset + count]:
                    if not rect.contains(fitz.Point(x, y)):
                        raise SelectionAlignmentError(
                            f"page {index + 1}, block {block['source_block']}: "
                            "recognition geometry does not match layout text"
                        )
                offset += count
        return pages


def detect_lines(source: Path, pages: list[list[dict]], work_dir: Path) -> list[list[list[dict]]]:
    """Run pinned MinerU native line OCR locally before starting a provider."""
    if not shutil.which("uvx"):
        raise SelectionAlignmentError("selection OCR requires uvx")
    work_dir.mkdir(parents=True, exist_ok=True)
    request: dict[str, Any] = {"model_repo": MODEL_REPO, "model_revision": MODEL_REVISION,
                               "model_files": MODEL_FILES, "pages": []}
    with fitz.open(source) as doc:
        if len(doc) != len(pages):
            raise SelectionAlignmentError("recognition and PDF page counts differ")
        for index, page in enumerate(doc):
            if not layout_evidence.has_page_image(page):
                request["pages"].append(None)
                continue
            blocks = [block for block in ocr_mineru.normalize_blocks(pages[index], layout=True)
                      if block["type"] in ocr_mineru.TEXT]
            if page.rotation:
                request["pages"].append({"skip_reason": "rotated PDF page retained", "blocks": blocks})
                continue
            image_path = work_dir / f"page-{index + 1:06}.png"
            page.get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72), alpha=False, annots=False).save(image_path)
            request["pages"].append({"image": str(image_path), "blocks": blocks})
    input_path, output_path = work_dir / "input.json", work_dir / "lines.json"
    input_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    data_root = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or Path.home() / ".cache" / "quasi")
    try:
        subprocess.run(_OCR_COMMAND + [_OCR_RUNNER, str(input_path), str(output_path),
                                       str(data_root / "selection-models")],
                       check=True, stdout=sys.stderr)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SelectionAlignmentError(f"MinerU line detection failed: {exc}") from exc
    try:
        result = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SelectionAlignmentError("MinerU line detection did not return complete results") from exc
    if not isinstance(result, list) or len(result) != len(pages):
        raise SelectionAlignmentError("MinerU line detection returned incomplete pages")
    return result


def prepare_selection(source: Path, recognition_path: Path, work_dir: Path) -> Path | None:
    """Prepare an aligned source before provider work; native PDFs need none."""
    with fitz.open(source) as doc:
        if not any(layout_evidence.has_page_image(page) for page in doc):
            return None
    pages = read_bound_recognition(source, recognition_path)
    work_dir.mkdir(parents=True, exist_ok=True)
    lines = detect_lines(source, pages, work_dir / "detection")
    staged = work_dir / "selection-source.pdf"
    build_selection_source(source, staged, pages, lines)
    return staged


def _graft_problem(dual: fitz.Document, source: fitz.Document, index: int) -> str | None:
    """Check one original-side graft without mutating the candidate."""
    try:
        page, source_page = dual[2 * index], source[index]
        if (page.rotation != source_page.rotation
                or abs(page.rect.width - source_page.rect.width) > 0.05
                or abs(page.rect.height - source_page.rect.height) > 0.05):
            return "provider original page geometry differs"
        before = page.get_pixmap(alpha=False, annots=False)
        expected = source_page.get_pixmap(alpha=False, annots=False)
        if (before.width != expected.width or before.height != expected.height
                or before.samples != expected.samples):
            return "provider original page image differs"
        with fitz.open() as trial:
            trial.insert_pdf(dual, from_page=2 * index, to_page=2 * index)
            probe = trial[0]
            empty = trial.get_new_xref()
            trial.update_object(empty, "<<>>")
            trial.update_stream(empty, b"")
            probe.set_contents(empty)
            probe.show_pdf_page(probe.rect, source, index, keep_proportion=False, overlay=True)
            after = probe.get_pixmap(alpha=False, annots=False)
            if (before.width != after.width or before.height != after.height or before.samples != after.samples):
                return "source-page graft changed rendered pixels"
            if " ".join(probe.get_text().split()) != " ".join(source_page.get_text().split()):
                return "source-page graft changed selectable text"
    except (ValueError, RuntimeError) as exc:
        return f"source-page graft could not be checked: {exc}"
    return None


def apply_selection_source(candidate: Path, selection_source: Path) -> None:
    """Replace only scan originals in a staged dual PDF, without changing pages.

    Original page objects, annotations, destinations, and translated pages stay
    in the existing document.  A grafted source form avoids mutating any of the
    provider's potentially shared text or image streams.
    """
    candidate, selection_source = Path(candidate), Path(selection_source)
    replacement = candidate.with_name(f".{candidate.name}.selection")
    if replacement.exists():
        raise SelectionAlignmentError("selection staging path already exists")
    try:
        with fitz.open(candidate) as dual, fitz.open(selection_source) as source:
            if len(dual) != len(source) * 2:
                raise SelectionAlignmentError("selection and dual PDF page counts differ")
            kind, selection_evidence = source.xref_get_key(source.pdf_catalog(), "QuasiSelection")
            if kind != "string":
                raise SelectionAlignmentError("selection source lacks embedded selection evidence")
            try:
                evidence = json.loads(selection_evidence)
            except (TypeError, ValueError) as exc:
                raise SelectionAlignmentError("selection source has invalid embedded evidence") from exc
            if (not isinstance(evidence, dict) or evidence.get("schema") != "quasi.selection.evidence/0.1"
                    or not isinstance(evidence.get("fallback_blocks"), list)):
                raise SelectionAlignmentError("selection source has invalid embedded evidence")
            skipped = list(evidence.get("skipped_pages", []))
            skip_numbers = {record["page"] for record in skipped}
            page_stats = {row["page"]: row for row in evidence.get("page_stats", [])}
            for page_no in skip_numbers:
                if page_no in page_stats:
                    page_stats[page_no]["applied"] = False
            for index, source_page in enumerate(source):
                if not layout_evidence.has_page_image(source_page) or index + 1 in skip_numbers:
                    continue
                page = dual[2 * index]
                reason = _graft_problem(dual, source, index)
                if reason:
                    record = {"page": index + 1, "reason": reason}
                    skipped.append(record)
                    if index + 1 in page_stats:
                        page_stats[index + 1]["applied"] = False
                    print(f"[selection] retained provider original page: {json.dumps(record, ensure_ascii=False)}",
                          file=sys.stderr)
                    continue
                before = page.get_pixmap(alpha=False, annots=False)
                empty_xref = dual.get_new_xref()
                dual.update_object(empty_xref, "<<>>")
                dual.update_stream(empty_xref, b"")
                page.set_contents(empty_xref)
                page.show_pdf_page(page.rect, source, index, keep_proportion=False, overlay=True)
                after = page.get_pixmap(alpha=False, annots=False)
                if (before.width != after.width or before.height != after.height
                        or before.samples != after.samples
                        or " ".join(page.get_text().split()) != " ".join(source_page.get_text().split())):
                    raise SelectionAlignmentError(f"page {index + 1}: graft differs from checked trial")
                if index + 1 in page_stats:
                    page_stats[index + 1]["applied"] = True
            evidence["skipped_pages"] = skipped
            selection_evidence = json.dumps(evidence, ensure_ascii=False)
            dual.xref_set_key(dual.pdf_catalog(), "QuasiSelection", fitz.get_pdf_str(selection_evidence))
            dual.save(replacement, garbage=0, deflate=True)
        os.replace(replacement, candidate)
    finally:
        replacement.unlink(missing_ok=True)


def _characters(text: str) -> list[tuple[str, int]]:
    """Comparison characters and offsets, without changing the emitted text."""
    result = []
    for index, char in enumerate(text):
        if char.isalnum():
            result.extend((folded, index) for folded in char.casefold())
    return result


def align_lines(text: str, lines: list[dict[str, Any]]) -> list[str]:
    """Assign original VLM characters to independently detected physical lines.

    An OCR-visible end-of-line hyphen is retained for PDF readers that join
    physically broken words. Other punctuation is preserved from the VLM.
    A mismatch that could belong to either side of a line boundary fails.
    """
    if not isinstance(text, str) or not text.strip() or not isinstance(lines, list) or not lines:
        raise SelectionAlignmentError("missing paragraph text or OCR lines")
    source = _characters(text)
    observed: list[tuple[str, int]] = []
    for line_no, line in enumerate(lines):
        if not isinstance(line, dict) or not isinstance(line.get("text"), str):
            raise SelectionAlignmentError(f"line {line_no + 1}: missing OCR text")
        chars = _characters(line["text"])
        if not chars:
            raise SelectionAlignmentError(f"line {line_no + 1}: no OCR characters")
        observed.extend((char, line_no) for char, _ in chars)
    if not source or not observed:
        raise SelectionAlignmentError("paragraph has no comparable characters")

    matcher = difflib.SequenceMatcher(None, [c for c, _ in observed], [c for c, _ in source], autojunk=False)
    if matcher.ratio() < 0.85:
        raise SelectionAlignmentError(f"OCR and VLM text disagree ({matcher.ratio():.3f})")
    owners: list[int | None] = [None] * len(source)
    for tag, i, j, k, end in matcher.get_opcodes():
        if tag == "equal":
            for old, new in zip(range(i, j), range(k, end)):
                owners[new] = observed[old][1]
            continue
        # Deletions have no VLM character to assign.  Replacements and
        # insertions are safe only when their entire context is on one line.
        if k == end:
            continue
        context = {observed[pos][1] for pos in range(i, j)}
        if not context:
            context = {observed[pos][1] for pos in (i - 1, i) if 0 <= pos < len(observed)}
        if len(context) != 1:
            raise SelectionAlignmentError("ambiguous OCR mismatch at a line boundary")
        owner = next(iter(context))
        for pos in range(k, end):
            owners[pos] = owner
    if any(owner is None for owner in owners):
        raise SelectionAlignmentError("some VLM characters could not be located")
    if owners != sorted(owners):
        raise SelectionAlignmentError("OCR line order disagrees with VLM reading order")

    boundaries = []
    for line_no in range(len(lines)):
        indices = [index for index, owner in enumerate(owners) if owner == line_no]
        if not indices:
            raise SelectionAlignmentError(f"line {line_no + 1}: no VLM text could be located")
        boundaries.append(source[indices[0]][1])
    boundaries[0] = 0
    boundaries.append(len(text))
    chunks = []
    original_chunks = []
    for line_no, line in enumerate(lines):
        chunk = text[boundaries[line_no]:boundaries[line_no + 1]].strip()
        if not chunk:
            raise SelectionAlignmentError(f"line {line_no + 1}: empty VLM text")
        original_chunks.append(chunk)
        # Physical wrap hyphens improve search and copy in PDF readers; do not
        # remove real hyphens already present in the recognized paragraph.
        if (line_no + 1 < len(lines) and line["text"].rstrip().endswith("-") and not chunk.endswith("-")):
            chunk += "-"
        chunks.append(chunk)
    if "".join("".join(chunk.split()) for chunk in original_chunks) != "".join(text.split()):
        raise SelectionAlignmentError("line splitting changed recognized paragraph text")
    return chunks


def _checked_rect(page: fitz.Page, box: object) -> fitz.Rect:
    if (not isinstance(box, (list, tuple)) or len(box) != 4
            or any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1 for value in box)
            or box[0] >= box[2] or box[1] >= box[3]):
        raise SelectionAlignmentError("invalid normalized OCR line box")
    return fitz.Rect(box[0] * page.rect.width, box[1] * page.rect.height,
                     box[2] * page.rect.width, box[3] * page.rect.height)


def _ordered_lines(page: fitz.Page, lines: list[dict], angle: int = 0) -> list[dict]:
    """Order physical lines within a paragraph; ambiguous rows use fallback."""
    checked = [(line, _checked_rect(page, line.get("bbox"))) for line in lines]
    if angle == 0:
        checked.sort(key=lambda item: ((item[1].y0 + item[1].y1) / 2, item[1].x0))
    elif angle == 90:
        checked.sort(key=lambda item: (-(item[1].x0 + item[1].x1) / 2, item[1].y0))
    elif angle == 180:
        checked.sort(key=lambda item: (-(item[1].y0 + item[1].y1) / 2, -item[1].x1))
    elif angle == 270:
        checked.sort(key=lambda item: ((item[1].x0 + item[1].x1) / 2, -item[1].y1))
    else:
        raise SelectionAlignmentError("unsupported OCR text angle")
    for (_, first), (_, second) in zip(checked, checked[1:]):
        if angle in {90, 270}:
            a0, a1, b0, b1 = first.x0, first.x1, second.x0, second.x1
        else:
            a0, a1, b0, b1 = first.y0, first.y1, second.y0, second.y1
        overlap = min(a1, b1) - max(a0, b0)
        separation = abs((a0 + a1 - b0 - b1) / 2)
        if overlap > 0.65 * min(a1 - a0, b1 - b0) and separation < 0.35 * max(a1 - a0, b1 - b0):
            raise SelectionAlignmentError("multiple OCR boxes share a physical row")
    return [line for line, _ in checked]


def _selection_font(texts: list[str]) -> tuple[str, str | None]:
    """Choose a round-tripping font without changing VLM punctuation."""
    try:
        "".join(texts).encode("latin-1")
        return "helv", None
    except UnicodeEncodeError:
        pass
    required = tuple(sorted({ord(char) for text in texts for char in text if not char.isspace()}))
    rejected = []
    for candidate in ocr_mineru._FONT_FILES:
        if not Path(candidate).is_file():
            continue
        font = ocr_mineru._unicode_font(candidate)
        if any(not font.has_glyph(code) for code in required):
            rejected.append(f"{Path(candidate).name}: missing glyph")
            continue
        if not ocr_mineru._font_roundtrips(candidate, required):
            rejected.append(f"{Path(candidate).name}: failed text round trip")
            continue
        name = "quasiunicode" + hashlib.sha256(candidate.encode()).hexdigest()[:8]
        return name, candidate
    raise SelectionAlignmentError("no available font can faithfully encode recognized text: "
                                  + ("; ".join(rejected) or "no font files"))


def _line_object(page: fitz.Page, texts: list[str], boxes: list[fitz.Rect],
                 fontname: str, fontfile: str | None, angle: int = 0) -> None:
    """Write all lines as a single invisible text object with one font size."""
    if len(texts) != len(boxes) or not texts:
        raise SelectionAlignmentError("line text/box count mismatch")
    font = fitz.Font(fontfile=fontfile) if fontfile else fitz.Font(fontname=fontname)
    size = statistics.median(box.width if angle in {90, 270} else box.height for box in boxes) / 1.2
    max_size = max(60.0, min(page.rect.width, page.rect.height) * 0.20)
    if not 3 <= size <= max_size:
        raise SelectionAlignmentError(f"unreasonable line font size: {size:.2f}pt")
    pieces = []
    for text, box in zip(texts, boxes):
        width = font.text_length(text, fontsize=size)
        if width <= 0:
            raise SelectionAlignmentError("could not measure line text")
        scale = (box.height if angle in {90, 270} else box.width) / width
        if not 0.45 <= scale <= 2.1:
            raise SelectionAlignmentError(f"unreasonable horizontal text scaling: {scale:.3f}")
        if angle == 0:
            origin = fitz.Point(box.x0, box.y0 + size * 0.9)
            matrix = f"{scale:.9f} 0 0 1"
        elif angle == 90:
            origin = fitz.Point(box.x1 - size * 0.9, box.y0)
            matrix = f"0 {-scale:.9f} 1 0"
        elif angle == 180:
            origin = fitz.Point(box.x1, box.y1 - size * 0.9)
            matrix = f"{-scale:.9f} 0 0 -1"
        elif angle == 270:
            origin = fitz.Point(box.x0 + size * 0.9, box.y1)
            matrix = f"0 {scale:.9f} -1 0"
        else:
            raise SelectionAlignmentError("unsupported OCR text angle")
        shape = page.new_shape()
        shape.insert_text(origin, text, fontsize=size, fontname=fontname, fontfile=fontfile, render_mode=3)
        # Shape produces a known single-line object.  Set horizontal scale in
        # its text matrix instead of per-line graphics transforms, so readers
        # see one coherent paragraph and every line keeps its own location.
        match = re.fullmatch(r"\s*q\s+BT\s+(1 0 0 1 [^\n]+ Tm\s+.*?)\s+ET\s+Q\s*", shape.text_cont, re.S)
        if not match:
            raise SelectionAlignmentError("unexpected PDF writer text object")
        inner = match.group(1)
        inner = re.sub(r"^1 0 0 1 ", matrix + " ", inner, count=1)
        pieces.append(inner)
    page_shape = page.new_shape()
    page_shape.text_cont = "\nq\nBT\n" + "\n".join(pieces) + "\nET\nQ\n"
    page_shape.commit(overlay=True)


def _referenced_streams(page: fitz.Page) -> set[int]:
    refs = set(page.get_contents())
    refs.update(xref for xref, *_ in page.get_xobjects()
                if page.parent.xref_get_key(xref, "Subtype")[1] == "/Form")
    return refs


def _stripped_streams(page: fitz.Page) -> set[int]:
    """Streams strip_text would actually modify (shared image-only forms are safe)."""
    doc = page.parent
    page_streams = [(xref, doc.xref_stream(xref)) for xref in page.get_contents()]
    stripped = ocr_mineru._strip_text_objects(page_streams)
    changed = {xref for (xref, original), (_, result) in zip(page_streams, stripped) if original != result}
    for xref in _referenced_streams(page) - set(page.get_contents()):
        original = doc.xref_stream(xref)
        result = ocr_mineru._strip_text_objects([(xref, original)])[0][1]
        if original != result:
            changed.add(xref)
    return changed


def build_selection_source(source: Path, output: Path, pages: list[list[dict]],
                           detection: list[list[list[dict]]]) -> dict[str, Any]:
    """Place aligned scan paragraphs, retaining original-style layout for difficult blocks."""
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve() or output.exists():
        raise SelectionAlignmentError("selection output must be a new path")
    source_sha = layout_evidence.file_sha256(source)
    fallbacks: list[dict[str, Any]] = []
    expected_pages: dict[int, str] = {}
    page_stats = []
    skipped_pages = []
    with fitz.open(source) as doc:
        if len(pages) != len(doc) or len(detection) != len(doc):
            raise SelectionAlignmentError("recognition and PDF page counts differ")
        references: dict[int, set[int]] = {}
        for page_no, page in enumerate(doc):
            for xref in _referenced_streams(page):
                references.setdefault(xref, set()).add(page_no)
        for page_no, page in enumerate(doc):
            if not layout_evidence.has_page_image(page):
                page_stats.append({"page": page_no + 1, "kind": "native", "blocks": 0,
                                   "aligned": 0, "fallback": 0, "non_text_blocks": 0})
                continue
            all_blocks = ocr_mineru.normalize_blocks(pages[page_no], layout=True)
            blocks = [block for block in all_blocks if block["type"] in ocr_mineru.TEXT]
            non_text = len(all_blocks) - len(blocks)
            shared = [ref for ref in _stripped_streams(page) if len(references[ref]) > 1]
            if (page.rotation and detection[page_no] is None) or shared:
                reason = ("rotated PDF page retained" if page.rotation and detection[page_no] is None
                          else "text stream or Form shared across pages")
                record = {"page": page_no + 1, "reason": reason}
                skipped_pages.append(record)
                page_stats.append({"page": page_no + 1, "kind": "scan", "blocks": len(blocks),
                                   "aligned": 0, "fallback": 0, "skipped": True,
                                   "non_text_blocks": non_text})
                print(f"[selection] retained original page: {json.dumps(record, ensure_ascii=False)}", file=sys.stderr)
                continue
            if not isinstance(detection[page_no], list) or len(detection[page_no]) != len(blocks):
                raise SelectionAlignmentError(f"page {page_no + 1}: OCR block count mismatch")
            if not blocks:
                page_stats.append({"page": page_no + 1, "kind": "scan", "blocks": 0,
                                   "aligned": 0, "fallback": 0, "non_text_blocks": non_text})
                continue
            try:
                fontname, fontfile = _selection_font([block["content"] for block in blocks])
            except SelectionAlignmentError as exc:
                record = {"page": page_no + 1, "reason": str(exc)}
                skipped_pages.append(record)
                page_stats.append({"page": page_no + 1, "kind": "scan", "blocks": len(blocks),
                                   "aligned": 0, "fallback": 0, "skipped": True,
                                   "non_text_blocks": non_text})
                print(f"[selection] retained original page: {json.dumps(record, ensure_ascii=False)}", file=sys.stderr)
                continue
            ocr_mineru.strip_text(page)
            paragraphs = []
            aligned = 0
            for block, raw_lines in zip(blocks, detection[page_no]):
                text = block["content"]
                rect = ocr_mineru.rectangle(page, block)
                reason = None
                try:
                    if raw_lines and isinstance(raw_lines[0], dict) and raw_lines[0].get("error"):
                        raise SelectionAlignmentError(str(raw_lines[0]["error"]))
                    lines = _ordered_lines(page, raw_lines, block["angle"])
                    chunks = align_lines(text, lines)
                    boxes = [_checked_rect(page, line.get("bbox")) for line in lines]
                    if any(not (rect + (-2, -2, 2, 2)).contains(box) for box in boxes):
                        raise SelectionAlignmentError("OCR line is outside its paragraph box")
                    _line_object(page, chunks, boxes, fontname, fontfile, block["angle"])
                    paragraphs.append(" ".join(" ".join(chunk.split()) for chunk in chunks))
                    aligned += 1
                except (SelectionAlignmentError, TypeError) as exc:
                    reason = str(exc)
                if reason is not None:
                    # Reuse the same paragraph-placement logic as the source
                    # layout, retaining all recognized words and the VLM box.
                    rotate = (-block["angle"]) % 360
                    try:
                        size = ocr_mineru.natural_size(page, rect, text, fontname, fontfile, rotate=rotate)
                        for shrink in ocr_mineru.SHRINK:
                            if ocr_mineru._textbox(page, rect, text, size * shrink, fontname, fontfile,
                                                   rotate=rotate, commit=True) >= 0:
                                break
                        else:
                            raise ValueError("paragraph could not be placed")
                    except ValueError as exc:
                        raise SelectionAlignmentError(
                            f"page {page_no + 1}, block {block['source_block']}: paragraph fallback failed: {exc}"
                        ) from exc
                    record = {"page": page_no + 1, "block": block["source_block"], "reason": reason}
                    fallbacks.append(record)
                    print(f"[selection] paragraph fallback: {json.dumps(record, ensure_ascii=False)}", file=sys.stderr)
                    paragraphs.append(" ".join(text.split()))
            page_stats.append({"page": page_no + 1, "kind": "scan", "blocks": len(blocks),
                               "aligned": aligned, "fallback": len(blocks) - aligned,
                               "non_text_blocks": non_text})
            expected_pages[page_no] = " ".join(paragraphs)
        if layout_evidence.file_sha256(source) != source_sha:
            raise SelectionAlignmentError("selection source changed during preparation")
        evidence = {"schema": "quasi.selection.evidence/0.1", "source_sha256": source_sha,
                    "fallback_blocks": fallbacks, "page_stats": page_stats, "skipped_pages": skipped_pages}
        doc.xref_set_key(doc.pdf_catalog(), "QuasiSelection", fitz.get_pdf_str(json.dumps(evidence, ensure_ascii=False)))
        doc.save(output, garbage=3, deflate=True)
    try:
        with fitz.open(output) as written:
            for page_no, expected in expected_pages.items():
                actual = " ".join(written[page_no].get_text().split())
                if actual != expected:
                    raise SelectionAlignmentError(f"page {page_no + 1}: saved selection text differs from planned text")
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    total = sum(item["blocks"] for item in page_stats if not item.get("skipped"))
    print(f"[selection] {total - len(fallbacks)}/{total} blocks aligned; {len(fallbacks)} paragraph fallbacks",
          file=sys.stderr)
    return {"paragraphs": total, "pages": len(page_stats), "fallback_blocks": fallbacks,
            "page_stats": page_stats, "skipped_pages": skipped_pages}
