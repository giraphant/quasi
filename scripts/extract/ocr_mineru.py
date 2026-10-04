#!/usr/bin/env python3
"""MinerU2.5-Pro recognition and paragraph placement, loaded once per invocation.

The default output is one reflowed text page per source page; --layout replaces
scan text while preserving the images. Neither path silently changes engines.
"""
from __future__ import annotations

import argparse
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
from pylatexenc.latex2text import LatexNodes2Text, MacroTextSpec

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
PICTURES = {"table", "equation", "image", "image_body", "table_body", "chart"}
# Labels select special presentation, not admission. Other nonempty content is
# an ordinary paragraph; an unfamiliar name must never silently lose its text.
TEXT_ALIASES = {"doc_title": "title", "image_footnote": "page_footnote",
                "footnote": "page_footnote"}
RECOGNITION_PROFILE = "mineru25-pro-2605-two-step/1"
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
    "/System/Library/Fonts/Supplemental/STIXTwoMath.otf",
    "/System/Library/Fonts/Supplemental/STIXGeneral.otf",
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

    def annotated_arrow(node, l2tobj):
        # pylatexenc's parser knows amsmath's [{ arguments, but its text
        # converter has no replacement. Keep both labels and their positions.
        args = node.nodeargd.argnlist if node.nodeargd else []
        if len(args) != 2 or args[1] is None:
            raise ValueError(f"malformed inline LaTeX command: {node.macroname}")
        labels = []
        for label, arg in (("above", args[1]), ("below", args[0])):
            if arg is not None:
                value = l2tobj.nodelist_to_text([arg]).strip()
                if value:
                    labels.append(f"{label}: {value}")
        arrow = "⟶" if node.macroname == "xrightarrow" else "⟵"
        return arrow + ("[" + "; ".join(labels) + "]" if labels else "")

    converter.latex_context.add_context_category(
        "quasi-annotated-arrows",
        macros=[MacroTextSpec(name, simplify_repl=annotated_arrow)
                for name in ("xrightarrow", "xleftarrow")],
        prepend=True,
    )

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
    text = re.sub(r"\\[a-zA-Z]+(?:\s*\[(?:[^\[\]{}]|\{[^{}]*\})*\])?(?:\s*\{(?:[^{}]|\{[^{}]*\})*\})*",
                  lambda m: latex(m[0]), text)
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


def normalize_blocks(rows: object, *, layout: bool = False) -> list[dict]:
    if not isinstance(rows, list):
        raise ValueError("MinerU page result is not a list")
    result = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"block {index}: MinerU block is not an object")
        original_kind = row.get("type")
        kind = original_kind if isinstance(original_kind, str) else ""
        kind = TEXT_ALIASES.get(kind, kind)
        box = row.get("bbox")
        if (not isinstance(box, (list, tuple)) or len(box) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in box)
                or box[0] >= box[2] or box[1] >= box[3]):
            raise ValueError(f"block {index} ({original_kind}): invalid normalized MinerU bounding box")
        content = row.get("content")
        if content is None or content == "None":
            content = ""
        if not isinstance(content, str):
            raise ValueError(f"block {index} ({original_kind}): MinerU block content is not text")
        if kind in TEXT and not content.strip():
            raise ValueError(f"block {index}: MinerU returned an empty {kind} block")
        if kind not in PICTURES and kind not in TEXT:
            # Containers with their own content also need a text projection.
            kind = "text" if content.strip() else "image"
            if content.strip():
                print(f"[mineru] block {index}: treating {original_kind!r} as text", file=sys.stderr)
        angle = row.get("angle") or 0
        if type(angle) is not int or angle not in {0, 90, 180, 270}:
            raise ValueError(f"block {index} ({original_kind}): unsupported MinerU text rotation")
        # Layout preserves tables and equations as source pixels. Converting
        # their unused LaTeX can fail the entire book for no placement benefit.
        try:
            cleaned = content if layout and kind in PICTURES else clean(content)
        except ValueError as exc:
            raise ValueError(f"block {index} ({original_kind}): {exc}") from exc
        result.append({"type": kind, "bbox": list(box), "content": cleaned, "angle": angle,
                       "source_type": original_kind, "source_block": index})
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
        rejected = []
        for candidate in ([fontfile] if fontfile else _FONT_FILES):
            if not Path(candidate).is_file():
                continue
            font = _unicode_font(candidate)
            missing = sorted(code for code in required if not font.has_glyph(code))
            if missing:
                codes = ", ".join(f"U+{code:04X}" for code in missing[:8])
                if len(missing) > 8:
                    codes += f" (+{len(missing) - 8} more)"
                rejected.append(f"{Path(candidate).name}: missing {codes}")
                continue
            if not _font_roundtrips(candidate, tuple(sorted(required))):
                rejected.append(f"{Path(candidate).name}: text round-trip mismatch")
                continue
            # A page may need a different font than earlier pages. Distinct
            # resource names also prevent accidentally reusing a limited font.
            name = "quasiunicode" + hashlib.sha256(candidate.encode()).hexdigest()[:8]
            return name, candidate, texts
        reason = "; ".join(rejected) or "no candidate font files are available"
        raise ValueError("a Unicode font covering every recognized character with faithful text extraction "
                         f"is required; refusing to discard text ({reason})")


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


