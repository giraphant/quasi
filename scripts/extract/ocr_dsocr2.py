#!/usr/bin/env python3
"""DeepSeek-OCR-2 engine for `quasi-extract ocr --engine dsocr2`.

Renders each PDF page (PyMuPDF, quasi venv) to PNG, then delegates to ONE
`uvx` subprocess (mlx-vlm pinned to 0.3.12) that loads the model **once** and
OCRs every page in a single loop. Delegating to uvx keeps this independent of
the quasi venv's Python (3.9) — mlx-vlm needs Python ≥3.10/3.12.

Why pin mlx-vlm==0.3.12: 0.4+ broke DeepSeek-OCR-2 in two ways — (a) the
processor won't load ("Unrecognized processing class") and (b) generate hits
"TokenizersBackend has no attribute stopping_criteria". 0.3.12 is the last
version where both load and generate work. The load magic: `import
mlx_vlm.generate` (NOT just `from mlx_vlm import load`) triggers full model
registration so the processor resolves. Modeled on larryteal/Mac-M5-Deepseek-OCR-2.

The recognized text is written into a text-layer PDF (one page per input page)
so the existing `split` flow is unchanged. Fail-soft: if uvx/mlx-vlm or the
model is missing, or this isn't Apple Silicon, exit non-zero so extract.py
falls back to tesseract.

Two output shapes:
  default    reflowed markdown in one textbox per page — for `split`/analysis.
  --layout   page image + invisible text at the model's own boxes — a replacement
             OCR layer, for feeding `quasi-translate`. Needs the `<|grounding|>`
             prompt, which returns <|ref|>text<|/ref|><|det|>[[x1,y1,x2,y2]]
             <|/det|> in a 0-999 space normalised to the page. Layout mode also
             runs MinerU2.5-Pro for paragraph grouping — see draw_layout_page.

Usage: ocr_dsocr2.py INPUT.pdf OUTPUT.pdf [LANGUAGE] [--layout]
  (LANGUAGE accepted for parity with ocr_pdf.sh but ignored — DS OCR2 is
   multilingual.) Model: QUASI_DSOCR2_MODEL (local dir or HF repo id;
   default mlx-community/DeepSeek-OCR-2-bf16), QUASI_MINERU_MODEL likewise.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz  # PyMuPDF — quasi dep

# A line's box hugs its ink, so its height depends on whether that line happens to
# carry ascenders and descenders, not on the type size. Deriving the font size from
# it therefore jitters -9%/+4% between body lines that are set identically, and
# BabelDOC copies the source font size onto its translation, so the noise ships as
# visibly uneven Chinese: 25 distinct sizes over a 10-page slice whose own text
# layer used 2. Snapping every size near the book's dominant one removes it (99.6%
# of characters land on one size on that slice).
#
# ponytail: this also flattens headings, and no threshold can avoid that — the boxes
# do not carry the distinction. On the same slice the chapter title is set 1.36x
# body in the source, but its *box* computes to 1.12x where body lines already reach
# 1.07x. Recovering headings needs an engine that labels blocks rather than lines:
# dots.ocr returns {bbox, category: Title|Text|Section-header, text} per paragraph,
# runs on this same mlx-vlm pin at 6-8s/page against this engine's ~20s, and over the
# same 10 pages made 1 word error to this engine's 6 plus 2 dropped phrases. It drops
# superscript footnote markers, which is its one real loss. Swap when that trade reads
# right for the corpus.
SNAP = 0.20

PROMPT = "Free OCR. "
LAYOUT_PROMPT = "<|grounding|>OCR this image."
# Boxes come back normalised to this range, not to the page or the PNG.
DET_SCALE = 999.0
MAX_TOKENS = 8000
RENDER_DPI = 220
# mlx-vlm 0.3.12 runs DeepSeek-OCR-2; 0.4+ broke it (see module docstring). The
# --with deps are the model's remote-code imports (torch etc.) needed for the
# processor/tokenizer load even though inference itself uses MLX.
_MLXVLM_CMD = [
    "uvx", "--from", "mlx-vlm==0.3.12",
    "--with", "torch", "--with", "torchvision", "--with", "addict",
    "--with", "einops", "--with", "matplotlib", "--with", "tqdm",
    "python", "-c",
]
# Runs inside the uvx env. `import mlx_vlm.generate` is the load magic (triggers
# model registration). Loads the model ONCE, OCRs each page, writes text list to
# a results file. Progress to stderr only.
_RUNNER = r'''
import json, os, sys, time
model_id = os.environ["DSOCR2_MODEL"]
if os.path.isdir(model_id):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
import mlx_vlm.generate  # noqa: F401 — triggers processor registration
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
pngs = json.load(open(os.environ["DSOCR2_PNG_LIST"]))
t0 = time.time()
# NO trust_remote_code: mlx-vlm ships its own DeepseekOCR2Processor, while the
# repo's remote code imports LlamaFlashAttention2, deleted from modern
# transformers. That ImportError is swallowed by mlx-vlm's bare `except` in
# models/base.py and resurfaces as a bogus "Unrecognized processing class",
# which sent every run silently down the tesseract fallback.
model, processor = load(model_id, None)
prompt = apply_chat_template(processor, model.config, os.environ.get("DSOCR2_PROMPT", "Free OCR. "), num_images=1)
sys.stderr.write(f"[mlx] model loaded in {time.time()-t0:.1f}s, OCRing {len(pngs)} pages\n")
out = []
mt = int(os.environ.get("DSOCR2_MAX_TOKENS", "8000"))
for i, p in enumerate(pngs, 1):
    r = generate(model, processor, prompt, [p], max_tokens=mt, temperature=0.0, verbose=False)
    out.append(getattr(r, "text", "") or "")
    sys.stderr.write(f"[mlx] page {i}/{len(pngs)}\n")
json.dump(out, open(os.environ["DSOCR2_RESULTS"], "w"), ensure_ascii=False)
'''

# MinerU2.5-Pro answers the one question DS OCR2's grounding cannot: which lines
# belong to one paragraph. It returns {type, bbox} only — no text — so DS OCR2 keeps
# every bit of its recognition advantage and MinerU is used purely as a grouper.
# Same mlx-vlm pin, ~2s/page against DS OCR2's ~20s. bbox comes back normalised 0-1.
_MINERU_MODEL_DEFAULT = "opendatalab/MinerU2.5-Pro-2605-1.2B"
_MINERU_CMD = [
    "uvx", "--from", "mlx-vlm==0.3.12",
    "--with", "mineru-vl-utils", "--with", "pillow",
    "--with", "torch", "--with", "torchvision",
    "python", "-c",
]
_MINERU_RUNNER = r'''
import json, os, sys
from PIL import Image
from mineru_vl_utils import MinerUClient
client = MinerUClient(backend="mlx-engine", model_path=os.environ["MINERU_MODEL"])
pngs = json.load(open(os.environ["MINERU_PNG_LIST"]))
out = []
for i, p in enumerate(pngs, 1):
    try:
        blocks = client.layout_detect(Image.open(p))
    except Exception as e:
        # one unreadable page must not cost the whole book its paragraph grouping
        sys.stderr.write(f"[mineru] page {i} layout failed: {e}\n")
        blocks = []
    out.append([{"c": b["type"], "b": b["bbox"]} for b in blocks])
    sys.stderr.write(f"[mineru] page {i}/{len(pngs)}\n")
json.dump(out, open(os.environ["MINERU_RESULTS"], "w"))
'''

# Blocks worth reflowing as one paragraph. Everything else (figure, caption,
# running head) stays per-line.
#
# `ref_text` is a footnote, and a footnote is a paragraph — leaving it per-line
# reproduces exactly the shredding this path exists to fix. It is the largest
# flowable category we were dropping (44/52/52 lines on the three footnote-heavy
# books measured) and adding it took margin scraps 3 -> 1 on galison and 32 -> 15
# on hounshell. The leaf rule still keeps each note separate: the `list` parent
# that holds them is dropped for having children, so six numbered notes do not
# flow as one blob.
FLOW = {"text", "list", "list-item", "paragraph", "ref_text"}
# The source layer is written slightly small so the translation has room: BabelDOC
# sets CJK at line_skip 1.50 into a box a scanned book built at ~1.15 pitch, and that
# vertical deficit — not character width — is what overflows. Below scale 0.70 it
# stops shrinking and expands the paragraph box rightwards instead, and that
# expansion is exactly the tail-in-the-margin defect this whole path exists to kill.
# Flat, not per-paragraph: BabelDOC caps every paragraph at min(multimode(scales))
# document-wide, so a source with mixed sizes comes out mixed (measured 41-49%
# of characters on the dominant size, against 72-94% for a flat source).
# 0.90 measured identical to 0.85 in defects across three books and 1.00 collides;
# entries past the first are a safety net for a block the English itself overruns,
# measured usage 0 blocks. ponytail: one constant, no per-book tuning.
SHRINK = (0.90, 0.85, 0.80, 0.75)

_CJK_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]


def _die(msg: str) -> "NoReturn":
    sys.stderr.write(f"[dsocr2] unavailable: {msg}\n")
    sys.exit(3)


def _resolve_model() -> str:
    """Local dir (preferred) or HF repo id. Default to the bf16 repo id."""
    env = os.environ.get("QUASI_DSOCR2_MODEL", "").strip()
    if env:
        return env
    local = Path.home() / ".cache" / "ocr-eval" / "dsocr2-bf16"
    if (local / "config.json").exists() and any(local.glob("*.safetensors")):
        return str(local)
    return "mlx-community/DeepSeek-OCR-2-bf16"


def _find_unicode_font() -> str | None:
    for f in _CJK_FONT_CANDIDATES:
        if Path(f).exists():
            return f
    return None


def _clean(text: str) -> str:
    _META = ("please make sure", "here is", "here's", "below is", "sure,", "okay",
             "certainly", "of course", "```markdown", "```")
    lines = text.splitlines()
    while lines and any(lines[0].strip().lower().startswith(m) for m in _META):
        lines.pop(0)
    out, blank = [], 0
    for line in lines:
        if line.strip():
            out.append(line.rstrip()); blank = 0
        else:
            blank += 1
            if blank <= 1:
                out.append("")
    return "\n".join(out).strip() + "\n"


_DET_RE = re.compile(r"<\|ref\|>(.*?)<\|/ref\|>\s*<\|det\|>\[\[(.*?)\]\]<\|/det\|>", re.S)


def parse_grounding(text: str, width: float, height: float) -> list[tuple[str, fitz.Rect]]:
    """Pull (line, page-space box) pairs out of one <|grounding|> response."""
    out = []
    for body, coords in _DET_RE.findall(text):
        body = body.strip()
        nums = [n for n in re.findall(r"-?\d+", coords)][:4]
        if not body or len(nums) < 4:
            continue
        x0, y0, x1, y1 = (int(n) / DET_SCALE for n in nums)
        rect = fitz.Rect(x0 * width, y0 * height, x1 * width, y1 * height)
        # A zero-height box would make the fitted font size 0 and drop the line.
        if rect.width > 1 and rect.height > 1:
            out.append((body, rect))
    return out


# Typographic characters a base-14 font cannot encode. Straightening them keeps
# whole English books on Helvetica; the alternative is 16MB of embedded font.
_ASCIIFY = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "…": "...", "′": "'", "″": '"', " ": " ",
})


def pick_font(texts: list[str], fontfile: str | None) -> tuple[str, str | None, list[str]]:
    """Font and the text to draw with it: base-14 Helvetica whenever it can encode.

    PyMuPDF embeds a fontfile whole and cannot subset without fontTools, so an
    unconditional Arial Unicode costs ~16MB per output. But base-14 goes through
    Latin-1 and silently renders anything outside it as `·` — and `Font.has_glyph`
    does NOT predict that, because it answers for a real Helvetica clone rather
    than for the encoding insert_text() will use. Latin-1 encodability is the
    honest test, so ask it of the straightened text.

    ponytail: a CJK source still pays that 16MB. Subset it if that case shows up.
    """
    straight = [text.translate(_ASCIIFY) for text in texts]
    try:
        "".join(straight).encode("latin-1")
    except UnicodeEncodeError:
        if fontfile:
            return "cjk", fontfile, texts
        sys.stderr.write("[dsocr2] WARNING: no Unicode font; non-Latin text will be lost.\n")
    return "helv", None, straight


def strip_text(page: fitz.Page) -> None:
    """Drop the page's existing text layer, leaving the scan and its compressed bytes.

    Editing the content stream rather than rebuilding the page keeps the original
    image object untouched; re-inserting a decoded image inflates a book ~10x.
    BT/ET cannot nest, so the non-greedy match is the whole text object.
    """
    doc = page.parent
    xrefs = list(page.get_contents())
    # ABBYY-style scans keep their text layer in a Form XObject (named OCR-<id>),
    # not in the page's own stream, and five of eight books measured are that shape.
    # Missing it left the old layer sitting under ours: BabelDOC then sees two
    # stacked text layers and drops body text — 19% of one book's page went missing.
    # Only Form subtypes: the same regex over an image stream would corrupt it.
    xrefs += [x for x, *_ in page.get_xobjects()
              if doc.xref_get_key(x, "Subtype")[1] == "/Form"]
    for xref in xrefs:
        stream = doc.xref_stream(xref)
        stripped = re.sub(rb"BT\b.*?\bET\b", b" ", stream, flags=re.S)
        if stripped != stream:
            doc.update_stream(xref, stripped)


def fit_size(body: str, rect: fitz.Rect, ruler: fitz.Font) -> float:
    """Font size that fills the box's height without overflowing its width."""
    size = rect.height * 0.8
    wide = ruler.text_length(body, fontsize=size)
    if wide > rect.width:
        # Shrink to the box: the layout model downstream reads these widths.
        size *= rect.width / wide
    return size


