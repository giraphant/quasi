#!/usr/bin/env python3
"""One durable page-range transaction for resumable Book OCR."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Callable, Iterator, Optional

import fitz


SCHEMA_VERSION = "quasi.ocr.progress/0.1"
ENGINES = {"dsocr2", "mineru", "tesseract"}
PROGRESS_KEYS = {
    "schema_version",
    "input_path",
    "output_path",
    "source_sha256",
    "engine",
    "chunk_pages",
    "total_pages",
    "completed_pages",
    "next_page",
}
Runner = Callable[[Path, Path, str, Optional[str]], int]
PartValidator = Callable[[Path, int], None]


def _regular_file(path: Path, *, allow_missing: bool = False) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return False
        raise ValueError(f"required file is missing: {path}")
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise ValueError(f"path is not a regular file: {path}")
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pdf_pages(path: Path) -> int:
    _regular_file(path)
    try:
        with fitz.open(path) as document:
            pages = document.page_count
    except Exception as exc:
        raise ValueError(f"OCR part is not a readable PDF: {path}: {exc}") from exc
    if pages <= 0:
        raise ValueError(f"OCR part has no pages: {path}")
    return pages


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        _regular_file(path)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        _fsync_directory(path.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp_name)


def _parse_progress(path: Path) -> dict[str, object]:
    _regular_file(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid OCR progress JSON: {exc}") from exc
    if not isinstance(value, dict) or set(value) != PROGRESS_KEYS:
        raise ValueError("invalid OCR progress keys")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("invalid OCR progress schema_version")
    for key in ("input_path", "output_path"):
        if not isinstance(value[key], str) or not value[key]:
            raise ValueError(f"invalid OCR progress {key}")
    if not isinstance(value["source_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", value["source_sha256"]
    ):
        raise ValueError("invalid OCR progress source_sha256")
    if value["engine"] not in ENGINES:
        raise ValueError("invalid OCR progress engine")
    for key in ("chunk_pages", "total_pages", "completed_pages"):
        if isinstance(value[key], bool) or not isinstance(value[key], int):
            raise ValueError(f"invalid OCR progress {key}")
    chunk = int(value["chunk_pages"])
    total = int(value["total_pages"])
    completed = int(value["completed_pages"])
    if not 1 <= chunk <= 32 or total < 1 or not 0 <= completed <= total:
        raise ValueError("invalid OCR progress counts")
    expected_next = completed + 1 if completed < total else None
    if value["next_page"] != expected_next:
        raise ValueError("invalid OCR progress next_page")
    return value


def _part_path(parts: Path, start: int, end: int) -> Path:
    return parts / f"pages-{start:06d}-{end:06d}.pdf"


def _expected_ranges(total: int, chunk: int, completed: int) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = 1
    while start <= completed:
        end = min(start + chunk - 1, total)
        if end > completed:
            raise ValueError("OCR progress does not end on a committed range")
        ranges.append((start, end))
        start = end + 1
    return ranges


@contextlib.contextmanager
def _progress_lock(path: Path) -> Iterator[None]:
    import fcntl

    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists() or lock_path.is_symlink():
        _regular_file(lock_path)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(str(lock_path), flags, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"OCR progress is locked: {path}") from exc
        yield
    finally:
        os.close(descriptor)


def _initial_progress(
    source: Path, output: Path, source_hash: str, engine: str, chunk: int, total: int
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "input_path": str(source),
        "output_path": str(output),
        "source_sha256": source_hash,
        "engine": engine,
        "chunk_pages": chunk,
        "total_pages": total,
        "completed_pages": 0,
        "next_page": 1,
    }


def _validate_identity(
    progress: dict[str, object],
    source: Path,
    output: Path,
    source_hash: str,
    engine: str,
    chunk: int,
    total: int,
) -> None:
    expected = {
        "input_path": str(source),
        "output_path": str(output),
        "source_sha256": source_hash,
        "engine": engine,
        "chunk_pages": chunk,
        "total_pages": total,
    }
    for key, value in expected.items():
        if progress[key] != value:
            raise ValueError(f"OCR progress {key} does not match this request")


def _slice_pdf(source: Path, target: Path, start: int, end: int) -> None:
    with fitz.open(source) as document:
        sliced = fitz.open()
        try:
            sliced.insert_pdf(document, from_page=start - 1, to_page=end - 1)
            sliced.save(target)
        finally:
            sliced.close()


def _merge_parts(parts: list[Path], target: Path, total: int) -> None:
    merged = fitz.open()
    try:
        for part in parts:
            with fitz.open(part) as document:
                merged.insert_pdf(document)
        if merged.page_count != total:
            raise ValueError("merged OCR page count does not match source")
        merged.save(target)
    finally:
        merged.close()


def run_ocr_step(
    input_path: str | Path,
    output_path: str | Path,
    progress_path: str | Path,
    engine: str,
    chunk_pages: int,
    language: str | None,
    *,
    runner: Runner,
    part_validator: PartValidator | None = None,
) -> dict[str, object]:
    """Run exactly one missing OCR range and publish durable progress."""

    source = Path(input_path)
    output = Path(output_path)
    progress_file = Path(progress_path)
    if engine not in {"mineru", "tesseract"}:
        raise ValueError("engine must be mineru or tesseract (dsocr2 is legacy read-only)")
    if isinstance(chunk_pages, bool) or not 1 <= chunk_pages <= 32:
        raise ValueError("chunk_pages must be between 1 and 32")
    _regular_file(source)
    total = _pdf_pages(source)
    source_hash = _sha256(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    progress_file.parent.mkdir(parents=True, exist_ok=True)

    with _progress_lock(progress_file):
        if output.exists() or output.is_symlink():
            if _pdf_pages(output) != total:
                raise ValueError("existing OCR output does not match source page count")
            return {
                "status": "existing",
                "input": str(source),
                "output": str(output),
                "progress": None,
            }

        if progress_file.exists() or progress_file.is_symlink():
            progress = _parse_progress(progress_file)
            _validate_identity(
                progress, source, output, source_hash, engine, chunk_pages, total
            )
        else:
            progress = _initial_progress(
                source, output, source_hash, engine, chunk_pages, total
            )
            _atomic_json(progress_file, progress)

        parts_dir = output.parent / ".ocr-parts"
        if parts_dir.exists() or parts_dir.is_symlink():
            if parts_dir.is_symlink() or not parts_dir.is_dir():
                raise ValueError(f"OCR parts path is not a directory: {parts_dir}")
        else:
            parts_dir.mkdir(mode=0o700)

        committed_ranges = _expected_ranges(
            total, chunk_pages, int(progress["completed_pages"])
        )
        expected_names = {
            _part_path(parts_dir, start, end).name for start, end in committed_ranges
        }
        for start, end in committed_ranges:
            part = _part_path(parts_dir, start, end)
            expected_pages = end - start + 1
            if _pdf_pages(part) != expected_pages:
                raise ValueError(f"committed OCR part has wrong page count: {part}")
            if part_validator is not None:
                part_validator(part, expected_pages)
        for child in parts_dir.iterdir():
            if child.name not in expected_names:
                # Only the exact next part may be an orphan from a crash between
                # part publication and progress publication.
                next_start = int(progress["completed_pages"]) + 1
                next_end = min(next_start + chunk_pages - 1, total)
                if child != _part_path(parts_dir, next_start, next_end):
                    raise ValueError(f"unexpected OCR part inventory: {child}")

        start = int(progress["completed_pages"]) + 1
        end = min(start + chunk_pages - 1, total)
        part = _part_path(parts_dir, start, end)
        if part.exists() or part.is_symlink():
            expected_pages = end - start + 1
            if _pdf_pages(part) != expected_pages:
                raise ValueError(f"orphan OCR part has wrong page count: {part}")
            if part_validator is not None:
                part_validator(part, expected_pages)
        else:
            work_dir = Path(
                tempfile.mkdtemp(prefix=f".{part.name}.", dir=str(parts_dir))
            )
            try:
                source_slice = work_dir / "input.pdf"
                candidate = work_dir / "output.pdf"
                _slice_pdf(source, source_slice, start, end)
                rc = runner(source_slice, candidate, engine, language)
                if rc != 0:
                    raise RuntimeError(f"OCR engine exited {rc}")
                expected_pages = end - start + 1
                if _pdf_pages(candidate) != expected_pages:
                    raise ValueError("OCR engine returned the wrong page count")
                if part_validator is not None:
                    part_validator(candidate, expected_pages)
                os.replace(candidate, part)
                _fsync_directory(parts_dir)
            finally:
                shutil.rmtree(work_dir, ignore_errors=True)

        completed = end
        progress = dict(progress)
        progress["completed_pages"] = completed
        progress["next_page"] = completed + 1 if completed < total else None
        _atomic_json(progress_file, progress)

        if completed < total:
            return {
                "status": "partial",
                "input": str(source),
                "output": str(output),
                "progress": progress,
            }

        all_ranges = _expected_ranges(total, chunk_pages, total)
        all_parts = [_part_path(parts_dir, first, last) for first, last in all_ranges]
        for current, (first, last) in zip(all_parts, all_ranges):
            expected_pages = last - first + 1
            if _pdf_pages(current) != expected_pages:
                raise ValueError(f"OCR part has wrong page count: {current}")
            if part_validator is not None:
                part_validator(current, expected_pages)
        descriptor, staged_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=str(output.parent)
        )
        os.close(descriptor)
        staged = Path(staged_name)
        try:
            staged.unlink()
            _merge_parts(all_parts, staged, total)
            _pdf_pages(staged)
            # Fail closed if another writer published after the entry check.
            try:
                os.link(staged, output)
            except FileExistsError as exc:
                raise RuntimeError(f"OCR output appeared during commit: {output}") from exc
            _fsync_directory(output.parent)
        finally:
            with contextlib.suppress(FileNotFoundError):
                staged.unlink()
        progress_file.unlink()
        shutil.rmtree(parts_dir)
        _fsync_directory(output.parent)
        return {
            "status": "ok",
            "input": str(source),
            "output": str(output),
            "progress": progress,
        }
