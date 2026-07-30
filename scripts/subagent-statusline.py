#!/usr/bin/env python3
"""Project Quasi Workflow tasks onto Claude Code's subagent panel."""

from __future__ import annotations

import json
import math
import re
import sys
import unicodedata
from collections.abc import Iterator
from typing import Any


DEFAULT_COLUMNS = 80
ELLIPSIS = "…"

ANSI_RE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)?)"
)
DATE_SUFFIX_RE = re.compile(r"-(?:19|20)\d{6}$")
CLAUDE_MODEL_RE = re.compile(
    r"^(?:claude-)?(?P<family>opus|sonnet|haiku)"
    r"(?:-(?P<major>\d+)(?:-(?P<minor>\d+))?)?"
    r"(?:-(?:19|20)\d{6})?$",
    re.IGNORECASE,
)
LEGACY_CLAUDE_MODEL_RE = re.compile(
    r"^claude-(?P<major>\d+)(?:-(?P<minor>\d+))?"
    r"-(?P<family>opus|sonnet|haiku)"
    r"(?:-(?:19|20)\d{6})?$",
    re.IGNORECASE,
)

LABEL_PHASES = (
    (
        "Paper",
        re.compile(
            r"^paper\.(?:download\.legacy|extract-text|assess|ocr|analyse|audit):"
        ),
    ),
    (
        "Author",
        re.compile(
            r"^(?:discover-books|discover-papers|synth-author|audit-author|"
            r"audit2-author|regen-author):"
        ),
    ),
    (
        "Topic",
        re.compile(
            r"^(?:recall|steer|probe-cards|webcard|synth-dossier|"
            r"synth-topic|regen-outline|regen-dossier|regen-card|regen-topic):"
        ),
    ),
    ("Topic", re.compile(r"^audit2?:vault/topics/")),
    (
        "Book",
        re.compile(
            r"^(?:download|extract|analyse-ch[^:]*|refill-ch[^:]*|synth|"
            r"synth2|audit|audit2|regen-synth|regen-ch[^:]*):"
        ),
    ),
    ("Topic", re.compile(r"^probe-done:[^:]+:r\d+(?::retry)?$")),
    ("Author", re.compile(r"^probe-done:[^:]+(?::retry)?$")),
)


def clean_text(value: Any) -> str:
    """Return one safe terminal line without accepting input escape sequences."""
    if not isinstance(value, str):
        return ""
    value = ANSI_RE.sub("", value)
    return "".join(
        " " if char in "\t\r\n" else char
        for char in value
        if char in {"\t", "\u200d"}
        or unicodedata.category(char) not in {"Cc", "Cf"}
    ).strip()


def task_phase(task: dict[str, Any]) -> tuple[str, str] | None:
    label = clean_text(task.get("label"))
    agent_type = clean_text(task.get("type"))
    name = clean_text(task.get("name"))

    for phase, pattern in LABEL_PHASES:
        if label and pattern.search(label):
            return phase, label

    for candidate in (agent_type, name):
        if candidate.startswith("quasi:"):
            return "Quasi", label or candidate
    return None


def short_model(value: Any) -> str:
    model = clean_text(value)
    if not model or model.lower() in {"default", "inherit", "unknown", "unresolved"}:
        return ""

    match = CLAUDE_MODEL_RE.fullmatch(model) or LEGACY_CLAUDE_MODEL_RE.fullmatch(
        model
    )
    if match:
        family = match.group("family").capitalize()
        major = match.group("major")
        minor = match.group("minor")
        version = ".".join(part for part in (major, minor) if part)
        return f"{family} {version}".strip()

    model = DATE_SUFFIX_RE.sub("", model)
    if model.lower().startswith("claude-"):
        model = model[7:]
    return model.replace("-", " ")


