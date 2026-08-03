#!/usr/bin/env python3
"""Report which canonical material workflow stages are proven on disk.

This command deliberately observes only project files.  It neither replays a
workflow nor interprets a prior run receipt: the artifact layout itself is the
admission state for the next deterministic stage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))
from scripts.schemas.pipeline import PIPELINE  # noqa: E402


STATUS_VERSION = "quasi.status/0.1"
SCAN_VERSION = "quasi.status-scan/0.1"
ERROR_VERSION = "quasi.status.error/0.1"
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")
CHAPTER_SLOT = re.compile(r"\d{2,3}[a-z]{0,2}\Z")
MEDIA_EXTENSIONS = (
    "mov",
    "mp4",
    "m4v",
    "mkv",
    "webm",
    "m4a",
    "wav",
    "mp3",
    "aac",
    "flac",
    "aiff",
    "aif",
    "ogg",
    "opus",
)


class InvocationError(ValueError):
    """A command-line error that must still produce a JSON object."""


class StatusArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InvocationError(message)


@dataclass(frozen=True)
class FileObservation:
    """Whether a caller-named filesystem artifact was seen and is usable."""

    present: bool
    usable: bool


def project_root() -> Path:
    """Use the same project-root precedence as quasi's agent-facing shims."""

    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def artifact_path(
    root: Path,
    kind: str,
    stage_name: str,
    role: str,
    **values: str,
) -> Path:
    """Expand one canonical pipeline artifact template under ``root``."""

    stage_definition = next(
        item
        for item in PIPELINE[kind]["stages"]
        if item["stage"] == stage_name
    )
    return root / stage_definition["artifacts"][role].format(**values)


def relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def observe_file(path: Path, *, nonempty: bool) -> FileObservation:
    """Safely inspect one file without following a failed read as success."""

    try:
        path.lstat()
    except OSError:
        return FileObservation(present=False, usable=False)

    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            return FileObservation(present=True, usable=False)
        if nonempty and info.st_size <= 0:
            return FileObservation(present=True, usable=False)
        # A metadata-only stat cannot distinguish a readable file from an
        # unreadable artifact.  One byte is enough for ordinary file stages.
        with path.open("rb") as handle:
            handle.read(1)
    except OSError:
        return FileObservation(present=True, usable=False)
    return FileObservation(present=True, usable=True)


def evidence(root: Path, paths: Iterable[Path]) -> list[str]:
    """Return exactly the named artifact paths that are present on disk."""

    found: list[str] = []
    for path in paths:
        try:
            path.lstat()
        except OSError:
            continue
        found.append(relative(root, path))
    return found


def stage(name: str, complete: bool | None, found: Iterable[str]) -> dict[str, Any]:
    return {"stage": name, "complete": complete, "evidence": list(found)}


def parse_frontmatter(path: Path) -> dict[str, Any] | None:
    """Read a YAML mapping enclosed by Markdown frontmatter fences."""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    closing = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() in {"---", "..."}
        ),
        None,
    )
    if closing is None:
        return None
    try:
        value = yaml.safe_load("\n".join(lines[1:closing]))
    except yaml.YAMLError:
        return None
    return value if isinstance(value, dict) else None


def observed_frontmatter(
    root: Path, path: Path
) -> tuple[bool, list[str], dict[str, Any] | None]:
    observation = observe_file(path, nonempty=True)
    found = evidence(root, [path])
    parsed = parse_frontmatter(path) if observation.usable else None
    return parsed is not None, found, parsed


def frontmatter_identity(frontmatter: dict[str, Any] | None) -> dict[str, Any] | None:
    """Project only canonical identity fields, preserving parsed disk values."""

    if frontmatter is None:
        return None
    fields = ("title", "authors", "name", "year")
    projected: dict[str, Any] = {}
    for field in fields:
        if field not in frontmatter:
            continue
        value = frontmatter[field]
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError):
            projected[field] = {
                "invalid_yaml_type": type(value).__name__,
                "value": str(value),
            }
        else:
            projected[field] = value
    return projected


