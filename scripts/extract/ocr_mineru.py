#!/usr/bin/env python3
"""MinerU2.5-Pro recognition and paragraph placement, loaded once per invocation.

The default output is one reflowed text page per source page; --layout replaces
scan text while preserving the images. Neither path silently changes engines.
"""
from __future__ import annotations

import html
import hashlib
import json
import math
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections import Counter
from html.parser import HTMLParser
from functools import lru_cache
from pathlib import Path

import pymupdf as fitz
from pylatexenc.latex2text import LatexNodes2Text

if __package__:
    from . import layout_evidence, ocr_quality
else:
    import layout_evidence
    import ocr_quality

MODEL = ocr_quality.MODEL
RENDER_DPI = 200
SNAP = 0.20
LINE_HEIGHT = 1.15
SHRINK = (0.90, 0.85, 0.80, 0.75)
TEXT = {"text", "title", "paragraph_title", "page_footnote", "ref_text", "table_footnote",
        "table_caption", "image_caption", "header", "footer", "page_number", "aside_text"}
FURNITURE = {"header", "footer", "page_number", "aside_text"}
PICTURES = {"table", "equation", "image", "image_body", "table_body"}
TYPES = TEXT | PICTURES | {"list"}
_MINERU_CMD = [
    "uvx", "--python", "3.12", "--from", "mlx-vlm==0.7.3",
    "--with", "mlx==0.32.2", "--with", "mineru-vl-utils==2.0.5",
    "--with", "pillow", "--with", "torch", "--with", "torchvision", "python", "-c",
]
_RUNNER = r'''
import json, os, sys, time
from PIL import Image
from mineru_vl_utils import MinerUClient
started = time.monotonic()
client = MinerUClient(backend="mlx-engine", model_path=os.environ["MINERU_MODEL"])
print(f"[mineru] loaded in {time.monotonic()-started:.1f}s", file=sys.stderr, flush=True)
pngs = json.load(open(os.environ["MINERU_PNG_LIST"]))
pages = []
for i, path in enumerate(pngs, 1):
    started = time.monotonic()
    with Image.open(path) as image:
        blocks = client.two_step_extract(image)
    rows = []
    for block in blocks:
        rows.append({key: block.get(key) if isinstance(block, dict) else getattr(block, key, None)
                     for key in ("type", "bbox", "content", "angle")})
    pages.append(rows)
    print(f"[mineru] page {i}/{len(pngs)}: {len(rows)} blocks, {time.monotonic()-started:.1f}s",
          file=sys.stderr, flush=True)
with open(os.environ["MINERU_RESULTS"], "w") as handle:
    json.dump(pages, handle, ensure_ascii=False)
'''

_FONT_FILES = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/System/Library/Fonts/PingFang.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]
_ASCIIFY = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                         "–": "-", "—": "-", "…": "...", "\u00a0": " "})


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, text):
        self.parts.append(text)

    def handle_endtag(self, tag):
        if tag in {"td", "th"}:
            self.parts.append(" | ")
        elif tag in {"tr", "p", "div"}:
            self.parts.append("\n")


