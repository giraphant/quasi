#!/usr/bin/env python3
"""Deterministically extract a PDF text layer with ``pdftotext``.

The command reports extraction signals, not a readability verdict.  A PDF with
an empty, sparse, or garbled text layer can therefore still be a successful
conversion; callers decide whether OCR or human judgement is needed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _output_state(path: Path) -> tuple[bool, int]:
    try:
        exists = path.is_file()
        return exists, path.stat().st_size if exists else 0
    except OSError:
        return False, 0


def _page_signals(text: str) -> tuple[int | None, int | None]:
    """Count form-feed-delimited pages when ``pdftotext`` exposes them."""
    if "\f" in text:
        parts = text.split("\f")
        if parts and parts[-1] == "":
            parts.pop()
        return len(parts), sum(bool(part.strip()) for part in parts)
    if text:
        return 1, 1
    return None, None


def _receipt(
    *,
    status: str,
    input_arg: str,
    output_arg: str,
    output_path: Path,
    exit_code: int,
    failure: dict[str, str] | None,
    text: str | None = None,
) -> dict[str, Any]:
    exists, size = _output_state(output_path)
    payload: dict[str, Any] = {
        "status": status,
        "input": input_arg,
        "output": output_arg,
        "exists": exists,
        "size": size,
        "chars": len(text) if text is not None else 0,
        "non_whitespace_chars": (
            sum(not char.isspace() for char in text) if text is not None else 0
        ),
        "pages": 0,
        "text_pages": 0,
        "exit": exit_code,
        "failure": failure,
    }
    if text is not None:
        pages, text_pages = _page_signals(text)
        if pages is not None:
            payload["pages"] = pages
            payload["text_pages"] = text_pages
    return payload


def _emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return
    if payload["status"] == "ok":
        print(
            f"wrote {payload['output']} "
            f"({payload['chars']} chars, {payload['size']} bytes)"
        )
        return
    failure = payload.get("failure") or {}
    print(
        f"quasi-extract text: {failure.get('message', 'extraction failed')}",
        file=sys.stderr,
    )


def _fail(
    *,
    input_arg: str,
    output_arg: str,
    output_path: Path,
    exit_code: int,
    code: str,
    message: str,
    as_json: bool,
) -> int:
    payload = _receipt(
        status="error",
        input_arg=input_arg,
        output_arg=output_arg,
        output_path=output_path,
        exit_code=exit_code,
        failure={"code": code, "message": message},
    )
    _emit(payload, as_json=as_json)
    return exit_code


def extract_text(input_arg: str, output_arg: str, *, as_json: bool) -> int:
    input_path = Path(input_arg).expanduser()
    output_path = Path(output_arg).expanduser()

    if not input_path.is_file():
        return _fail(
            input_arg=input_arg,
            output_arg=output_arg,
            output_path=output_path,
            exit_code=2,
            code="input_missing",
            message=f"input file not found: {input_arg}",
            as_json=as_json,
        )

    try:
        same_path = input_path.resolve() == output_path.resolve()
    except OSError:
        same_path = False
    if same_path:
        return _fail(
            input_arg=input_arg,
            output_arg=output_arg,
            output_path=output_path,
            exit_code=2,
            code="input_output_conflict",
            message="input and output must be different paths",
            as_json=as_json,
        )

    pdftotext = shutil.which("pdftotext")
    if pdftotext is None:
        return _fail(
            input_arg=input_arg,
            output_arg=output_arg,
            output_path=output_path,
            exit_code=127,
            code="pdftotext_missing",
            message="pdftotext is not available on PATH",
            as_json=as_json,
        )

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
        )
        os.close(fd)
    except OSError as exc:
        return _fail(
            input_arg=input_arg,
            output_arg=output_arg,
            output_path=output_path,
            exit_code=1,
            code="output_prepare_failed",
            message=str(exc),
            as_json=as_json,
        )

    temp_path = Path(temp_name)
    try:
        proc = subprocess.run(
            [pdftotext, "-enc", "UTF-8", str(input_path), str(temp_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "pdftotext failed").strip()
            return _fail(
                input_arg=input_arg,
                output_arg=output_arg,
                output_path=output_path,
                exit_code=proc.returncode or 1,
                code="pdftotext_failed",
                message=detail[-2000:],
                as_json=as_json,
            )

        raw = temp_path.read_bytes()
        text = raw.decode("utf-8")
        encoded = text.encode("utf-8")
        with temp_path.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, output_path)

        payload = _receipt(
            status="ok",
            input_arg=input_arg,
            output_arg=output_arg,
            output_path=output_path,
            exit_code=0,
            failure=None,
            text=text,
        )
        _emit(payload, as_json=as_json)
        return 0
    except (OSError, UnicodeError) as exc:
        return _fail(
            input_arg=input_arg,
            output_arg=output_arg,
            output_path=output_path,
            exit_code=1,
            code="output_write_failed",
            message=str(exc),
            as_json=as_json,
        )
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="quasi-extract text",
        description=(
            "Extract a PDF text layer atomically and report deterministic signals. "
            "No readability threshold is applied."
        ),
    )
    parser.add_argument("input", help="source PDF")
    parser.add_argument("output", help="UTF-8 text output")
    parser.add_argument("--json", action="store_true", help="emit a JSON receipt")
    args = parser.parse_args(argv)
    return extract_text(args.input, args.output, as_json=args.json)


if __name__ == "__main__":
    sys.exit(main())