def safe_chapter_filename(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or "/" in value
        or "\\" in value
        or ".." in value
    ):
        return None
    return value


def chapter_refs(
    root: Path, slug: str
) -> tuple[bool, list[dict[str, str]], list[str]]:
    """Load the committed Book chapter inventory, without accepting guesses.

    The workflow's exact chapter join is:
    ``processing/chapters/{slug}/{filename}`` ->
    ``vault/books/{slug}/ch{slot}-{chapter-slug}.md``.
    """

    chapter_root = artifact_path(
        root, "book", "prepare", "outputDir", slug=slug
    )
    manifest = artifact_path(root, "book", "prepare", "manifest", slug=slug)
    manifest_found = evidence(root, [manifest])
    observation = observe_file(manifest, nonempty=True)
    if not observation.usable:
        return False, [], manifest_found
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False, [], manifest_found
    rows = payload.get("chapters") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return False, [], manifest_found

    result: list[dict[str, str]] = []
    seen_slots: set[str] = set()
    seen_filenames: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            return False, [], manifest_found
        slot = row.get("slot")
        chapter_slug = row.get("slug")
        filename = safe_chapter_filename(row.get("filename"))
        if (
            not isinstance(slot, str)
            or CHAPTER_SLOT.fullmatch(slot) is None
            or not isinstance(chapter_slug, str)
            or SLUG.fullmatch(chapter_slug) is None
            or filename is None
            or slot in seen_slots
            or filename in seen_filenames
        ):
            return False, [], manifest_found
        seen_slots.add(slot)
        seen_filenames.add(filename)
        result.append({"slot": slot, "slug": chapter_slug, "filename": filename})
    return True, result, manifest_found


def paper_status(root: Path, slug: str, *, include_identity: bool = False) -> dict[str, Any]:
    source = artifact_path(root, "paper", "acquire", "output", slug=slug)
    source_text = artifact_path(
        root, "paper", "prepare", "normalized", slug=slug
    )
    ocr_source = artifact_path(
        root, "paper", "prepare", "recoverySource", slug=slug
    )
    ocr_text = artifact_path(
        root, "paper", "prepare", "recoveryText", slug=slug
    )
    canonical = artifact_path(root, "paper", "analyse", "output", slug=slug)

    acquire = observe_file(source, nonempty=True)
    prepared = [source_text, ocr_text]
    prepared_observations = [observe_file(path, nonempty=True) for path in prepared]
    analyse_complete, analyse_evidence, canonical_frontmatter = observed_frontmatter(
        root, canonical
    )
    observations = {
        "acquire": (acquire.usable, evidence(root, [source])),
        "prepare": (
            any(item.usable for item in prepared_observations),
            evidence(root, prepared),
        ),
        "analyse": (analyse_complete, analyse_evidence),
    }
    stages = [
        stage(item["stage"], *observations[item["stage"]])
        for item in PIPELINE["paper"]["stages"]
        if item["stage"] in observations
    ]
    next_stage = first_incomplete(stages)
    if next_stage == "acquire":
        refs: dict[str, Any] = {"outputs": [relative(root, source)]}
    elif next_stage == "prepare":
        refs = {
            "input": relative(root, source),
            "outputs": [
                relative(root, source_text),
                relative(root, ocr_source),
                relative(root, ocr_text),
            ],
        }
    elif next_stage == "analyse":
        refs = {
            "inputs": [
                relative(root, path)
                for path, item in zip(prepared, prepared_observations)
                if item.usable
            ],
            "output": relative(root, canonical),
        }
    else:
        refs = {}
    return status_payload(
        "paper",
        slug,
        stages,
        next_stage,
        refs,
        identity=(
            frontmatter_identity(canonical_frontmatter)
            if include_identity and analyse_complete
            else None
        ),
        include_identity=include_identity,
    )


