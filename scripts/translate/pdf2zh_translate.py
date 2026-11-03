#!/usr/bin/env python3
"""Translate a Quasi PDF via pdf2zh-next (BabelDOC) + an OpenAI-compatible endpoint.

Same output contract as immersive_translate.py: one bilingual PDF at
processing/translations/{slug}-{lang}.pdf with alternating original/translated
pages and a bookmark tree.

pdf2zh-next's `--use-alternating-pages-dual` already emits the exact page
layout that immersive_translate produces *after* split_dual_pdf(), so the
shared transaction handles publication, page counts, bookmarks and coverage;
this adapter only writes the caller-named candidate PDF.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


# Put `scripts/` on the path so this resolves to the same module object whether we
# were run as a script or imported as `translate.pdf2zh_translate` — otherwise the
# exception classes differ and callers' `except TranslationError` silently misses.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from translate.immersive_translate import (  # noqa: E402
    MissingAuthKeyError,
    TranslationError,
)
from translate.translate_commit import redact_text, validate_language  # noqa: E402

# ponytail: unpinned. Pin to `pdf2zh-next==X.Y.Z` here if a release breaks the CLI.
PDF2ZH_SPEC = "pdf2zh-next"
PDF2ZH_PYTHON = "3.12"  # upstream macOS install guidance


def normalise_base_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise TranslationError(
            "Invalid translate_base_url: expected an http(s) API base URL.",
        )
    if parts.username or parts.password or parts.query or parts.fragment:
        raise TranslationError(
            "Invalid translate_base_url: userinfo, query strings, and fragments are not allowed.",
        )
    path = parts.path.rstrip("/")
    # ponytail: root-only OpenAI-compatible endpoints conventionally expose /v1;
    # preserve every explicit path because real providers also use /v4 and /openai/v1.
    if not path:
        path = "/v1"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def load_backend_config() -> dict[str, str]:
    """Read the OpenAI-compatible endpoint config injected by the userconfig hook."""
    cfg = {
        "base_url": os.environ.get("QUASI_TRANSLATE_BASE_URL", "").strip(),
        "api_key": os.environ.get("QUASI_TRANSLATE_API_KEY", "").strip(),
        "model": os.environ.get("QUASI_TRANSLATE_MODEL", "").strip(),
    }
    missing = sorted(f"translate_{name}" for name, value in cfg.items() if not value)
    if missing:
        raise MissingAuthKeyError(
            "pdf2zh backend is not configured. Run /plugin → Configure options and fill: "
            + ", ".join(missing),
        )
    cfg["base_url"] = normalise_base_url(cfg["base_url"])
    return cfg


def build_command(
    *,
    source_pdf: Path,
    work_dir: Path,
    target_language: str,
) -> list[str]:
    return [
        "uvx",
        "--python",
        PDF2ZH_PYTHON,
        "--from",
        PDF2ZH_SPEC,
        # BabelDOC still imports BitStream, which bitstring 5 removed. Constrain
        # uvx's isolated environment; the plugin venv cannot supply this dependency.
        "--with",
        "bitstring<5",
        "pdf2zh_next",
        str(source_pdf),
        "--output",
        str(work_dir),
        "--lang-out",
        target_language,
        "--no-mono",
        "--use-alternating-pages-dual",
        "--watermark-output-mode",
        "no_watermark",
        # Parity with the immersive backend's `ocr_workaround: "auto"`. Without it
        # BabelDOC hard-refuses any scanned book, even one carrying an OCR text layer.
        "--auto-enable-ocr-workaround",
        "--openaicompatible",
        # Provider configuration is delivered through the provider's native
        # PDF2ZH_* environment surface in run_pdf2zh.  In particular, the API
        # key must never appear in argv or a receipt.
    ]


def find_dual_pdf(work_dir: Path) -> Path:
    # Naming varies with the flags in play: plain `{stem}-dual.pdf`, but
    # `{stem}.no_watermark.{lang}.dual.pdf` once --watermark-output-mode is set.
    matches = sorted(path for path in work_dir.rglob("*dual.pdf") if path.is_file())
    if not matches:
        # Observed in the wild: pdf2zh-next exits 0 after every translation request
        # fails (e.g. the endpoint 503s), leaving no output at all. Its own log above
        # is the only place the real cause appears.
        raise TranslationError(
            f"pdf2zh-next produced no dual PDF under {work_dir} but exited successfully — "
            "it almost certainly failed. Scroll back through its log for the real error "
            "(seen so far: endpoint 503s, scanned-PDF refusal).",
        )
    if len(matches) > 1:
        joined = "\n".join(f"- {path}" for path in matches)
        raise TranslationError(f"Expected one dual PDF, found several:\n{joined}")
    return matches[0]


def run_pdf2zh(cmd: list[str], work_dir: Path) -> None:
    if shutil.which("uvx") is None:
        raise TranslationError(
            "uvx not found. Install uv (https://docs.astral.sh/uv/) to use the pdf2zh backend.",
        )
    cfg = load_backend_config()
    child_env = os.environ.copy()
    child_env.update(
        {
            "PDF2ZH_OPENAICOMPATIBLE": "true",
            "PDF2ZH_OPENAI_COMPATIBLE_BASE_URL": cfg["base_url"],
            "PDF2ZH_OPENAI_COMPATIBLE_API_KEY": cfg["api_key"],
            "PDF2ZH_OPENAI_COMPATIBLE_MODEL": cfg["model"],
        }
    )
    # The strict CLI's stdout is one receipt; provider progress belongs on stderr.
    result = subprocess.run(cmd, check=False, env=child_env, stdout=sys.stderr)
    if result.returncode != 0:
        raise TranslationError(
            redact_text(
                f"pdf2zh-next exited {result.returncode}. Partial output kept at {work_dir}.",
                secrets=(cfg["api_key"],),
            ),
        )


def translate_to_candidate(
    *,
    source_pdf: Path,
    candidate_pdf: Path,
    target_language: str,
    work_dir: Path,
    on_state,
) -> dict[str, object]:
    """Run pdf2zh once and move only its alternating PDF to staged candidate."""
    validate_language(target_language)
    load_backend_config()
    work_dir.mkdir(parents=True, exist_ok=False)
    on_state("backend_running", None)
    run_pdf2zh(
        build_command(
            source_pdf=source_pdf,
            work_dir=work_dir,
            target_language=target_language,
        ),
        work_dir,
    )
    dual_pdf = find_dual_pdf(work_dir)
    candidate_pdf.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(dual_pdf), str(candidate_pdf))
    return {"task_id": None}
