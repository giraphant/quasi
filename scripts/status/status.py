#!/usr/bin/env python3
"""Report factual on-disk observations for one logical material."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))
from scripts.schemas.operations import OPERATION_CATALOG  # noqa: E402
from scripts.schemas.chapter_manifest import valid_chapter_page_pair  # noqa: E402
from scripts.schemas.topic import TopicSchema  # noqa: E402
from scripts.translate.translate_commit import (  # noqa: E402
    TranslateContractError,
    output_paths,
    validate_language,
)
from scripts.webpage.webarchive import (  # noqa: E402
    WebArchiveDocument,
    normalize_web_url,
    read_webarchive,
)


STATUS_VERSION = "quasi.status/0.2"
SCAN_VERSION = "quasi.status-scan/0.2"
ERROR_VERSION = "quasi.status.error/0.1"
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")
CHAPTER_SLOT = re.compile(r"\d{2,3}[a-z]{0,2}\Z")
CHAPTER_TITLE = re.compile(r"[^\x00-\x1f\x7f-\x9f]+\Z")
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
    operation: str,
    role: str,
    **values: str,
) -> Path:
    """Expand one canonical operation artifact template under ``root``."""

    template = OPERATION_CATALOG[operation]["artifacts"][role]
    return root / template.format(**values)


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
        with path.open("rb") as handle:
            handle.read(1)
    except OSError:
        return FileObservation(present=True, usable=False)
    return FileObservation(present=True, usable=True)


def artifact_observation(root: Path, path: Path) -> dict[str, Any]:
    observed = observe_file(path, nonempty=True)
    return {
        "path": relative(root, path),
        "present": observed.present,
        "usable": observed.usable,
    }


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


def canonical_observation(
    root: Path, path: Path
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Observe a canonical Markdown artifact and parse its identity envelope."""

    observation = artifact_observation(root, path)
    frontmatter = parse_frontmatter(path) if observation["usable"] else None
    observation["usable"] = frontmatter is not None
    return observation, frontmatter


def _regular_nonempty_artifact(root: Path, path: Path) -> dict[str, Any]:
    """Observe one exact Webpage artifact without admitting symlinks as regular files."""
    observation = artifact_observation(root, path)
    try:
        mode = path.lstat().st_mode
    except OSError:
        return observation
    if not stat.S_ISREG(mode):
        observation["usable"] = False
    return observation


def webpage_snapshot_observation(
    root: Path, path: Path
) -> tuple[dict[str, Any], WebArchiveDocument | None]:
    """Observe a saved WebArchive and its parseable main resource only."""
    observation = _regular_nonempty_artifact(root, path)
    if not observation["usable"]:
        return observation, None
    try:
        document = read_webarchive(path)
    except (OSError, ValueError):
        observation["usable"] = False
        return observation, None
    if not document.html.strip():
        observation["usable"] = False
        return observation, None
    return observation, document


def utf8_markdown_observation(root: Path, path: Path) -> dict[str, Any]:
    """Observe a non-empty regular UTF-8 Markdown projection."""
    observation = _regular_nonempty_artifact(root, path)
    if not observation["usable"]:
        return observation
    try:
        path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        observation["usable"] = False
    return observation


def snapshot_captured_at(path: Path) -> str:
    """Project an immutable snapshot mtime as a UTC whole-second timestamp."""
    value = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return value.replace(microsecond=0).isoformat(timespec="seconds").replace("+00:00", "Z")


def webpage_identity(slug: str, title: str, url: str, site: str) -> dict[str, str]:
    """Return the closed identity row used for snapshot and canonical evidence."""
    return {"slug": slug, "title": title, "url": url, "site": site}


def webpage_frontmatter_identity(
    slug: str, frontmatter: dict[str, Any] | None
) -> dict[str, str] | None:
    """Project a valid Webpage canonical identity, defaulting an omitted site to host."""
    if not isinstance(frontmatter, dict) or frontmatter.get("type") != "webpage":
        return None
    title = frontmatter.get("title")
    raw_url = frontmatter.get("url")
    if not isinstance(title, str) or not title.strip() or not isinstance(raw_url, str):
        return None
    try:
        url = normalize_web_url(raw_url)
    except ValueError:
        return None
    raw_site = frontmatter.get("site")
    site = raw_site.strip() if isinstance(raw_site, str) else ""
    if not site:
        site = urlsplit(url).hostname or ""
    return webpage_identity(slug, title, url, site)


