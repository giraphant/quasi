"""Closed WebKit capture commands for immutable Webpage material."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

try:
    from typing import TypeAlias
except ImportError:  # Python 3.9 remains supported by the plugin bootstrap.
    from typing_extensions import TypeAlias

from .webarchive import extract_webarchive, normalize_web_url, read_webarchive


@dataclass(frozen=True)
class NativeResult:
    final_url: str
    title: str
    site: str


InspectRunner: TypeAlias = Callable[[str], NativeResult]
CaptureRunner: TypeAlias = Callable[[str, Path], NativeResult]


class WebpageCommandError(Exception):
    """A closed command error which can safely cross the CLI boundary."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _data_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PLUGIN_DATA") or Path.home() / ".cache" / "quasi")


def _native_source() -> Path:
    return Path(__file__).with_name("webpage_capture.swift")


def _native_binary() -> Path:
    return _data_dir() / "bin" / "quasi-webpage-webkit"


def _macos_11_or_newer() -> bool:
    version = platform.mac_ver()[0]
    try:
        return int(version.split(".", 1)[0]) >= 11
    except (ValueError, IndexError):
        return False


def _ensure_native_binary() -> Path:
    if sys.platform != "darwin" or not _macos_11_or_newer():
        raise WebpageCommandError(
            "webpage.capture_unavailable", "WebKit capture requires macOS 11 or newer"
        )
    swiftc = shutil.which("swiftc")
    if not swiftc:
        raise WebpageCommandError(
            "webpage.capture_unavailable", "WebKit capture requires swiftc"
        )
    source = _native_source()
    binary = _native_binary()
    try:
        if binary.exists() and binary.stat().st_mtime >= source.stat().st_mtime:
            return binary
    except OSError as exc:
        raise WebpageCommandError("webpage.capture_unavailable", str(exc)) from exc
    binary.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            [
                swiftc,
                "-O",
                "-parse-as-library",
                "-framework",
                "WebKit",
                str(source),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WebpageCommandError("webpage.capture_unavailable", str(exc)) from exc
    if completed.returncode != 0 or not binary.exists():
        detail = completed.stderr.strip() or "swiftc could not compile the WebKit helper"
        raise WebpageCommandError("webpage.capture_unavailable", detail)
    return binary


def _run_native(mode: str, url: str, staging: Path | None = None) -> NativeResult:
    binary = _ensure_native_binary()
    arguments = [str(binary), mode, url]
    if staging is not None:
        arguments.append(str(staging))
    try:
        completed = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            timeout=65,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WebpageCommandError("webpage.capture_failed", str(exc)) from exc
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise WebpageCommandError(
            "webpage.capture_failed", completed.stderr.strip() or "WebKit helper returned invalid JSON"
        ) from exc
    if completed.returncode != 0 or payload.get("status") == "failed":
        raise WebpageCommandError(
            str(payload.get("code") or "webpage.capture_failed"),
            str(payload.get("message") or completed.stderr.strip() or "WebKit capture failed"),
        )
    try:
        return NativeResult(
            final_url=str(payload["final_url"]),
            title=str(payload["title"]),
            site=str(payload["site"]),
        )
    except KeyError as exc:
        raise WebpageCommandError("webpage.capture_failed", "WebKit helper omitted metadata") from exc


def run_native_inspect(url: str) -> NativeResult:
    """Load exactly once for the read-only identity operation."""

    return _run_native("inspect", url)


def run_native_capture(url: str, staging: Path) -> NativeResult:
    """Load exactly once and write only the caller-owned staging path."""

    return _run_native("capture", url, staging)


def _failure(schema_version: str, code: str, message: str) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "status": "failed",
        "issue": {"code": code, "message": message},
    }


def _metadata(result: NativeResult) -> tuple[str, str, str]:
    final_url = normalize_web_url(result.final_url)
    title = " ".join(result.title.split()) or final_url
    site = " ".join(result.site.split()) or (urlsplit(final_url).hostname or "")
    return final_url, title, site


