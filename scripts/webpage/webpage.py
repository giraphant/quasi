"""Closed WebKit capture commands for immutable Webpage material."""

from __future__ import annotations

import argparse
import array
import socket
import base64
import functools
import hashlib
import json
import os
import platform
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
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
from .paths import (
    PinnedOutput,
)


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


def _native_binary(source_digest: str) -> Path:
    return _data_dir() / "bin" / f"quasi-webpage-webkit-{source_digest}"


def _macos_11_or_newer() -> bool:
    version = platform.mac_ver()[0]
    try:
        return int(version.split(".", 1)[0]) >= 11
    except (ValueError, IndexError):
        return False


NATIVE_COMPILER_FLAGS = ("-O", "-parse-as-library", "-framework", "WebKit")


def _compiler_environment():
    # No ambient service credentials or compiler injection variables propagate.
    environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"}
    for key in ("HOME", "TMPDIR", "SDKROOT", "DEVELOPER_DIR", "TOOLCHAINS",
                "MACOSX_DEPLOYMENT_TARGET", "SWIFT_MODULECACHE_PATH", "CLANG_MODULE_CACHE_PATH"):
        if key in os.environ:
            environment[key] = os.environ[key]
    return environment


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
    try:
        source_bytes = source.read_bytes()
    except OSError as exc:
        raise WebpageCommandError("webpage.capture_unavailable", str(exc)) from exc
    flags = ["-target", platform.machine() + "-apple-macos11", *NATIVE_COMPILER_FLAGS]
    environment = _compiler_environment()
    version = _compiler_job({"mode": "version", "compiler": swiftc, "environment": environment}).get("version")
    if type(version) is not str or not version:
        raise WebpageCommandError("webpage.capture_unavailable", "invalid compiler identity")
    recipe = json.dumps([str(Path(swiftc).resolve()), version, flags, platform.machine(), sys.platform, environment],
                        sort_keys=True,
                        separators=(",", ":")).encode()
    binary = _native_binary(hashlib.sha256(source_bytes + b"\0" + recipe).hexdigest())
    try:
        mode = binary.lstat().st_mode
        if stat.S_ISREG(mode) and binary.stat().st_size > 0 and os.access(binary, os.X_OK):
            return binary
    except FileNotFoundError:
        pass
    binary.parent.mkdir(parents=True, exist_ok=True)
    _compiler_job({"mode": "compile", "compiler": swiftc, "flags": flags,
                   "source": base64.b64encode(source_bytes).decode(), "binary": str(binary), "environment": environment})
    return binary


def _compiler_job(job):
    # The supervisor owns creation, cleanup and publication; it watches this PID
    # even if SIGKILL prevents the caller from executing any Python finally.
    with _native_cancellation():
        try:
            process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("compiler_guard.py")), str(os.getpid())],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, start_new_session=True)
        except OSError as exc:
            raise WebpageCommandError("webpage.capture_unavailable", "compiler supervisor unavailable") from exc
        try:
            stdout, _stderr = process.communicate(json.dumps(job), timeout=310 if job["mode"] == "compile" else 12)
        except BaseException as exc:
            _stop_native(process)
            if isinstance(exc, subprocess.TimeoutExpired):
                raise WebpageCommandError("webpage.capture_unavailable", "compiler deadline exceeded") from exc
            raise
        if process.returncode:
            raise WebpageCommandError("webpage.capture_unavailable", "compiler failed")
        try:
            return json.loads(stdout)
        except ValueError as exc:
            raise WebpageCommandError("webpage.capture_unavailable", "invalid compiler response") from exc


NATIVE_PARENT_TIMEOUT_SECONDS = 65.0
NATIVE_TERMINATION_GRACE_SECONDS = 1.0
NATIVE_DRAIN_TIMEOUT_SECONDS = 1.0
NATIVE_REAP_TIMEOUT_SECONDS = 1.0


