#!/usr/bin/env python3
"""Translate a Quasi PDF via pdf2zh-next (BabelDOC) + an OpenAI-compatible endpoint.

Same output contract as immersive_translate.py: one bilingual PDF at
processing/translations/{slug}-{lang}.pdf with alternating original/translated
pages and a bookmark tree.

pdf2zh-next's `--use-alternating-pages-dual` already emits the exact page
layout that immersive_translate produces *after* split_dual_pdf(), so the
source-resolution, output-path and TOC helpers are reused verbatim and there
is no splitting step here.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pymupdf

# Put `scripts/` on the path so this resolves to the same module object whether we
# were run as a script or imported as `translate.pdf2zh_translate` — otherwise the
# exception classes differ and callers' `except TranslationError` silently misses.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from translate.immersive_translate import (  # noqa: E402
    PROJECT_ROOT,
    TOC_PAGE_SIDES,
    AmbiguousSourceError,
    MissingAuthKeyError,
    SourceNotFoundError,
    TranslationError,
    add_toc_to_split_pdf,
    build_output_paths,
    resolve_source_pdf,
)
from translate.coverage import check as check_coverage  # noqa: E402
from translate.tounicode import repair_pdf as repair_tounicode  # noqa: E402

# ponytail: unpinned. Pin to `pdf2zh-next==X.Y.Z` here if a release breaks the CLI.
PDF2ZH_SPEC = "pdf2zh-next"
PDF2ZH_PYTHON = "3.12"  # upstream macOS install guidance


def normalise_base_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise TranslationError(
            "Invalid translate_base_url: expected an http(s) API base URL.",
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
    cfg: dict[str, str],
    extra_args: list[str],
) -> list[str]:
    # ponytail: api key lands on the argv, visible to this user's own `ps`.
    # Matches the existing hook, which already does `export QUASI_...=<secret>; cmd`.
    # Move to a 0600 config file if the threat model ever includes other local users.
    return [
        "uvx",
        "--python",
        PDF2ZH_PYTHON,
        "--from",
        PDF2ZH_SPEC,
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
        # --pages only limits *what gets translated*; without this the dual PDF still
        # carries every source page, burying the translated range in a full-book file.
        *(["--only-include-translated-page"] if _has_pages_flag(extra_args) else []),
        "--openaicompatible",
        "--openai-compatible-base-url",
        cfg["base_url"],
        "--openai-compatible-api-key",
        cfg["api_key"],
        "--openai-compatible-model",
        cfg["model"],
        *extra_args,
    ]


def _has_pages_flag(extra_args: list[str]) -> bool:
    return any(arg == "--pages" or arg.startswith("--pages=") for arg in extra_args)


def page_count(pdf_path: Path) -> int:
    try:
        doc = pymupdf.open(str(pdf_path))
        count = len(doc)
        doc.close()
    except Exception as exc:
        raise TranslationError(f"Failed to read PDF {pdf_path}: {exc}") from exc
    return count


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
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise TranslationError(
            f"pdf2zh-next exited {result.returncode}. Partial output kept at {work_dir}.",
        )


def translate_slug(
    slug: str,
    *,
    source_file: Path | None = None,
    target_language: str = "zh-CN",
    project_root: Path = PROJECT_ROOT,
    toc_json: Path | None = None,
    toc_page_side: str = "original",
    extra_args: list[str] | None = None,
) -> dict[str, object]:
    cfg = load_backend_config()
    source_pdf = resolve_source_pdf(slug, project_root=project_root, explicit_source=source_file)
    outputs = build_output_paths(
        slug=slug,
        target_language=target_language,
        project_root=project_root,
    )

    # Kept (not a TemporaryDirectory) so a failed or suspicious run stays inspectable.
    work_dir = outputs["output_dir"] / f".pdf2zh-{slug}"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    run_pdf2zh(
        build_command(
            source_pdf=source_pdf,
            work_dir=work_dir,
            target_language=target_language,
            cfg=cfg,
            extra_args=extra_args or [],
        ),
        work_dir,
    )

    dual_pdf = find_dual_pdf(work_dir)
    # A mangled translation still exits 0 upstream, so page count is the acceptance gate.
    actual_pages = page_count(dual_pdf)
    if _has_pages_flag(extra_args or []):
        # ponytail: knowing the exact expected count would mean reimplementing pdf2zh's
        # range parser ("1-3", "25-", "1,3,10-20"). Even-and-nonzero is the most a cheap
        # check can assert on a subset; do a full run for the strict gate.
        if actual_pages == 0 or actual_pages % 2:
            raise TranslationError(
                f"pdf2zh-next produced {actual_pages} pages, expected a non-zero even count "
                f"(alternating dual). Output kept at {dual_pdf} — inspect before trusting it.",
            )
    else:
        expected_pages = page_count(source_pdf) * 2
        if actual_pages != expected_pages:
            raise TranslationError(
                f"pdf2zh-next produced {actual_pages} pages, expected {expected_pages} "
                f"(alternating dual = 2x source). Output kept at {dual_pdf} — inspect before trusting it.",
            )

    outputs["final_pdf"].parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(dual_pdf), str(outputs["final_pdf"]))

    if _has_pages_flag(extra_args or []):
        # Bookmarks are placed by source page number; a trimmed output breaks that
        # mapping, so they would land on the wrong pages with no visible symptom.
        print("Skipping TOC: --pages output has no 1:1 source page mapping.", file=sys.stderr)
        toc_entries = 0
    else:
        chapter_manifest = project_root / "processing" / "chapters" / slug / "manifest.json"
        toc_entries = add_toc_to_split_pdf(
            source_pdf=source_pdf,
            split_pdf=outputs["final_pdf"],
            toc_json=toc_json,
            fallback_toc_json=chapter_manifest,
            page_side=toc_page_side,
        )
    # BabelDOC ships a ToUnicode CMap too small to decode its own CJK output; without
    # this the PDF renders fine but copy/paste and in-PDF search return mojibake.
    repair_tounicode(outputs["final_pdf"])

    # Page count says the file is well-formed, not that it carries a translation.
    # Must run after the ToUnicode repair: an unrepaired book extracts as mojibake in
    # the CJK extension-A block, which this counter does not count, so a healthy
    # 400-page book scores 0.17 and gets rejected.
    report = check_coverage(outputs["final_pdf"], target_language=target_language)
    if not report["ok"]:
        raise TranslationError(str(report["detail"]))
    print(report["detail"], file=sys.stderr)

    shutil.rmtree(work_dir, ignore_errors=True)

    return {
        "slug": slug,
        "source_pdf": source_pdf,
        "final_pdf": outputs["final_pdf"],
        "toc_entries": toc_entries,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Translate a Quasi PDF via pdf2zh-next and an OpenAI-compatible endpoint.",
    )
    parser.add_argument("slug", help="Quasi slug used to locate the source PDF")
    parser.add_argument("--source-file", type=Path, help="Explicit source PDF path")
    parser.add_argument("--target-language", default="zh-CN", help="Target language tag")
    parser.add_argument("--toc-json", type=Path, help="Tocify-style JSON with title/level/page")
    parser.add_argument(
        "--toc-page-side",
        choices=sorted(TOC_PAGE_SIDES),
        default="original",
        help="Which page each bookmark should target",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    # Unrecognised flags (--qps, --pool-max-workers, temperature knobs, ...)
    # pass straight through to pdf2zh_next.
    args, extra_args = parser.parse_known_args(argv)
    try:
        result = translate_slug(
            slug=args.slug,
            source_file=args.source_file,
            target_language=args.target_language,
            toc_json=args.toc_json,
            toc_page_side=args.toc_page_side,
            extra_args=extra_args,
        )
    except AmbiguousSourceError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except SourceNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except MissingAuthKeyError as exc:
        print(str(exc), file=sys.stderr)
        return 5
    except TranslationError as exc:
        print(str(exc), file=sys.stderr)
        return 6

    print("TRANSLATE_RESULT:")
    print(f"- slug: {result['slug']}")
    print(f"- source_pdf: {result['source_pdf']}")
    print("- pdf_id: -")
    print(f"- final_pdf: {result['final_pdf']}")
    print(f"- toc_entries: {result['toc_entries']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
