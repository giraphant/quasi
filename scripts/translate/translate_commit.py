#!/usr/bin/env python3
"""Transactional storage boundary for Quasi PDF translations.

Provider work is injected through ``backend_runner``.  This module owns the
project-local paths, request identity, source selection, output lock, staging,
postconditions, manifest-last publication, and strict operation receipts.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator, Optional
from urllib.parse import urlsplit, urlunsplit

import pymupdf


MANIFEST_SCHEMA = "quasi.translation.manifest/0.1"
OBSERVE_SCHEMA = "quasi.operation.translation.reconcile.receipt/0.1"
RUN_SCHEMA = "quasi.operation.translation.run.receipt/0.1"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
LANG_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8}){0,3}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
GENERATION_RE = re.compile(r"^[a-f0-9]{32}$")
MODES = {"initial", "recovery", "final"}
COVERAGE_SIGNALS = {
    "pending",
    "not_applicable",
    "insufficient_evidence",
    "pass",
    "under_translated",
}


class TranslateContractError(RuntimeError):
    """Known failure detected before an ambiguous canonical side effect."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def fingerprint(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def redact_text(value: object, *, secrets: tuple[str, ...] = ()) -> str:
    """Redact configured secrets and secret-bearing URL components."""
    text = str(value)
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        text = text.replace(secret, "<redacted>")

    def clean_url(match: re.Match[str]) -> str:
        raw = match.group(0).rstrip(".,);]")
        suffix = match.group(0)[len(raw) :]
        try:
            parts = urlsplit(raw)
            host = parts.hostname or ""
            if parts.port:
                host = f"{host}:{parts.port}"
            cleaned = urlunsplit((parts.scheme, host, parts.path, "", ""))
            if parts.query or parts.fragment or parts.username or parts.password:
                cleaned += "?<redacted>"
            return cleaned + suffix
        except Exception:
            return "<redacted-url>" + suffix

    text = re.sub(r"https?://[^\s<>\"']+", clean_url, text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|token|authorization|cookie|bearer)"
        r"(\s*[:=]\s*|\s+)[^\s,;]+",
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>",
        text,
    )
    return text[:4000]


def validate_slug(slug: str) -> str:
    if not SLUG_RE.fullmatch(slug):
        raise TranslateContractError(
            "translation.invalid_slug",
            "slug must be 1-80 lowercase ASCII letters, digits, or hyphens",
        )
    return slug


def validate_language(language: str) -> str:
    if not LANG_RE.fullmatch(language):
        raise TranslateContractError(
            "translation.invalid_target_language",
            "target language must be a bounded BCP47-like ASCII tag",
        )
    parts = language.split("-")
    normalised = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 2 and part.isalpha():
            normalised.append(part.upper())
        else:
            normalised.append(part.lower())
    return "-".join(normalised)


def validate_sha256(value: str, *, field: str) -> str:
    normalised = value.lower()
    if not SHA256_RE.fullmatch(normalised):
        raise TranslateContractError(
            "translation.invalid_fingerprint",
            f"{field} must be a lowercase SHA-256 digest",
        )
    return normalised