def clean(text: str) -> str:
    """Convert inline math/HTML without interpreting plain prose as LaTeX."""
    converter = LatexNodes2Text(math_mode="text")

    def latex(fragment: str) -> str:
        fragment = re.sub(r"\\tag\s*\{([^{}]*)\}", r"(\1)", fragment)
        footnote = re.fullmatch(r"\s*\^\{([^{}]+)\}\s*", fragment)
        if footnote:
            return footnote[1]
        for macro in re.findall(r"\\([a-zA-Z]+)", fragment):
            if macro not in {"begin", "end"} and converter.latex_context.get_macro_spec(macro) is None:
                raise ValueError(f"unsupported inline LaTeX command: {macro}")
        return converter.latex_to_text(fragment)

    text = re.sub(r"\\\((.*?)\\\)|\\\[(.*?)\\\]", lambda m: latex(m[1] if m[1] is not None else m[2]), text, flags=re.S)
    text = re.sub(r"\\[a-zA-Z]+(?:\s*\{(?:[^{}]|\{[^{}]*\})*\})*", lambda m: latex(m[0]), text)
    text = re.sub(r"\\([$%&#_{}])", r"\1", text)
    if re.search(r"\\[()\[\]a-zA-Z]", text):
        raise ValueError("unconverted LaTeX markup")
    parser = _HTMLText()
    parser.feed(text)
    parser.close()
    text = html.unescape("".join(parser.parts))
    text = re.sub(r"(?m)^#+\s*", "", text).replace("**", "")
    text = re.sub(r"(?<!\w)\*(\S[^*]*?)\*(?!\w)", r"\1", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def normalize_blocks(rows: object) -> list[dict]:
    if not isinstance(rows, list):
        raise ValueError("MinerU page result is not a list")
    result = []
    for row in rows:
        if not isinstance(row, dict) or row.get("type") not in TYPES:
            raise ValueError(f"unknown or malformed MinerU block type: {row.get('type') if isinstance(row, dict) else None}")
        box = row.get("bbox")
        if (not isinstance(box, (list, tuple)) or len(box) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in box)
                or box[0] >= box[2] or box[1] >= box[3]):
            raise ValueError("invalid normalized MinerU bounding box")
        content = row.get("content")
        if content is None or content == "None":
            content = ""
        if not isinstance(content, str):
            raise ValueError("MinerU block content is not text")
        if row["type"] in TEXT and not content.strip():
            raise ValueError(f"MinerU returned an empty {row['type']} block")
        angle = row.get("angle") or 0
        if type(angle) is not int or angle not in {0, 90, 180, 270}:
            raise ValueError("unsupported MinerU text rotation")
        result.append({"type": row["type"], "bbox": list(box), "content": clean(content), "angle": angle})
    return result


@lru_cache(maxsize=8)
def _unicode_font(path: str):
    return fitz.Font(fontfile=path)


@lru_cache(maxsize=128)
def _font_roundtrips(path: str, required: tuple[int, ...]) -> bool:
    # Some fonts map hyphen to soft hyphen or semicolon to Greek question mark
    # in PyMuPDF's generated ToUnicode map despite containing every glyph.
    characters = "".join(map(chr, required))
    text = "\n".join(characters[i:i + 64] for i in range(0, len(characters), 64))
    with fitz.open() as doc:
        page = doc.new_page(width=1000, height=1000)
        left = page.insert_textbox(fitz.Rect(10, 10, 990, 990), text,
                                  fontname="checkunicode", fontfile=path, fontsize=4)
        return left >= 0 and Counter(c for c in page.get_text() if not c.isspace()) == Counter(characters)


def pick_font(texts: list[str], fontfile: str | None = None) -> tuple[str, str | None, list[str]]:
    straight = [text.translate(_ASCIIFY) for text in texts]
    try:
        "".join(straight).encode("latin-1")
        return "helv", None, straight
    except UnicodeEncodeError:
        required = {ord(char) for text in texts for char in text if not char.isspace()}
        for candidate in ([fontfile] if fontfile else _FONT_FILES):
            if (Path(candidate).is_file()
                    and all(_unicode_font(candidate).has_glyph(code) for code in required)
                    and _font_roundtrips(candidate, tuple(sorted(required)))):
                # A page may need a different font than earlier pages. Distinct
                # resource names also prevent accidentally reusing a limited font.
                name = "quasiunicode" + hashlib.sha256(candidate.encode()).hexdigest()[:8]
                return name, candidate, texts
        raise ValueError("a Unicode font covering every recognized character with faithful text extraction is required; refusing to discard text")


def strip_text(page) -> None:
    doc = page.parent
    xrefs = list(page.get_contents())
    xrefs += [x for x, *_ in page.get_xobjects() if doc.xref_get_key(x, "Subtype")[1] == "/Form"]
    for xref in xrefs:
        stream = doc.xref_stream(xref)
        stripped = re.sub(rb"BT\b.*?\bET\b", b" ", stream, flags=re.S)
        if stream != stripped:
            doc.update_stream(xref, stripped)


