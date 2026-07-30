#!/usr/bin/env python3
"""quasi-extract — file → MD pipeline.

This is the unified extraction entrypoint. Worker scripts stay as sibling
implementation files, but callers route through this file via bin/quasi-extract.

    epub   process_epub.py        EPUB → chapter md
    text   extract_text.py        PDF → normalized UTF-8 text + signals
    ocr    ocr_pdf.sh             PDF → searchable PDF (OCR)
    split  split_chapters.py      PDF → per-chapter files (by TOC / pages)
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


HELP = """\
quasi-extract — file → MD pipeline.

Usage:
  quasi-extract epub  SOURCE_EPUB CHAPTERS_DIR [--json]
  quasi-extract text  INPUT.pdf OUTPUT.txt [--json]
  quasi-extract ocr   INPUT.pdf [OUTPUT.pdf] [LANGUAGE] [--engine dsocr2|tesseract]
                                [--layout] [--no-clobber] [--json]
  quasi-extract split INPUT.pdf --output-dir DIR
                                [--method toc|pattern]
                                [--max-chapters N]
                                [--expected-manifest-fingerprint SHA256]
                                [--chapters JSON] [--json]
                                [--pages RANGE --title T --slot S --json]

Each subcommand has its own --help with full args:
  quasi-extract epub --help
  quasi-extract text --help
  quasi-extract ocr --help
  quasi-extract split --help
