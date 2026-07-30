#!/usr/bin/env python3
"""Transactional primitives shared by the strict Talk CLI operations.

The transcription command owns two small artifact sets (``processing/talks``
and ``vault/talks``).  Writers build in sibling staging directories, serialize
on one per-slug lock, publish artifacts, and replace the processing manifest
last.  The manifest is the generation commit marker and the only source of
truth used by reconciliation.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import unicodedata
from contextlib import contextmanager
from datetime import date as date_type
from pathlib import Path
from typing import Callable, Iterator


MANIFEST_SCHEMA = "quasi.talk.transcription.manifest/0.1"
MANIFEST_NAME = "manifest.json"
KNOWN_ENGINES = ("soniox", "whisper", "apple", "parakeet")
_MANIFEST_KEYS = {
    "schema_version",
    "slug",
    "request_fingerprint",
    "source",
    "title",
    "lang",
    "engines",
    "status",
    "primary_engine",
    "per_engine",
    "artifacts",
    "failure",
}
_SOURCE_KEYS = {"path", "sha256", "size"}
_ENGINE_KEYS = {"name", "status", "segments", "path", "sha256"}
_ARTIFACT_KEYS = {"role", "path", "sha256", "size"}
_FAILURE_KEYS = {"code", "operation_key", "outcome", "retryable", "message"}


class TalkFailure(Exception):
    """A closed failed/known or blocked/unknown CLI failure."""

    def __init__(
        self,
        code: str,
        message: str | None,
        *,
        operation_key: str,
        status: str = "failed",
        outcome: str = "known",
        exit_code: int = 1,
    ) -> None:
        super().__init__(message or code)
        if status not in {"failed", "blocked"}:
            raise ValueError(f"invalid Talk failure status: {status}")
        expected = "known" if status == "failed" else "unknown"
        if outcome != expected:
            raise ValueError("Talk failure matrix is failed/known or blocked/unknown")
        self.code = code
        self.message = message
        self.operation_key = operation_key
        self.status = status
        self.outcome = outcome
        self.exit_code = exit_code

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "operation_key": self.operation_key,
            "outcome": self.outcome,
            "retryable": False,
            "message": self.message,
        }


def compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def emit_json(value: object) -> None:
    print(compact_json(value))


def validate_slug(value: object, *, operation_key: str) -> str:
    """Validate the shared Material canonical ASCII slug contract."""
    if not isinstance(value, str) or re.fullmatch(
        r"[a-z0-9][a-z0-9-]{0,79}", value
    ) is None:
        raise TalkFailure(
            "invalid_slug",
            "slug must be canonical ASCII kebab (1..80 characters)",
            operation_key=operation_key,
            exit_code=2,
        )
    return value


def validate_date(value: object, *, operation_key: str) -> str:
    if not isinstance(value, str):
        raise TalkFailure(
            "invalid_date", "date must be an ISO calendar date", operation_key=operation_key, exit_code=2
        )
    try:
        parsed = date_type.fromisoformat(value)
    except ValueError as exc:
        raise TalkFailure(
            "invalid_date", "date must be an ISO calendar date", operation_key=operation_key, exit_code=2
        ) from exc
    if parsed.isoformat() != value:
        raise TalkFailure(
            "invalid_date", "date must use YYYY-MM-DD", operation_key=operation_key, exit_code=2
        )
    return value


def validate_text(
    value: object,
    name: str,
    *,
    operation_key: str,
    max_length: int = 500,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > max_length
        or any(unicodedata.category(char) == "Cc" and char not in "\t" for char in value)
    ):
        raise TalkFailure(
            f"invalid_{name}",
            f"{name} must be a non-empty bounded scalar without control characters",
            operation_key=operation_key,
            exit_code=2,
        )
    return value


def validate_engines(value: object, *, operation_key: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise TalkFailure(
            "invalid_engines", "at least one engine is required", operation_key=operation_key, exit_code=2
        )
    if (
        any(not isinstance(name, str) or name not in KNOWN_ENGINES for name in value)
        or len(set(value)) != len(value)
    ):
        raise TalkFailure(
            "invalid_engines",
            "engines must be a unique ordered list of supported engine names",
            operation_key=operation_key,
            exit_code=2,
        )
    return list(value)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def real_directory(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISDIR(mode) and not stat.S_ISLNK(mode)


def inspect_source(path: Path, *, operation_key: str) -> dict:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise TalkFailure(
            "input_missing", f"input file does not exist: {path}", operation_key=operation_key, exit_code=2
        ) from exc
    except OSError as exc:
        raise TalkFailure(
            "input_unreadable", f"cannot inspect input: {exc}", operation_key=operation_key, exit_code=2
        ) from exc
    if not stat.S_ISREG(info.st_mode):
        raise TalkFailure(
            "input_not_regular",
            f"input path is not a regular file: {path}",
            operation_key=operation_key,
            exit_code=2,
        )
    try:
        digest = sha256_file(path)
    except OSError as exc:
        raise TalkFailure(
            "input_unreadable", f"cannot read input: {exc}", operation_key=operation_key, exit_code=2
        ) from exc
    return {"path": str(path.resolve()), "sha256": digest, "size": info.st_size}


def project_relative(path: Path, root: Path, *, operation_key: str) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise TalkFailure(
            "path_outside_project",
            f"path is outside project root: {path}",
            operation_key=operation_key,
            exit_code=2,
        ) from exc


def _check_existing_chain(root: Path, target: Path, *, operation_key: str) -> None:
    """Reject symlink/non-directory ancestors without resolving through them."""
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise TalkFailure(
            "path_outside_project",
            f"output path is outside project root: {target}",
            operation_key=operation_key,
            exit_code=2,
        ) from exc
    cursor = root
    if not real_directory(root):
        raise TalkFailure(
            "project_root_invalid",
            f"project root is not a real directory: {root}",
            operation_key=operation_key,
            status="blocked",
            outcome="unknown",
        )
    for part in relative.parts[:-1]:
        cursor = cursor / part
        if cursor.exists() or cursor.is_symlink():
            if not real_directory(cursor):
                raise TalkFailure(
                    "output_ancestor_invalid",
                    f"output ancestor is not a real directory: {cursor}",
                    operation_key=operation_key,
                    status="blocked",
                    outcome="unknown",
                )


def safe_output(path: Path, root: Path, *, operation_key: str) -> Path:
    lexical = Path(os.path.abspath(path))
    _check_existing_chain(root, lexical, operation_key=operation_key)
    return lexical


def ensure_directory(path: Path, root: Path, *, operation_key: str) -> None:
    safe_output(path / ".sentinel", root, operation_key=operation_key)
    if path.exists() or path.is_symlink():
        if not real_directory(path):
            raise TalkFailure(
                "output_not_directory",
                f"output is not a real directory: {path}",
                operation_key=operation_key,
                status="blocked",
                outcome="unknown",
            )
        return
    path.mkdir(parents=True)
    if not real_directory(path):
        raise TalkFailure(
            "output_not_directory",
            f"output is not a real directory: {path}",
            operation_key=operation_key,
            status="blocked",
            outcome="unknown",
        )


def request_fingerprint(source: dict, engines: list[str], lang: str, title: str) -> str:
    # mtime is deliberately excluded: stable content identity is the contract.
    payload = {
        "source_sha256": source["sha256"],
        "engines": engines,
        "lang": lang,
        "title": title,
    }
    return hashlib.sha256(compact_json(payload).encode("utf-8")).hexdigest()


def _manifest_digest(path: Path, *, operation_key: str) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    if not regular_file(path):
        raise TalkFailure(
            "manifest_not_regular",
            f"manifest is not a regular file: {path}",
            operation_key=operation_key,
            status="blocked",
            outcome="unknown",
        )
    try:
        return sha256_file(path)
    except OSError as exc:
        raise TalkFailure(
            "manifest_unreadable",
            f"cannot read manifest: {exc}",
            operation_key=operation_key,
            status="blocked",
            outcome="unknown",
        ) from exc


def _valid_failure(value: object, operation_key: str) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == _FAILURE_KEYS
        and isinstance(value.get("code"), str)
        and value.get("operation_key") == operation_key
        and value.get("outcome") == "known"
        and value.get("retryable") is False
        and (value.get("message") is None or isinstance(value.get("message"), str))
    )


def _valid_relative_artifact(
    value: object, root: Path, slug: str, *, operation_key: str
) -> bool:
    if not isinstance(value, dict) or set(value) != _ARTIFACT_KEYS:
        return False
    if (
        not isinstance(value.get("role"), str)
        or not isinstance(value.get("path"), str)
        or not isinstance(value.get("sha256"), str)
        or len(value["sha256"]) != 64
        or not isinstance(value.get("size"), int)
        or isinstance(value.get("size"), bool)
        or value["size"] < 0
    ):
        return False
    rel = Path(value["path"])
    allowed = (
        Path("processing") / "talks" / slug,
        Path("vault") / "talks" / slug,
    )
    if rel.is_absolute() or ".." in rel.parts or not any(rel.parent == base for base in allowed):
        return False
    target = root / rel
    try:
        safe_output(target, root, operation_key=operation_key)
    except TalkFailure:
        return False
    return regular_file(target) and target.stat().st_size == value["size"] and sha256_file(target) == value["sha256"]


def load_manifest(
    manifest_path: Path,
    root: Path,
    slug: str,
    *,
    operation_key: str,
) -> dict | None:
    if _manifest_digest(manifest_path, operation_key=operation_key) is None:
        return None
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TalkFailure(
            "manifest_invalid",
            f"cannot parse manifest: {exc}",
            operation_key=operation_key,
            status="blocked",
            outcome="unknown",
        ) from exc
    if not isinstance(value, dict) or set(value) != _MANIFEST_KEYS:
        raise TalkFailure(
            "manifest_invalid",
            "manifest does not have the exact Talk generation shape",
            operation_key=operation_key,
            status="blocked",
            outcome="unknown",
        )
    source = value.get("source")
    per_engine = value.get("per_engine")
    artifacts = value.get("artifacts")
    if (
        value.get("schema_version") != MANIFEST_SCHEMA
        or value.get("slug") != slug
        or not isinstance(value.get("request_fingerprint"), str)
        or not isinstance(source, dict)
        or set(source) != _SOURCE_KEYS
        or not isinstance(source.get("path"), str)
        or not isinstance(source.get("sha256"), str)
        or len(source["sha256"]) != 64
        or not isinstance(source.get("size"), int)
        or isinstance(source.get("size"), bool)
        or not isinstance(value.get("title"), str)
        or not isinstance(value.get("lang"), str)
        or not isinstance(value.get("engines"), list)
        or not isinstance(per_engine, list)
        or not isinstance(artifacts, list)
        or value.get("status") not in {"succeeded", "failed"}
        or (value.get("primary_engine") is not None and value.get("primary_engine") not in value["engines"])
    ):
        raise TalkFailure(
            "manifest_invalid",
            "manifest fields are invalid",
            operation_key=operation_key,
            status="blocked",
            outcome="unknown",
        )
    try:
        validate_engines(value["engines"], operation_key=operation_key)
    except TalkFailure as exc:
        raise TalkFailure(
            "manifest_invalid",
            str(exc),
            operation_key=operation_key,
            status="blocked",
            outcome="unknown",
        ) from exc
    if len(per_engine) != len(value["engines"]):
        raise TalkFailure(
            "manifest_invalid",
            "manifest engine rows do not match the requested engine order",
            operation_key=operation_key,
            status="blocked",
            outcome="unknown",
        )
    # The plugin bootstrap still supports Python 3.9 installations.  The
    # explicit length check above provides the same invariant as strict zip
    # iteration without requiring Python 3.10.
    for expected, row in zip(value["engines"], per_engine):
        if (
            not isinstance(row, dict)
            or set(row) != _ENGINE_KEYS
            or row.get("name") != expected
            or row.get("status") not in {"succeeded", "empty", "unavailable", "failed"}
            or not isinstance(row.get("segments"), int)
            or isinstance(row.get("segments"), bool)
            or row["segments"] < 0
            or (row.get("path") is not None and not isinstance(row.get("path"), str))
            or (row.get("sha256") is not None and not isinstance(row.get("sha256"), str))
        ):
            raise TalkFailure(
                "manifest_invalid",
                "manifest engine row is invalid",
                operation_key=operation_key,
                status="blocked",
                outcome="unknown",
            )
    if not all(_valid_relative_artifact(row, root, slug, operation_key=operation_key) for row in artifacts):
        raise TalkFailure(
            "artifact_set_incomplete",
            "manifest-owned Talk artifacts are missing or changed",
            operation_key=operation_key,
            status="blocked",
            outcome="unknown",
        )
    failure = value.get("failure")
    if value["status"] == "succeeded":
        if failure is not None or value["primary_engine"] is None or not artifacts:
            raise TalkFailure(
                "manifest_invalid",
                "successful manifest has an invalid status matrix",
                operation_key=operation_key,
                status="blocked",
                outcome="unknown",
            )
    elif value["primary_engine"] is not None or artifacts or not _valid_failure(failure, "talk.transcribe"):
        raise TalkFailure(
            "manifest_invalid",
            "failed manifest has an invalid status matrix",
            operation_key=operation_key,
            status="blocked",
            outcome="unknown",
        )
    return value


@contextmanager
def slug_lock(processing_parent: Path, slug: str, root: Path, *, operation_key: str) -> Iterator[None]:
    ensure_directory(processing_parent, root, operation_key=operation_key)
    lock_path = safe_output(
        processing_parent / f".{slug}.quasi-transcribe.lock", root, operation_key=operation_key
    )
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise TalkFailure(
            "lock_unavailable",
            f"cannot open Talk lock: {exc}",
            operation_key=operation_key,
            status="blocked",
            outcome="unknown",
        ) from exc
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise TalkFailure(
            "lock_invalid",
            "Talk lock is not a regular file",
            operation_key=operation_key,
            status="blocked",
            outcome="unknown",
        )
    try:
        with os.fdopen(fd, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def artifact_row(role: str, target: Path, root: Path) -> dict:
    return {
        "role": role,
        "path": target.relative_to(root).as_posix(),
        "sha256": sha256_file(target),
        "size": target.stat().st_size,
    }


def _owned_paths(manifest: dict | None, root: Path, slug: str, *, operation_key: str) -> dict[Path, str]:
    owned: dict[Path, str] = {}
    for row in (manifest or {}).get("artifacts", []):
        if not _valid_relative_artifact(row, root, slug, operation_key=operation_key):
            raise TalkFailure(
                "artifact_set_incomplete",
                "cannot snapshot an invalid prior Talk generation",
                operation_key=operation_key,
                status="blocked",
                outcome="unknown",
            )
        owned[root / row["path"]] = row["sha256"]
    return owned


def _publish(
    *,
    root: Path,
    manifest_path: Path,
    previous_manifest: dict | None,
    staged_manifest_path: Path,
    staged_files: dict[Path, Path],
    operation_key: str,
) -> list[str]:
    previous = _owned_paths(previous_manifest, root, previous_manifest["slug"] if previous_manifest else staged_manifest_path.parent.name, operation_key=operation_key)
    new_targets = set(staged_files)
    for target in new_targets:
        safe_output(target, root, operation_key=operation_key)
        ensure_directory(target.parent, root, operation_key=operation_key)
        if (target.exists() or target.is_symlink()) and target not in previous:
            raise TalkFailure(
                "unmanaged_output_conflict",
                f"refusing to replace unmanaged path: {target}",
                operation_key=operation_key,
            )
    stale = sorted(set(previous) - new_targets, key=str)
    backup_dir = Path(
        tempfile.mkdtemp(prefix=".talk-backup-", dir=str(manifest_path.parent.parent))
    )
    backups: dict[Path, Path] = {}
    published: list[Path] = []
    manifest_replaced = False
    try:
        for index, target in enumerate(sorted(previous, key=str)):
            backup = backup_dir / f"{index:04d}"
            shutil.copy2(target, backup)
            backups[target] = backup
        try:
            for target in sorted(new_targets, key=str):
                os.replace(staged_files[target], target)
                published.append(target)
            for target in stale:
                target.unlink()
            for directory in sorted({target.parent for target in previous} | {target.parent for target in new_targets}, key=str):
                fsync_directory(directory)
            os.replace(staged_manifest_path, manifest_path)
            manifest_replaced = True
            fsync_directory(manifest_path.parent)
        except BaseException:
            # Before the commit marker moves, restore the exact old generation.
            # After it moves, every new artifact is already present; a final
            # fsync error means durability is unknown but rolling back only the
            # artifacts would create a manifest/file split generation.
            if not manifest_replaced:
                for target in published:
                    backup = backups.get(target)
                    if backup is not None and backup.exists():
                        os.replace(backup, target)
                    elif target.exists() and not target.is_symlink():
                        target.unlink()
                for target in stale:
                    backup = backups.get(target)
                    if backup is not None and backup.exists():
                        os.replace(backup, target)
            raise
    finally:
        shutil.rmtree(backup_dir, ignore_errors=True)
    return [path.relative_to(root).as_posix() for path in stale]


def commit_transcription(
    *,
    root: Path,
    slug: str,
    source: dict,
    title: str,
    lang: str,
    engines: list[str],
    fingerprint: str,
    build: Callable[[Path, Path], tuple[dict, dict[Path, Path]]],
) -> tuple[dict, str, bool]:
    """Return ``(manifest, disposition, previous_manifest_preserved)``."""
    operation_key = "talk.transcribe"
    processing_parent = root / "processing" / "talks"
    output_dir = processing_parent / slug
    talk_dir = root / "vault" / "talks" / slug
    ensure_directory(processing_parent, root, operation_key=operation_key)
    ensure_directory(root / "vault" / "talks", root, operation_key=operation_key)
    manifest_path = output_dir / MANIFEST_NAME
    stage_proc: Path | None = None
    stage_talk: Path | None = None
    with slug_lock(processing_parent, slug, root, operation_key=operation_key):
        ensure_directory(output_dir, root, operation_key=operation_key)
        ensure_directory(talk_dir, root, operation_key=operation_key)
        previous_digest = _manifest_digest(manifest_path, operation_key=operation_key)
        previous = load_manifest(manifest_path, root, slug, operation_key=operation_key)
        if previous is not None and previous["request_fingerprint"] == fingerprint:
            if (
                previous["source"].get("sha256") != source.get("sha256")
                or previous["source"].get("size") != source.get("size")
            ):
                raise TalkFailure(
                    "source_identity_mismatch",
                    "matching request fingerprint has different source identity",
                    operation_key=operation_key,
                    status="blocked",
                    outcome="unknown",
                )
            return previous, "reconciled", True
        if previous is None:
            # Fixed managed names without a manifest are uncommitted unknown
            # state.  Never pay an engine again over those bytes.
            managed = [
                talk_dir / "transcript.md",
                talk_dir / "recording.srt",
                *(output_dir.glob("transcript.*.srt") if real_directory(output_dir) else []),
            ]
            if any(path.exists() or path.is_symlink() for path in managed):
                raise TalkFailure(
                    "uncommitted_artifacts",
                    "Talk artifacts exist without a trusted manifest",
                    operation_key=operation_key,
                    status="blocked",
                    outcome="unknown",
                )
        stage_proc = Path(tempfile.mkdtemp(prefix=f".{slug}.stage-", dir=str(processing_parent)))
        stage_talk = Path(
            tempfile.mkdtemp(prefix=f".{slug}.stage-", dir=str(root / "vault" / "talks"))
        )
        try:
            manifest, staged_files = build(stage_proc, stage_talk)
            if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
                raise TalkFailure(
                    "writer_receipt_invalid",
                    "transcription builder returned an invalid manifest",
                    operation_key=operation_key,
                    status="blocked",
                    outcome="unknown",
                )
            if inspect_source(Path(source["path"]), operation_key=operation_key) != source:
                raise TalkFailure(
                    "input_changed",
                    "media changed during transcription",
                    operation_key=operation_key,
                )
            if _manifest_digest(manifest_path, operation_key=operation_key) != previous_digest:
                raise TalkFailure(
                    "manifest_conflict",
                    "Talk manifest changed while transcription was running",
                    operation_key=operation_key,
                    status="blocked",
                    outcome="unknown",
                )
            manifest_stage = stage_proc / MANIFEST_NAME
            manifest_stage.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with manifest_stage.open("rb") as handle:
                os.fsync(handle.fileno())
            _publish(
                root=root,
                manifest_path=manifest_path,
                previous_manifest=previous,
                staged_manifest_path=manifest_stage,
                staged_files=staged_files,
                operation_key=operation_key,
            )
            committed = load_manifest(manifest_path, root, slug, operation_key=operation_key)
            if committed != manifest:
                raise TalkFailure(
                    "commit_verification_failed",
                    "committed Talk generation does not match the staged manifest",
                    operation_key=operation_key,
                    status="blocked",
                    outcome="unknown",
                )
            return committed, "replaced" if previous is not None else "created", False
        finally:
            if stage_proc is not None:
                shutil.rmtree(stage_proc, ignore_errors=True)
            if stage_talk is not None:
                shutil.rmtree(stage_talk, ignore_errors=True)