def rectangle(page, block: dict):
    w, h = page.rect.width, page.rect.height
    return fitz.Rect(*(value * (w if i % 2 == 0 else h) for i, value in enumerate(block["bbox"])))


def _textbox(page, rect, text, size, fontname, fontfile, *, rotate=0, invisible=True, commit=False):
    shape = page.new_shape()
    left = shape.insert_textbox(rect, text, fontsize=size, fontname=fontname, fontfile=fontfile,
                                lineheight=LINE_HEIGHT, rotate=rotate, render_mode=3 if invisible else 0)
    if left >= 0 and commit:
        shape.commit(overlay=True)
    return left


def natural_size(page, rect, text, fontname, fontfile, *, rotate=0) -> float:
    lo, hi = 3.0, 30.0
    if _textbox(page, rect, text, lo, fontname, fontfile, rotate=rotate) < 0:
        raise ValueError("paragraph cannot fit its box even at 3pt; refusing to drop text")
    for _ in range(14):
        mid = (lo + hi) / 2
        if _textbox(page, rect, text, mid, fontname, fontfile, rotate=rotate) >= 0:
            lo = mid
        else:
            hi = mid
    return lo


def write_output(source: Path, output: Path, pages: list[list[dict]], *, layout: bool, model: str) -> dict:
    source_sha = layout_evidence.file_sha256(source)
    quality = ocr_quality.empty_quality()
    with fitz.open(source) as src, (fitz.open(source) if layout else fitz.open()) as out:
        if len(pages) != len(src):
            raise ValueError("incomplete MinerU page results")
        plans, sizes = [], []
        for i, rows in enumerate(pages):
            if layout and not layout_evidence.has_page_image(src[i]):
                plans.append([])
                continue
            blocks = normalize_blocks(rows)
            if not blocks and len(ocr_quality.words(src[i].get_text())) >= 50:
                raise ValueError(f"page {i + 1}: no recognized blocks despite a usable old text layer")
            ocr_quality.check_page(src[i], blocks, i + 1, quality)
            if not blocks:
                print(f"[mineru] page {i + 1}: no blocks; retaining source image for inspection", file=sys.stderr)
            if layout:
                page = out[i]
                selected = [b for b in blocks if b["type"] in TEXT]
                fontname, fontfile, texts = pick_font([b["content"] for b in selected])
                plan = []
                for block, text in zip(selected, texts):
                    rect = rectangle(page, block)
                    rotate = (-block["angle"]) % 360
                    size = natural_size(page, rect, text, fontname, fontfile, rotate=rotate)
                    plan.append((block, rect, text, size, fontname, fontfile, rotate))
                    if block["type"] == "text" and len(text) >= 200:
                        sizes.append(size)
                plans.append(plan)
            else:
                # Preserve model reading order; footnotes remain separate blocks.
                text = "\n\n".join(b["content"] for b in blocks if b["type"] not in FURNITURE | {"list", "image", "image_body"} and b["content"])
                if not text:
                    out.insert_pdf(src, from_page=i, to_page=i)
                    continue
                page = out.new_page(width=src[i].rect.width, height=src[i].rect.height)
                name, fontfile, texts = pick_font([text])
                rect = fitz.Rect(20, 20, page.rect.width - 20, page.rect.height - 20)
                size = natural_size(page, rect, texts[0], name, fontfile)
                if _textbox(page, rect, texts[0], min(9.0, size * .98), name, fontfile, invisible=False, commit=True) < 0:
                    raise ValueError(f"page {i + 1}: failed to place all recognized text")
        paragraphs = grouped_pages = 0
        if layout:
            dominant = statistics.median(sizes) if sizes else 0.0
            for i, plan in enumerate(plans):
                if not layout_evidence.has_page_image(src[i]):
                    continue
                page = out[i]
                strip_text(page)
                placed = 0
                for block, rect, text, size, name, fontfile, rotate in plan:
                    if block["type"] == "text" and dominant and abs(size - dominant) <= dominant * SNAP:
                        size = dominant
                    for shrink in SHRINK:
                        if _textbox(page, rect, text, size * shrink, name, fontfile, rotate=rotate, commit=True) >= 0:
                            break
                    else:
                        raise ValueError(f"page {i + 1}: paragraph did not fit; no per-line fallback")
                    placed += block["type"] not in FURNITURE
                paragraphs += placed
                grouped_pages += placed > 0
            if any(layout_evidence.has_page_image(p) for p in src) and not paragraphs:
                raise ValueError("layout placed no paragraphs; output not published")
        if layout_evidence.file_sha256(source) != source_sha:
            raise ValueError("source changed during OCR")
        ocr_quality.stamp(out, source_sha256=source_sha, quality=quality, model=model)
        if layout:
            layout_evidence.stamp(out, source_sha256=source_sha, grouped_pages=grouped_pages, paragraphs=paragraphs)
        out.save(output, garbage=3, deflate=True)
    print(f"[mineru] agreement check: {quality['checked_blocks']} body blocks, {len(quality['suspects'])} suspect; "
          f"{len(quality['unavailable_pages'])} pages without a usable old layer. New recognition retained.", file=sys.stderr)
    if quality["suspects"]:
        review_pages = sorted({row["page"] for row in quality["suspects"]})
        print(f"[mineru] review output pages: {review_pages}; full excerpts and boxes are in PDF QuasiOCR evidence", file=sys.stderr)
    if quality["empty_pages"]:
        print(f"[mineru] empty recognition pages: {quality['empty_pages']}; source images retained", file=sys.stderr)
    return quality