def write_output(source: Path, output: Path, pages: list[list[dict]], *, layout: bool, model: str,
                 review: dict | None = None) -> dict:
    source_sha = layout_evidence.file_sha256(source)
    if review is not None and (not layout or review.get("source_sha256") != source_sha):
        raise ValueError("layout review does not match the source being placed")
    quality = ocr_quality.empty_quality()
    reviewed = {row["page"]: row["blocks"] for row in review["pages"]} if review else {}
    with fitz.open(source) as src, (fitz.open(source) if layout else fitz.open()) as out:
        if len(pages) != len(src):
            raise ValueError("incomplete MinerU page results")
        plans, sizes, placement_errors = [], [], []
        for i, rows in enumerate(pages):
            if layout and not layout_evidence.has_page_image(src[i]):
                plans.append([])
                continue
            if i + 1 in reviewed:
                rows = reviewed[i + 1]
            try:
                blocks = normalize_blocks(rows, layout=layout)
            except ValueError as exc:
                raise ValueError(f"page {i + 1}: {exc}") from exc
            if not blocks and i + 1 not in reviewed and len(ocr_quality.words(src[i].get_text())) >= 50:
                raise ValueError(f"page {i + 1}: no recognized blocks despite a usable old text layer")
            ocr_quality.check_page(src[i], blocks, i + 1, quality)
            if not blocks:
                print(f"[mineru] page {i + 1}: no blocks; retaining source image for inspection", file=sys.stderr)
            if layout:
                page = out[i]
                selected = [b for b in blocks if b["type"] in TEXT]
                try:
                    fontname, fontfile, texts = pick_font([b["content"] for b in selected])
                except ValueError as exc:
                    raise ValueError(f"page {i + 1}: {exc}") from exc
                plan = []
                for block, text in zip(selected, texts):
                    rect = rectangle(page, block)
                    rotate = (-block["angle"]) % 360
                    try:
                        size = natural_size(page, rect, text, fontname, fontfile, rotate=rotate)
                    except ValueError as exc:
                        placement_errors.append(
                            f"page {i + 1}, block {block['source_block']} ({block['source_type']}), "
                            f"bbox={block['bbox']}, rotation={block['angle']}, chars={len(text)}, "
                            f"excerpt={text[:120]!r}: {exc}"
                        )
                        continue
                    plan.append((block, rect, text, size, fontname, fontfile, rotate))
                    if block["type"] == "text" and len(text) >= 200:
                        sizes.append(size)
                plans.append(plan)
            else:
                # Preserve model reading order; footnotes remain separate blocks.
                text = "\n\n".join(b["content"] for b in blocks
                                   if b["type"] not in FURNITURE | {"image", "image_body", "chart"}
                                   and b["content"])
                if not text:
                    out.insert_pdf(src, from_page=i, to_page=i)
                    continue
                page = out.new_page(width=src[i].rect.width, height=src[i].rect.height)
                try:
                    name, fontfile, texts = pick_font([text])
                except ValueError as exc:
                    raise ValueError(f"page {i + 1}: {exc}") from exc
                rect = fitz.Rect(20, 20, page.rect.width - 20, page.rect.height - 20)
                size = natural_size(page, rect, texts[0], name, fontfile)
                if _textbox(page, rect, texts[0], min(9.0, size * .98), name, fontfile, invisible=False, commit=True) < 0:
                    raise ValueError(f"page {i + 1}: failed to place all recognized text")
        if placement_errors:
            raise ValueError("layout placement failed:\n" + "\n".join(placement_errors))
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
            layout_evidence.stamp(out, source_sha256=source_sha, grouped_pages=grouped_pages,
                                  paragraphs=paragraphs, review=review)
        out.save(output, garbage=3, deflate=True)
    print(f"[mineru] agreement check: {quality['checked_blocks']} body blocks, {len(quality['suspects'])} suspect; "
          f"{len(quality['unavailable_pages'])} pages without a usable old layer. New recognition retained.", file=sys.stderr)
    if quality["suspects"]:
        review_pages = sorted({row["page"] for row in quality["suspects"]})
        print(f"[mineru] review output pages: {review_pages}; full excerpts and boxes are in PDF QuasiOCR evidence", file=sys.stderr)
    if quality["empty_pages"]:
        print(f"[mineru] empty recognition pages: {quality['empty_pages']}; source images retained", file=sys.stderr)
    return quality