def _frontmatter_captured_at(value: Any) -> str | None:
    """Normalize YAML's timestamp scalar or its textual form to UTC seconds."""
    if isinstance(value, datetime):
        if value.tzinfo is None or value.microsecond:
            return None
        return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    if not isinstance(value, str):
        return None
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return value


def webpage_artifacts_cohere(
    snapshot_identity: dict[str, str] | None,
    captured_at: str | None,
    canonical_identity: dict[str, str] | None,
    frontmatter: dict[str, Any] | None,
) -> bool:
    """Require canonical Webpage identity and capture provenance to agree exactly."""
    if canonical_identity is None or not isinstance(frontmatter, dict):
        return False
    canonical_captured_at = _frontmatter_captured_at(frontmatter.get("captured_at"))
    if canonical_captured_at is None:
        return False
    if snapshot_identity is None:
        return True
    return (
        canonical_identity == snapshot_identity
        and canonical_captured_at == captured_at
    )


def frontmatter_identity(frontmatter: dict[str, Any] | None) -> dict[str, Any] | None:
    """Project only canonical identity fields, preserving parsed disk values."""

    if frontmatter is None:
        return None
    projected: dict[str, Any] = {}
    for field in ("title", "authors", "name", "year"):
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


def status_payload(
    kind: str,
    slug: str,
    identity: dict[str, Any] | None,
    facts: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": STATUS_VERSION,
        "kind": kind,
        "slug": slug,
        "identity": identity,
        "facts": facts,
    }


def paper_status(root: Path, slug: str) -> dict[str, Any]:
    source = artifact_path(root, "paper.acquire", "output", slug=slug)
    prepared = [
        artifact_path(root, "paper.prepare", "normalized", slug=slug),
        artifact_path(root, "paper.prepare", "recoveryText", slug=slug),
    ]
    canonical = artifact_path(root, "paper.analyse", "output", slug=slug)
    canonical_fact, frontmatter = canonical_observation(root, canonical)
    return status_payload(
        "paper",
        slug,
        frontmatter_identity(frontmatter) if canonical_fact["usable"] else None,
        {
            "kind": "paper",
            "source": artifact_observation(root, source),
            "prepared": [artifact_observation(root, path) for path in prepared],
            "canonical": canonical_fact,
        },
    )


def webpage_status(root: Path, slug: str) -> dict[str, Any]:
    snapshot_path = artifact_path(root, "webpage.capture", "snapshot", slug=slug)
    prepared_path = artifact_path(root, "webpage.prepare", "output", slug=slug)
    canonical_path = artifact_path(root, "webpage.analyse", "output", slug=slug)
    snapshot, document = webpage_snapshot_observation(root, snapshot_path)
    prepared = utf8_markdown_observation(root, prepared_path)
    canonical, frontmatter = canonical_observation(root, canonical_path)
    captured_at = snapshot_captured_at(snapshot_path) if document else None
    snapshot_identity = (
        webpage_identity(slug, document.title, document.url, document.site)
        if document
        else None
    )
    canonical_identity = webpage_frontmatter_identity(slug, frontmatter)
    if not webpage_artifacts_cohere(
        snapshot_identity, captured_at, canonical_identity, frontmatter
    ):
        canonical["usable"] = False
    return status_payload(
        "webpage",
        slug,
        snapshot_identity or (canonical_identity if canonical["usable"] else None),
        {
            "kind": "webpage",
            "snapshot": snapshot,
            "prepared": prepared,
            "canonical": canonical,
            "captured_at": captured_at,
        },
    )


def safe_chapter_filename(value: object, slot: str) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or not value.startswith(f"{slot}_")
        or not value.endswith(".txt")
        or "/" in value
        or "\\" in value
        or ".." in value
    ):
        return None
    return value


