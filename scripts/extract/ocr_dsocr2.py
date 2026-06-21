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

Usage: ocr_dsocr2.py INPUT.pdf OUTPUT.pdf [LANGUAGE]
  (LANGUAGE accepted for parity with ocr_pdf.sh but ignored — DS OCR2 is
   multilingual.) Model: QUASI_DSOCR2_MODEL (local dir or HF repo id;
   default mlx-community/DeepSeek-OCR-2-bf16).
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz  # PyMuPDF — quasi dep

PROMPT = "Free OCR. "
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
os.environ.setdefault("HF_HUB_TRUST_REMOTE_CODE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
import mlx_vlm.generate  # noqa: F401 — triggers processor registration
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
model_id = os.environ["DSOCR2_MODEL"]
pngs = json.load(open(os.environ["DSOCR2_PNG_LIST"]))
prompt = apply_chat_template(None, None, os.environ.get("DSOCR2_PROMPT", "Free OCR. "), num_images=1) if False else None
t0 = time.time()
model, processor = load(model_id, None, trust_remote_code=True)
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


def main() -> int:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        _die("requires macOS Apple Silicon (MLX). Use --engine tesseract.")
    if not shutil.which("uvx"):
        _die("`uvx` not on PATH (install uv). Use --engine tesseract.")

    args = sys.argv[1:]
    if len(args) < 2:
        sys.stderr.write("Usage: ocr_dsocr2.py INPUT.pdf OUTPUT.pdf [LANGUAGE]\n")
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
        import json
        pnglist.write_text(json.dumps(pngs))
        env = dict(os.environ,
                   DSOCR2_MODEL=model,
                   DSOCR2_PNG_LIST=str(pnglist),
                   DSOCR2_RESULTS=str(resfile),
                   DSOCR2_PROMPT=PROMPT,
                   DSOCR2_MAX_TOKENS=str(MAX_TOKENS))
        sys.stderr.write(f"[dsocr2] model: {model} | pages: {n} | load-once via uvx mlx-vlm==0.3.12...\n")
        proc = subprocess.run(_MLXVLM_CMD + [_RUNNER], env=env, text=True, capture_output=True)
        if proc.returncode != 0 or not resfile.exists():
            sys.stderr.write("[dsocr2] mlx-vlm inference failed:\n" + proc.stderr[-2000:] + "\n")
            return 3
        texts = json.loads(resfile.read_text(encoding="utf-8"))

    out = fitz.open()
    for i in range(n):
        rect = src[i].rect
        new = out.new_page(width=rect.width, height=rect.height)
        body = _clean(texts[i] if i < len(texts) else "")
        if body:
            kw = {"fontsize": 9, "color": (0, 0, 0)}
            if fontfile:
                kw.update(fontname="cjk", fontfile=fontfile)
            else:
                kw["fontname"] = "helv"
            new.insert_textbox(fitz.Rect(20, 20, rect.width - 20, rect.height - 20), body, **kw)
    out.save(str(output_pdf))
    out.close(); src.close()
    sys.stderr.write(f"[dsocr2] wrote {output_pdf} ({n} pages)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