def main() -> int:
    args = sys.argv[1:]
    layout = "--layout" in args
    args = [a for a in args if a != "--layout"]
    if len(args) not in {2, 3}:
        print("Usage: ocr_mineru.py INPUT.pdf OUTPUT.pdf [LANGUAGE] [--layout]", file=sys.stderr)
        return 2
    source, output = Path(args[0]), Path(args[1])
    try:
        initial_sha = layout_evidence.file_sha256(source)
        model = MODEL
        with fitz.open(source) as doc, tempfile.TemporaryDirectory(prefix="quasi-mineru-") as directory:
            indices = [i for i in range(len(doc)) if not layout or layout_evidence.has_page_image(doc[i])]
            results = [[] for _ in doc]
            if indices:
                if platform.system() != "Darwin" or platform.machine() != "arm64" or not shutil.which("uvx"):
                    raise RuntimeError("MinerU requires macOS Apple Silicon and uvx")
                temporary = Path(directory)
                pngs = []
                for i in indices:
                    png = temporary / f"p{i + 1:06d}.png"
                    doc[i].get_pixmap(dpi=RENDER_DPI, alpha=False).save(png)
                    pngs.append(str(png))
                listing, result_file = temporary / "pages.json", temporary / "results.json"
                listing.write_text(json.dumps(pngs))
                env = dict(os.environ, MINERU_MODEL=model, MINERU_PNG_LIST=str(listing),
                           MINERU_RESULTS=str(result_file), LOGURU_LEVEL="WARNING")
                print(f"[mineru] {len(indices)} pages; two_step_extract, model loaded once", file=sys.stderr)
                process = subprocess.run(_MINERU_CMD + [_RUNNER], env=env, stdout=subprocess.PIPE, text=True)
                if process.returncode or not result_file.is_file():
                    raise RuntimeError(f"MinerU inference failed ({process.returncode}); no engine fallback")
                detected = json.loads(result_file.read_text())
                if not isinstance(detected, list) or len(detected) != len(indices):
                    raise ValueError("incomplete MinerU page list")
                for i, blocks in zip(indices, detected):
                    results[i] = blocks
        if layout_evidence.file_sha256(source) != initial_sha:
            raise ValueError("source changed during recognition")
        write_output(source, output, results, layout=layout, model=model)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[mineru] failed: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