def _signal_group(process: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass  # The process group exited between timeout and signal.
    except PermissionError:
        # macOS can return EPERM for the empty group of an already-dead leader.
        # Reap/check that leader; do not hide a permission failure on a live one.
        if process.poll() is None:
            raise


def _stop_native(process: subprocess.Popen) -> None:
    """Bound every shutdown phase, including inherited pipes outside the group."""
    for sig, budget in ((signal.SIGTERM, NATIVE_TERMINATION_GRACE_SECONDS),
                        (signal.SIGKILL, NATIVE_DRAIN_TIMEOUT_SECONDS)):
        try:
            _signal_group(process, sig)
        except OSError:
            pass  # Still attempt the next signal, pipe close and leader reap.
        try:
            process.communicate(timeout=budget)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    for pipe in (getattr(process, "stdin", None), process.stdout, process.stderr):
        if pipe is not None:
            try:
                pipe.close()
            except OSError:
                pass
    try:
        process.wait(timeout=NATIVE_REAP_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        pass


class _NativeSignal(BaseException):
    def __init__(self, signum):
        self.signum = signum


_cancellation_state = threading.local()


@contextmanager
def _native_cancellation():
    if getattr(_cancellation_state, "active", False):
        yield
        return
    _cancellation_state.active = True
    previous = {}
    def interrupted(signum, _frame):
        # A second signal must not interrupt bounded cleanup.
        for number in previous:
            signal.signal(number, signal.SIG_IGN)
        raise _NativeSignal(signum)
    try:
        if threading.current_thread() is threading.main_thread():
            for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                previous[number] = signal.getsignal(number)
                if previous[number] != signal.SIG_IGN:
                    signal.signal(number, interrupted)
        yield
    except _NativeSignal as exc:
        for number, handler in previous.items():
            signal.signal(number, handler)
        signal.raise_signal(exc.signum)
        raise SystemExit(128 + exc.signum)
    finally:
        _cancellation_state.active = False
        for number, handler in previous.items():
            signal.signal(number, handler)


@contextmanager
def _defer_termination():
    # Register ownership before delivering a pending signal, and finish cleanup
    # before propagating it. This CLI owns these descriptors on its main thread.
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT, signal.SIGHUP})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def cancellable(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        with _native_cancellation():
            return function(*args, **kwargs)
    return wrapped


@cancellable
def _run_native(mode: str, url: str, staging: Path | None = None, descriptor: int | None = None, binary: Path | None = None) -> NativeResult:
    binary = binary if binary is not None else _ensure_native_binary()
    arguments = [str(binary), mode, url]
    if staging is not None:
        arguments.extend([str(staging), str(descriptor) if descriptor is not None else "-1"])
    with _native_cancellation():
        try:
            process = subprocess.Popen(
                arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, start_new_session=True, pass_fds=(() if descriptor is None else (descriptor,)),
            )
        except OSError as exc:
            raise WebpageCommandError("webpage.capture_failed", str(exc)) from exc
        try:
            stdout, stderr = process.communicate(timeout=NATIVE_PARENT_TIMEOUT_SECONDS)
        except BaseException as exc:
            if threading.current_thread() is threading.main_thread():
                for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                    signal.signal(number, signal.SIG_IGN)
            try:
                _stop_native(process)
            finally:
                if staging is not None and descriptor is None:
                    try:
                        staging.unlink(missing_ok=True)
                    except OSError:
                        pass  # Preserve the original cancellation/timeout semantics.
            if isinstance(exc, subprocess.TimeoutExpired):
                raise WebpageCommandError(
                    "webpage.capture_timeout", "WebKit helper exceeded parent watchdog deadline"
                ) from exc
            raise
    def invalid():
        return WebpageCommandError("webpage.capture_failed", "invalid native helper protocol")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result
    try:
        payload = json.loads(stdout, object_pairs_hook=pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError("constant")))
        if type(payload) is not dict:
            raise invalid()
        if payload.get("status") == "failed":
            if set(payload) != {"status", "code", "message"} or any(type(v) is not str for v in payload.values()):
                raise invalid()
            if process.returncode == 0 or payload["code"] not in {
                "webpage.capture_timeout", "webpage.stabilization_failed", "webpage.navigation_failed",
                "webpage.metadata_failed", "webpage.capture_failed", "webpage.invalid_arguments", "webpage.invalid_url"}:
                raise invalid()
            raise WebpageCommandError(payload["code"], payload["message"])
        keys = {"status", "final_url", "title", "site"} | ({"staging_path"} if staging is not None else set())
        if set(payload) != keys or process.returncode != 0 or payload["status"] != "complete" or any(type(v) is not str for v in payload.values()):
            raise invalid()
        normalize_web_url(payload["final_url"])
        if staging is not None and payload["staging_path"] != str(staging):
            raise invalid()
        return NativeResult(payload["final_url"], payload["title"], payload["site"])
    except (ValueError, TypeError):
        raise invalid() from None