def book_status(root: Path, slug: str, *, include_identity: bool = False) -> dict[str, Any]:
    source_epub = artifact_path(
        root, "book", "prepare", "source", slug=slug, format="epub"
    )
    source_pdf = artifact_path(
        root, "book", "prepare", "source", slug=slug, format="pdf"
    )
    sources = [source_epub, source_pdf]
    source_observations = [observe_file(path, nonempty=True) for path in sources]
    inventory_valid, chapters, manifest_evidence = chapter_refs(root, slug)

    chapter_root = artifact_path(
        root, "book", "prepare", "outputDir", slug=slug
    )
    chapter_inputs = [chapter_root / item["filename"] for item in chapters]
    input_observations = [observe_file(path, nonempty=True) for path in chapter_inputs]
    prepare_evidence = manifest_evidence + evidence(root, chapter_inputs)
    prepare_complete = inventory_valid and all(
        item.usable for item in input_observations
    )

    overview = artifact_path(root, "book", "synthesise", "output", slug=slug)
    book_dir = overview.parent
    chapter_outputs = [
        book_dir / f"ch{item['slot']}-{item['slug']}.md" for item in chapters
    ]
    chapter_frontmatter = [observed_frontmatter(root, path) for path in chapter_outputs]
    analyse_complete = inventory_valid and all(
        complete for complete, _found, _frontmatter in chapter_frontmatter
    )
    synthesise_complete, synthesise_evidence, overview_frontmatter = (
        observed_frontmatter(root, overview)
    )

    observations = {
        "acquire": (
            any(item.usable for item in source_observations),
            evidence(root, sources),
        ),
        "prepare": (prepare_complete, prepare_evidence),
        "analyse": (analyse_complete, evidence(root, chapter_outputs)),
        "synthesise": (synthesise_complete, synthesise_evidence),
    }
    stages = [
        stage(item["stage"], *observations[item["stage"]])
        for item in PIPELINE["book"]["stages"]
        if item["stage"] in observations
    ]
    next_stage = first_incomplete(stages)
    if next_stage == "acquire":
        refs: dict[str, Any] = {"outputs": [relative(root, path) for path in sources]}
    elif next_stage == "prepare":
        refs = {
            "inputs": [
                relative(root, path)
                for path, item in zip(sources, source_observations)
                if item.usable
            ],
            "output_dir": relative(root, chapter_root),
            "manifest": relative(
                root,
                artifact_path(root, "book", "prepare", "manifest", slug=slug),
            ),
        }
    elif next_stage == "analyse":
        refs = {
            "manifest": relative(
                root,
                artifact_path(root, "book", "prepare", "manifest", slug=slug),
            ),
            "inputs": [relative(root, path) for path in chapter_inputs],
            "outputs": [relative(root, path) for path in chapter_outputs],
        }
    elif next_stage == "synthesise":
        refs = {
            "inputs": [relative(root, path) for path in chapter_outputs],
            "output": relative(root, overview),
        }
    else:
        refs = {}
    return status_payload(
        "book",
        slug,
        stages,
        next_stage,
        refs,
        identity=(
            frontmatter_identity(overview_frontmatter)
            if include_identity and synthesise_complete
            else None
        ),
        include_identity=include_identity,
    )


def talk_transcripts(root: Path, slug: str) -> list[Path]:
    directory = artifact_path(
        root, "talk", "prepare", "processingDir", slug=slug
    )
    try:
        entries = sorted(directory.iterdir(), key=lambda item: item.name)
    except OSError:
        return []
    return [
        path
        for path in entries
        if path.name.startswith("transcript.") and path.name != "transcript.json"
    ]


