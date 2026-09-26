#!/usr/bin/env python3
"""quasi-extract — file → MD pipeline.

This is the unified extraction entrypoint. Worker scripts stay as sibling
implementation files, but callers route through this file via bin/quasi-extract.

    epub   process_epub.py        EPUB → chapter md
    text   extract_text.py        PDF → normalized UTF-8 text + signals
    ocr       ocr_pdf.sh          PDF → searchable PDF (OCR)
    ocr-generation ocr_generation.py  PDF → shared immutable OCR generation
    split     split_chapters.py   PDF → per-chapter files (by TOC / pages)
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
  quasi-extract ocr   INPUT.pdf [OUTPUT.pdf] [LANGUAGE] [--engine mineru|tesseract]
                                [--layout] [--no-clobber] [--json]
                                [--resume --progress-file PATH --chunk-pages N]
  quasi-extract ocr-generation --kind paper|book --slug SLUG
                                --source-file PATH --expected-source-sha256 SHA256
                                --generation-key SHA256
                                --profile mineru-text|tesseract-text [--json]
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
  quasi-extract ocr-generation --help
  quasi-extract split --help
"""


def _run_ocr(here: Path, rest: list[str]) -> int:
    """Dispatch `quasi-extract ocr` to an OCR engine.

    `--engine mineru` (default, MinerU2.5-Pro via mlx-vlm) | `tesseract`
    (ocrmypdf, explicit only). MinerU failure never silently changes engines.
    """
    engine = "mineru"
    layout: list[str] = []
    positional: list[str] = []
    json_mode = "--json" in rest
    no_clobber = False
    resume = False
    progress_file = ""
    chunk_pages = 8
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
        elif a == "--resume":
            if "resume" in seen:
                errors.append("duplicate --resume")
            seen.add("resume")
            resume = True
            i += 1
        elif a == "--progress-file":
            if "progress-file" in seen:
                errors.append("duplicate --progress-file")
            seen.add("progress-file")
            if i + 1 >= len(rest) or rest[i + 1].startswith("-"):
                errors.append("--progress-file requires a path")
                i += 1
            else:
                progress_file = rest[i + 1]
                i += 2
        elif a == "--chunk-pages":
            if "chunk-pages" in seen:
                errors.append("duplicate --chunk-pages")
            seen.add("chunk-pages")
            if i + 1 >= len(rest) or rest[i + 1].startswith("-"):
                errors.append("--chunk-pages requires an integer")
                i += 1
            else:
                try:
                    chunk_pages = int(rest[i + 1])
                except ValueError:
                    errors.append("--chunk-pages requires an integer")
                i += 2
        elif a == "--engine":
            if "engine" in seen:
                errors.append("duplicate --engine")
            if i + 1 >= len(rest) or rest[i + 1].startswith("-"):
                errors.append("--engine requires a value (mineru|tesseract)")
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
                errors.append("--engine requires a value (mineru|tesseract)")
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

    if resume and progress_file and "engine" not in seen:
        # Resume only the engine named by the caller's exact legacy progress;
        # the helper below still validates every identity field before writing.
        try:
            saved_progress = json.loads(Path(progress_file).read_text())
            if isinstance(saved_progress, dict) and saved_progress.get("engine") in {"mineru", "tesseract", "dsocr2"}:
                engine = saved_progress["engine"]
        except (OSError, ValueError):
            pass  # The normal resume validator reports malformed/missing state.
    if engine == "dsocr2":
        errors.append("DS OCR2 progress is read-only; start a new mineru-text generation")
    elif engine not in ("mineru", "tesseract"):
        errors.append(f"unknown engine '{engine}' (expected mineru|tesseract)")
    if layout and engine == "tesseract":
        errors.append("--layout requires MinerU recognition and paragraph placement; tesseract cannot supply it")
    if not positional or not positional[0]:
        errors.append("missing INPUT")
    if len(positional) > 3:
        errors.append("too many positional arguments")
    if (json_mode or no_clobber) and (
        len(positional) < 2 or not positional[1]
    ):
        errors.append("--json/--no-clobber requires an explicit OUTPUT")
    if resume:
        if not progress_file:
            errors.append("--resume requires --progress-file")
        if not json_mode:
            errors.append("--resume requires --json")
        if not no_clobber:
            errors.append("--resume requires --no-clobber")
        if layout:
            errors.append("--resume is only supported for non-layout Book OCR")
        if len(positional) < 2 or not positional[1]:
            errors.append("--resume requires an explicit OUTPUT")
        if not 1 <= chunk_pages <= 32:
            errors.append("--chunk-pages must be between 1 and 32")
    elif progress_file or "chunk-pages" in seen:
        errors.append("--progress-file/--chunk-pages requires --resume")
    if errors:
        return fail(errors[0])

    # mineru needs an explicit output path (ocr_pdf.sh auto-generates one).
    if engine == "mineru" and len(positional) < 2:
        stem = positional[0][: -len(".pdf")] if positional[0].lower().endswith(".pdf") else positional[0]
        positional.append(f"{stem}_ocr.pdf")

    input_arg = positional[0]
    output_arg = positional[1] if len(positional) > 1 else ""
    if layout:
        import layout_evidence
        try:
            layout_source_sha = layout_evidence.file_sha256(Path(input_arg))
        except OSError as exc:
            return fail(f"cannot read layout source: {exc}")

    def layout_valid(path: str) -> bool:
        if not layout:
            return True
        try:
            return (
                layout_evidence.inspect(Path(path), source_sha256=layout_source_sha)["prepared"]
                and layout_evidence.file_sha256(Path(input_arg)) == layout_source_sha
            )
        except Exception:
            return False
    if resume:
        from ocr_resume import run_ocr_step

        language = positional[2] if len(positional) > 2 else None

        def run_range(
            source_slice: Path,
            staged_output: Path,
            selected_engine: str,
            selected_language: str | None,
        ) -> int:
            args = [str(source_slice), str(staged_output)]
            if selected_language:
                args.append(selected_language)
            if selected_engine == "tesseract":
                command = ["bash", str(here / "ocr_pdf.sh"), *args]
                return subprocess.call(command, stdout=sys.stderr, stderr=sys.stderr)
            command = [sys.executable, str(here / "ocr_mineru.py"), *args]
            return subprocess.call(command, stdout=sys.stderr, stderr=sys.stderr)

        try:
            result = run_ocr_step(
                input_arg,
                output_arg,
                progress_file,
                engine,
                chunk_pages,
                language,
                runner=run_range,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            exists, size, _ = _ocr_output_state(output_arg)
            _emit_ocr_json(
                status="failed",
                input_arg=input_arg,
                output_arg=output_arg,
                exit_code=1,
                exists=exists,
                size=size,
                failure={"code": "ocr_resume_failed", "message": str(exc)},
            )
            return 1
        print(json.dumps({**result, "exit": 0, "failure": None}, ensure_ascii=False))
        return 0
    if no_clobber:
        exists, size, regular = _ocr_output_state(output_arg)
        if exists:
            if regular and size > 0 and layout_valid(output_arg):
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
            code = "layout_unproven" if regular and size > 0 else ("output_empty" if regular else "output_not_regular")
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
            if layout:
                output_path.parent.mkdir(parents=True, exist_ok=True)
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
                    str(here / "ocr_mineru.py"),
                    *engine_positional,
                    *layout,
                ]
            )

        if not (json_mode or no_clobber or layout):
            return rc

        validation_path = engine_positional[1]
        staged_exists, staged_size, staged_regular = _ocr_output_state(
            validation_path
        )
        layout_proven = layout_valid(validation_path) if rc == 0 and staged_regular and staged_size > 0 else False
        success = rc == 0 and staged_regular and staged_size > 0 and layout_proven
        if not success:
            exists, size, _ = _ocr_output_state(output_arg)
            failure = None
            if rc != 0:
                failure = {
                    "code": "layout_failed" if layout else "ocr_failed",
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
            elif staged_size == 0:
                failure = {
                    "code": "output_empty",
                    "message": "OCR output is empty",
                }
            else:
                failure = {
                    "code": "layout_unproven",
                    "message": "layout output does not prove paragraph placement for this exact source",
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
            elif failure:
                print(f"[extract] {failure['message']}", file=sys.stderr)
            return rc if rc != 0 else 1

        if no_clobber:
            try:
                os.link(validation_path, output_arg)
            except FileExistsError:
                exists, size, regular = _ocr_output_state(output_arg)
                if regular and size > 0 and layout_valid(output_arg):
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
                code = "layout_unproven" if regular and size > 0 else ("output_empty" if regular else "output_not_regular")
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
        "[--engine mineru|tesseract] [--layout] [--no-clobber] [--json] "
        "[--resume --progress-file PATH --chunk-pages N]"
    )
    print(
        "Default engine: mineru (MinerU2.5-Pro). "
        "Tesseract is available only when explicitly selected."
    )
    print("--layout: page image + invisible text at the OCR boxes, to re-OCR a")
    print("          source PDF before quasi-translate; requires MinerU paragraph grouping.")
    print("          No tesseract fallback in layout mode. Default output is reflowed text.")
    print("--no-clobber: require an explicit OUTPUT and never overwrite an existing path.")
    print("--json: require an explicit OUTPUT; emit exactly one JSON receipt on stdout.")
    print("--resume: run one Book OCR page range and persist exact progress.")
    print("--progress-file: exact durable JSON progress path required by --resume.")
    print("--chunk-pages: pages per resumable step (default 8, range 1-32).")


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
    if code == "layout_unproven":
        message = "existing output has no valid layout evidence for this source; preserved without overwriting"
    elif code == "output_empty":
        message = "refusing to overwrite an empty output"
    else:
        message = "refusing to overwrite a non-regular output"
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
    if subcmd == "ocr-generation":
        return subprocess.call([sys.executable, str(here / "ocr_generation.py"), *rest])
    if subcmd == "split":
        return subprocess.call([sys.executable, str(here / "split_chapters.py"), *rest])

    print(f"quasi-extract: unknown subcommand: {subcmd}", file=sys.stderr)
    print("valid subcommands: epub | text | ocr | ocr-generation | split", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