def run_native_inspect(url: str) -> NativeResult:
    """Load exactly once for the read-only identity operation."""

    return _run_native("inspect", url)


def run_native_capture(url: str, staging: Path, *, descriptor: int | None = None, binary: Path | None = None) -> NativeResult:
    """Load exactly once and write only the caller-owned staging path."""

    # The guardian alone owns directory cleanup. The native helper receives only
    # the owned descriptor alias, so its parent-death cleanup cannot resolve a
    # swapped caller directory (or unlink an attacker-selected external file).
    native_path = Path(f"/dev/fd/{descriptor}") if descriptor is not None else staging
    return _run_native("capture", url, native_path, descriptor, binary)


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


@cancellable
def capture(url: str, expected_final_url: str, output: Path) -> dict[str, object]:
    """Capture once, validate its loaded identity, then atomically no-clobber publish."""

    schema = "quasi.webpage.capture/0.1"
    try:
        requested_url = normalize_web_url(url)
        expected_url = normalize_web_url(expected_final_url)
        try:
            pinned = PinnedOutput(output)
        except FileExistsError:
            return _failure(schema, "webpage.output_exists", "snapshot output already exists")
        safe_output = pinned.path
        descriptor = None
        guardian = None
        channel = None
        committed = False
        publication_uncertain = False
        stage_name = None
        try:
            binary = _ensure_native_binary()
            pinned.verify()
            with _defer_termination():
                channel, child_channel = socket.socketpair()
                try:
                    guardian = subprocess.Popen(
                        [sys.executable, str(Path(__file__).with_name("capture_guard.py")),
                         str(os.getpid()), str(pinned.directory), str(child_channel.fileno())],
                        pass_fds=(pinned.directory, child_channel.fileno()), start_new_session=True,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                finally:
                    child_channel.close()
                channel.settimeout(5)
                data, ancillary, _flags, _address = channel.recvmsg(256, socket.CMSG_SPACE(array.array('i').itemsize))
                received = array.array('i')
                for level, kind, value in ancillary:
                    if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                        received.frombytes(value)
                if len(received) != 1 or not data.startswith(b'.capture-'):
                    for fd in received:
                        os.close(fd)
                    raise ValueError("invalid capture guardian response")
                descriptor = received[0]
                stage_name = data.decode('ascii')
            staging = safe_output.parent / stage_name
            owned = os.fstat(descriptor)
            def verify_owned(name):
                actual = os.stat(name, dir_fd=pinned.directory, follow_symlinks=False)
                if not stat.S_ISREG(actual.st_mode) or PinnedOutput.identity(actual) != PinnedOutput.identity(owned):
                    raise ValueError("capture staging identity changed")
            native = run_native_capture(requested_url, staging, descriptor=descriptor, binary=binary)
            verify_owned(stage_name)
            os.lseek(descriptor, 0, os.SEEK_SET)
            archive = read_webarchive(Path(f"/dev/fd/{descriptor}"))
            native_url, _native_title, _native_site = _metadata(native)
            if archive.url != expected_url or native_url != expected_url:
                return _failure(
                    schema,
                    "webpage.capture_identity_changed",
                    "captured page final URL differs from the expected final URL",
                )
            captured = datetime.now(timezone.utc).replace(microsecond=0)
            captured_epoch = int(captured.timestamp())
            os.utime(descriptor, ns=(captured_epoch * 1_000_000_000,) * 2)
            os.fsync(descriptor)
            payload = os.pread(descriptor, os.fstat(descriptor).st_size, 0)
            receipt = {
                "schema_version": schema,
                "status": "complete",
                "output_path": str(output),
                "url": requested_url,
                "final_url": native_url,
                "title": archive.title,
                "site": archive.site,
                "captured_at": captured.isoformat().replace("+00:00", "Z"),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
                "write_state": "written",
            }
            verify_owned(stage_name)
            pinned.verify()
            publication_error = None
            publication_uncertain = True
            try:
                os.link(stage_name, safe_output.name, src_dir_fd=pinned.directory,
                        dst_dir_fd=pinned.directory, follow_symlinks=False)
            except OSError as exc:
                publication_error = exc
            # Even a syscall wrapper that raises after linking must not report a
            # safe precommit failure. Establish ownership from the pinned inode.
            try:
                actual = os.stat(safe_output.name, dir_fd=pinned.directory, follow_symlinks=False)
            except FileNotFoundError:
                publication_uncertain = False
                if publication_error is not None:
                    raise publication_error
                raise ValueError("capture publication absent")
            publication_uncertain = False
            committed = PinnedOutput.identity(actual) == PinnedOutput.identity(owned)
            if not committed:
                return _failure(schema, "webpage.output_exists", "snapshot output already exists")
            if publication_error is not None:
                raise publication_error
            verify_owned(safe_output.name)
            pinned.verify()
            os.fsync(pinned.directory)
            return receipt
        except (OSError, ValueError) as exc:
            if committed or publication_uncertain:
                return _failure(schema, "webpage.capture_outcome_unknown",
                                "capture commit outcome requires fresh disk observation; do not replay")
            raise
        finally:
            with _defer_termination():
                cleanup_error = None
                actions = []
                if descriptor is not None:
                    actions.append(lambda: os.close(descriptor))
                if channel is not None:
                    actions.append(channel.close)  # EOF instructs unlinkat.
                if guardian is not None:
                    actions.append(lambda: guardian.wait(timeout=5))
                actions.append(pinned.close)
                for action in actions:
                    try:
                        action()
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        cleanup_error = exc
                if cleanup_error is not None or (guardian is not None and guardian.returncode):
                    raise WebpageCommandError("webpage.capture_outcome_unknown",
                                              "capture cleanup requires fresh disk observation; do not replay") from cleanup_error
    except WebpageCommandError as exc:
        return _failure(schema, exc.code, exc.message)
    except (OSError, ValueError) as exc:
        return _failure(schema, "webpage.capture_failed", str(exc))


def extract(
    snapshot: Path,
    output: Path,
    *,
    replace_existing: bool = False,
) -> dict[str, object]:
    """Expose Task 2's snapshot-only projection under the command receipt."""

    schema = "quasi.webpage.extract/0.1"
    try:
        result = extract_webarchive(
            snapshot,
            output,
            replace_existing=replace_existing,
        )
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
    extract_parser.add_argument("--replace-existing", action="store_true")
    extract_parser.add_argument("--json", action="store_true", required=True)
    arguments = parser.parse_args(argv)
    if arguments.command == "inspect":
        result = inspect(arguments.url)
    elif arguments.command == "capture":
        result = capture(arguments.url, arguments.expected_final_url, Path(arguments.output))
    else:
        result = extract(
            Path(arguments.snapshot),
            Path(arguments.output),
            replace_existing=arguments.replace_existing,
        )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