def talk_status(root: Path, slug: str, *, include_identity: bool = False) -> dict[str, Any]:
    sources = [root / "sources" / f"{slug}.{extension}" for extension in MEDIA_EXTENSIONS]
    source_observations = [observe_file(path, nonempty=True) for path in sources]
    transcripts = talk_transcripts(root, slug)
    transcript_observations = [
        observe_file(path, nonempty=True) for path in transcripts
    ]
    processing_dir = artifact_path(
        root, "talk", "prepare", "processingDir", slug=slug
    )
    canonical = artifact_path(root, "talk", "analyse", "output", slug=slug)
    canonical_complete, canonical_evidence, canonical_frontmatter = (
        observed_frontmatter(root, canonical)
    )

    prepare_evidence = evidence(root, sources) + evidence(root, transcripts)
    observations = {
        "prepare": (
            any(item.usable for item in transcript_observations),
            prepare_evidence,
        ),
        "analyse": (canonical_complete, canonical_evidence),
    }
    stages = [
        stage(item["stage"], *observations[item["stage"]])
        for item in PIPELINE["talk"]["stages"]
        if item["stage"] in observations
    ]
    next_stage = first_incomplete(stages)
    if next_stage == "prepare":
        refs = {
            "inputs": [
                relative(root, path)
                for path, item in zip(sources, source_observations)
                if item.usable
            ],
            "output_dir": relative(root, processing_dir),
        }
    elif next_stage == "analyse":
        refs = {
            "inputs": [
                relative(root, path)
                for path, item in zip(transcripts, transcript_observations)
                if item.usable
            ],
            "output": relative(root, canonical),
        }
    else:
        refs = {}
    return status_payload(
        "talk",
        slug,
        stages,
        next_stage,
        refs,
        identity=(
            frontmatter_identity(canonical_frontmatter)
            if include_identity and canonical_complete
            else None
        ),
        include_identity=include_identity,
    )


def translation_status(root: Path, slug: str) -> dict[str, Any]:
    source = artifact_path(root, "translation", "prepare", "source", slug=slug)
    source_observation = observe_file(source, nonempty=True)
    derivative_pattern = artifact_path(
        root, "translation", "prepare", "derivatives", slug=slug
    )
    try:
        derivatives = sorted(
            derivative_pattern.parent.glob(derivative_pattern.name),
            key=lambda path: path.name,
        )
    except OSError:
        derivatives = []
    derivative_observations = [
        observe_file(path, nonempty=True) for path in derivatives
    ]
    observations = {
        "prepare": (
            any(item.usable for item in derivative_observations),
            evidence(root, derivatives),
        )
    }
    stages = [
        # Acquire is an observation view of Prepare's source precondition, not
        # a dispatchable Translation pipeline stage.
        stage(
            "acquire",
            source_observation.usable,
            evidence(root, [source]),
        ),
        *(
            stage(item["stage"], *observations[item["stage"]])
            for item in PIPELINE["translation"]["stages"]
            if item["stage"] in observations
        ),
    ]
    next_stage = first_incomplete(stages)
    refs: dict[str, Any] = {
        "source": relative(root, source),
        "derivatives": [relative(root, path) for path in derivatives],
    }
    return status_payload("translation", slug, stages, next_stage, refs)


def first_incomplete(stages: Iterable[dict[str, Any]]) -> str | None:
    return next(
        (item["stage"] for item in stages if item["complete"] is False),
        None,
    )


def status_payload(
    kind: str,
    slug: str,
    stages: list[dict[str, Any]],
    next_stage: str | None,
    refs: dict[str, Any],
    *,
    identity: dict[str, Any] | None = None,
    include_identity: bool = False,
) -> dict[str, Any]:
    payload = {
        "schema_version": STATUS_VERSION,
        "kind": kind,
        "slug": slug,
        "stages": stages,
        "next_stage": next_stage,
        "refs": refs,
    }
    if include_identity:
        payload["identity"] = identity
    return payload


def children(directory: Path) -> list[Path]:
    try:
        return list(directory.iterdir())
    except OSError:
        return []


def valid_slug(value: str) -> bool:
    return SLUG.fullmatch(value) is not None


