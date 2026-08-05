#!/usr/bin/env python3
"""Transactional commit support for chapter extraction commands.

The extractors build a complete chapter set in a sibling staging directory.
This module validates that set, serialises writers with a sibling lock, and
publishes chapter files before replacing ``manifest.json`` as the commit marker.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))
from scripts.schemas.chapter_manifest import valid_chapter_page_pair  # noqa: E402


SCHEMA_VERSION = "quasi.extract.chapters.receipt/0.1"
MANIFEST_NAME = "manifest.json"
_UNSET = object()


class ChapterFailure(Exception):
    """A classified extraction failure suitable for a structured receipt."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: str = "failed",
        outcome: str = "known",
        retryable: bool = False,
        exit_code: int = 1,
    ) -> None:
        super().__init__(message)
        if status not in {"failed", "blocked"}:
            raise ValueError(f"invalid chapter failure status: {status}")
        expected_outcome = "known" if status == "failed" else "unknown"
        if outcome != expected_outcome or retryable:
            raise ValueError(
                "chapter failure matrix requires failed/known or "
                "blocked/unknown with retryable=false"
            )
        self.code = code
        self.message = message
        self.status = status
        self.outcome = outcome
        self.retryable = retryable
        self.exit_code = exit_code


def _failure_dict(exc: ChapterFailure) -> dict:
    return {
        "code": exc.code,
        "outcome": exc.outcome,
        "retryable": exc.retryable,
        "message": exc.message,
    }


