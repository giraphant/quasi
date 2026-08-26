#!/usr/bin/env python3
"""Immutable, source/profile-bound OCR generations shared by Paper and Book."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

import fitz

PROFILE_SCHEMA = "quasi.ocr.profile/0.2"
REQUEST_SCHEMA = "quasi.ocr.generation.request/0.1"
PROGRESS_SCHEMA = "quasi.ocr.generation.progress/0.1"
MANIFEST_SCHEMA = "quasi.ocr.generation.manifest/0.1"
RECEIPT_SCHEMA = "quasi.operation.ocr-generation.receipt/0.1"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
KINDS = {"paper", "book"}
PROFILE_BASE: dict[str, Any] = {
    "schema_version": PROFILE_SCHEMA,
    "language": "chi_sim+eng",
    "text_extractor": "pymupdf",
}
PROFILE_ENGINES: dict[str, dict[str, Any]] = {
    "dsocr2-text": {
        "engine_order": ["dsocr2", "tesseract"],
        "chunk_pages": 16,
    },
    "tesseract-text": {
        "engine_order": ["tesseract"],
        "chunk_pages": 32,
    },
}
VALIDATION_POLICIES = {"paper": "paper-text-v1", "book": "book-pdf-v1"}


@dataclass(frozen=True)
class EngineResult:
    engine: Literal["dsocr2", "tesseract"]
    returncode: int


Runner = Callable[[Path, Path, tuple[str, ...], str, str], EngineResult]


class OcrGenerationContractError(RuntimeError):
    """Known or unknown OCR contract failure."""

    def __init__(self, code: str, message: str, *, outcome: str = "known"):
        super().__init__(message)
        self.code = code
        self.outcome = outcome


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def validate_kind(value: str) -> str:
    if value not in KINDS:
        raise OcrGenerationContractError(
            "ocr.generation_invalid_kind", "kind must be paper or book"
        )
    return value


def resolve_profile(kind: str, profile_name: str) -> dict[str, Any]:
    validate_kind(kind)
    engine = PROFILE_ENGINES.get(profile_name)
    if engine is None:
        raise OcrGenerationContractError(
            "ocr.generation_invalid_profile",
            "profile must be dsocr2-text or tesseract-text",
        )
    return {
        **PROFILE_BASE,
        **engine,
        "name": profile_name,
        "validation_policy": VALIDATION_POLICIES[kind],
    }


def profile_fingerprint(kind: str = "paper", profile_name: str = "dsocr2-text") -> str:
    return fingerprint(resolve_profile(kind, profile_name))


def request_payload(
    *, kind: str, slug: str, source_path: str,
    source_sha256: str, profile_name: str,
) -> dict[str, Any]:
    validate_kind(kind)
    validate_slug(slug)
    validate_sha256(source_sha256, "source_sha256")
    expected_path = f"sources/{slug}.pdf"
    if source_path != expected_path:
        raise OcrGenerationContractError(
            "ocr.generation_source_role_invalid",
            f"source_path must be the exact PDF role {expected_path}",
        )
    return {
        "schema_version": REQUEST_SCHEMA,
        "material_key": f"{kind}:{slug}",
        "source_path": source_path,
        "source_sha256": source_sha256,
        "profile": resolve_profile(kind, profile_name),
    }


def generation_key(
    *, kind: str = "paper", slug: str, source_path: str | None = None,
    source_sha256: str, profile_name: str = "dsocr2-text",
) -> str:
    source_path = source_path or f"sources/{slug}.pdf"
    return fingerprint(request_payload(
        kind=kind, slug=slug, source_path=source_path,
        source_sha256=source_sha256, profile_name=profile_name,
    ))


def validate_slug(value: str) -> str:
    if not SLUG_RE.fullmatch(value):
        raise OcrGenerationContractError(
            "ocr.generation_invalid_slug",
            "slug must contain 1-80 lowercase ASCII letters, digits, or hyphens",
        )
    return value


def validate_sha256(value: str, field: str) -> str:
    if not SHA256_RE.fullmatch(value):
        raise OcrGenerationContractError(
            "ocr.generation_invalid_fingerprint",
            f"{field} must be a lowercase SHA-256 digest",
        )
    return value


def _absolute(path: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return Path(os.path.abspath(candidate))


def project_relative(path: Path, project_root: Path) -> str:
    root = project_root.expanduser().resolve()
    try:
        return _absolute(path).relative_to(root).as_posix()
    except (OSError, ValueError) as exc:
        raise OcrGenerationContractError(
            "ocr.generation_path_outside_project",
            f"path must stay inside the project root: {path}",
        ) from exc


def _regular_file(path: Path, *, field: str) -> Path:
    candidate = _absolute(path)
    try:
        mode = candidate.lstat().st_mode
    except FileNotFoundError as exc:
        raise OcrGenerationContractError(
            f"ocr.generation_{field}_missing",
            f"{field} does not exist: {candidate}",
        ) from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise OcrGenerationContractError(
            f"ocr.generation_{field}_not_regular",
            f"{field} must be a regular non-symlink file: {candidate}",
        )
    return candidate


def validate_source(path: Path, project_root: Path, slug: str) -> Path:
    source = _regular_file(path, field="source")
    expected = f"sources/{validate_slug(slug)}.pdf"
    if project_relative(source, project_root) != expected:
        raise OcrGenerationContractError(
            "ocr.generation_source_role_invalid",
            f"source must be the exact material PDF role {expected}",
        )
    return source


def pdf_page_count(path: Path) -> int:
    _regular_file(path, field="pdf")
    try:
        with fitz.open(path) as document:
            pages = document.page_count
    except Exception as exc:
        raise OcrGenerationContractError(
            "ocr.generation_pdf_invalid",
            f"failed to read PDF {path}: {exc}",
        ) from exc
    if pages <= 0:
        raise OcrGenerationContractError(
            "ocr.generation_pdf_empty",
            f"PDF has no pages: {path}",
        )
    return pages


def paths_for(
    *, project_root: Path, kind: str = "paper", slug: str, generation: str
) -> dict[str, Path]:
    root = project_root.expanduser().resolve()
    validate_kind(kind)
    validate_slug(slug)
    validate_sha256(generation, "generation_key")
    material_dir = root / "processing" / ("papers" if kind == "paper" else "chapters") / slug
    work_dir = material_dir / ".ocr-work" / generation
    generation_dir = material_dir / "ocr-generations" / generation
    return {
        "project_root": root,
        "source": root / "sources" / f"{slug}.pdf",
        "material_dir": material_dir,
        "lock": material_dir / ".ocr-generation.lock",
        "work_dir": work_dir,
        "progress": work_dir / "ocr.progress.json",
        "work_pdf": work_dir / "ocr.pdf",
        "work_text": work_dir / "ocr.txt",
        "work_manifest": work_dir / "manifest.stage.json",
        "generation_dir": generation_dir,
        "manifest": generation_dir / "manifest.json",
        "pdf": generation_dir / "ocr.pdf",
        "text": generation_dir / "ocr.txt",
    }


def public_paths(paths: dict[str, Path]) -> dict[str, str]:
    root = paths["project_root"]
    return {
        key: project_relative(path, root)
        for key, path in paths.items()
        if key not in {"project_root", "source", "material_dir", "work_pdf", "work_text", "work_manifest"}
    }


def _safe_directory(path: Path, root: Path) -> None:
    root = root.resolve()
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            current.mkdir(mode=0o700)
            mode = current.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise OcrGenerationContractError(
                "ocr.generation_output_root_unsafe",
                f"output component must be a real directory: {current}",
            )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def text_signals(path: Path) -> dict[str, Any]:
    _regular_file(path, field="recovery_pdf")
    try:
        with fitz.open(path) as document:
            page_text = [page.get_text("text") for page in document]
    except Exception as exc:
        raise OcrGenerationContractError(
            "ocr.generation_text_extraction_failed",
            f"failed to extract recovery text: {exc}",
        ) from exc
    counts = [sum(not char.isspace() for char in text) for text in page_text]
    normalized = "\n\f\n".join(text.rstrip() for text in page_text).rstrip() + "\n"
    return {
        "text": normalized,
        "pages": len(page_text),
        "text_pages": sum(count > 0 for count in counts),
        "page_non_whitespace_chars": counts,
        "chars": len(normalized),
        "non_whitespace_chars": sum(not char.isspace() for char in normalized),
    }


def validate_pdf_quality(
    path: Path, expected_pages: int, validation_policy: str = "paper-text-v1"
) -> dict[str, Any]:
    pages = pdf_page_count(path)
    if pages != expected_pages:
        raise OcrGenerationContractError(
            "ocr.generation_page_count_mismatch",
            f"OCR candidate has {pages} pages; expected {expected_pages}",
        )
    signals = text_signals(path)
    if signals["pages"] != expected_pages:
        raise OcrGenerationContractError(
            "ocr.generation_text_page_count_mismatch",
            "OCR text signals do not match the physical page count",
        )
    empty_pages = [index for index, count in enumerate(
        signals["page_non_whitespace_chars"], start=1
    ) if count <= 0]
    if validation_policy == "paper-text-v1" and empty_pages:
        rendered = ", ".join(str(page) for page in empty_pages[:16])
        raise OcrGenerationContractError(
            "ocr.generation_empty_text_pages",
            f"OCR candidate has empty text on physical pages: {rendered}",
        )
    if validation_policy not in {"paper-text-v1", "book-pdf-v1"}:
        raise OcrGenerationContractError(
            "ocr.generation_validation_policy_invalid",
            f"unknown OCR validation policy: {validation_policy}",
        )
    return signals


def _file_fact(path: Path, root: Path, *, kind: str) -> dict[str, Any]:
    fact: dict[str, Any] = {
        "path": project_relative(path, root),
        "exists": False,
        "regular": None,
        "sha256": None,
        "size": 0,
    }
    if kind == "pdf":
        fact["pages"] = 0
    elif kind == "text":
        fact["utf8"] = None
        fact["chars"] = 0
        fact["non_whitespace_chars"] = 0
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return fact
    fact["exists"] = True
    regular = stat.S_ISREG(mode) and not stat.S_ISLNK(mode)
    fact["regular"] = regular
    if not regular:
        return fact
    fact["sha256"] = sha256_file(path)
    fact["size"] = path.stat().st_size
    if kind == "pdf":
        try:
            fact["pages"] = pdf_page_count(path)
        except OcrGenerationContractError:
            fact["pages"] = 0
    elif kind == "text":
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            fact["utf8"] = False
            fact["chars"] = 0
            fact["non_whitespace_chars"] = 0
        else:
            fact["utf8"] = True
            fact["chars"] = len(text)
            fact["non_whitespace_chars"] = sum(
                not char.isspace() for char in text
            )
    return fact


def _progress_expected_keys() -> set[str]:
    return {
        "schema_version",
        "material_key",
        "generation_key",
        "profile",
        "config_fingerprint",
        "source",
        "total_pages",
        "completed_pages",
        "next_page",
        "ranges",
    }


def _validate_progress(
    path: Path,
    *,
    project_root: Path,
    kind: str,
    slug: str,
    generation: str,
    profile: dict[str, Any],
    source_path: str,
    source_sha256: str,
    source_size: int,
    source_pages: int,
) -> dict[str, Any]:
    value = _read_json(path)
    if value is None or set(value) != _progress_expected_keys():
        raise OcrGenerationContractError(
            "ocr.generation_progress_invalid",
            "OCR progress is missing, non-regular, or malformed",
        )
    expected = {
        "schema_version": PROGRESS_SCHEMA,
        "material_key": f"{kind}:{slug}",
        "generation_key": generation,
        "profile": profile,
        "config_fingerprint": fingerprint(profile),
        "source": {
            "path": source_path,
            "sha256": source_sha256,
            "size": source_size,
            "pages": source_pages,
        },
        "total_pages": source_pages,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise OcrGenerationContractError(
            "ocr.generation_progress_identity_mismatch",
            "OCR progress does not match the expected source-bound generation",
        )
    completed = value.get("completed_pages")
    next_page = value.get("next_page")
    if (
        isinstance(completed, bool)
        or not isinstance(completed, int)
        or not 0 <= completed <= source_pages
        or next_page != (completed + 1 if completed < source_pages else None)
    ):
        raise OcrGenerationContractError(
            "ocr.generation_progress_invalid",
            "OCR progress page cursor is invalid",
        )
    ranges = value.get("ranges")
    if not isinstance(ranges, list):
        raise OcrGenerationContractError(
            "ocr.generation_progress_invalid", "OCR ranges must be a list"
        )
    cursor = 1
    allowed_engines = set(profile["engine_order"])
    work_root = project_relative(path.parent, project_root)
    for item in ranges:
        if not isinstance(item, dict) or set(item) != {
            "start_page", "end_page", "engine", "path", "sha256", "pages"
        }:
            raise OcrGenerationContractError(
                "ocr.generation_progress_invalid", "OCR range record is malformed"
            )
        start, end = item.get("start_page"), item.get("end_page")
        if (
            isinstance(start, bool) or not isinstance(start, int)
            or isinstance(end, bool) or not isinstance(end, int)
            or start != cursor or end < start or end > source_pages
            or item.get("engine") not in allowed_engines
            or item.get("pages") != end - start + 1
            or not isinstance(item.get("path"), str)
            or not SHA256_RE.fullmatch(str(item.get("sha256", "")))
        ):
            raise OcrGenerationContractError(
                "ocr.generation_progress_invalid", "OCR range record is incoherent"
            )
        expected_range_path = (
            f"{work_root}/parts/part-{start:06d}-{end:06d}.{item['engine']}.pdf"
        )
        if item["path"] != expected_range_path:
            raise OcrGenerationContractError(
                "ocr.generation_progress_invalid",
                "OCR range path does not match its exact generation slot",
            )
        candidate = project_root / item["path"]
        try:
            candidate = _regular_file(candidate, field="range")
            if (
                sha256_file(candidate) != item["sha256"]
                or pdf_page_count(candidate) != item["pages"]
            ):
                raise OcrGenerationContractError(
                    "ocr.generation_progress_invalid",
                    "OCR range bytes do not match committed progress",
                )
            validate_pdf_quality(
                candidate,
                item["pages"],
                str(profile["validation_policy"]),
            )
        except OcrGenerationContractError as exc:
            if exc.code == "ocr.generation_progress_invalid":
                raise
            raise OcrGenerationContractError(
                "ocr.generation_progress_invalid",
                f"OCR range is not a valid committed part: {exc}",
            ) from exc
        cursor = end + 1
    if cursor - 1 != completed:
        raise OcrGenerationContractError(
            "ocr.generation_progress_invalid", "OCR ranges do not match completed_pages"
        )
    parts_dir = path.parent / "parts"
    try:
        parts_mode = parts_dir.lstat().st_mode
    except FileNotFoundError:
        if ranges:
            raise OcrGenerationContractError(
                "ocr.generation_progress_invalid",
                "OCR progress names committed parts but the parts directory is missing",
            )
        return value
    if stat.S_ISLNK(parts_mode) or not stat.S_ISDIR(parts_mode):
        raise OcrGenerationContractError(
            "ocr.generation_part_inventory_unknown",
            "OCR parts inventory is not a real directory",
            outcome="unknown",
        )
    expected_names = {Path(str(item["path"])).name for item in ranges}
    try:
        observed_names = {child.name for child in parts_dir.iterdir()}
    except OSError as exc:
        raise OcrGenerationContractError(
            "ocr.generation_part_inventory_unknown",
            f"failed to observe OCR parts inventory: {exc}",
            outcome="unknown",
        ) from exc
    extras = observed_names - expected_names
    if completed < source_pages:
        next_end = min(completed + int(profile["chunk_pages"]), source_pages)
        allowed_orphans = {
            _part_name(completed + 1, next_end, engine)
            for engine in profile["engine_order"]
        }
        if extras.issubset(allowed_orphans) and len(extras) <= 1:
            return value
    if extras:
        raise OcrGenerationContractError(
            "ocr.generation_part_inventory_unknown",
            "OCR parts inventory contains an unowned or ambiguous entry",
            outcome="unknown",
        )
    return value


def _expected_manifest_keys() -> set[str]:
    return {
        "schema_version",
        "material_key",
        "kind",
        "slug",
        "generation_key",
        "profile",
        "config_fingerprint",
        "source",
        "ranges",
        "recovery_pdf",
        "normalized_text",
    }


def _artifact_keys(kind: str) -> set[str]:
    common = {"path", "sha256", "size"}
    if kind == "source":
        return common | {"pages"}
    if kind == "pdf":
        return common | {"pages"}
    return common | {
        "chars",
        "non_whitespace_chars",
        "pages",
        "text_pages",
        "page_non_whitespace_chars",
        "recovery_pdf_sha256",
    }


def _manifest_ranges_match(
    ranges: object,
    *,
    paths: dict[str, Path],
    profile: dict[str, Any],
    source_pages: int,
) -> bool:
    if not isinstance(ranges, list) or not ranges:
        return False
    cursor = 1
    allowed_engines = set(profile["engine_order"])
    chunk_pages = int(profile["chunk_pages"])
    work_root = project_relative(paths["work_dir"], paths["project_root"])
    for item in ranges:
        if not isinstance(item, dict) or set(item) != {
            "start_page", "end_page", "engine", "path", "sha256", "pages"
        }:
            return False
        start = item.get("start_page")
        end = item.get("end_page")
        engine = item.get("engine")
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or start != cursor
            or end != min(start + chunk_pages - 1, source_pages)
            or engine not in allowed_engines
            or item.get("pages") != end - start + 1
            or item.get("path")
            != f"{work_root}/parts/part-{start:06d}-{end:06d}.{engine}.pdf"
            or not isinstance(item.get("sha256"), str)
            or not SHA256_RE.fullmatch(item["sha256"])
        ):
            return False
        cursor = end + 1
    return cursor - 1 == source_pages


def _manifest_matches(
    manifest: dict[str, Any],
    *,
    paths: dict[str, Path],
    kind: str,
    slug: str,
    profile: dict[str, Any],
    source_sha256: str,
    source_size: int,
    source_pages: int,
    generation: str,
) -> bool:
    if set(manifest) != _expected_manifest_keys():
        return False
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        return False
    if (
        manifest.get("material_key") != f"{kind}:{slug}"
        or manifest.get("kind") != kind
        or manifest.get("slug") != slug
    ):
        return False
    if manifest.get("generation_key") != generation:
        return False
    if manifest.get("profile") != profile:
        return False
    if manifest.get("config_fingerprint") != fingerprint(profile):
        return False
    ranges = manifest.get("ranges")
    if not _manifest_ranges_match(
        ranges,
        paths=paths,
        profile=profile,
        source_pages=source_pages,
    ):
        return False
    source = manifest.get("source")
    recovery = manifest.get("recovery_pdf")
    normalized = manifest.get("normalized_text")
    if not all(isinstance(value, dict) for value in (source, recovery, normalized)):
        return False
    if set(source) != _artifact_keys("source"):
        return False
    if set(recovery) != _artifact_keys("pdf"):
        return False
    if set(normalized) != _artifact_keys("text"):
        return False
    exact_source = {
        "path": project_relative(paths["source"], paths["project_root"]),
        "sha256": source_sha256,
        "size": source_size,
        "pages": source_pages,
    }
    if source != exact_source:
        return False
    pdf = paths["pdf"]
    text = paths["text"]
    try:
        pdf_mode = pdf.lstat().st_mode
        text_mode = text.lstat().st_mode
        if (
            stat.S_ISLNK(pdf_mode)
            or not stat.S_ISREG(pdf_mode)
            or stat.S_ISLNK(text_mode)
            or not stat.S_ISREG(text_mode)
        ):
            return False
        pdf_sha = sha256_file(pdf)
        pdf_pages = pdf_page_count(pdf)
        signals = validate_pdf_quality(
            pdf, source_pages, str(profile["validation_policy"])
        )
        text_value = text.read_text(encoding="utf-8")
        text_sha = sha256_file(text)
    except (OSError, UnicodeError, OcrGenerationContractError):
        return False
    if text_value != signals["text"]:
        return False
    exact_recovery = {
        "path": project_relative(pdf, paths["project_root"]),
        "sha256": pdf_sha,
        "size": pdf.stat().st_size,
        "pages": pdf_pages,
    }
    exact_text = {
        "path": project_relative(text, paths["project_root"]),
        "sha256": text_sha,
        "size": text.stat().st_size,
        "chars": signals["chars"],
        "non_whitespace_chars": signals["non_whitespace_chars"],
        "pages": signals["pages"],
        "text_pages": signals["text_pages"],
        "page_non_whitespace_chars": signals["page_non_whitespace_chars"],
        "recovery_pdf_sha256": pdf_sha,
    }
    return recovery == exact_recovery and normalized == exact_text


def _directory_inventory(path: Path) -> tuple[str, list[str]]:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return "missing", []
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        return "unsafe", []
    try:
        return "directory", sorted(child.name for child in path.iterdir())
    except OSError:
        return "unsafe", []


def observe_generation(
    *,
    project_root: Path,
    kind: str = "paper",
    slug: str,
    source_sha256: str,
    source_size: int,
    source_pages: int,
    generation: str,
    profile_name: str = "dsocr2-text",
) -> dict[str, Any]:
    root = project_root.expanduser().resolve()
    source_path = f"sources/{slug}.pdf"
    profile = resolve_profile(kind, profile_name)
    expected_generation = generation_key(
        kind=kind, slug=slug, source_path=source_path,
        source_sha256=source_sha256, profile_name=profile_name,
    )
    if generation != expected_generation:
        raise OcrGenerationContractError(
            "ocr.generation_generation_mismatch",
            "generation_key does not match the current source and OCR profile",
        )
    paths = paths_for(project_root=root, kind=kind, slug=slug, generation=generation)
    capsule: dict[str, Any] = {
        "state": "missing",
        "material_key": f"{kind}:{slug}",
        "kind": kind,
        "slug": slug,
        "generation_key": generation,
        "profile": profile,
        "config_fingerprint": fingerprint(profile),
        "source": {
            "path": source_path,
            "sha256": source_sha256,
            "size": source_size,
            "pages": source_pages,
        },
        "paths": public_paths(paths),
        "progress": None,
        "manifest": _file_fact(paths["manifest"], root, kind="json"),
        "recovery_pdf": _file_fact(paths["pdf"], root, kind="pdf"),
        "normalized_text": _file_fact(paths["text"], root, kind="text"),
        "failure": None,
    }

    final_kind, final_inventory = _directory_inventory(paths["generation_dir"])
    if final_kind == "unsafe":
        capsule["state"] = "unknown"
        capsule["failure"] = "ocr.generation_generation_directory_unsafe"
        return capsule
    if final_kind == "directory":
        if set(final_inventory) - {"ocr.pdf", "ocr.txt", "manifest.json"}:
            capsule["state"] = "unknown"
            capsule["failure"] = "ocr.generation_generation_inventory_unknown"
            return capsule
        manifest = _read_json(paths["manifest"])
        if manifest is None:
            capsule["state"] = "unknown"
            capsule["failure"] = "ocr.generation_uncommitted_generation"
            return capsule
        if _manifest_matches(
            manifest,
            paths=paths,
            kind=kind,
            slug=slug,
            profile=profile,
            source_sha256=source_sha256,
            source_size=source_size,
            source_pages=source_pages,
            generation=generation,
        ):
            capsule["state"] = "committed"
            return capsule
        capsule["state"] = "invalid"
        capsule["failure"] = "ocr.generation_manifest_invalid"
        return capsule

    work_kind, work_inventory = _directory_inventory(paths["work_dir"])
    if work_kind == "missing":
        return capsule
    if work_kind == "unsafe":
        capsule["state"] = "unknown"
        capsule["failure"] = "ocr.generation_work_directory_unsafe"
        return capsule
    allowed = {
        "ocr.progress.json",
        "parts",
        "ocr.pdf",
        "ocr.txt",
        "manifest.stage.json",
    }
    if set(work_inventory) - allowed:
        capsule["state"] = "unknown"
        capsule["failure"] = "ocr.generation_work_inventory_unknown"
        return capsule
    progress_exists = paths["progress"].exists() or paths["progress"].is_symlink()
    work_pdf_exists = paths["work_pdf"].exists() or paths["work_pdf"].is_symlink()
    work_text_exists = paths["work_text"].exists() or paths["work_text"].is_symlink()
    if progress_exists:
        if work_pdf_exists or work_text_exists:
            capsule["state"] = "invalid"
            capsule["failure"] = "ocr.generation_progress_output_conflict"
            return capsule
        try:
            progress = _validate_progress(
                paths["progress"],
                project_root=root,
                kind=kind,
                slug=slug,
                generation=generation,
                profile=profile,
                source_path=source_path,
                source_sha256=source_sha256,
                source_size=source_size,
                source_pages=source_pages,
            )
        except OcrGenerationContractError as exc:
            capsule["state"] = "unknown" if exc.outcome == "unknown" else "invalid"
            capsule["failure"] = exc.code
            return capsule
        capsule["state"] = "in_progress"
        capsule["progress"] = {
            "completed_pages": progress["completed_pages"],
            "total_pages": progress["total_pages"],
            "next_page": progress["next_page"],
            "ranges": progress["ranges"],
        }
        return capsule
    if work_pdf_exists:
        try:
            signals = validate_pdf_quality(
                paths["work_pdf"], source_pages, str(profile["validation_policy"])
            )
            if work_text_exists:
                text = _regular_file(paths["work_text"], field="work_text").read_text(
                    encoding="utf-8"
                )
                if text != signals["text"]:
                    raise OcrGenerationContractError(
                        "ocr.generation_work_text_mismatch",
                        "private OCR text does not match the private recovery PDF",
                    )
        except (OSError, UnicodeError, OcrGenerationContractError) as exc:
            capsule["state"] = "invalid"
            capsule["failure"] = (
                exc.code if isinstance(exc, OcrGenerationContractError) else "ocr.generation_work_invalid"
            )
            return capsule
        capsule["state"] = "in_progress"
        capsule["progress"] = {
            "completed_pages": source_pages,
            "total_pages": source_pages,
            "next_page": None,
            "ranges": [],
        }
        return capsule
    capsule["state"] = "unknown"
    capsule["failure"] = "ocr.generation_work_inventory_incomplete"
    return capsule


def _failure(code: str, message: object, *, outcome: str = "known") -> dict[str, Any]:
    return {
        "code": code,
        "outcome": outcome,
        "retryable": code == "ocr.generation_locked",
        "message": str(message)[:4000],
    }


def _receipt(
    *,
    status: str,
    disposition: str | None,
    paths: dict[str, Path],
    kind: str,
    slug: str,
    generation: str,
    profile: dict[str, Any],
    source_sha256: str,
    source_size: int,
    source_pages: int,
    state: str,
    progress: dict[str, Any] | None,
    failure: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": RECEIPT_SCHEMA,
        "key": f"{kind}.ocr",
        "effect": "writer",
        "status": status,
        "disposition": disposition,
        "material_key": f"{kind}:{slug}",
        "kind": kind,
        "slug": slug,
        "generation_key": generation,
        "profile": profile,
        "config_fingerprint": fingerprint(profile),
        "source": {
            "path": f"sources/{slug}.pdf",
            "sha256": source_sha256,
            "size": source_size,
            "pages": source_pages,
        },
        "paths": public_paths(paths),
        "state": state,
        "progress": progress,
        "artifacts": [
            _file_fact(paths["pdf"], paths["project_root"], kind="pdf"),
            _file_fact(paths["text"], paths["project_root"], kind="text"),
            _file_fact(paths["manifest"], paths["project_root"], kind="json"),
        ],
        "failure": failure,
    }


@contextlib.contextmanager
def generation_lock(path: Path, root: Path) -> Iterator[None]:
    _safe_directory(path.parent, root)
    if path.exists() or path.is_symlink():
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise OcrGenerationContractError(
                "ocr.generation_lock_unsafe", f"failed to inspect OCR lock: {exc}"
            ) from exc
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise OcrGenerationContractError(
                "ocr.generation_lock_unsafe", "OCR generation lock must be a regular file"
            )
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(str(path), flags, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise OcrGenerationContractError(
                "ocr.generation_locked", "another OCR generation transaction holds the exact lock"
            ) from exc
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _engine_runner(extract_dir: Path) -> Runner:
    def run(
        source_slice: Path,
        candidate: Path,
        engine_order: tuple[str, ...],
        language: str,
        validation_policy: str,
    ) -> EngineResult:
        with fitz.open(source_slice) as document:
            expected_pages = document.page_count
        last_rc = 1
        for engine in engine_order:
            candidate.unlink(missing_ok=True)
            if engine == "dsocr2":
                command = [
                    sys.executable, str(extract_dir / "ocr_dsocr2.py"),
                    str(source_slice), str(candidate),
                ]
            elif engine == "tesseract":
                command = [
                    "bash", str(extract_dir / "ocr_pdf.sh"),
                    str(source_slice), str(candidate), language,
                ]
            else:  # closed profiles make this unreachable
                raise OcrGenerationContractError(
                    "ocr.generation_engine_invalid", f"unknown OCR engine: {engine}"
                )
            last_rc = subprocess.call(command, stdout=sys.stderr, stderr=sys.stderr)
            if last_rc != 0:
                sys.stderr.write(f"[extract] {engine} unavailable/failed.\n")
                continue
            try:
                validate_pdf_quality(candidate, expected_pages, validation_policy)
            except OcrGenerationContractError as exc:
                sys.stderr.write(
                    f"[extract] {engine} quality rejection ({exc.code}).\n"
                )
                continue
            return EngineResult(engine=engine, returncode=0)  # type: ignore[arg-type]
        candidate.unlink(missing_ok=True)
        return EngineResult(
            engine=engine_order[-1], returncode=last_rc or 1  # type: ignore[arg-type]
        )

    return run


def _part_name(start: int, end: int, engine: str) -> str:
    return f"part-{start:06d}-{end:06d}.{engine}.pdf"


def _slice_pdf(source: Path, target: Path, start: int, end: int) -> None:
    with fitz.open(source) as document:
        sliced = fitz.open()
        sliced.insert_pdf(document, from_page=start - 1, to_page=end - 1)
        sliced.save(target)
        sliced.close()


def _merge_parts(records: list[dict[str, Any]], root: Path, output: Path) -> None:
    merged = fitz.open()
    try:
        for record in records:
            part = root / str(record["path"])
            with fitz.open(part) as document:
                merged.insert_pdf(document)
        merged.save(output)
    finally:
        merged.close()


def _initial_progress(
    *, kind: str, slug: str, generation: str, profile: dict[str, Any],
    source_path: str, source_sha256: str, source_size: int, source_pages: int,
) -> dict[str, Any]:
    return {
        "schema_version": PROGRESS_SCHEMA,
        "material_key": f"{kind}:{slug}",
        "generation_key": generation,
        "profile": profile,
        "config_fingerprint": fingerprint(profile),
        "source": {
            "path": source_path, "sha256": source_sha256,
            "size": source_size, "pages": source_pages,
        },
        "total_pages": source_pages,
        "completed_pages": 0,
        "next_page": 1,
        "ranges": [],
    }


def _advance_one_range(
    *, paths: dict[str, Path], source: Path, progress: dict[str, Any],
    profile: dict[str, Any], runner: Runner,
) -> dict[str, Any]:
    total = int(progress["total_pages"])
    start = int(progress["next_page"])
    end = min(start + int(profile["chunk_pages"]) - 1, total)
    parts_dir = paths["work_dir"] / "parts"
    _safe_directory(parts_dir, paths["project_root"])
    existing = sorted(parts_dir.glob(f"part-{start:06d}-{end:06d}.*.pdf"))
    if len(existing) > 1:
        raise OcrGenerationContractError(
            "ocr.generation_orphan_ambiguous", "multiple exact orphan OCR parts exist",
            outcome="unknown",
        )
    if existing:
        part = existing[0]
        engine = part.name.rsplit(".", 2)[-2]
        if engine not in profile["engine_order"]:
            raise OcrGenerationContractError(
                "ocr.generation_orphan_invalid", "orphan OCR part engine is invalid"
            )
        validate_pdf_quality(part, end - start + 1, str(profile["validation_policy"]))
    else:
        stage_dir = Path(tempfile.mkdtemp(prefix=".range-", dir=str(paths["work_dir"])))
        try:
            source_slice = stage_dir / "source.pdf"
            candidate = stage_dir / "candidate.pdf"
            _slice_pdf(source, source_slice, start, end)
            result = runner(
                source_slice, candidate, tuple(profile["engine_order"]),
                str(profile["language"]), str(profile["validation_policy"]),
            )
            if result.returncode != 0:
                raise OcrGenerationContractError(
                    "ocr.generation_engine_failed",
                    f"OCR engines exited {result.returncode}",
                )
            validate_pdf_quality(
                candidate, end - start + 1, str(profile["validation_policy"])
            )
            engine = result.engine
            part = parts_dir / _part_name(start, end, engine)
            if part.exists() or part.is_symlink():
                raise OcrGenerationContractError(
                    "ocr.generation_part_conflict", "OCR part appeared before publish",
                    outcome="unknown",
                )
            os.replace(candidate, part)
            _fsync_directory(parts_dir)
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)
    record = {
        "start_page": start,
        "end_page": end,
        "engine": engine,
        "path": project_relative(part, paths["project_root"]),
        "sha256": sha256_file(part),
        "pages": end - start + 1,
    }
    updated = {**progress}
    updated["ranges"] = [*progress["ranges"], record]
    updated["completed_pages"] = end
    updated["next_page"] = end + 1 if end < total else None
    _write_atomic(paths["progress"], canonical_json(updated) + b"\n")
    return updated


def _build_manifest(
    *,
    paths: dict[str, Path],
    kind: str,
    slug: str,
    generation: str,
    profile: dict[str, Any],
    ranges: list[dict[str, Any]],
    source_sha256: str,
    source_size: int,
    source_pages: int,
    signals: dict[str, Any],
) -> dict[str, Any]:
    pdf_sha = sha256_file(paths["work_pdf"])
    return {
        "schema_version": MANIFEST_SCHEMA,
        "material_key": f"{kind}:{slug}",
        "kind": kind,
        "slug": slug,
        "generation_key": generation,
        "profile": profile,
        "config_fingerprint": fingerprint(profile),
        "source": {
            "path": f"sources/{slug}.pdf",
            "sha256": source_sha256,
            "size": source_size,
            "pages": source_pages,
        },
        "ranges": ranges,
        "recovery_pdf": {
            "path": project_relative(paths["pdf"], paths["project_root"]),
            "sha256": pdf_sha,
            "size": paths["work_pdf"].stat().st_size,
            "pages": source_pages,
        },
        "normalized_text": {
            "path": project_relative(paths["text"], paths["project_root"]),
            "sha256": sha256_file(paths["work_text"]),
            "size": paths["work_text"].stat().st_size,
            "chars": signals["chars"],
            "non_whitespace_chars": signals["non_whitespace_chars"],
            "pages": signals["pages"],
            "text_pages": signals["text_pages"],
            "page_non_whitespace_chars": signals["page_non_whitespace_chars"],
            "recovery_pdf_sha256": pdf_sha,
        },
    }


def _publish(
    *,
    paths: dict[str, Path],
    manifest: dict[str, Any],
) -> None:
    root = paths["project_root"]
    _safe_directory(paths["generation_dir"].parent, root)
    if paths["generation_dir"].exists() or paths["generation_dir"].is_symlink():
        raise OcrGenerationContractError(
            "ocr.generation_concurrent_generation",
            "generation directory appeared before publish",
            outcome="unknown",
        )
    _write_atomic(paths["work_manifest"], canonical_json(manifest) + b"\n")
    paths["generation_dir"].mkdir(mode=0o700)
    try:
        os.link(paths["work_pdf"], paths["pdf"])
        os.link(paths["work_text"], paths["text"])
        _fsync_directory(paths["generation_dir"])
        os.link(paths["work_manifest"], paths["manifest"])
        _fsync_directory(paths["generation_dir"])
    except Exception as exc:
        raise OcrGenerationContractError(
            "ocr.generation_commit_outcome_unknown",
            f"generation publication did not reach a proven manifest-last outcome: {exc}",
            outcome="unknown",
        ) from exc


def _cleanup_work(paths: dict[str, Path]) -> None:
    try:
        shutil.rmtree(paths["work_dir"])
        parent = paths["work_dir"].parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass


def run_transaction(
    *,
    project_root: Path,
    kind: str = "paper",
    slug: str,
    source_file: Path,
    expected_source_sha256: str,
    expected_generation_key: str,
    profile_name: str = "dsocr2-text",
    extract_dir: Path | None = None,
    runner: Runner | None = None,
) -> dict[str, Any]:
    root = project_root.expanduser().resolve()
    kind = validate_kind(kind)
    slug = validate_slug(slug)
    profile = resolve_profile(kind, profile_name)
    source_path = f"sources/{slug}.pdf"
    expected_source_sha256 = validate_sha256(
        expected_source_sha256, "expected_source_sha256"
    )
    expected_generation_key = validate_sha256(
        expected_generation_key, "generation_key"
    )
    source = validate_source(source_file, root, slug)
    source_sha = sha256_file(source)
    source_size = source.stat().st_size
    source_pages = pdf_page_count(source)
    paths = paths_for(
        project_root=root, kind=kind, slug=slug, generation=expected_generation_key
    )

    def result(
        status: str,
        disposition: str | None,
        state: str,
        *,
        progress: dict[str, Any] | None = None,
        failure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _receipt(
            status=status,
            disposition=disposition,
            paths=paths,
            kind=kind,
            slug=slug,
            generation=expected_generation_key,
            profile=profile,
            source_sha256=source_sha,
            source_size=source_size,
            source_pages=source_pages,
            state=state,
            progress=progress,
            failure=failure,
        )

    if source_sha != expected_source_sha256:
        return result(
            "failed",
            None,
            "invalid",
            failure=_failure(
                "ocr.generation_source_fingerprint_mismatch",
                "source SHA-256 did not match expected_source_sha256",
            ),
        )
    calculated = generation_key(
        kind=kind, slug=slug, source_path=source_path,
        source_sha256=source_sha, profile_name=profile_name,
    )
    if calculated != expected_generation_key:
        return result(
            "failed",
            None,
            "invalid",
            failure=_failure(
                "ocr.generation_generation_mismatch",
                "generation_key did not match the exact source and OCR profile",
            ),
        )

    try:
        with generation_lock(paths["lock"], root):
            locked_sha = sha256_file(source)
            if locked_sha != expected_source_sha256:
                source_sha = locked_sha
                return result(
                    "failed",
                    None,
                    "invalid",
                    failure=_failure(
                        "ocr.generation_source_changed",
                        "source changed while waiting for the OCR generation lock",
                    ),
                )
            observed = observe_generation(
                project_root=root,
                kind=kind,
                slug=slug,
                source_sha256=expected_source_sha256,
                source_size=source_size,
                source_pages=source_pages,
                generation=expected_generation_key,
                profile_name=profile_name,
            )
            if observed["state"] == "committed":
                return result("succeeded", "reconciled", "committed")
            if observed["state"] in {"invalid", "unknown"}:
                return result(
                    "blocked",
                    None,
                    observed["state"],
                    progress=observed["progress"],
                    failure=_failure(
                        str(observed["failure"]),
                        "existing OCR generation evidence is not safe to overwrite",
                        outcome="unknown" if observed["state"] == "unknown" else "known",
                    ),
                )

            _safe_directory(paths["work_dir"], root)
            selected_runner = runner or _engine_runner(
                extract_dir or Path(__file__).resolve().parent
            )
            if paths["progress"].exists() or paths["progress"].is_symlink():
                progress = _validate_progress(
                    paths["progress"], project_root=root,
                    kind=kind, slug=slug,
                    generation=expected_generation_key, profile=profile,
                    source_path=source_path, source_sha256=source_sha,
                    source_size=source_size, source_pages=source_pages,
                )
            else:
                progress = _initial_progress(
                    kind=kind, slug=slug, generation=expected_generation_key,
                    profile=profile, source_path=source_path,
                    source_sha256=source_sha, source_size=source_size,
                    source_pages=source_pages,
                )
                _write_atomic(paths["progress"], canonical_json(progress) + b"\n")
            if progress["next_page"] is not None:
                progress = _advance_one_range(
                    paths=paths, source=source, progress=progress,
                    profile=profile, runner=selected_runner,
                )
            if progress["completed_pages"] < source_pages:
                return result(
                    "succeeded",
                    "partial",
                    "in_progress",
                    progress={
                        "completed_pages": progress["completed_pages"],
                        "total_pages": progress["total_pages"],
                        "next_page": progress["next_page"],
                        "ranges": progress["ranges"],
                    },
                )

            if not paths["work_pdf"].exists():
                _merge_parts(progress["ranges"], root, paths["work_pdf"])
                _fsync_directory(paths["work_dir"])
            signals = validate_pdf_quality(
                paths["work_pdf"], source_pages, str(profile["validation_policy"])
            )
            text_bytes = str(signals["text"]).encode("utf-8")
            if paths["work_text"].exists() or paths["work_text"].is_symlink():
                work_text = _regular_file(paths["work_text"], field="work_text")
                if work_text.read_bytes() != text_bytes:
                    return result(
                        "blocked",
                        None,
                        "invalid",
                        failure=_failure(
                            "ocr.generation_work_text_mismatch",
                            "existing private OCR text does not match the recovery PDF",
                        ),
                    )
            else:
                _write_atomic(paths["work_text"], text_bytes)
            if sha256_file(source) != expected_source_sha256:
                return result(
                    "failed",
                    None,
                    "invalid",
                    failure=_failure(
                        "ocr.generation_source_changed",
                        "source changed before OCR generation publication",
                    ),
                )
            manifest = _build_manifest(
                paths=paths,
                kind=kind,
                slug=slug,
                generation=expected_generation_key,
                profile=profile,
                ranges=progress["ranges"],
                source_sha256=expected_source_sha256,
                source_size=source_size,
                source_pages=source_pages,
                signals=signals,
            )
            _publish(paths=paths, manifest=manifest)
            committed = observe_generation(
                project_root=root,
                kind=kind,
                slug=slug,
                source_sha256=expected_source_sha256,
                source_size=source_size,
                source_pages=source_pages,
                generation=expected_generation_key,
                profile_name=profile_name,
            )
            if committed["state"] != "committed":
                return result(
                    "blocked",
                    None,
                    committed["state"],
                    failure=_failure(
                        str(committed["failure"] or "ocr.generation_commit_unproven"),
                        "published OCR generation did not pass strict validation",
                        outcome="unknown",
                    ),
                )
            receipt = result("succeeded", "created", "committed")
            _cleanup_work(paths)
            return receipt
    except OcrGenerationContractError as exc:
        return result(
            "blocked" if exc.outcome == "unknown" or exc.code == "ocr.generation_locked" else "failed",
            None,
            "unknown" if exc.outcome == "unknown" else "invalid",
            failure=_failure(exc.code, exc, outcome=exc.outcome),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return result(
            "failed",
            None,
            "invalid",
            failure=_failure("ocr.generation_step_failed", exc),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="quasi-extract ocr-generation",
        description="Advance one immutable source/profile-bound OCR page range.",
    )
    parser.add_argument("--kind", required=True, choices=sorted(KINDS))
    parser.add_argument("--slug", required=True)
    parser.add_argument("--source-file", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--generation-key", required=True)
    parser.add_argument("--profile", required=True, choices=sorted(PROFILE_ENGINES))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt = run_transaction(
            project_root=Path.cwd(),
            kind=args.kind,
            slug=args.slug,
            source_file=Path(args.source_file),
            expected_source_sha256=args.expected_source_sha256,
            expected_generation_key=args.generation_key,
            profile_name=args.profile,
        )
    except OcrGenerationContractError as exc:
        receipt = {
            "schema_version": RECEIPT_SCHEMA,
            "key": f"{args.kind}.ocr",
            "effect": "writer",
            "status": "failed",
            "disposition": None,
            "material_key": f"{args.kind}:{args.slug}",
            "kind": args.kind,
            "slug": args.slug,
            "generation_key": args.generation_key,
            "profile": None,
            "config_fingerprint": None,
            "source": None,
            "paths": None,
            "state": "invalid",
            "progress": None,
            "artifacts": [],
            "failure": _failure(exc.code, exc, outcome=exc.outcome),
        }
    if args.json:
        print(json.dumps(receipt, ensure_ascii=False))
    elif receipt["status"] == "succeeded":
        print(
            f"OCR generation {receipt['disposition']}: {receipt['generation_key']}"
        )
    else:
        failure = receipt.get("failure") or {}
        print(f"quasi-extract ocr-generation: {failure.get('message', 'failed')}", file=sys.stderr)
    return 0 if receipt["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