def scan_status(root: Path) -> dict[str, Any]:
    """Discover all material layouts and preserve PDF's honest ambiguity.

    A bare ``sources/{slug}.pdf`` is valid for either a Paper or a Book.  If
    its later kind-specific layout exists, it selects that kind; otherwise scan
    emits both possibilities rather than silently assigning a material type.
    """

    discovered: dict[str, set[str]] = {"paper": set(), "book": set(), "talk": set()}
    scan_slug = "scan-root"
    for directory, kind, suffix in (
        (
            artifact_path(root, "paper", "analyse", "output", slug=scan_slug).parent,
            "paper",
            ".md",
        ),
        (
            artifact_path(
                root, "paper", "prepare", "normalized", slug=scan_slug
            ).parent.parent,
            "paper",
            None,
        ),
        (
            artifact_path(
                root, "book", "synthesise", "output", slug=scan_slug
            ).parent.parent,
            "book",
            None,
        ),
        (
            artifact_path(
                root, "book", "prepare", "outputDir", slug=scan_slug
            ).parent,
            "book",
            None,
        ),
        (
            artifact_path(root, "talk", "analyse", "output", slug=scan_slug).parent.parent,
            "talk",
            None,
        ),
        (
            artifact_path(
                root, "talk", "prepare", "processingDir", slug=scan_slug
            ).parent,
            "talk",
            None,
        ),
    ):
        for entry in children(directory):
            name = entry.stem if suffix else entry.name
            if suffix and entry.suffix != suffix:
                continue
            if valid_slug(name):
                discovered[kind].add(name)

    source_directory = artifact_path(
        root, "paper", "acquire", "output", slug=scan_slug
    ).parent
    for entry in children(source_directory):
        name = entry.name
        suffix = entry.suffix.lower()
        slug = entry.stem
        if not valid_slug(slug):
            continue
        if suffix == ".epub":
            discovered["book"].add(slug)
        elif suffix == ".pdf":
            known_kinds = [
                kind for kind in ("paper", "book") if slug in discovered[kind]
            ]
            for kind in known_kinds or ["paper", "book"]:
                discovered[kind].add(slug)
        elif suffix[1:] in MEDIA_EXTENSIONS:
            discovered["talk"].add(slug)

    items = [
        {
            "kind": kind,
            "slug": slug,
            "next_stage": material_status(root, kind, slug)["next_stage"],
        }
        for kind in sorted(discovered)
        for slug in sorted(discovered[kind])
    ]
    return {"schema_version": SCAN_VERSION, "items": items}


def material_status(
    root: Path,
    kind: str,
    slug: str,
    *,
    include_identity: bool = False,
) -> dict[str, Any]:
    if kind == "paper":
        return paper_status(root, slug, include_identity=include_identity)
    if kind == "book":
        return book_status(root, slug, include_identity=include_identity)
    if kind == "talk":
        return talk_status(root, slug, include_identity=include_identity)
    if kind == "translation":
        if include_identity:
            raise InvocationError("--identity is not supported for translation")
        return translation_status(root, slug)
    raise AssertionError(f"unsupported kind: {kind}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = StatusArgumentParser(add_help=True, prog="quasi-status")
    parser.add_argument("--kind", choices=("paper", "book", "talk", "translation"))
    parser.add_argument("--slug")
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--identity", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.json:
        raise InvocationError("--json is required")
    if args.scan:
        if args.kind is not None or args.slug is not None or args.identity:
            raise InvocationError(
                "--scan cannot be combined with --kind, --slug, or --identity"
            )
        return args
    if args.kind is None or args.slug is None:
        raise InvocationError("--kind and --slug are required unless --scan is used")
    if not valid_slug(args.slug):
        raise InvocationError("--slug must be canonical ASCII kebab (1..80 characters)")
    return args


def emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except InvocationError as exc:
        emit(
            {
                "schema_version": ERROR_VERSION,
                "error": {"code": "invalid_invocation", "message": str(exc)},
            }
        )
        return 2
    root = project_root()
    if args.scan:
        emit(scan_status(root))
    else:
        emit(
            material_status(
                root,
                args.kind,
                args.slug,
                include_identity=args.identity,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