def chapter_inventory(
    root: Path, slug: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = artifact_path(root, "book.prepare", "manifest", slug=slug)
    manifest_fact = artifact_observation(root, manifest)
    manifest_fact["valid"] = False
    if not manifest_fact["usable"]:
        return manifest_fact, []
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return manifest_fact, []
    rows = payload.get("chapters") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        return manifest_fact, []

    projected: list[dict[str, Any]] = []
    seen_slots: set[str] = set()
    seen_filenames: set[str] = set()
    seen_slugs: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            return manifest_fact, []
        slot = row.get("slot")
        title = row.get("title")
        chapter_slug = row.get("slug")
        word_count = row.get("word_count")
        if not isinstance(slot, str) or CHAPTER_SLOT.fullmatch(slot) is None:
            return manifest_fact, []
        filename = safe_chapter_filename(row.get("filename"), slot)
        if (
            filename is None
            or not isinstance(title, str)
            or not 1 <= len(title) <= 500
            or CHAPTER_TITLE.fullmatch(title) is None
            or not isinstance(chapter_slug, str)
            or SLUG.fullmatch(chapter_slug) is None
            or type(word_count) is not int
            or word_count < 0
            or not valid_chapter_page_pair(
                row.get("start_page"), row.get("end_page")
            )
            or slot in seen_slots
            or filename in seen_filenames
            or chapter_slug in seen_slugs
        ):
            return manifest_fact, []
        seen_slots.add(slot)
        seen_filenames.add(filename)
        seen_slugs.add(chapter_slug)
        projected.append(
            {
                "slot": slot,
                "title": title,
                "filename": filename,
                "slug": chapter_slug,
                "word_count": word_count,
                "start_page": row.get("start_page"),
                "end_page": row.get("end_page"),
            }
        )
    manifest_fact["valid"] = True
    return manifest_fact, projected


def book_status(root: Path, slug: str) -> dict[str, Any]:
    sources = [
        (
            format_name,
            artifact_path(
                root,
                "book.prepare",
                "source",
                slug=slug,
                format=format_name,
            ),
        )
        for format_name in ("epub", "pdf")
    ]
    manifest_fact, inventory = chapter_inventory(root, slug)
    chapter_root = artifact_path(root, "book.prepare", "outputDir", slug=slug)
    book_root = artifact_path(
        root, "book.synthesise", "output", slug=slug
    ).parent
    chapters = [
        {
            **chapter,
            "input": artifact_observation(
                root, chapter_root / chapter["filename"]
            ),
            "output": canonical_observation(
                root,
                book_root / f"ch{chapter['slot']}-{chapter['slug']}.md",
            )[0],
        }
        for chapter in inventory
    ]
    overview = artifact_path(root, "book.synthesise", "output", slug=slug)
    overview_fact, frontmatter = canonical_observation(root, overview)
    return status_payload(
        "book",
        slug,
        frontmatter_identity(frontmatter) if overview_fact["usable"] else None,
        {
            "kind": "book",
            "sources": [
                {
                    "format": format_name,
                    "artifact": artifact_observation(root, path),
                }
                for format_name, path in sources
            ],
            "manifest": manifest_fact,
            "chapters": chapters,
            "overview": overview_fact,
        },
    )


def talk_transcripts(root: Path, slug: str) -> list[Path]:
    directory = artifact_path(root, "talk.prepare", "processingDir", slug=slug)
    try:
        entries = sorted(directory.iterdir(), key=lambda item: item.name)
    except OSError:
        return []
    return [
        path
        for path in entries
        if path.name.startswith("transcript.") and path.name != "transcript.json"
    ]


def talk_status(root: Path, slug: str) -> dict[str, Any]:
    media = [root / "sources" / f"{slug}.{extension}" for extension in MEDIA_EXTENSIONS]
    transcripts = talk_transcripts(root, slug)
    canonical = artifact_path(root, "talk.analyse", "output", slug=slug)
    canonical_fact, frontmatter = canonical_observation(root, canonical)
    return status_payload(
        "talk",
        slug,
        frontmatter_identity(frontmatter) if canonical_fact["usable"] else None,
        {
            "kind": "talk",
            "media": [artifact_observation(root, path) for path in media],
            "transcripts": [artifact_observation(root, path) for path in transcripts],
            "canonical": canonical_fact,
        },
    )


def translation_status(
    root: Path,
    slug: str,
    target_language: str,
) -> dict[str, Any]:
    target_language = validate_language(target_language)
    resolved_root = root.expanduser().resolve()
    paths = output_paths(
        project_root=resolved_root,
        slug=slug,
        target_language=target_language,
    )
    output = cast(Path, paths["output_path"])
    manifest = cast(Path, paths["manifest_path"])
    source = artifact_path(
        resolved_root, "translation.prepare", "source", slug=slug
    )
    return status_payload(
        "translation",
        slug,
        None,
        {
            "kind": "translation",
            "target_language": target_language,
            "source": artifact_observation(resolved_root, source),
            "output": artifact_observation(resolved_root, output),
            "manifest": artifact_observation(resolved_root, manifest),
        },
    )


def author_status(root: Path, slug: str) -> dict[str, Any]:
    canonical = artifact_path(root, "author.synthesise", "output", slug=slug)
    canonical_fact, frontmatter = canonical_observation(root, canonical)
    return status_payload(
        "author",
        slug,
        frontmatter_identity(frontmatter) if canonical_fact["usable"] else None,
        {"kind": "author", "canonical": canonical_fact},
    )


def member_path(root: Path, kind: str, slug: str) -> Path:
    if kind == "paper":
        return artifact_path(root, "paper.analyse", "output", slug=slug)
    if kind == "book":
        return artifact_path(root, "book.synthesise", "output", slug=slug)
    return artifact_path(root, "talk.analyse", "output", slug=slug)


def topic_projection(
    root: Path,
    topic_slug: str,
    frontmatter: dict[str, Any] | None,
) -> dict[str, Any] | None:
    try:
        outline = TopicSchema.model_validate(frontmatter)
    except (TypeError, ValueError):
        return None
    if outline.kind != "outline":
        return None

    subquestions: list[dict[str, Any]] = []
    members: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    for subquestion in outline.subquestions or []:
        subquestions.append(
            {
                "id": subquestion.id,
                "question": subquestion.question,
                "coverage": subquestion.coverage,
                "channel": subquestion.channel,
                "theory_used": subquestion.theory_used,
            }
        )
        for member in subquestion.items or []:
            if SLUG.fullmatch(member.slug) is None:
                return None
            path = member_path(root, member.kind, member.slug)
            artifact, _frontmatter = canonical_observation(root, path)
            members.append(
                {
                    "kind": member.kind,
                    "slug": member.slug,
                    "subq": subquestion.id,
                    "role": member.role,
                    "artifact": artifact,
                }
            )
        for card_slug in subquestion.cards:
            if SLUG.fullmatch(card_slug) is None:
                return None
            path = root / "vault" / "topics" / topic_slug / "cards" / f"{card_slug}.md"
            artifact, card_frontmatter = canonical_observation(root, path)
            title = (
                card_frontmatter.get("title")
                if artifact["usable"]
                and isinstance(card_frontmatter, dict)
                and isinstance(card_frontmatter.get("title"), str)
                else None
            )
            cards.append(
                {
                    "slug": card_slug,
                    "subq": subquestion.id,
                    "title": title,
                    "artifact": artifact,
                }
            )
    return {"subquestions": subquestions, "members": members, "cards": cards}


def topic_status(root: Path, slug: str) -> dict[str, Any]:
    outline = artifact_path(root, "topic.steer", "outputPath", slug=slug)
    overview = artifact_path(
        root, "topic.synthesise.overview", "outputPath", slug=slug
    )
    resources = artifact_path(
        root, "topic.synthesise.resources", "outputPath", slug=slug
    )
    outline_fact = artifact_observation(root, outline)
    outline_frontmatter = parse_frontmatter(outline) if outline_fact["usable"] else None
    projection = topic_projection(root, slug, outline_frontmatter)
    outline_fact.update({"valid": projection is not None, "projection": projection})
    overview_fact, overview_frontmatter = canonical_observation(root, overview)
    resources_fact, _resources_frontmatter = canonical_observation(root, resources)
    return status_payload(
        "topic",
        slug,
        (
            frontmatter_identity(overview_frontmatter)
            if overview_fact["usable"]
            else None
        ),
        {
            "kind": "topic",
            "outline": outline_fact,
            "overview": overview_fact,
            "resources": resources_fact,
        },
    )


def children(directory: Path) -> list[Path]:
    try:
        return list(directory.iterdir())
    except OSError:
        return []


def valid_slug(value: str) -> bool:
    return SLUG.fullmatch(value) is not None


def scan_status(root: Path) -> dict[str, Any]:
    """Discover material layouts without turning observations into control hints."""

    discovered: dict[str, set[str]] = {
        "author": set(),
        "paper": set(),
        "book": set(),
        "talk": set(),
        "topic": set(),
        "webpage": set(),
    }
    scan_slug = "scan-root"
    for directory, kind, suffix in (
        (
            artifact_path(root, "author.synthesise", "output", slug=scan_slug).parent,
            "author",
            ".md",
        ),
        (
            artifact_path(root, "paper.analyse", "output", slug=scan_slug).parent,
            "paper",
            ".md",
        ),
        (
            artifact_path(root, "paper.prepare", "normalized", slug=scan_slug).parent.parent,
            "paper",
            None,
        ),
        (
            artifact_path(root, "book.synthesise", "output", slug=scan_slug).parent.parent,
            "book",
            None,
        ),
        (
            artifact_path(root, "book.prepare", "outputDir", slug=scan_slug).parent,
            "book",
            None,
        ),
        (
            artifact_path(root, "talk.analyse", "output", slug=scan_slug).parent.parent,
            "talk",
            None,
        ),
        (
            artifact_path(root, "talk.prepare", "processingDir", slug=scan_slug).parent,
            "talk",
            None,
        ),
        (
            artifact_path(root, "topic.steer", "outputPath", slug=scan_slug).parent.parent,
            "topic",
            None,
        ),
    ):
        for entry in children(directory):
            name = entry.stem if suffix else entry.name
            if suffix and entry.suffix != suffix:
                continue
            if valid_slug(name):
                discovered[kind].add(name)

    for directory, filename in (
        (root / "vault" / "webpages", "snapshot.webarchive"),
        (root / "vault" / "webpages", "webpage.md"),
        (root / "processing" / "webpages", "source.md"),
    ):
        for entry in children(directory):
            if not valid_slug(entry.name):
                continue
            try:
                if not stat.S_ISDIR(entry.lstat().st_mode):
                    continue
                artifact = entry / filename
                if not stat.S_ISREG(artifact.lstat().st_mode):
                    continue
            except OSError:
                continue
            discovered["webpage"].add(entry.name)

    source_directory = artifact_path(
        root, "paper.acquire", "output", slug=scan_slug
    ).parent
    for entry in children(source_directory):
        slug = entry.stem
        suffix = entry.suffix.lower()
        if not valid_slug(slug):
            continue
        if suffix == ".epub":
            discovered["book"].add(slug)
        elif suffix == ".pdf":
            known = [kind for kind in ("paper", "book") if slug in discovered[kind]]
            for kind in known or ["paper", "book"]:
                discovered[kind].add(slug)
        elif suffix[1:] in MEDIA_EXTENSIONS:
            discovered["talk"].add(slug)

    return {
        "schema_version": SCAN_VERSION,
        "items": [
            {"kind": kind, "slug": slug}
            for kind in sorted(discovered)
            for slug in sorted(discovered[kind])
        ],
    }


def material_status(
    root: Path,
    kind: str,
    slug: str,
    *,
    target_language: str | None = None,
) -> dict[str, Any]:
    if kind == "paper":
        return paper_status(root, slug)
    if kind == "webpage":
        return webpage_status(root, slug)
    if kind == "book":
        return book_status(root, slug)
    if kind == "talk":
        return talk_status(root, slug)
    if kind == "translation":
        if target_language is None:
            raise InvocationError("--target-language is required for translation")
        return translation_status(root, slug, target_language)
    if kind == "author":
        return author_status(root, slug)
    if kind == "topic":
        return topic_status(root, slug)
    raise AssertionError(f"unsupported kind: {kind}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = StatusArgumentParser(add_help=True, prog="quasi-status")
    parser.add_argument(
        "--kind", choices=("paper", "book", "talk", "translation", "author", "topic", "webpage")
    )
    parser.add_argument("--slug")
    parser.add_argument("--target-language")
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.json:
        raise InvocationError("--json is required")
    if args.scan:
        if args.kind is not None or args.slug is not None or args.target_language is not None:
            raise InvocationError(
                "--scan cannot be combined with --kind, --slug, or --target-language"
            )
        return args
    if args.kind is None or args.slug is None:
        raise InvocationError("--kind and --slug are required unless --scan is used")
    if not valid_slug(args.slug):
        raise InvocationError("--slug must be canonical ASCII kebab (1..80 characters)")
    if args.kind == "translation":
        if args.target_language is None:
            raise InvocationError("--target-language is required for translation")
        try:
            args.target_language = validate_language(args.target_language)
        except TranslateContractError as exc:
            raise InvocationError(str(exc)) from exc
    elif args.target_language is not None:
        raise InvocationError("--target-language is only valid for translation")
    return args


def emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        value = (
            scan_status(project_root())
            if args.scan
            else material_status(
                project_root(),
                args.kind,
                args.slug,
                target_language=args.target_language,
            )
        )
    except InvocationError as exc:
        emit(
            {
                "schema_version": ERROR_VERSION,
                "error": {"code": "invalid_invocation", "message": str(exc)},
            }
        )
        return 2
    emit(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