def emit_receipt(receipt: dict) -> None:
    """Emit exactly one compact JSON object on stdout."""
    print(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")))


def _regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_identity(path: Path) -> dict:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ChapterFailure(
            "input_missing",
            f"input file does not exist: {path}",
            exit_code=2,
        ) from exc
    except OSError as exc:
        raise ChapterFailure(
            "input_unreadable",
            f"cannot inspect input file: {exc}",
            exit_code=2,
        ) from exc
    if not stat.S_ISREG(info.st_mode):
        raise ChapterFailure(
            "input_not_regular",
            f"input path is not a regular file: {path}",
            exit_code=2,
        )
    try:
        digest = _sha256(path)
    except OSError as exc:
        raise ChapterFailure(
            "input_unreadable",
            f"cannot read input file: {exc}",
            exit_code=2,
        ) from exc
    return {
        "path": str(path.resolve()),
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "sha256": digest,
    }


def request_fingerprint(input_path: Path, mode: str, options: dict) -> tuple[str, dict]:
    identity = _source_identity(input_path)
    encoded = json.dumps(
        {"input": identity, "mode": mode, "options": options},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), identity


def _manifest_digest(path: Path) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    if not _regular_file(path):
        raise ChapterFailure(
            "manifest_not_regular",
            f"manifest is not a regular file: {path}",
            status="blocked",
            outcome="unknown",
        )
    try:
        return _sha256(path)
    except OSError as exc:
        raise ChapterFailure(
            "manifest_unreadable",
            f"cannot read manifest: {exc}",
            status="blocked",
            outcome="unknown",
        ) from exc


def _receipt_manifest_digest(path: Path) -> str | None:
    """Return the exact readable manifest byte digest, else ``None``."""
    try:
        return _manifest_digest(path)
    except ChapterFailure:
        return None


def verify_expected_manifest(
    output_dir: Path, expected_manifest_fingerprint: str | None
) -> str | None:
    """Check an optional raw-manifest SHA-256 precondition without writing."""
    if expected_manifest_fingerprint is not None and re.fullmatch(
        r"[0-9a-f]{64}", expected_manifest_fingerprint
    ) is None:
        raise ChapterFailure(
            "invalid_expected_manifest_fingerprint",
            "--expected-manifest-fingerprint must be a lowercase SHA-256 digest",
            exit_code=2,
        )
    observed = _manifest_digest(output_dir / MANIFEST_NAME)
    if (
        expected_manifest_fingerprint is not None
        and observed != expected_manifest_fingerprint
    ):
        raise ChapterFailure(
            "expected_manifest_mismatch",
            "manifest fingerprint does not match the caller precondition",
        )
    return observed


def _safe_filename(value: object) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise ChapterFailure(
            "manifest_invalid",
            "chapter filename must be a non-empty basename",
            status="blocked",
            outcome="unknown",
        )
    path = Path(value)
    if path.name != value or path.suffix.lower() != ".txt":
        raise ChapterFailure(
            "manifest_invalid",
            f"unsafe chapter filename in manifest: {value!r}",
            status="blocked",
            outcome="unknown",
        )
    return value


def load_manifest(manifest_path: Path) -> dict | None:
    digest = _manifest_digest(manifest_path)
    if digest is None:
        return None
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ChapterFailure(
            "manifest_invalid",
            f"cannot parse existing manifest: {exc}",
            status="blocked",
            outcome="unknown",
        ) from exc
    if not isinstance(value, dict) or not isinstance(value.get("chapters"), list):
        raise ChapterFailure(
            "manifest_invalid",
            "manifest must be an object with a chapters array",
            status="blocked",
            outcome="unknown",
        )
    return value


def validate_manifest(manifest: dict, root: Path) -> None:
    chapters = manifest.get("chapters")
    skipped = manifest.get("skipped", [])
    if not isinstance(chapters, list) or not isinstance(skipped, list):
        raise ChapterFailure(
            "manifest_invalid",
            "manifest chapters and skipped fields must be arrays",
            status="blocked",
            outcome="unknown",
        )

    slots: set[str] = set()
    filenames: set[str] = set()
    for row in chapters:
        if not isinstance(row, dict):
            raise ChapterFailure(
                "manifest_invalid",
                "every chapter row must be an object",
                status="blocked",
                outcome="unknown",
            )
        slot = row.get("slot")
        if (
            not isinstance(slot, str)
            or re.fullmatch(r"[0-9]+[a-z]*", slot) is None
            or slot in slots
        ):
            raise ChapterFailure(
                "manifest_invalid",
                f"chapter slot is missing or duplicated: {slot!r}",
                status="blocked",
                outcome="unknown",
            )
        slots.add(slot)
        filename = _safe_filename(row.get("filename"))
        if filename in filenames:
            raise ChapterFailure(
                "manifest_invalid",
                f"chapter filename is duplicated: {filename}",
                status="blocked",
                outcome="unknown",
            )
        filenames.add(filename)
        chapter_path = root / filename
        if not _regular_file(chapter_path):
            raise ChapterFailure(
                "chapter_set_incomplete",
                f"chapter output is missing or non-regular: {chapter_path}",
                status="blocked",
                outcome="unknown",
            )
        if chapter_path.stat().st_size <= 0:
            raise ChapterFailure(
                "chapter_set_incomplete",
                f"chapter output is empty: {chapter_path}",
                status="blocked",
                outcome="unknown",
            )
        expected_hash = row.get("sha256")
        if expected_hash is not None and (
            not isinstance(expected_hash, str) or _sha256(chapter_path) != expected_hash
        ):
            raise ChapterFailure(
                "chapter_set_mismatch",
                f"chapter output does not match its manifest: {chapter_path}",
                status="blocked",
                outcome="unknown",
            )
        if not valid_chapter_page_pair(
            row.get("start_page"), row.get("end_page")
        ):
            raise ChapterFailure(
                "manifest_page_range_invalid",
                "chapter manifest page range must be paired and ordered",
                status="blocked",
                outcome="unknown",
            )


def _owned_snapshot(manifest: dict | None, root: Path) -> dict[str, str]:
    if manifest is None:
        return {}
    validate_manifest(manifest, root)
    return {
        _safe_filename(row["filename"]): _sha256(root / row["filename"])
        for row in manifest["chapters"]
    }


def _same_snapshot(expected: dict[str, str], root: Path) -> bool:
    for filename, digest in expected.items():
        path = root / filename
        if not _regular_file(path) or _sha256(path) != digest:
            return False
    return True


@contextmanager
def _output_lock(output_dir: Path) -> Iterator[None]:
    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    lock_path = parent / f".{output_dir.name}.quasi-extract.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ChapterFailure(
            "lock_unavailable",
            f"cannot open chapter output lock: {exc}",
        ) from exc
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ChapterFailure(
            "lock_invalid",
            f"chapter output lock is not a regular file: {lock_path}",
        )
    try:
        with os.fdopen(fd, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except BaseException:
        # fdopen owns the descriptor once entered; close only if it did not.
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _receipt(
    *,
    input_path: Path,
    output_dir: Path,
    mode: str,
    fingerprint: str | None,
    max_chapters: int,
    status: str,
    disposition: str | None,
    exit_code: int,
    manifest: dict | None,
    removed_files: list[str],
    previous_manifest_preserved: bool,
    failure: dict | None,
) -> dict:
    chapters = copy.deepcopy(manifest.get("chapters", [])) if manifest else []
    skipped = copy.deepcopy(manifest.get("skipped", [])) if manifest else []
    manifest_path = output_dir / MANIFEST_NAME
    manifest_exists = _regular_file(manifest_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "mode": mode,
        "disposition": disposition,
        "exit": exit_code,
        "manifest_path": str(manifest_path),
        "manifest_exists": manifest_exists,
        "request_fingerprint": fingerprint,
        "manifest_fingerprint": (
            _receipt_manifest_digest(manifest_path) if manifest_exists else None
        ),
        "chapter_count": len(chapters),
        "chapters": chapters,
        "skipped": skipped,
        "removed_files": removed_files,
        "limit": {
            "max_chapters": max_chapters,
            "exceeded": len(chapters) > max_chapters,
        },
        "previous_manifest_preserved": previous_manifest_preserved,
        "failure": failure,
    }


def failure_receipt(
    *,
    input_path: Path,
    output_dir: Path,
    mode: str,
    max_chapters: int,
    error: ChapterFailure,
    fingerprint: str | None = None,
    expected_manifest_digest: str | None | object = _UNSET,
) -> dict:
    manifest_path = output_dir / MANIFEST_NAME
    previous_digest: str | None = None
    manifest: dict | None = None
    try:
        previous_digest = _manifest_digest(manifest_path)
        manifest = load_manifest(manifest_path)
        if manifest is not None:
            validate_manifest(manifest, output_dir)
    except ChapterFailure:
        manifest = None
    preserved = (
        previous_digest is not None
        if expected_manifest_digest is _UNSET
        else (
            expected_manifest_digest is not None
            and previous_digest == expected_manifest_digest
        )
    )
    return _receipt(
        input_path=input_path,
        output_dir=output_dir,
        mode=mode,
        fingerprint=fingerprint,
        max_chapters=max_chapters,
        status=error.status,
        disposition=None,
        exit_code=error.exit_code,
        manifest=manifest,
        removed_files=[],
        previous_manifest_preserved=preserved,
        failure=_failure_dict(error),
    )


def _prepare_staged_manifest(
    stage_dir: Path, manifest: dict, fingerprint: str, source_identity: dict
) -> dict:
    prepared = copy.deepcopy(manifest)
    prepared["request_fingerprint"] = fingerprint
    prepared["source_identity"] = copy.deepcopy(source_identity)
    prepared["extracted_count"] = len(prepared.get("chapters", []))
    for row in prepared.get("chapters", []):
        filename = _safe_filename(row.get("filename"))
        row["sha256"] = _sha256(stage_dir / filename)
    manifest_path = stage_dir / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(prepared, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    validate_manifest(prepared, stage_dir)
    return prepared


def _publish(
    *,
    output_dir: Path,
    stage_dir: Path,
    previous_manifest: dict | None,
    new_manifest: dict,
) -> list[str]:
    if output_dir.exists() or output_dir.is_symlink():
        try:
            mode = output_dir.lstat().st_mode
        except OSError as exc:
            raise ChapterFailure(
                "output_uninspectable",
                f"cannot inspect output directory: {exc}",
            ) from exc
        if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
            raise ChapterFailure(
                "output_not_directory",
                f"output path is not a real directory: {output_dir}",
            )
    else:
        output_dir.mkdir()

    previous_names = {
        _safe_filename(row["filename"])
        for row in (previous_manifest or {}).get("chapters", [])
    }
    new_names = {
        _safe_filename(row["filename"]) for row in new_manifest["chapters"]
    }
    for filename in new_names:
        target = output_dir / filename
        if (target.exists() or target.is_symlink()) and filename not in previous_names:
            raise ChapterFailure(
                "unmanaged_output_conflict",
                f"refusing to overwrite an unmanaged path: {target}",
            )

    stale_names = sorted(previous_names - new_names)
    backup_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.backup-",
            dir=str(output_dir.parent),
        )
    )
    published: list[str] = []
    manifest_replaced = False
    try:
        for filename in sorted(previous_names):
            source = output_dir / filename
            shutil.copy2(source, backup_dir / filename)

        try:
            for filename in sorted(new_names):
                os.replace(stage_dir / filename, output_dir / filename)
                published.append(filename)
            for filename in stale_names:
                (output_dir / filename).unlink()
            directory_fd = os.open(output_dir, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            os.replace(stage_dir / MANIFEST_NAME, output_dir / MANIFEST_NAME)
            manifest_replaced = True
            directory_fd = os.open(output_dir, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            # Before manifest replacement, the old manifest is still the commit
            # marker and its chapter set must be restored.  Once replacement
            # succeeds, however, the complete new generation is current.  A
            # later directory-fsync error makes durability unknown but must not
            # roll chapter files back underneath the new manifest.
            if not manifest_replaced:
                for filename in published:
                    target = output_dir / filename
                    backup = backup_dir / filename
                    if backup.exists():
                        os.replace(backup, target)
                    elif target.exists() and not target.is_symlink():
                        target.unlink()
                for filename in stale_names:
                    backup = backup_dir / filename
                    if backup.exists():
                        os.replace(backup, output_dir / filename)
            raise
    finally:
        shutil.rmtree(backup_dir, ignore_errors=True)
    return stale_names


def commit_chapter_set(
    *,
    input_path: Path,
    output_dir: Path,
    mode: str,
    options: dict,
    max_chapters: int,
    build_stage: Callable[[Path, dict | None], dict],
    success_disposition: str | None = None,
    require_previous: bool = False,
    expected_manifest_fingerprint: str | None = None,
) -> tuple[int, dict]:
    """Build and atomically publish one complete chapter generation."""
    fingerprint: str | None = None
    expected_manifest_digest: str | None | object = _UNSET
    manifest_path = output_dir / MANIFEST_NAME
    try:
        observed_manifest_digest = verify_expected_manifest(
            output_dir, expected_manifest_fingerprint
        )
    except ChapterFailure as exc:
        return exc.exit_code, failure_receipt(
            input_path=input_path,
            output_dir=output_dir,
            mode=mode,
            max_chapters=max_chapters,
            error=exc,
        )
    try:
        fingerprint, initial_identity = request_fingerprint(input_path, mode, options)
    except ChapterFailure as exc:
        return exc.exit_code, failure_receipt(
            input_path=input_path,
            output_dir=output_dir,
            mode=mode,
            max_chapters=max_chapters,
            error=exc,
            fingerprint=fingerprint,
        )

    stage_dir: Path | None = None
    try:
        with _output_lock(output_dir):
            expected_manifest_digest = _manifest_digest(manifest_path)
            previous_manifest = load_manifest(manifest_path)
            if (
                expected_manifest_fingerprint is not None
                and expected_manifest_digest != expected_manifest_fingerprint
            ):
                raise ChapterFailure(
                    "expected_manifest_mismatch",
                    "manifest fingerprint changed before the writer acquired the lock",
                )
            if observed_manifest_digest != expected_manifest_digest:
                if (
                    previous_manifest is not None
                    and previous_manifest.get("request_fingerprint") == fingerprint
                ):
                    validate_manifest(previous_manifest, output_dir)
                    return 0, _receipt(
                        input_path=input_path,
                        output_dir=output_dir,
                        mode=mode,
                        fingerprint=fingerprint,
                        max_chapters=max_chapters,
                        status="existing",
                        disposition="reconciled",
                        exit_code=0,
                        manifest=previous_manifest,
                        removed_files=[],
                        previous_manifest_preserved=True,
                        failure=None,
                    )
                raise ChapterFailure(
                    "manifest_conflict",
                    "a competing chapter generation committed before this writer acquired the lock",
                )
            if require_previous and previous_manifest is None:
                raise ChapterFailure(
                    "manifest_missing",
                    "repair requires an existing manifest",
                    exit_code=2,
                )
            if require_previous and previous_manifest is not None:
                recorded_identity = previous_manifest.get("source_identity")
                recorded_name = previous_manifest.get(
                    "source_pdf", previous_manifest.get("source_epub")
                )
                if (
                    recorded_identity is not None
                    and recorded_identity != initial_identity
                ) or (
                    recorded_identity is None
                    and recorded_name is not None
                    and recorded_name != input_path.name
                ):
                    raise ChapterFailure(
                        "source_mismatch",
                        "repair input does not match the manifest source",
                        exit_code=2,
                    )
            previous_snapshot = _owned_snapshot(previous_manifest, output_dir)

            if (
                previous_manifest is not None
                and previous_manifest.get("request_fingerprint") == fingerprint
            ):
                validate_manifest(previous_manifest, output_dir)
                return 0, _receipt(
                    input_path=input_path,
                    output_dir=output_dir,
                    mode=mode,
                    fingerprint=fingerprint,
                    max_chapters=max_chapters,
                    status="existing",
                    disposition="reconciled",
                    exit_code=0,
                    manifest=previous_manifest,
                    removed_files=[],
                    previous_manifest_preserved=True,
                    failure=None,
                )

            stage_dir = Path(
                tempfile.mkdtemp(
                    prefix=f".{output_dir.name}.stage-",
                    dir=str(output_dir.parent),
                )
            )
            try:
                staged_manifest = build_stage(stage_dir, previous_manifest)
            except ChapterFailure:
                raise
            except Exception as exc:
                raise ChapterFailure(
                    "extract_failed",
                    f"chapter extraction failed: {exc}",
                    status="failed",
                    outcome="known",
                ) from exc
            if not isinstance(staged_manifest, dict):
                raise ChapterFailure(
                    "writer_receipt_invalid",
                    "chapter builder did not return a manifest object",
                    status="blocked",
                    outcome="unknown",
                )
            if not staged_manifest.get("chapters"):
                raise ChapterFailure(
                    "no_chapters",
                    "extraction produced no chapters",
                    status="failed",
                    outcome="known",
                )
            staged_manifest = _prepare_staged_manifest(
                stage_dir, staged_manifest, fingerprint, initial_identity
            )

            if _source_identity(input_path) != initial_identity:
                raise ChapterFailure(
                    "input_changed",
                    "input changed while chapters were being extracted",
                )
            current_manifest_digest = _manifest_digest(manifest_path)
            if (
                expected_manifest_fingerprint is not None
                and current_manifest_digest != expected_manifest_fingerprint
            ):
                raise ChapterFailure(
                    "expected_manifest_mismatch",
                    "manifest fingerprint changed before chapter replacement",
                )
            if current_manifest_digest != expected_manifest_digest:
                raise ChapterFailure(
                    "manifest_conflict",
                    "manifest changed before chapter replacement",
                )
            if not _same_snapshot(previous_snapshot, output_dir):
                raise ChapterFailure(
                    "chapter_conflict",
                    "manifest-owned chapter files changed before replacement",
                )

            removed = _publish(
                output_dir=output_dir,
                stage_dir=stage_dir,
                previous_manifest=previous_manifest,
                new_manifest=staged_manifest,
            )
            disposition = success_disposition or (
                "replaced" if previous_manifest is not None else "created"
            )
            return 0, _receipt(
                input_path=input_path,
                output_dir=output_dir,
                mode=mode,
                fingerprint=fingerprint,
                max_chapters=max_chapters,
                status="ok",
                disposition=disposition,
                exit_code=0,
                manifest=staged_manifest,
                removed_files=removed,
                previous_manifest_preserved=False,
                failure=None,
            )
    except ChapterFailure as exc:
        return exc.exit_code, failure_receipt(
            input_path=input_path,
            output_dir=output_dir,
            mode=mode,
            max_chapters=max_chapters,
            error=exc,
            fingerprint=fingerprint,
            expected_manifest_digest=expected_manifest_digest,
        )
    except Exception as exc:
        error = ChapterFailure(
            "commit_failed",
            f"chapter commit failed: {exc}",
            status="blocked",
            outcome="unknown",
        )
        return error.exit_code, failure_receipt(
            input_path=input_path,
            output_dir=output_dir,
            mode=mode,
            max_chapters=max_chapters,
            error=error,
            fingerprint=fingerprint,
            expected_manifest_digest=expected_manifest_digest,
        )
    finally:
        if stage_dir is not None:
            shutil.rmtree(stage_dir, ignore_errors=True)