"""


def _run_ocr(here: Path, rest: list[str]) -> int:
    """Dispatch `quasi-extract ocr` to an OCR engine.

    `--engine dsocr2` (default, DeepSeek-OCR-2 via mlx-vlm) | `tesseract`
    (ocrmypdf). dsocr2 auto-falls-back to tesseract if it is unavailable or
    fails, so OCR still works on machines without MLX or the model.
    """
    engine = "dsocr2"
    layout: list[str] = []
    positional: list[str] = []
    json_mode = "--json" in rest
    no_clobber = False
    seen: set[str] = set()
    errors: list[str] = []

    def fail(message: str) -> int:
        input_arg = positional[0] if positional else ""
        output_arg = positional[1] if len(positional) > 1 else ""
        if json_mode:
            exists, size, _ = _ocr_output_state(output_arg)
            _emit_ocr_json(
                status="failed",
                input_arg=input_arg,
                output_arg=output_arg,
                exit_code=2,
                exists=exists,
                size=size,
                failure={"code": "invalid_arguments", "message": message},
            )
        else:
            print(f"quasi-extract ocr: {message}", file=sys.stderr)
        return 2

    if not json_mode and any(arg in ("-h", "--help") for arg in rest):
        _print_ocr_help()
        return 0

    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--layout":
            if "layout" in seen:
                errors.append("duplicate --layout")
            seen.add("layout")
            layout = [a]
            i += 1
        elif a == "--json":
            if "json" in seen:
                errors.append("duplicate --json")
            seen.add("json")
            json_mode = True
            i += 1
        elif a == "--no-clobber":
            if "no-clobber" in seen:
                errors.append("duplicate --no-clobber")
            seen.add("no-clobber")
            no_clobber = True
            i += 1
        elif a == "--engine":
            if "engine" in seen:
                errors.append("duplicate --engine")
            if i + 1 >= len(rest) or rest[i + 1].startswith("-"):
                errors.append("--engine requires a value (dsocr2|tesseract)")
                seen.add("engine")
                i += 1
            else:
                seen.add("engine")
                engine = rest[i + 1]
                i += 2
        elif a.startswith("--engine="):
            if "engine" in seen:
                errors.append("duplicate --engine")
            seen.add("engine")
            engine = a.split("=", 1)[1]
            if not engine:
                errors.append("--engine requires a value (dsocr2|tesseract)")
            i += 1
        elif a in ("-h", "--help"):
            errors.append("--help cannot be combined with --json")
            i += 1
        elif a.startswith("-"):
            errors.append(f"unknown option: {a}")
            i += 1
        else:
            positional.append(a)
            i += 1

    if engine not in ("dsocr2", "tesseract"):
        errors.append(f"unknown engine '{engine}' (expected dsocr2|tesseract)")
    if not positional or not positional[0]:
        errors.append("missing INPUT")
    if len(positional) > 3:
        errors.append("too many positional arguments")
    if (json_mode or no_clobber) and (
        len(positional) < 2 or not positional[1]
    ):
        errors.append("--json/--no-clobber requires an explicit OUTPUT")
    if errors:
        return fail(errors[0])

    # dsocr2 needs an explicit output path (ocr_pdf.sh auto-generates one).
    if engine == "dsocr2" and len(positional) < 2:
        stem = positional[0][: -len(".pdf")] if positional[0].lower().endswith(".pdf") else positional[0]
        positional.append(f"{stem}_ocr.pdf")

    input_arg = positional[0]
    output_arg = positional[1] if len(positional) > 1 else ""
    if no_clobber:
        exists, size, regular = _ocr_output_state(output_arg)
        if exists:
            if regular and size > 0:
                if json_mode:
                    _emit_ocr_json(
                        status="existing",
                        input_arg=input_arg,
                        output_arg=output_arg,
                        exit_code=0,
                        exists=True,
                        size=size,
                        failure=None,
                    )
                else:
                    print(f"OCR output already exists: {output_arg}", file=sys.stderr)
                return 0
            code = "output_empty" if regular else "output_not_regular"
            return _ocr_collision_failure(
                input_arg=input_arg,
                output_arg=output_arg,
                size=size,
                code=code,
                json_mode=json_mode,
            )

    stage_dir: Path | None = None
    engine_positional = positional
    if no_clobber:
        output_path = Path(output_arg)
        try:
            stage_dir = Path(
                tempfile.mkdtemp(
                    prefix=f".{output_path.name}.ocr-",
                    dir=str(output_path.parent),
                )
            )
        except OSError as exc:
            exists, size, _ = _ocr_output_state(output_arg)
            if json_mode:
                _emit_ocr_json(
                    status="failed",
                    input_arg=input_arg,
                    output_arg=output_arg,
                    exit_code=2,
                    exists=exists,
                    size=size,
                    failure={
                        "code": "staging_failed",
                        "message": f"could not create OCR staging directory: {exc}",
                    },
                )
            else:
                print(
                    f"quasi-extract ocr: could not create staging directory: {exc}",
                    file=sys.stderr,
                )
            return 2
        engine_positional = positional.copy()
        engine_positional[1] = str(stage_dir / output_path.name)

    def run_child(command: list[str]) -> int:
        try:
            if json_mode:
                return subprocess.call(
                    command, stdout=sys.stderr, stderr=sys.stderr
                )
            return subprocess.call(command)
        except OSError as exc:
            if not (json_mode or no_clobber):
                raise
            print(f"[extract] could not launch OCR engine: {exc}", file=sys.stderr)
            return 127

    try:
        if engine == "tesseract":
            rc = run_child(["bash", str(here / "ocr_pdf.sh"), *engine_positional])
        else:
            rc = run_child(
                [
                    sys.executable,
                    str(here / "ocr_dsocr2.py"),
                    *engine_positional,
                    *layout,
                ]
            )
            if rc != 0:
                # tesseract always writes image + text layer, so it satisfies
                # --layout by default.
                sys.stderr.write(
                    "[extract] DS OCR2 unavailable/failed; falling back to tesseract.\n"
                )
                rc = run_child(
                    ["bash", str(here / "ocr_pdf.sh"), *engine_positional]
                )

        if not (json_mode or no_clobber):
            return rc

        validation_path = engine_positional[1]
        staged_exists, staged_size, staged_regular = _ocr_output_state(
            validation_path
        )
        success = rc == 0 and staged_regular and staged_size > 0
        if not success:
            exists, size, _ = _ocr_output_state(output_arg)
            failure = None
            if rc != 0:
                failure = {
                    "code": "ocr_failed",
                    "message": f"final OCR engine exited {rc}",
                }
            elif not staged_exists:
                failure = {
                    "code": "output_missing",
                    "message": "OCR exited 0 but did not create its output",
                }
            elif not staged_regular:
                failure = {
                    "code": "output_not_regular",
                    "message": "OCR output is not a regular file",
                }
            else:
                failure = {
                    "code": "output_empty",
                    "message": "OCR output is empty",
                }
            if json_mode:
                _emit_ocr_json(
                    status="failed",
                    input_arg=input_arg,
                    output_arg=output_arg,
                    exit_code=rc,
                    exists=exists,
                    size=size,
                    failure=failure,
                )
            return rc if rc != 0 else 1

        if no_clobber:
            try:
                os.link(validation_path, output_arg)
            except FileExistsError:
                exists, size, regular = _ocr_output_state(output_arg)
                if regular and size > 0:
                    if json_mode:
                        _emit_ocr_json(
                            status="existing",
                            input_arg=input_arg,
                            output_arg=output_arg,
                            exit_code=0,
                            exists=True,
                            size=size,
                            failure=None,
                        )
                    else:
                        print(
                            f"OCR output already exists: {output_arg}",
                            file=sys.stderr,
                        )
                    return 0
                if not exists:
                    if json_mode:
                        _emit_ocr_json(
                            status="failed",
                            input_arg=input_arg,
                            output_arg=output_arg,
                            exit_code=rc,
                            exists=False,
                            size=0,
                            failure={
                                "code": "commit_race_lost",
                                "message": "competing OCR output disappeared before validation",
                            },
                        )
                    return rc if rc != 0 else 1
                code = "output_empty" if regular else "output_not_regular"
                return _ocr_collision_failure(
                    input_arg=input_arg,
                    output_arg=output_arg,
                    size=size,
                    code=code,
                    json_mode=json_mode,
                    receipt_exit=rc,
                    cli_exit=rc if rc != 0 else 1,
                )
            except OSError as exc:
                exists, size, _ = _ocr_output_state(output_arg)
                if json_mode:
                    _emit_ocr_json(
                        status="failed",
                        input_arg=input_arg,
                        output_arg=output_arg,
                        exit_code=rc,
                        exists=exists,
                        size=size,
                        failure={
                            "code": "commit_failed",
                            "message": f"atomic OCR commit failed: {exc}",
                        },
                    )
                else:
                    print(
                        f"quasi-extract ocr: atomic commit failed: {exc}",
                        file=sys.stderr,
                    )
                return rc if rc != 0 else 1

        exists, size, regular = _ocr_output_state(output_arg)
        success = rc == 0 and regular and size > 0
        if json_mode:
            _emit_ocr_json(
                status="ok" if success else "failed",
                input_arg=input_arg,
                output_arg=output_arg,
                exit_code=rc,
                exists=exists,
                size=size,
                failure=(
                    None
                    if success
                    else {
                        "code": "commit_invalid",
                        "message": "exact OCR output is missing, empty, or non-regular",
                    }
                ),
            )
        if success:
            return 0
        return rc if rc != 0 else 1
    finally:
        if stage_dir is not None:
            shutil.rmtree(stage_dir, ignore_errors=True)


def _ocr_output_state(output_arg: str) -> tuple[bool, int, bool]:
    if not output_arg:
        return False, 0, False
    try:
        info = Path(output_arg).lstat()
    except FileNotFoundError:
        return False, 0, False
    except OSError:
        # An uninspectable path is not safe to hand to a clobbering writer.
        return True, 0, False
    return True, info.st_size, stat.S_ISREG(info.st_mode)


def _print_ocr_help() -> None:
    print(
        "Usage: quasi-extract ocr INPUT.pdf [OUTPUT.pdf] [LANGUAGE] "
        "[--engine dsocr2|tesseract] [--layout] [--no-clobber] [--json]"
    )
    print(
        "Default engine: dsocr2 (DeepSeek-OCR-2). "
        "Falls back to tesseract if unavailable."
    )
    print("--layout: page image + invisible text at the OCR boxes, to re-OCR a")
    print("          source PDF before quasi-translate. Default output is reflowed text.")
    print("--no-clobber: require an explicit OUTPUT and never overwrite an existing path.")
    print("--json: require an explicit OUTPUT; emit exactly one JSON receipt on stdout.")


def _emit_ocr_json(
    *,
    status: str,
    input_arg: str,
    output_arg: str,
    exit_code: int,
    exists: bool,
    size: int,
    failure: dict[str, str] | None,
) -> None:
    print(
        json.dumps(
            {
                "status": status,
                "input": input_arg,
                "output": output_arg,
                "exit": exit_code,
                "exists": exists,
                "size": size,
                "failure": failure,
            },
            ensure_ascii=False,
        )
    )


def _ocr_collision_failure(
    *,
    input_arg: str,
    output_arg: str,
    size: int,
    code: str,
    json_mode: bool,
    receipt_exit: int = 2,
    cli_exit: int = 2,
) -> int:
    message = (
        "refusing to overwrite an empty output"
        if code == "output_empty"
        else "refusing to overwrite a non-regular output"
    )
    if json_mode:
        _emit_ocr_json(
            status="failed",
            input_arg=input_arg,
            output_arg=output_arg,
            exit_code=receipt_exit,
            exists=True,
            size=size,
            failure={"code": code, "message": message},
        )
    else:
        print(f"quasi-extract ocr: {message}: {output_arg}", file=sys.stderr)
    return cli_exit


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        sys.stdout.write(HELP)
        return 0

    here = Path(__file__).resolve().parent
    subcmd, rest = sys.argv[1], sys.argv[2:]
    if subcmd == "epub":
        return subprocess.call([sys.executable, str(here / "process_epub.py"), *rest])
    if subcmd == "text":
        return subprocess.call([sys.executable, str(here / "extract_text.py"), *rest])
    if subcmd == "ocr":
        return _run_ocr(here, rest)
    if subcmd == "split":
        return subprocess.call([sys.executable, str(here / "split_chapters.py"), *rest])

    print(f"quasi-extract: unknown subcommand: {subcmd}", file=sys.stderr)
    print("valid subcommands: epub | text | ocr | split", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