def inspect(url: str) -> dict[str, object]:
    """Return final identity metadata after one offscreen page load."""

    schema = "quasi.webpage.inspect/0.1"
    try:
        requested_url = normalize_web_url(url)
        final_url, title, site = _metadata(run_native_inspect(requested_url))
        return {
            "schema_version": schema,
            "status": "complete",
            "url": requested_url,
            "final_url": final_url,
            "title": title,
            "site": site,
        }
    except WebpageCommandError as exc:
        return _failure(schema, exc.code, exc.message)
    except (OSError, ValueError) as exc:
        return _failure(schema, "webpage.inspect_failed", str(exc))


def _fsync_file(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def capture(url: str, expected_final_url: str, output: Path) -> dict[str, object]:
    """Capture once, validate its loaded identity, then atomically no-clobber publish."""

    schema = "quasi.webpage.capture/0.1"
    try:
        requested_url = normalize_web_url(url)
        expected_url = normalize_web_url(expected_final_url)
        if output.exists():
            return _failure(schema, "webpage.output_exists", "snapshot output already exists")
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, stage_name = tempfile.mkstemp(
            prefix=f".{output.name}.capture-", dir=str(output.parent)
        )
        os.close(descriptor)
        staging = Path(stage_name)
        staging.unlink()
        try:
            native = run_native_capture(requested_url, staging)
            archive = read_webarchive(staging)
            native_url, title, site = _metadata(native)
            if archive.url != expected_url or native_url != expected_url:
                return _failure(
                    schema,
                    "webpage.capture_identity_changed",
                    "captured page final URL differs from the expected final URL",
                )
            captured = datetime.now(timezone.utc).replace(microsecond=0)
            captured_epoch = int(captured.timestamp())
            os.utime(staging, ns=(captured_epoch * 1_000_000_000,) * 2)
            _fsync_file(staging)
            try:
                os.link(staging, output)
            except FileExistsError:
                return _failure(schema, "webpage.output_exists", "snapshot output already exists")
            _fsync_directory(output.parent)
            payload = output.read_bytes()
            return {
                "schema_version": schema,
                "status": "complete",
                "output_path": str(output),
                "final_url": native_url,
                "title": title,
                "site": site,
                "captured_at": captured.isoformat().replace("+00:00", "Z"),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
                "write_state": "written",
            }
        finally:
            try:
                staging.unlink()
            except FileNotFoundError:
                pass
    except WebpageCommandError as exc:
        return _failure(schema, exc.code, exc.message)
    except (OSError, ValueError) as exc:
        return _failure(schema, "webpage.capture_failed", str(exc))


def extract(snapshot: Path, output: Path) -> dict[str, object]:
    """Expose Task 2's snapshot-only projection under the command receipt."""

    schema = "quasi.webpage.extract/0.1"
    try:
        result = extract_webarchive(snapshot, output)
        return {
            "schema_version": schema,
            "status": "complete",
            "snapshot_path": str(snapshot),
            "output_path": str(output),
            "final_url": result.url,
            "title": result.title,
            "site": result.site,
            "sha256": result.sha256,
            "size": result.size,
            "write_state": "written",
        }
    except (OSError, ValueError) as exc:
        return _failure(schema, "webpage.extract_failed", str(exc))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quasi-webpage")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--url", required=True)
    inspect_parser.add_argument("--json", action="store_true", required=True)
    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--url", required=True)
    capture_parser.add_argument("--expected-final-url", required=True)
    capture_parser.add_argument("--output", required=True)
    capture_parser.add_argument("--json", action="store_true", required=True)
    extract_parser = subparsers.add_parser("extract")
    extract_parser.add_argument("--snapshot", required=True)
    extract_parser.add_argument("--output", required=True)
    extract_parser.add_argument("--json", action="store_true", required=True)
    arguments = parser.parse_args(argv)
    if arguments.command == "inspect":
        result = inspect(arguments.url)
    elif arguments.command == "capture":
        result = capture(arguments.url, arguments.expected_final_url, Path(arguments.output))
    else:
        result = extract(Path(arguments.snapshot), Path(arguments.output))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