def effort_text(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or value < 0:
            return ""
        return str(int(value)) if value == int(value) else str(value)
    return clean_text(value)


def context_percentage(task: dict[str, Any]) -> str:
    tokens = task.get("tokenCount")
    window = task.get("contextWindowSize")
    if (
        isinstance(tokens, bool)
        or isinstance(window, bool)
        or not isinstance(tokens, (int, float))
        or not isinstance(window, (int, float))
        or not math.isfinite(tokens)
        or not math.isfinite(window)
        or tokens < 0
        or window <= 0
    ):
        return ""
    percentage = int((tokens * 100 / window) + 0.5)
    return f"{percentage}%"


def character_width(char: str) -> int:
    if (
        char == "\u200d"
        or unicodedata.combining(char)
        or unicodedata.category(char) in {"Mn", "Me"}
        or "\ufe00" <= char <= "\ufe0f"
        or "\U0001f3fb" <= char <= "\U0001f3ff"
    ):
        return 0
    return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1


def grapheme_clusters(text: str) -> Iterator[str]:
    cluster = ""
    regional_count = 0
    for char in text:
        codepoint = ord(char)
        is_regional = 0x1F1E6 <= codepoint <= 0x1F1FF
        joins_previous = (
            bool(cluster)
            and (
                cluster.endswith("\u200d")
                or char == "\u200d"
                or unicodedata.combining(char)
                or unicodedata.category(char) in {"Mn", "Me"}
                or 0xFE00 <= codepoint <= 0xFE0F
                or 0x1F3FB <= codepoint <= 0x1F3FF
                or (is_regional and regional_count == 1)
            )
        )
        if cluster and not joins_previous:
            yield cluster
            cluster = ""
            regional_count = 0
        cluster += char
        if is_regional:
            regional_count += 1
        elif char != "\u200d" and not joins_previous:
            regional_count = 0
    if cluster:
        yield cluster


def cluster_width(cluster: str) -> int:
    widths = [character_width(char) for char in cluster]
    if "\u200d" in cluster:
        return max(widths, default=0)
    if (
        sum(0x1F1E6 <= ord(char) <= 0x1F1FF for char in cluster) == 2
        or "\u20e3" in cluster
    ):
        return 2
    return sum(widths)


def display_width(text: str) -> int:
    return sum(cluster_width(cluster) for cluster in grapheme_clusters(text))


def truncate_columns(text: str, columns: int) -> str:
    if columns <= 0:
        return ""
    if display_width(text) <= columns:
        return text
    if columns == 1:
        return ELLIPSIS

    budget = columns - display_width(ELLIPSIS)
    used = 0
    kept: list[str] = []
    for cluster in grapheme_clusters(text):
        width = cluster_width(cluster)
        if used + width > budget:
            break
        kept.append(cluster)
        used += width
    return "".join(kept) + ELLIPSIS


def usable_columns(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_COLUMNS
    if not math.isfinite(value):
        return DEFAULT_COLUMNS
    columns = int(value)
    return columns if columns >= 0 else DEFAULT_COLUMNS


def project_task(task: Any, columns: int) -> dict[str, str] | None:
    if not isinstance(task, dict):
        return None
    task_id = task.get("id")
    operation = task_phase(task)
    if not isinstance(task_id, str) or not task_id or not operation:
        return None

    phase, label = operation
    status = clean_text(task.get("status")) or "unknown"
    segments = [f"{phase}/{label}", status]

    model = short_model(task.get("model"))
    if model:
        segments.append(model)
    effort = effort_text(task.get("effort"))
    if effort:
        segments.append(effort)
    percentage = context_percentage(task)
    if percentage:
        segments.append(percentage)

    return {
        "id": task_id,
        "content": truncate_columns(" · ".join(segments), columns),
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object")
        tasks = payload.get("tasks", [])
        if not isinstance(tasks, list):
            raise ValueError("tasks must be an array")

        columns = usable_columns(payload.get("columns"))
        rows = [
            row
            for task in tasks
            if (row := project_task(task, columns)) is not None
        ]
        if rows:
            sys.stdout.write(
                "\n".join(
                    json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                    for row in rows
                )
                + "\n"
            )
    except Exception as error:
        sys.stderr.write(f"quasi subagent status line: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
