#!/usr/bin/env python3
"""Atomic, replay-aware single-recording compression for process-talk."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path


SCHEMA_VERSION = "quasi.operation.talk.prepare-media.receipt/0.1"
MANIFEST_SCHEMA = "quasi.talk.prepared-media.manifest/0.1"
FAILURE_KEYS = {"code", "operation_key", "outcome", "retryable", "message"}


class PrepareFailure(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: str = "failed",
        outcome: str = "known",
        exit_code: int = 1,
    ) -> None:
        super().__init__(message)
        if status not in {"failed", "blocked"}:
            raise ValueError("invalid prepare-media status")
        if outcome != ("known" if status == "failed" else "unknown"):
            raise ValueError("prepare-media failure matrix mismatch")
        self.code = code
        self.message = message
        self.status = status
        self.outcome = outcome
        self.exit_code = exit_code

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "operation_key": "talk.prepare-media",
            "outcome": self.outcome,
            "retryable": False,
            "message": self.message,
        }


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="quasi-transcribe prepare-media")
    ap.add_argument("--project-dir")
    ap.add_argument("--media", required=True, help="source video/audio file")
    ap.add_argument("--output", required=True, help="compressed output path")
    ap.add_argument("--crf", default="28", help="x265 CRF; lower is larger/better")
    ap.add_argument("--preset", default="veryfast", help="x265 preset")
    ap.add_argument("--audio-bitrate", default="96k", help="AAC audio bitrate")
    ap.add_argument("--force", action="store_true", help="legacy explicit replacement")
    ap.add_argument("--json", action="store_true", help="emit strict Operation receipt")
    return ap.parse_args(argv)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _real_dir(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISDIR(mode) and not stat.S_ISLNK(mode)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise PrepareFailure(
            "path_outside_project",
            f"path is outside project root: {path}",
            exit_code=2,
        ) from exc


def _safe_target(path: Path, root: Path) -> Path:
    path = Path(os.path.abspath(path))
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PrepareFailure(
            "path_outside_project",
            f"output is outside project root: {path}",
            exit_code=2,
        ) from exc
    cursor = root
    if not _real_dir(root):
        raise PrepareFailure(
            "project_root_invalid",
            "project root is not a real directory",
            status="blocked",
            outcome="unknown",
        )
    for part in relative.parts[:-1]:
        cursor /= part
        if cursor.exists() or cursor.is_symlink():
            if not _real_dir(cursor):
                raise PrepareFailure(
                    "output_ancestor_invalid",
                    f"output ancestor is not a real directory: {cursor}",
                    status="blocked",
                    outcome="unknown",
                )
    return path


def _inspect_source(path: Path) -> tuple[str, int]:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise PrepareFailure(
            "input_missing", f"media not found: {path}", exit_code=2
        ) from exc
    if not stat.S_ISREG(info.st_mode):
        raise PrepareFailure(
            "input_not_regular",
            f"media is not a regular file: {path}",
            exit_code=2,
        )
    return _sha(path), info.st_size


def _fingerprint(source_sha: str, args: argparse.Namespace) -> str:
    value = {
        "source_sha256": source_sha,
        "crf": str(args.crf),
        "preset": args.preset,
        "audio_bitrate": args.audio_bitrate,
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def default_fingerprint(source_sha: str) -> str:
    """Fingerprint the exact default prepare-media command used by the graph."""
    return _fingerprint(
        source_sha,
        argparse.Namespace(crf="28", preset="veryfast", audio_bitrate="96k"),
    )


def inspect_prepared(output: Path, source_sha: str) -> tuple[str, int] | None:
    """Return a current prepared artifact identity, or ``None`` for stale/absent."""
    output = Path(output)
    manifest_path = output.with_name(f".{output.name}.quasi-compress.json")
    output_present = output.exists() or output.is_symlink()
    manifest_present = manifest_path.exists() or manifest_path.is_symlink()
    if not output_present and not manifest_present:
        return None
    if output_present != manifest_present:
        raise PrepareFailure(
            "prepared_generation_incomplete",
            "prepared media and its manifest are not a complete pair",
            status="blocked",
            outcome="unknown",
        )
    expected = default_fingerprint(source_sha)
    manifest = _load_manifest(manifest_path, output, expected)
    if (
        manifest["request_fingerprint"] != expected
        or manifest["input_sha256"] != source_sha
    ):
        return None
    return manifest["output_sha256"], manifest["size"]


def _load_manifest(path: Path, output: Path, fingerprint: str) -> dict | None:
    if not path.exists() and not path.is_symlink():
        return None
    if not _regular(path):
        raise PrepareFailure(
            "manifest_not_regular",
            "prepared-media manifest is not a regular file",
            status="blocked",
            outcome="unknown",
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PrepareFailure(
            "manifest_invalid",
            f"cannot parse prepared-media manifest: {exc}",
            status="blocked",
            outcome="unknown",
        ) from exc
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "request_fingerprint",
            "input_sha256",
            "output_sha256",
            "size",
        }
        or value.get("schema_version") != MANIFEST_SCHEMA
        or not isinstance(value.get("request_fingerprint"), str)
        or not isinstance(value.get("input_sha256"), str)
        or not isinstance(value.get("output_sha256"), str)
        or not isinstance(value.get("size"), int)
        or isinstance(value.get("size"), bool)
    ):
        raise PrepareFailure(
            "manifest_invalid",
            "prepared-media manifest has an invalid shape",
            status="blocked",
            outcome="unknown",
        )
    if not _regular(output) or output.stat().st_size != value["size"] or _sha(output) != value["output_sha256"]:
        raise PrepareFailure(
            "artifact_mismatch",
            "prepared media does not match its manifest",
            status="blocked",
            outcome="unknown",
        )
    if value["request_fingerprint"] != fingerprint:
        return value
    return value


def _lock(path: Path):
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise PrepareFailure(
            "lock_invalid",
            "prepare-media lock is not a regular file",
            status="blocked",
            outcome="unknown",
        )
    handle = os.fdopen(fd, "a+")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _receipt(
    *,
    root: Path,
    requested_input_path: str | None,
    output: Path | None,
    input_sha: str | None,
    action: str | None,
    error: PrepareFailure | None,
) -> dict:
    exists = output is not None and _regular(output)
    slug = (
        output.parent.name
        if output is not None
        and output.parent.parent.name == "talks"
        and output.parent.parent.parent.name == "vault"
        else None
    )
    def receipt_path(path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            return _relative(path, root)
        except PrepareFailure:
            return None

    return {
        "schema_version": SCHEMA_VERSION,
        "key": "talk.prepare-media",
        "effect": "writer",
        "status": error.status if error else "succeeded",
        "attempt": 1,
        "material_key": f"talk:{slug}" if slug else None,
        "input_path": requested_input_path,
        "output_path": receipt_path(output),
        "artifact_roles": ["prepared_media"],
        "input_sha256": input_sha,
        "output_sha256": _sha(output) if exists and error is None else None,
        "size": output.stat().st_size if exists and error is None else 0,
        "action": action,
        "failure": error.as_dict() if error else None,
    }


def run(args: argparse.Namespace) -> tuple[int, dict]:
    root = Path(
        args.project_dir
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.getcwd()
    ).resolve()
    source: Path | None = None
    output: Path | None = None
    source_sha: str | None = None
    action: str | None = "create"
    error: PrepareFailure | None = None
    try:
        source = Path(args.media)
        if not source.is_absolute():
            source = root / source
        source = Path(os.path.abspath(source))
        source_sha, _ = _inspect_source(source)
        output = Path(args.output)
        if not output.is_absolute():
            output = root / output
        output = _safe_target(output, root)
        if args.json:
            parts = output.relative_to(root).parts
            if (
                len(parts) != 4
                or parts[:2] != ("vault", "talks")
                or not parts[2]
                or parts[3] != "recording.mp4"
            ):
                raise PrepareFailure(
                    "invalid_output_path",
                    "strict prepared media must be vault/talks/{slug}/recording.mp4",
                    exit_code=2,
                )
        if shutil.which("ffmpeg") is None:
            raise PrepareFailure("ffmpeg_missing", "Missing required tool: ffmpeg")
        output.parent.mkdir(parents=True, exist_ok=True)
        if not _real_dir(output.parent):
            raise PrepareFailure(
                "output_parent_invalid",
                "prepared-media parent is not a real directory",
                status="blocked",
                outcome="unknown",
            )
        fingerprint = _fingerprint(source_sha, args)
        manifest_path = output.with_name(f".{output.name}.quasi-compress.json")
        lock_path = output.with_name(f".{output.name}.quasi-compress.lock")
        # Strict validation failures are read-only.  In particular, do not
        # create the sibling lock merely to discover an unmanaged target.
        if (
            args.json
            and not args.force
            and (output.exists() or output.is_symlink())
            and not (manifest_path.exists() or manifest_path.is_symlink())
        ):
            raise PrepareFailure(
                "unmanaged_output_conflict",
                "prepared output exists without a trusted manifest",
                status="blocked",
                outcome="unknown",
            )
        if (manifest_path.exists() or manifest_path.is_symlink()) and not _regular(
            manifest_path
        ):
            raise PrepareFailure(
                "manifest_not_regular",
                "prepared-media manifest is not a regular file",
                status="blocked",
                outcome="unknown",
            )
        with _lock(lock_path) as handle:
            try:
                manifest = _load_manifest(manifest_path, output, fingerprint)
                if manifest is not None and manifest["request_fingerprint"] == fingerprint:
                    action = "reconciled"
                else:
                    if (output.exists() or output.is_symlink()) and manifest is None and not args.force:
                        if args.json:
                            raise PrepareFailure(
                                "unmanaged_output_conflict",
                                "prepared output exists without a trusted manifest",
                                status="blocked",
                                outcome="unknown",
                            )
                        # Preserve the legacy skip contract.
                        action = "reconciled"
                    elif manifest is not None and not args.force and not args.json:
                        raise PrepareFailure(
                            "output_exists_requires_reconcile",
                            "prepared output belongs to a different request",
                            status="blocked",
                            outcome="unknown",
                        )
                    else:
                        fd, stage_name = tempfile.mkstemp(
                            prefix=f".{output.name}.stage-",
                            suffix=output.suffix,
                            dir=str(output.parent),
                        )
                        os.close(fd)
                        stage = Path(stage_name)
                        manifest_fd, manifest_name = tempfile.mkstemp(
                            prefix=f".{manifest_path.name}.stage-",
                            dir=str(output.parent),
                        )
                        os.close(manifest_fd)
                        manifest_stage = Path(manifest_name)
                        backup: Path | None = None
                        marker_replaced = False
                        try:
                            stage.unlink()
                            cmd = [
                                "ffmpeg",
                                "-hide_banner",
                                "-nostdin",
                                "-y",
                                "-i",
                                str(source),
                                "-map",
                                "0:v:0?",
                                "-map",
                                "0:a?",
                                "-map_metadata",
                                "0",
                                "-c:v",
                                "libx265",
                                "-preset",
                                args.preset,
                                "-crf",
                                str(args.crf),
                                "-pix_fmt",
                                "yuv420p",
                                "-tag:v",
                                "hvc1",
                                "-x265-params",
                                "log-level=error",
                                "-c:a",
                                "aac",
                                "-b:a",
                                args.audio_bitrate,
                                "-movflags",
                                "+faststart",
                                str(stage),
                            ]
                            result = subprocess.run(cmd, text=True)
                            if result.returncode != 0 or not _regular(stage):
                                raise PrepareFailure(
                                    "ffmpeg_failed",
                                    f"ffmpeg exited {result.returncode}",
                                )
                            with stage.open("rb") as staged_handle:
                                os.fsync(staged_handle.fileno())
                            output_sha = _sha(stage)
                            manifest_value = {
                                "schema_version": MANIFEST_SCHEMA,
                                "request_fingerprint": fingerprint,
                                "input_sha256": source_sha,
                                "output_sha256": output_sha,
                                "size": stage.stat().st_size,
                            }
                            manifest_stage.write_text(
                                json.dumps(manifest_value, sort_keys=True) + "\n",
                                encoding="utf-8",
                            )
                            with manifest_stage.open("rb") as staged_handle:
                                os.fsync(staged_handle.fileno())
                            if _regular(output):
                                backup_fd, backup_name = tempfile.mkstemp(
                                    prefix=f".{output.name}.backup-",
                                    dir=str(output.parent),
                                )
                                os.close(backup_fd)
                                backup = Path(backup_name)
                                shutil.copy2(output, backup)
                            try:
                                os.replace(stage, output)
                                _fsync_dir(output.parent)
                                os.replace(manifest_stage, manifest_path)
                                marker_replaced = True
                                _fsync_dir(output.parent)
                            except BaseException:
                                if not marker_replaced:
                                    if backup is not None and backup.exists():
                                        os.replace(backup, output)
                                    elif output.exists() and not output.is_symlink():
                                        output.unlink()
                                raise
                            action = "create"
                        finally:
                            for temp in (stage, manifest_stage, backup):
                                if temp is not None:
                                    try:
                                        temp.unlink()
                                    except FileNotFoundError:
                                        pass
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()
    except PrepareFailure as exc:
        error = exc
    except Exception as exc:
        error = PrepareFailure(
            "commit_failed",
            f"prepare-media transaction failed: {exc}",
            status="blocked",
            outcome="unknown",
        )
    receipt = _receipt(
        root=root,
        requested_input_path=args.media,
        output=output,
        input_sha=source_sha,
        action=action,
        error=error,
    )
    return (0 if error is None else error.exit_code), receipt


def main(argv=None) -> int:
    args = parse_args(argv)
    code, receipt = run(args)
    if args.json:
        print(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")))
    elif receipt["status"] == "succeeded":
        if receipt["action"] == "reconciled":
            print(f"skip: output exists: {receipt['output_path']}")
        else:
            print(receipt["output_path"])
    else:
        print(receipt["failure"]["message"], file=os.sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