def read_recognition(path: Path, source_sha: str, page_count: int) -> list | None:
    try:
        saved = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    if (not isinstance(saved, dict)
            or saved.get("profile") != RECOGNITION_PROFILE
            or saved.get("source_sha256") != source_sha
            or saved.get("model") != MODEL
            or saved.get("render_dpi") != RENDER_DPI):
        raise ValueError(f"recognition artifact does not match this source/model: {path}; preserved")
    pages = saved.get("pages")
    if not isinstance(pages, list) or len(pages) != page_count or any(not isinstance(p, list) for p in pages):
        raise ValueError(f"recognition artifact has incomplete page results: {path}; preserved")
    return pages


def save_recognition(path: Path, source_sha: str, pages: list) -> list:
    """Publish complete raw recognition before placement, without replacing a peer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({"profile": RECOGNITION_PROFILE, "source_sha256": source_sha,
                       "model": MODEL, "render_dpi": RENDER_DPI, "pages": pages}, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            existing = read_recognition(path, source_sha, len(pages))
            if existing is None:
                raise ValueError(f"recognition artifact disappeared during publication: {path}")
            return existing
        return pages
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_review(path: Path, source_sha: str, document) -> dict:
    """A source-bound replacement for selected raw pages, with review reasons.

    {"source_sha256": "...", "pages": [{"page": 16, "reason": "...", "blocks": []}]}
    Each blocks list replaces the whole selected page. Raw recognition is never
    edited. Empty blocks explicitly mean a visually reviewed blank scan page.
    """
    review = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(review, dict) or review.get("source_sha256") != source_sha:
        raise ValueError("layout review does not match this source")
    pages = review.get("pages")
    if not isinstance(pages, list):
        raise ValueError("layout review pages must be a list")
    seen = set()
    for row in pages:
        if not isinstance(row, dict):
            raise ValueError("layout review page must be an object")
        page = row.get("page")
        if type(page) is not int or not 1 <= page <= len(document) or page in seen:
            raise ValueError("layout review needs unique one-based physical page numbers within the source")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise ValueError(f"page {page}: layout review needs a reason")
        if not isinstance(row.get("blocks"), list):
            raise ValueError(f"page {page}: layout review blocks must be a list")
        if not layout_evidence.has_page_image(document[page - 1]):
            raise ValueError(f"page {page}: layout review cannot replace native text pages")
        seen.add(page)
    return review


def recognize(source: Path, *, layout: bool) -> list:
    with fitz.open(source) as doc, tempfile.TemporaryDirectory(prefix="quasi-mineru-") as directory:
        indices = [i for i in range(len(doc)) if not layout or layout_evidence.has_page_image(doc[i])]
        results = [[] for _ in doc]
        if not indices:
            return results
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
        env = dict(os.environ, MINERU_MODEL=MODEL, MINERU_PNG_LIST=str(listing),
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
        return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("language", nargs="?")
    parser.add_argument("--layout", action="store_true")
    parser.add_argument("--recognition-json", type=Path)
    parser.add_argument("--review-json", type=Path)
    args = parser.parse_args()
    source, output, layout = args.source, args.output, args.layout
    recognition = args.recognition_json
    try:
        if recognition is not None and (not layout or recognition.resolve() in {source.resolve(), output.resolve()}):
            raise ValueError("--recognition-json requires layout and a separate JSON artifact path")
        if args.review_json is not None and (not layout or recognition is None):
            raise ValueError("--review-json requires --layout and --recognition-json")
        initial_sha = layout_evidence.file_sha256(source)
        with fitz.open(source) as doc:
            pages = len(doc)
            review = read_review(args.review_json, initial_sha, doc) if args.review_json else None
        results = read_recognition(recognition, initial_sha, pages) if recognition else None
        if review is not None and results is None:
            raise ValueError("layout review requires saved recognition; no new inference started")
        if results is None:
            results = recognize(source, layout=layout)
            if recognition is not None:
                if layout_evidence.file_sha256(source) != initial_sha:
                    raise ValueError("source changed during recognition")
                results = save_recognition(recognition, initial_sha, results)
                print(f"[mineru] recognition saved: {recognition}", file=sys.stderr)
        else:
            print(f"[mineru] reusing recognition: {recognition}; placement only", file=sys.stderr)
        if layout_evidence.file_sha256(source) != initial_sha:
            raise ValueError("source changed during recognition")
        if review is not None:
            print(f"[mineru] applying reviewed pages: {[r['page'] for r in review['pages']]}", file=sys.stderr)
        write_output(source, output, results, layout=layout, model=MODEL, **({"review": review} if review else {}))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[mineru] failed: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