def dominant_size(pages: list[list], ruler: fitz.Font) -> float:
    """The book's body font size: character-weighted median over every grounded line.

    Book-wide rather than per-page. One page holds too few lines to see through the
    grid jitter, and a real book sets its body at one size from cover to cover.
    """
    sizes: list[float] = []
    for lines in pages:
        for body, rect in lines:
            size = fit_size(body, rect, ruler)
            if size >= 1:
                sizes.extend([size] * len(body))
    return statistics.median(sizes) if sizes else 0.0


def join_lines(texts: list[str]) -> str:
    """Join a paragraph's lines, undoing the source's end-of-line hyphenation.

    A plain space hands the translator 'rep- resentation' and 'physi- cists' — 104
    of them over two 10-page slices. Only a hyphen at a LINE END is a break: the
    same repair on the joined string would also eat the real one in 'pre-logical'.
    A suspended hyphen ('a table- or room-sized chamber') ends a line too, so the
    next word still has to be checked.
    """
    out = texts[0]
    for t in texts[1:]:
        if out.endswith("-") and re.match(r"[a-z]+\b", t) and \
                not re.match(r"(?:or|and|to|but|nor)\b", t):
            out = out[:-1] + t
        else:
            out += " " + t
    return out


def flow_boxes(page: fitz.Page, blocks: list[dict]) -> list[fitz.Rect]:
    """One page's MinerU blocks as page-space paragraph boxes, flowable ones only."""
    w, h = page.rect.width, page.rect.height
    out = [(fitz.Rect(b["b"][0] * w, b["b"][1] * h, b["b"][2] * w, b["b"][3] * h), b["c"])
           for b in blocks]
    out = [(r, c) for r, c in out if r.height > 5 and r.width > 5]
    # Geometry runs over EVERY block and the FLOW filter comes last. Filtering first
    # breaks two things: `ref_text` footnotes vanish before the nesting test, so their
    # `list` parent looks childless and six numbered notes flow as one blob; and
    # `image`/`image_caption` vanish before the extend test, so the body block above a
    # figure grows straight through it and swallows the caption.
    out = [(r, c) for r, c in out if not any(o is not r and r.contains(o) for o, _ in out)]
    out.sort(key=lambda t: t[0].y0)
    # A block's box hugs its ink; grow its bottom edge into the whitespace above the
    # next block below it so a rewrap that needs one more line has somewhere to go.
    for n, (r, _) in enumerate(out):
        below = [o.y0 for o, _ in out[n + 1:] if o.x1 > r.x0 and o.x0 < r.x1 and o.y0 > r.y0]
        r.y1 = max(r.y1, min(below) - 1 if below else h - 24)
    return [r for r, c in out if c in FLOW]