def _absolute(path: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return Path(os.path.abspath(candidate))


def _lstat_regular(path: Path, *, field: str, suffix: str) -> Path:
    candidate = _absolute(path)
    try:
        mode = candidate.lstat().st_mode
    except FileNotFoundError as exc:
        raise TranslateContractError(
            f"translation.{field}_missing",
            f"{field} does not exist: {candidate}",
        ) from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise TranslateContractError(
            f"translation.{field}_not_regular",
            f"{field} must be a regular non-symlink file: {candidate}",
        )
    if candidate.suffix.lower() != suffix:
        raise TranslateContractError(
            f"translation.{field}_wrong_type",
            f"{field} must end in {suffix}: {candidate}",
        )
    return candidate


def validate_source(path: Path) -> Path:
    return _lstat_regular(path, field="source", suffix=".pdf")


def validate_toc(path: Path | None) -> Path | None:
    if path is None:
        return None
    return _lstat_regular(path, field="toc", suffix=".json")


def project_relative(path: Path, project_root: Path) -> str:
    root = project_root.expanduser().resolve()
    try:
        return path.resolve().relative_to(root).as_posix()
    except (OSError, ValueError) as exc:
        raise TranslateContractError(
            "translation.path_outside_project",
            f"path must stay inside the project root: {path}",
        ) from exc


def validate_project_source(
    path: Path,
    project_root: Path,
    *,
    slug: str | None = None,
    target_language: str | None = None,
) -> Path:
    source = validate_source(path)
    relative = project_relative(source, project_root)
    if slug is not None:
        allowed = {
            f"sources/{slug}.pdf",
            f"processing/papers/{slug}/ocr.pdf",
        }
        if target_language is not None:
            tag = validate_language(target_language).lower()
            allowed.add(f"processing/translations/{slug}-{tag}-reocr.pdf")
        if relative not in allowed:
            raise TranslateContractError(
                "translation.source_role_invalid",
                "source must be an exact canonical or recovery role for this slug",
            )
    return source


def validate_project_toc(path: Path | None, project_root: Path) -> Path | None:
    toc = validate_toc(path)
    if toc is not None:
        project_relative(toc, project_root)
    return toc


def pdf_page_count(path: Path) -> int:
    try:
        document = pymupdf.open(str(path))
        count = len(document)
        document.close()
    except Exception as exc:
        raise TranslateContractError(
            "translation.pdf_invalid",
            f"failed to read PDF {path}: {redact_text(exc)}",
        ) from exc
    if count <= 0:
        raise TranslateContractError("translation.pdf_empty", f"PDF has no pages: {path}")
    return count


def output_paths(
    *,
    project_root: Path,
    slug: str,
    target_language: str,
) -> dict[str, Path | str]:
    root = project_root.expanduser().resolve()
    slug = validate_slug(slug)
    target_language = validate_language(target_language)
    language_stem = target_language.lower()
    output_dir = root / "processing" / "translations"
    stem = f"{slug}-{language_stem}"
    return {
        "project_root": root,
        "output_dir": output_dir,
        "stem": stem,
        "output_path": output_dir / f"{stem}.pdf",
        "manifest_path": output_dir / f"{stem}.manifest.json",
        "lock_path": output_dir / f".{stem}.translate.lock",
        "generation_prefix": f".{stem}.translate-",
    }


def _ensure_output_dir(paths: dict[str, Path | str]) -> None:
    root = paths["project_root"]
    output_dir = paths["output_dir"]
    assert isinstance(root, Path) and isinstance(output_dir, Path)
    current = root
    for part in output_dir.relative_to(root).parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            current.mkdir(mode=0o755, exist_ok=True)
            mode = current.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise TranslateContractError(
                "translation.output_root_unsafe",
                f"output path component must be a real directory: {current}",
            )


@contextlib.contextmanager
def output_lock(paths: dict[str, Path | str]) -> Iterator[None]:
    _ensure_output_dir(paths)
    lock_path = paths["lock_path"]
    assert isinstance(lock_path, Path)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise TranslateContractError(
            "translation.output_lock_unsafe",
            f"failed to open safe output lock: {redact_text(exc)}",
        ) from exc
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise TranslateContractError(
            "translation.output_lock_unsafe",
            "output lock must be a regular file",
        )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json(path: Path, value: dict[str, Any], *, sync_parent: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if sync_parent:
            _fsync_directory(path.parent)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _regular_file_state(path: Path) -> tuple[bool, str | None]:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False, None
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        return True, None
    return True, sha256_file(path)


def request_payload(
    *,
    project_root: Path,
    slug: str,
    backend: str,
    target_language: str,
    input_path: Path,
    input_sha256: str,
    input_pages: int,
    toc_path: Path | None,
    toc_sha256: str | None,
    toc_page_side: str,
    attempt: int,
    config_fingerprint: str,
) -> dict[str, Any]:
    return {
        "slug": slug,
        "backend": backend,
        "target_language": target_language,
        "input_path": project_relative(input_path, project_root),
        "input_sha256": input_sha256,
        "input_pages": input_pages,
        "toc_path": project_relative(toc_path, project_root) if toc_path else None,
        "toc_sha256": toc_sha256,
        "toc_page_side": toc_page_side,
        "attempt": attempt,
        "config_fingerprint": config_fingerprint,
    }


def request_fingerprint(**kwargs: Any) -> str:
    return fingerprint(request_payload(**kwargs))


def _coverage_pending() -> dict[str, Any]:
    return {
        "signal": "pending",
        "median": None,
        "measured_pages": 0,
        "minimum_median": 0.0,
        "weakest": [],
        "detail": None,
    }


def normalise_coverage(report: dict[str, Any]) -> dict[str, Any]:
    signal = str(report.get("signal") or "")
    if signal not in COVERAGE_SIGNALS:
        raise TranslateContractError(
            "translation.coverage_invalid",
            f"coverage returned unknown signal: {signal}",
        )
    weakest = report.get("weakest")
    if not isinstance(weakest, list) or len(weakest) > 32:
        raise TranslateContractError(
            "translation.coverage_invalid",
            "coverage weakest rows were malformed",
        )
    rows: list[dict[str, Any]] = []
    for row in weakest:
        if (
            not isinstance(row, dict)
            or set(row) != {"page", "ratio"}
            or not isinstance(row["page"], int)
            or row["page"] < 1
            or not isinstance(row["ratio"], (int, float))
            or row["ratio"] < 0
        ):
            raise TranslateContractError(
                "translation.coverage_invalid",
                "coverage weakest rows were malformed",
            )
        rows.append({"page": row["page"], "ratio": float(row["ratio"])})
    median = report.get("median")
    minimum = report.get("minimum_median")
    measured = report.get("measured_pages")
    if median is not None and (not isinstance(median, (int, float)) or median < 0):
        raise TranslateContractError("translation.coverage_invalid", "invalid coverage median")
    if not isinstance(minimum, (int, float)) or minimum < 0:
        raise TranslateContractError("translation.coverage_invalid", "invalid coverage threshold")
    if not isinstance(measured, int) or measured < 0:
        raise TranslateContractError("translation.coverage_invalid", "invalid measured page count")
    return {
        "signal": signal,
        "median": None if median is None else float(median),
        "measured_pages": measured,
        "minimum_median": float(minimum),
        "weakest": rows,
        "detail": redact_text(report.get("detail")) if report.get("detail") else None,
    }


def operation_failure(
    *,
    code: str,
    operation_key: str,
    outcome: str,
    message: object,
) -> dict[str, Any]:
    if outcome not in {"known", "unknown"}:
        raise AssertionError("failure outcome invariant")
    return {
        "code": code,
        "operation_key": operation_key,
        "outcome": outcome,
        "retryable": False,
        "message": redact_text(message) if message is not None else None,
    }


def _toc_public(
    toc: Path | None,
    project_root: Path,
    toc_page_side: str,
    entries: int = 0,
) -> dict[str, Any]:
    return {
        "input_path": project_relative(toc, project_root) if toc else None,
        "page_side": toc_page_side,
        "entries": entries,
    }


def _receipt(
    *,
    operation: str,
    status: str,
    slug: str,
    backend: str,
    target_language: str,
    paths: dict[str, Path | str],
    input_path: Path | None,
    source_sha256: str | None,
    source_pages: int,
    request_fingerprint_value: str | None,
    toc_json: Path | None,
    toc_page_side: str,
    coverage: dict[str, Any] | None,
    failure: dict[str, Any] | None,
    attempt: int = 1,
    mode: str = "initial",
    generation_attempt: int = 0,
    requested_source: Path | None = None,
    signal: str | None = None,
    candidates: list[dict[str, Any]] | None = None,
    candidates_fingerprint: str | None = None,
    gate: dict[str, Any] | None = None,
    disposition: str | None = None,
    canonical_committed: bool = False,
    previous_manifest_preserved: bool = True,
    toc_entries: int = 0,
) -> dict[str, Any]:
    root = paths["project_root"]
    output = paths["output_path"]
    manifest = paths["manifest_path"]
    assert isinstance(root, Path) and isinstance(output, Path) and isinstance(manifest, Path)
    input_public = project_relative(input_path, root) if input_path else None
    requested_public = project_relative(requested_source, root) if requested_source else None
    toc_public = project_relative(toc_json, root) if toc_json else None
    output_public = project_relative(output, root)
    manifest_public = project_relative(manifest, root)
    output_exists, output_sha = _regular_file_state(output)
    manifest_exists, manifest_sha = _regular_file_state(manifest)
    output_size = output.stat().st_size if output_sha else 0
    output_pages = 0
    if output_sha:
        try:
            output_pages = pdf_page_count(output)
        except TranslateContractError:
            output_pages = 0
    source_size = input_path.stat().st_size if input_path else 0

    if operation == "translation.reconcile":
        reused = status == "succeeded" and signal == "reused"
        return {
            "schema_version": OBSERVE_SCHEMA,
            "key": operation,
            "effect": "readonly",
            "status": status,
            "attempt": 1,
            "derivative_key": f"translation:paper:{slug}:{target_language}",
            "slug": slug,
            "mode": mode,
            "generation_attempt": generation_attempt,
            "requested_source": requested_public,
            "source_path": input_public,
            "output_path": output_public,
            "manifest_path": manifest_public,
            "target_language": target_language,
            "toc_json": toc_public,
            "toc_page_side": toc_page_side,
            "backend": backend,
            "signal": signal,
            "request_fingerprint": request_fingerprint_value,
            "source_sha256": source_sha256,
            "source_size": source_size,
            "source_pages": source_pages,
            "output_sha256": output_sha if reused else None,
            "manifest_sha256": manifest_sha if reused else None,
            "output_size": output_size if reused else 0,
            "output_pages": output_pages if reused else 0,
            "toc_entries": toc_entries if reused else 0,
            "coverage": coverage if reused else None,
            "candidates": candidates or [],
            "candidates_fingerprint": candidates_fingerprint,
            "gate": gate,
            "failure": failure,
        }

    succeeded = status == "succeeded"
    return {
        "schema_version": RUN_SCHEMA,
        "key": operation,
        "effect": "writer",
        "status": status,
        "attempt": attempt,
        "derivative_key": f"translation:paper:{slug}:{target_language}",
        "slug": slug,
        "backend": backend,
        "input_path": input_public or "",
        "output_path": output_public,
        "manifest_path": manifest_public,
        "target_language": target_language,
        "toc_json": toc_public,
        "toc_page_side": toc_page_side,
        "request_fingerprint": request_fingerprint_value or "",
        "source_sha256": source_sha256 or "",
        "output_sha256": output_sha if succeeded else None,
        "manifest_sha256": manifest_sha if succeeded else None,
        "output_size": output_size if succeeded else 0,
        "source_pages": source_pages,
        "output_pages": output_pages if succeeded else 0,
        "toc_entries": toc_entries if succeeded else 0,
        "coverage": coverage,
        "disposition": disposition if succeeded else None,
        "canonical_committed": canonical_committed if succeeded else False,
        "previous_manifest_preserved": previous_manifest_preserved,
        "gate": gate,
        "failure": failure,
    }


def discover_source_candidates(
    *,
    project_root: Path,
    slug: str,
) -> tuple[list[dict[str, Any]], str]:
    root = project_root.expanduser().resolve()
    validate_slug(slug)
    candidates: list[dict[str, Any]] = []
    exact_paths = [
        root / "sources" / f"{slug}.pdf",
        root / "processing" / "papers" / slug / "ocr.pdf",
    ]
    for path in exact_paths:
        try:
            source = validate_project_source(path, root, slug=slug)
            candidates.append(
                {
                    "path": project_relative(source, root),
                    "sha256": sha256_file(source),
                    "size": source.stat().st_size,
                    "pages": pdf_page_count(source),
                }
            )
        except TranslateContractError:
            continue
    candidates.sort(key=lambda row: row["path"])
    return candidates, fingerprint(candidates)


def _gate(
    *,
    kind: str,
    missing_fields: list[str] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    candidates_fingerprint: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "missing_fields": missing_fields or [],
        "candidates": candidates or [],
        "candidates_fingerprint": candidates_fingerprint,
    }


def _manifest_expected_keys() -> set[str]:
    return {
        "schema_version",
        "derivative_key",
        "slug",
        "backend",
        "target_language",
        "input_path",
        "input_sha256",
        "input_pages",
        "toc_path",
        "toc_sha256",
        "toc_page_side",
        "attempt",
        "config_fingerprint",
        "request_fingerprint",
        "output_path",
        "output_sha256",
        "output_size",
        "output_pages",
        "toc_entries",
        "tounicode",
        "coverage",
    }


def _manifest_matches(
    manifest: dict[str, Any],
    *,
    paths: dict[str, Path | str],
    slug: str,
    backend: str,
    target_language: str,
    input_path: Path,
    input_sha256: str,
    input_pages: int,
    toc_path: Path | None,
    toc_sha256: str | None,
    toc_page_side: str,
    config_fingerprint: str,
    generation_attempt: int,
) -> bool:
    root = paths["project_root"]
    output = paths["output_path"]
    assert isinstance(root, Path) and isinstance(output, Path)
    if set(manifest) != _manifest_expected_keys():
        return False
    if generation_attempt not in {1, 2} or manifest.get("attempt") != generation_attempt:
        return False
    payload = request_payload(
        project_root=root,
        slug=slug,
        backend=backend,
        target_language=target_language,
        input_path=input_path,
        input_sha256=input_sha256,
        input_pages=input_pages,
        toc_path=toc_path,
        toc_sha256=toc_sha256,
        toc_page_side=toc_page_side,
        attempt=generation_attempt,
        config_fingerprint=config_fingerprint,
    )
    exact = {
        "schema_version": MANIFEST_SCHEMA,
        "derivative_key": f"translation:paper:{slug}:{target_language}",
        **payload,
        "request_fingerprint": fingerprint(payload),
        "output_path": project_relative(output, root),
    }
    if any(manifest.get(key) != value for key, value in exact.items()):
        return False
    exists, output_sha = _regular_file_state(output)
    if not exists or output_sha is None or manifest.get("output_sha256") != output_sha:
        return False
    try:
        pages = pdf_page_count(output)
    except TranslateContractError:
        return False
    if (
        manifest.get("output_pages") != pages
        or manifest.get("output_size") != output.stat().st_size
        or not isinstance(manifest.get("toc_entries"), int)
        or manifest["toc_entries"] < 0
        or not isinstance(manifest.get("tounicode"), dict)
        or not isinstance(manifest.get("coverage"), dict)
    ):
        return False
    try:
        normalise_coverage(manifest["coverage"])
    except TranslateContractError:
        return False
    return True


def _resolve_source(
    *,
    project_root: Path,
    slug: str,
    target_language: str,
    source_file: Path | None,
    decision_path: Path | None,
    decision_sha256: str | None,
    decision_candidates_fingerprint: str | None,
) -> tuple[
    Path | None,
    Path | None,
    list[dict[str, Any]],
    str,
    dict[str, Any] | None,
    dict[str, Any] | None,
]:
    root = project_root.expanduser().resolve()
    candidates, current_fingerprint = discover_source_candidates(
        project_root=root,
        slug=slug,
    )
    requested = (
        validate_project_source(
            source_file,
            root,
            slug=slug,
            target_language=target_language,
        )
        if source_file is not None
        else None
    )
    decision_values = (
        decision_path,
        decision_sha256,
        decision_candidates_fingerprint,
    )
    if any(value is not None for value in decision_values):
        if not all(value is not None for value in decision_values) or requested is None:
            raise TranslateContractError(
                "translation.source_decision_incomplete",
                "source decision requires source, path, SHA-256, and candidates fingerprint",
            )
        assert decision_path is not None
        assert decision_sha256 is not None
        assert decision_candidates_fingerprint is not None
        selected_path = validate_project_source(
            decision_path,
            root,
            slug=slug,
            target_language=target_language,
        )
        selected_public = project_relative(selected_path, root)
        selected_sha = validate_sha256(decision_sha256, field="decision_sha256")
        selected = next(
            (candidate for candidate in candidates if candidate["path"] == selected_public),
            None,
        )
        if (
            decision_candidates_fingerprint != current_fingerprint
            or selected_path != requested
            or selected is None
            or selected["sha256"] != selected_sha
            or sha256_file(selected_path) != selected_sha
        ):
            raise TranslateContractError(
                "translation.source_decision_stale",
                "source decision no longer matches the current closed candidate set",
            )
        return requested, requested, [], current_fingerprint, None, None

    if requested is not None:
        return requested, requested, [], current_fingerprint, None, None
    if len(candidates) == 1:
        source = validate_project_source(
            root / candidates[0]["path"],
            root,
            slug=slug,
            target_language=target_language,
        )
        return None, source, [], current_fingerprint, None, None
    if not candidates:
        return (
            None,
            None,
            [],
            current_fingerprint,
            None,
            operation_failure(
                code="translation.source_missing",
                operation_key="translation.reconcile",
                outcome="known",
                message="no exact regular PDF source matched the translation slug",
            ),
        )
    selection_gate = _gate(
        kind="source_selection",
        candidates=candidates,
        candidates_fingerprint=current_fingerprint,
    )
    return (
        None,
        None,
        candidates,
        current_fingerprint,
        selection_gate,
        operation_failure(
            code="translation.source_selection_required",
            operation_key="translation.reconcile",
            outcome="known",
            message="multiple exact source roles require an explicit closed decision",
        ),
    )


def observe(
    *,
    project_root: Path,
    slug: str,
    backend: str,
    target_language: str,
    source_file: Path | None,
    toc_json: Path | None,
    toc_page_side: str,
    config_fingerprint: str,
    mode: str,
    configuration_missing: list[str] | None = None,
    decision_path: Path | None = None,
    decision_sha256: str | None = None,
    candidates_fingerprint: str | None = None,
) -> dict[str, Any]:
    root = project_root.expanduser().resolve()
    slug = validate_slug(slug)
    target_language = validate_language(target_language)
    if mode not in MODES:
        raise TranslateContractError("translation.invalid_mode", "invalid reconcile mode")
    if backend not in {"immersive", "pdf2zh"}:
        raise TranslateContractError("translation.invalid_backend", "invalid configured backend")
    if toc_page_side not in {"original", "translated"}:
        raise TranslateContractError(
            "translation.invalid_toc_page_side",
            "TOC page side must be original or translated",
        )
    paths = output_paths(
        project_root=root,
        slug=slug,
        target_language=target_language,
    )
    toc = validate_project_toc(toc_json, root)
    requested, source, gate_candidates, current_candidates_fp, source_gate, source_failure = (
        _resolve_source(
            project_root=root,
            slug=slug,
            target_language=target_language,
            source_file=source_file,
            decision_path=decision_path,
            decision_sha256=decision_sha256,
            decision_candidates_fingerprint=candidates_fingerprint,
        )
    )
    if source is None:
        selection = source_gate is not None
        return _receipt(
            operation="translation.reconcile",
            status="blocked" if selection else "failed",
            slug=slug,
            backend=backend,
            target_language=target_language,
            paths=paths,
            input_path=None,
            source_sha256=None,
            source_pages=0,
            request_fingerprint_value=None,
            toc_json=toc,
            toc_page_side=toc_page_side,
            coverage=None,
            failure=source_failure,
            mode=mode,
            generation_attempt=0,
            requested_source=requested,
            signal="source_selection" if selection else None,
            candidates=gate_candidates,
            candidates_fingerprint=current_candidates_fp if selection else None,
            gate=source_gate,
        )

    source_sha = sha256_file(source)
    source_pages = pdf_page_count(source)
    toc_sha = sha256_file(toc) if toc else None
    desired_attempt = 2 if mode == "recovery" else 1
    request_fp = request_fingerprint(
        project_root=root,
        slug=slug,
        backend=backend,
        target_language=target_language,
        input_path=source,
        input_sha256=source_sha,
        input_pages=source_pages,
        toc_path=toc,
        toc_sha256=toc_sha,
        toc_page_side=toc_page_side,
        attempt=desired_attempt,
        config_fingerprint=config_fingerprint,
    )
    output = paths["output_path"]
    manifest_path = paths["manifest_path"]
    assert isinstance(output, Path) and isinstance(manifest_path, Path)
    output_exists, _ = _regular_file_state(output)
    manifest_exists, _ = _regular_file_state(manifest_path)
    manifest = _read_json(manifest_path)
    manifest_attempt = (
        manifest.get("attempt")
        if isinstance(manifest, dict) and manifest.get("attempt") in {1, 2}
        else desired_attempt
    )
    matching_attempt = manifest_attempt if mode == "final" else desired_attempt
    if manifest is not None and _manifest_matches(
        manifest,
        paths=paths,
        slug=slug,
        backend=backend,
        target_language=target_language,
        input_path=source,
        input_sha256=source_sha,
        input_pages=source_pages,
        toc_path=toc,
        toc_sha256=toc_sha,
        toc_page_side=toc_page_side,
        config_fingerprint=config_fingerprint,
        generation_attempt=matching_attempt,
    ):
        return _receipt(
            operation="translation.reconcile",
            status="succeeded",
            slug=slug,
            backend=backend,
            target_language=target_language,
            paths=paths,
            input_path=source,
            source_sha256=source_sha,
            source_pages=source_pages,
            request_fingerprint_value=str(manifest["request_fingerprint"]),
            toc_json=toc,
            toc_page_side=toc_page_side,
            coverage=normalise_coverage(manifest["coverage"]),
            failure=None,
            mode=mode,
            generation_attempt=int(manifest["attempt"]),
            requested_source=requested,
            signal="reused",
            candidates_fingerprint=(
                current_candidates_fp if decision_path is not None else None
            ),
            toc_entries=int(manifest["toc_entries"]),
        )
    if output_exists or manifest_exists:
        return _receipt(
            operation="translation.reconcile",
            status="blocked",
            slug=slug,
            backend=backend,
            target_language=target_language,
            paths=paths,
            input_path=source,
            source_sha256=source_sha,
            source_pages=source_pages,
            request_fingerprint_value=request_fp,
            toc_json=toc,
            toc_page_side=toc_page_side,
            coverage=None,
            failure=operation_failure(
                code="translation.existing_output_unproven",
                operation_key="translation.reconcile",
                outcome="unknown",
                message="existing output and manifest do not prove this exact request",
            ),
            mode=mode,
            generation_attempt=matching_attempt,
            requested_source=requested,
            signal=None,
        )
    missing = sorted(set(configuration_missing or []))
    if missing:
        config_gate = _gate(kind="configuration_required", missing_fields=missing)
        return _receipt(
            operation="translation.reconcile",
            status="blocked",
            slug=slug,
            backend=backend,
            target_language=target_language,
            paths=paths,
            input_path=source,
            source_sha256=source_sha,
            source_pages=source_pages,
            request_fingerprint_value=request_fp,
            toc_json=toc,
            toc_page_side=toc_page_side,
            coverage=None,
            failure=operation_failure(
                code="translation.configuration_required",
                operation_key="translation.reconcile",
                outcome="known",
                message=f"missing configured fields: {', '.join(missing)}",
            ),
            mode=mode,
            generation_attempt=0,
            requested_source=requested,
            signal="configuration_required",
            gate=config_gate,
        )
    return _receipt(
        operation="translation.reconcile",
        status="succeeded",
        slug=slug,
        backend=backend,
        target_language=target_language,
        paths=paths,
        input_path=source,
        source_sha256=source_sha,
        source_pages=source_pages,
        request_fingerprint_value=request_fp,
        toc_json=toc,
        toc_page_side=toc_page_side,
        coverage=None,
        failure=None,
        mode=mode,
        generation_attempt=desired_attempt,
        requested_source=requested,
        signal="missing",
        candidates_fingerprint=(
            current_candidates_fp if decision_path is not None else None
        ),
    )


BackendRunner = Callable[
    [Path, Path, str, Path, Callable[[str, Optional[str]], None]],
    dict[str, Any],
]


def _generation_dirs(paths: dict[str, Path | str]) -> list[Path]:
    output_dir = paths["output_dir"]
    prefix = paths["generation_prefix"]
    assert isinstance(output_dir, Path) and isinstance(prefix, str)
    if not output_dir.exists():
        return []
    return sorted(
        (
            path
            for path in output_dir.iterdir()
            if path.name.startswith(prefix)
            and path.is_dir()
            and not path.is_symlink()
        ),
        key=lambda path: path.name,
    )


def _persist_receipt(generation_dir: Path, receipt: dict[str, Any]) -> None:
    try:
        _write_json(generation_dir / "receipt.json", receipt)
    except Exception:
        pass


def run_transaction(
    *,
    project_root: Path,
    slug: str,
    backend: str,
    target_language: str,
    source_file: Path,
    expected_source_sha256: str,
    toc_json: Path | None,
    toc_page_side: str,
    attempt: int,
    config_fingerprint: str,
    backend_runner: BackendRunner,
    add_toc: Callable[..., int],
    repair_tounicode: Callable[[Path], dict[str, int]],
    check_coverage: Callable[..., dict[str, Any]],
    configuration_missing: list[str] | None = None,
) -> dict[str, Any]:
    root = project_root.expanduser().resolve()
    slug = validate_slug(slug)
    target_language = validate_language(target_language)
    if backend not in {"immersive", "pdf2zh"}:
        raise TranslateContractError("translation.invalid_backend", "invalid configured backend")
    if toc_page_side not in {"original", "translated"}:
        raise TranslateContractError(
            "translation.invalid_toc_page_side",
            "TOC page side must be original or translated",
        )
    if attempt not in {1, 2}:
        raise TranslateContractError("translation.invalid_attempt", "attempt must be 1 or 2")
    expected_source_sha256 = validate_sha256(
        expected_source_sha256,
        field="expected_source_sha256",
    )
    source = validate_project_source(
        source_file,
        root,
        slug=slug,
        target_language=target_language,
    )
    toc = validate_project_toc(toc_json, root)
    source_sha = sha256_file(source)
    source_pages = pdf_page_count(source)
    toc_sha = sha256_file(toc) if toc else None
    request_fp = request_fingerprint(
        project_root=root,
        slug=slug,
        backend=backend,
        target_language=target_language,
        input_path=source,
        input_sha256=source_sha,
        input_pages=source_pages,
        toc_path=toc,
        toc_sha256=toc_sha,
        toc_page_side=toc_page_side,
        attempt=attempt,
        config_fingerprint=config_fingerprint,
    )
    paths = output_paths(
        project_root=root,
        slug=slug,
        target_language=target_language,
    )

    def run_receipt(
        status: str,
        *,
        failure: dict[str, Any] | None,
        coverage_value: dict[str, Any] | None = None,
        disposition: str | None = None,
        canonical: bool = False,
        previous: bool = True,
        toc_entries: int = 0,
        gate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _receipt(
            operation="translation.run",
            status=status,
            slug=slug,
            backend=backend,
            target_language=target_language,
            paths=paths,
            input_path=source,
            source_sha256=source_sha,
            source_pages=source_pages,
            request_fingerprint_value=request_fp,
            toc_json=toc,
            toc_page_side=toc_page_side,
            coverage=coverage_value,
            failure=failure,
            attempt=attempt,
            disposition=disposition,
            canonical_committed=canonical,
            previous_manifest_preserved=previous,
            toc_entries=toc_entries,
            gate=gate,
        )

    if source_sha != expected_source_sha256:
        return run_receipt(
            "failed",
            failure=operation_failure(
                code="translation.source_fingerprint_mismatch",
                operation_key="translation.run",
                outcome="known",
                message="source SHA-256 did not match expected_source_sha256",
            ),
        )
    missing = sorted(set(configuration_missing or []))
    if missing:
        config_gate = _gate(kind="configuration_required", missing_fields=missing)
        return run_receipt(
            "blocked",
            failure=operation_failure(
                code="translation.configuration_required",
                operation_key="translation.run",
                outcome="known",
                message=f"missing configured fields: {', '.join(missing)}",
            ),
            gate=config_gate,
        )

    with output_lock(paths):
        locked_sha = sha256_file(source)
        if locked_sha != expected_source_sha256:
            source_sha = locked_sha
            return run_receipt(
                "failed",
                failure=operation_failure(
                    code="translation.source_changed",
                    operation_key="translation.run",
                    outcome="known",
                    message="source changed while waiting for the output lock",
                ),
            )
        output = paths["output_path"]
        manifest_path = paths["manifest_path"]
        assert isinstance(output, Path) and isinstance(manifest_path, Path)
        manifest = _read_json(manifest_path)
        if manifest is not None and _manifest_matches(
            manifest,
            paths=paths,
            slug=slug,
            backend=backend,
            target_language=target_language,
            input_path=source,
            input_sha256=source_sha,
            input_pages=source_pages,
            toc_path=toc,
            toc_sha256=toc_sha,
            toc_page_side=toc_page_side,
            config_fingerprint=config_fingerprint,
            generation_attempt=attempt,
        ):
            return run_receipt(
                "succeeded",
                failure=None,
                coverage_value=normalise_coverage(manifest["coverage"]),
                disposition="reconciled",
                canonical=True,
                toc_entries=int(manifest["toc_entries"]),
            )
        output_exists, _ = _regular_file_state(output)
        manifest_exists, _ = _regular_file_state(manifest_path)
        if output_exists or manifest_exists:
            return run_receipt(
                "blocked",
                failure=operation_failure(
                    code="translation.existing_output_unproven",
                    operation_key="translation.run",
                    outcome="unknown",
                    message="strict run will not overwrite an unproven existing generation",
                ),
            )

        for generation_dir in _generation_dirs(paths):
            intent = _read_json(generation_dir / "intent.json")
            if not intent or intent.get("request_fingerprint") != request_fp:
                continue
            prior = _read_json(generation_dir / "receipt.json")
            if (
                prior
                and prior.get("schema_version") == RUN_SCHEMA
                and prior.get("request_fingerprint") == request_fp
            ):
                return prior
            return run_receipt(
                "blocked",
                failure=operation_failure(
                    code="translation.generation_requires_reconcile",
                    operation_key="translation.run",
                    outcome="unknown",
                    message="a previous fenced generation has no terminal receipt",
                ),
            )

        output_dir = paths["output_dir"]
        prefix = paths["generation_prefix"]
        assert isinstance(output_dir, Path) and isinstance(prefix, str)
        generation = uuid.uuid4().hex
        if not GENERATION_RE.fullmatch(generation):
            raise AssertionError("uuid4 invariant")
        generation_dir = output_dir / f"{prefix}{generation}"
        generation_dir.mkdir(mode=0o700)
        candidate = generation_dir / "candidate.pdf"
        intent_path = generation_dir / "intent.json"
        intent: dict[str, Any] = {
            "schema_version": "quasi.translation.intent/0.1",
            "generation": generation,
            "request_fingerprint": request_fp,
            "backend": backend,
            "state": "prepared",
            "task_id": None,
        }
        _write_json(intent_path, intent)

        def on_state(state: str, task_id: str | None = None) -> None:
            intent["state"] = state
            if task_id is not None:
                intent["task_id"] = task_id
            _write_json(intent_path, intent)

        backend_info: dict[str, Any] = {}
        try:
            on_state("backend_starting")
            backend_info = backend_runner(
                source,
                candidate,
                target_language,
                generation_dir,
                on_state,
            )
            on_state("backend_complete", backend_info.get("task_id"))
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            state = str(intent.get("state") or "unknown")
            creation_unknown = (
                backend == "immersive"
                and state == "creating_remote_task"
                and not intent.get("task_id")
            )
            result = run_receipt(
                "blocked" if creation_unknown else "failed",
                failure=operation_failure(
                    code=(
                        "translation.remote_task_creation_unknown"
                        if creation_unknown
                        else "translation.backend_failed"
                    ),
                    operation_key="translation.run",
                    outcome="unknown" if creation_unknown else "known",
                    message=exc,
                ),
            )
            _persist_receipt(generation_dir, result)
            return result

        manifest_replaced = False
        try:
            candidate = validate_source(candidate)
            candidate_pages = pdf_page_count(candidate)
            if candidate_pages != source_pages * 2:
                raise TranslateContractError(
                    "translation.page_count_mismatch",
                    f"backend produced {candidate_pages} pages; expected {source_pages * 2}",
                )
            on_state("postprocessing", backend_info.get("task_id"))
            fallback_manifest = root / "processing" / "chapters" / slug / "manifest.json"
            toc_entries = int(
                add_toc(
                    source_pdf=source,
                    split_pdf=candidate,
                    toc_json=toc,
                    fallback_toc_json=fallback_manifest,
                    page_side=toc_page_side,
                )
            )
            repaired = repair_tounicode(candidate)
            tounicode_receipt = {
                "status": "repaired" if repaired else "unchanged",
                "repaired_fonts": len(repaired),
                "entries": sum(int(value) for value in repaired.values()),
            }
            raw_coverage = dict(
                check_coverage(candidate, target_language=target_language)
            )
            if raw_coverage.get("detail"):
                raw_coverage["detail"] = str(raw_coverage["detail"]).replace(
                    str(candidate),
                    "the preserved staged candidate",
                )
            coverage_receipt = normalise_coverage(raw_coverage)
            if coverage_receipt["signal"] == "under_translated":
                intent["state"] = "quality_rejected"
                _write_json(intent_path, intent)
                result = run_receipt(
                    "failed",
                    failure=operation_failure(
                        code="translation.under_translated",
                        operation_key="translation.run",
                        outcome="known",
                        message=coverage_receipt["detail"],
                    ),
                    coverage_value=coverage_receipt,
                )
                _persist_receipt(generation_dir, result)
                return result
            if coverage_receipt["signal"] not in {
                "pass",
                "not_applicable",
                "insufficient_evidence",
            }:
                raise TranslateContractError(
                    "translation.coverage_invalid",
                    "translation candidate did not reach a terminal coverage signal",
                )
            if sha256_file(source) != expected_source_sha256:
                raise TranslateContractError(
                    "translation.source_changed",
                    "source changed before translation publish",
                )
            if toc and sha256_file(toc) != toc_sha:
                raise TranslateContractError(
                    "translation.toc_changed",
                    "TOC input changed before translation publish",
                )
            if output.exists() or manifest_path.exists():
                raise TranslateContractError(
                    "translation.concurrent_output",
                    "translation output appeared before publish",
                )
            candidate_sha = sha256_file(candidate)
            candidate_size = candidate.stat().st_size
            with candidate.open("rb") as handle:
                os.fsync(handle.fileno())
            payload = request_payload(
                project_root=root,
                slug=slug,
                backend=backend,
                target_language=target_language,
                input_path=source,
                input_sha256=source_sha,
                input_pages=source_pages,
                toc_path=toc,
                toc_sha256=toc_sha,
                toc_page_side=toc_page_side,
                attempt=attempt,
                config_fingerprint=config_fingerprint,
            )
            manifest_value = {
                "schema_version": MANIFEST_SCHEMA,
                "derivative_key": f"translation:paper:{slug}:{target_language}",
                **payload,
                "request_fingerprint": request_fp,
                "output_path": project_relative(output, root),
                "output_sha256": candidate_sha,
                "output_size": candidate_size,
                "output_pages": candidate_pages,
                "toc_entries": toc_entries,
                "tounicode": tounicode_receipt,
                "coverage": coverage_receipt,
            }
            manifest_temp = generation_dir / "manifest.json"
            _write_json(manifest_temp, manifest_value)
            os.link(candidate, output)
            _fsync_directory(output.parent)
            os.replace(manifest_temp, manifest_path)
            manifest_replaced = True
            _fsync_directory(manifest_path.parent)
            intent["state"] = "published"
            try:
                _write_json(intent_path, intent)
            except Exception:
                pass
            result = run_receipt(
                "succeeded",
                failure=None,
                coverage_value=coverage_receipt,
                disposition="created",
                canonical=True,
                toc_entries=toc_entries,
            )
            try:
                for child in generation_dir.iterdir():
                    child.unlink(missing_ok=True)
                generation_dir.rmdir()
            except OSError:
                pass
            return result
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            coherent_committed = manifest_replaced
            cleanup_ok = True
            if not manifest_replaced:
                try:
                    output.unlink(missing_ok=True)
                    _fsync_directory(output.parent)
                except OSError:
                    cleanup_ok = False
            unknown = coherent_committed or not cleanup_ok
            result = run_receipt(
                "blocked" if unknown else "failed",
                failure=operation_failure(
                    code=(
                        "translation.commit_outcome_unknown"
                        if unknown
                        else (
                            exc.code
                            if isinstance(exc, TranslateContractError)
                            else "translation.postcondition_failed"
                        )
                    ),
                    operation_key="translation.run",
                    outcome="unknown" if unknown else "known",
                    message=exc,
                ),
                previous=not manifest_replaced,
            )
            intent["state"] = (
                "commit_outcome_unknown" if unknown else "postcondition_failed"
            )
            try:
                _write_json(intent_path, intent)
            except Exception:
                pass
            _persist_receipt(generation_dir, result)
            return result


def contract_failure_receipt(
    *,
    command: str,
    project_root: Path,
    backend: str,
    slug: str,
    target_language: str,
    attempt: int,
    mode: str,
    toc_json: Path | None,
    toc_page_side: str,
    source_file: Path | None,
    code: str,
    message: object,
) -> dict[str, Any]:
    safe_slug = slug if SLUG_RE.fullmatch(slug) else "invalid"
    try:
        language = validate_language(target_language)
    except TranslateContractError:
        language = "zh-CN"
    paths = output_paths(
        project_root=project_root,
        slug=safe_slug,
        target_language=language,
    )
    operation = "translation.reconcile" if command == "observe" else "translation.run"
    return _receipt(
        operation=operation,
        status="failed",
        slug=slug,
        backend=backend if backend in {"immersive", "pdf2zh"} else "immersive",
        target_language=language,
        paths=paths,
        input_path=None,
        source_sha256=None,
        source_pages=0,
        request_fingerprint_value=None,
        toc_json=None,
        toc_page_side=toc_page_side if toc_page_side in {"original", "translated"} else "original",
        coverage=None,
        failure=operation_failure(
            code=code,
            operation_key=operation,
            outcome="known",
            message=message,
        ),
        attempt=attempt if attempt in {1, 2} else 1,
        mode=mode if mode in MODES else "initial",
        generation_attempt=0,
        requested_source=None,
        signal=None,
    )