def draw_layout_page(
    page: fitz.Page,
    lines,
    fontname: str,
    fontfile: str | None,
    snap_to: float = 0.0,
    blocks: list[dict] | None = None,
) -> int:
    """Invisible text at the OCR boxes, over the scan — an ocrmypdf-shaped layer.

    Drawn text-over-image (not ocrmypdf's text-under-image): BabelDOC substitutes
    the translation in place, so under the image it would render invisible.

    With `blocks`, each paragraph is written as ONE flowed textbox instead of a
    stack of line boxes. That is the difference between a readable translation and
    a shredded one: given a LINE box, BabelDOC must fit that line's Chinese into
    that line's width and parks the tail in the margin, so a paragraph arrives cut
    into pieces. A paragraph box has nowhere to spill to — it rewraps internally.
    Leading comes from the source's own line pitch, so the flow lands on the ink it
    replaces rather than needing the box to grow (growing is what makes boxes
    overlap and translations stack). Lines no block claims stay per-line.
    """
    kw = {"fontname": fontname, "render_mode": 3}
    if fontfile:
        kw["fontfile"] = fontfile
    # get_text_length() only knows the base-14 names, not our embedded alias.
    ruler = fitz.Font(fontfile=fontfile) if fontfile else fitz.Font(fontname)
    boxes = flow_boxes(page, blocks) if blocks else []
    claimed: set[int] = set()
    drawn = 0
    for box in boxes:
        mine = [(n, l) for n, l in enumerate(lines)
                if fitz.Point((l[1].x0 + l[1].x1) / 2, (l[1].y0 + l[1].y1) / 2) in box]
        if len(mine) < 2:
            continue
        rs = [l[1] for _, l in mine]
        size = statistics.median([fit_size(t, r, ruler) for _, (t, r) in mine])
        if size < 1:
            continue
        if snap_to and abs(size - snap_to) <= snap_to * SNAP:
            size = snap_to
        # Geometry off sorted extents, never off first/last: the grounding order is
        # reading order, and on a page with figures a block's last line can sit
        # ABOVE its first — which built an inverted (empty) rect and crashed.
        ys = sorted(r.y0 for r in rs)
        pitch = statistics.median([b - a for a, b in zip(ys, ys[1:])]) or size * 1.2
        # Left edge from the lines, not the block: a first-line indent must survive.
        area = fitz.Rect(min(r.x0 for r in rs), ys[0] - size * 0.15,
                         max(box.x1, max(r.x1 for r in rs)),
                         max(r.y1 for r in rs) + size * 0.15)
        text = join_lines([t for _, (t, _) in mine])
        for shrink in SHRINK:
            left = page.insert_textbox(area, text, fontsize=size * shrink,
                                       lineheight=pitch / (size * shrink), **kw)
            if left >= 0:
                break
        if left >= 0:      # never grow the box; a block that still overruns goes per-line
            claimed.update(n for n, _ in mine)
            drawn += 1
    for n, (body, rect) in enumerate(lines):
        if n in claimed:
            continue
        size = fit_size(body, rect, ruler)
        if size < 1:
            continue
        # Furniture — running head, folio, caption — keeps its measured size. Snapping
        # it to body is what made BabelDOC read a running head as the first line of the
        # paragraph under it. Without blocks there is nothing to tell them apart, so
        # the old unconditional snap stands.
        inside = not boxes or any(
            fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2) in b for b in boxes
        )
        if inside and snap_to and abs(size - snap_to) <= snap_to * SNAP:
            size = snap_to
        page.insert_text((rect.x0, rect.y1 - rect.height * 0.2), body, fontsize=size, **kw)
        drawn += 1
    return drawn


def relayer_page(
    page: fitz.Page,
    raw: str,
    fontname: str,
    fontfile: str | None,
    snap_to: float = 0.0,
    blocks: list[dict] | None = None,
) -> int:
    """Replace one page's text layer with the model's grounded lines.

    Returns the number of lines drawn, or -1 for a page deliberately left alone.
    A page with no image object is born-digital: its text *is* the page, so
    stripping would leave a blank, and the layer it already has is the clean one
    --layout exists to produce for scans.
    """
    if not page.get_images():
        return -1
    lines = parse_grounding(raw, page.rect.width, page.rect.height)
    strip_text(page)
    return draw_layout_page(page, lines, fontname, fontfile, snap_to, blocks)


def _detect_layout(pngs: list[str], td: Path) -> list[list[dict]]:
    """Paragraph blocks per page from MinerU2.5-Pro, or [] if it cannot run.

    Fail-soft like the rest of this engine: no MinerU means the per-line layer,
    which is what shipped before paragraph flow existed — degraded, never broken.
    """
    model = os.environ.get("QUASI_MINERU_MODEL", "").strip() or _MINERU_MODEL_DEFAULT
    resfile, pnglist = td / "layout.json", td / "layout-pngs.json"
    pnglist.write_text(json.dumps(pngs))
    # mineru-vl-utils logs every page's raw box list at DEBUG, which buries the
    # per-page progress line this run is otherwise judged by.
    env = dict(os.environ, MINERU_MODEL=model, LOGURU_LEVEL="WARNING",
               MINERU_PNG_LIST=str(pnglist), MINERU_RESULTS=str(resfile))
    sys.stderr.write(f"[dsocr2] paragraph layout: {model} ({len(pngs)} pages)...\n")
    proc = subprocess.run(_MINERU_CMD + [_MINERU_RUNNER], env=env, text=True,
                          stdout=subprocess.PIPE)
    if proc.returncode != 0 or not resfile.exists():
        sys.stderr.write(
            f"[dsocr2] layout detection unavailable (exit {proc.returncode}); "
            "falling back to a per-line text layer.\n")
        return []
    return json.loads(resfile.read_text())


def main() -> int:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        _die("requires macOS Apple Silicon (MLX). Use --engine tesseract.")
    if not shutil.which("uvx"):
        _die("`uvx` not on PATH (install uv). Use --engine tesseract.")

    args = sys.argv[1:]
    layout = "--layout" in args
    args = [a for a in args if a != "--layout"]
    if len(args) < 2:
        sys.stderr.write("Usage: ocr_dsocr2.py INPUT.pdf OUTPUT.pdf [LANGUAGE] [--layout]\n")
        return 2
    input_pdf, output_pdf = Path(args[0]), Path(args[1])
    if not input_pdf.exists():
        sys.stderr.write(f"[dsocr2] input not found: {input_pdf}\n")
        return 2

    model = _resolve_model()
    fontfile = _find_unicode_font()
    if fontfile is None:
        sys.stderr.write("[dsocr2] WARNING: no Unicode font; CJK text layer may degrade.\n")

    src = fitz.open(input_pdf)
    n = src.page_count
    matrix = fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)

    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        pngs = []
        for i in range(n):
            png = td / f"p{i:05d}.png"
            src[i].get_pixmap(matrix=matrix, alpha=False).save(str(png))
            pngs.append(str(png))
        resfile, pnglist = td / "results.json", td / "pngs.json"
        pnglist.write_text(json.dumps(pngs))
        env = dict(os.environ,
                   DSOCR2_MODEL=model,
                   DSOCR2_PNG_LIST=str(pnglist),
                   DSOCR2_RESULTS=str(resfile),
                   DSOCR2_PROMPT=LAYOUT_PROMPT if layout else PROMPT,
                   DSOCR2_MAX_TOKENS=str(MAX_TOKENS))
        sys.stderr.write(f"[dsocr2] model: {model} | pages: {n} | load-once via uvx mlx-vlm==0.3.12...\n")
        # stderr is inherited, not captured: a book-length run is an hour of silence
        # otherwise, and the per-page progress line is the only sign it is alive.
        proc = subprocess.run(_MLXVLM_CMD + [_RUNNER], env=env, text=True, stdout=subprocess.PIPE)
        if proc.returncode != 0 or not resfile.exists():
            sys.stderr.write(f"[dsocr2] mlx-vlm inference failed (exit {proc.returncode}); see its log above.\n")
            return 3
        texts = json.loads(resfile.read_text(encoding="utf-8"))

        fontname, fontfile, texts = pick_font(texts, fontfile)
        # Layout mode edits the source's own pages so the scan is never re-encoded.
        out = fitz.open(input_pdf) if layout else fitz.open()
        snap = 0.0
        layouts: list[list[dict]] = []
        if layout:
            ruler = fitz.Font(fontfile=fontfile) if fontfile else fitz.Font(fontname)
            snap = dominant_size(
                [
                    parse_grounding(
                        texts[i] if i < len(texts) else "", src[i].rect.width, src[i].rect.height
                    )
                    for i in range(n)
                ],
                ruler,
            )
            sys.stderr.write(f"[dsocr2] body text {snap:.2f}pt, snapping within {SNAP:.0%}\n")
            layouts = _detect_layout(pngs, td)
        untouched = []
        for i in range(n):
            rect = src[i].rect
            new = out[i] if layout else out.new_page(width=rect.width, height=rect.height)
            raw = texts[i] if i < len(texts) else ""
            if layout:
                drawn = relayer_page(new, raw, fontname, fontfile, snap,
                                     layouts[i] if i < len(layouts) else None)
                if drawn < 0:
                    untouched.append(i + 1)
                elif not drawn:
                    sys.stderr.write(f"[dsocr2] page {i + 1}: no grounded lines, image only\n")
                continue
            body = _clean(raw)
            if body:
                kw = {"fontsize": 9, "color": (0, 0, 0), "fontname": fontname}
                if fontfile:
                    kw["fontfile"] = fontfile
                new.insert_textbox(fitz.Rect(20, 20, rect.width - 20, rect.height - 20), body, **kw)
        if untouched:
            sys.stderr.write(
                f"[dsocr2] left {len(untouched)}/{n} born-digital page(s) alone "
                f"(no image behind the text): {untouched[:10]}{'...' if len(untouched) > 10 else ''}\n",
            )
        out.save(str(output_pdf), garbage=3, deflate=True)
        out.close()
    src.close()
    sys.stderr.write(f"[dsocr2] wrote {output_pdf} ({n} pages{', layout' if layout else ''})\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
