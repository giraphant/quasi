"""Webpage-only filesystem containment and publication checks."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Literal


PathState = Literal["missing", "regular", "directory", "unsafe"]


class WebpagePathError(ValueError):
    """A caller-named Webpage path is outside its trusted project boundary."""


def trusted_project_root() -> Path:
    """Resolve the configured project root once as the trusted anchor."""

    configured = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(configured if configured else os.getcwd()).expanduser().resolve(strict=True)


def trusted_root(root: Path) -> Path:
    """Resolve an explicitly supplied project root once as a trusted anchor."""

    return root.expanduser().resolve(strict=True)


def lexical_project_path(root: Path, candidate: Path) -> Path:
    """Normalize dot segments without resolving any candidate symlink."""

    anchor = root
    joined = candidate.expanduser() if candidate.is_absolute() else anchor / candidate
    lexical = Path(os.path.abspath(os.fspath(joined)))
    try:
        lexical.relative_to(anchor)
    except ValueError as exc:
        raise WebpagePathError("webpage path must remain inside the project root") from exc
    return lexical


def path_state(root: Path, candidate: Path) -> PathState:
    """Inspect a contained path without following any named symlink."""

    anchor = root
    path = lexical_project_path(anchor, candidate)
    relative = path.relative_to(anchor)
    current = anchor
    for index, part in enumerate(relative.parts):
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            return "missing"
        except OSError:
            return "unsafe"
        last = index == len(relative.parts) - 1
        if stat.S_ISLNK(mode):
            return "unsafe"
        if not last and not stat.S_ISDIR(mode):
            return "unsafe"
        if last:
            if stat.S_ISREG(mode):
                return "regular"
            if stat.S_ISDIR(mode):
                return "directory"
            return "unsafe"
    return "directory"


def webpage_route_state(root: Path, slug: str) -> Literal["safe", "unsafe"]:
    """Require both Webpage slug routes to have only safe directory ancestry."""

    anchor = root
    for route in (
        anchor / "vault" / "webpages" / slug,
        anchor / "processing" / "webpages" / slug,
    ):
        state = path_state(anchor, route)
        if state not in {"missing", "directory"}:
            return "unsafe"
    return "safe"


def require_safe_webpage_routes(root: Path, slug: str) -> None:
    if webpage_route_state(root, slug) != "safe":
        raise WebpagePathError(
            "webpage route or ancestor is symlink/non-directory"
        )


def require_input_file(root: Path, path: Path) -> Path:
    """Return one contained, non-symlink regular input leaf."""

    anchor = root
    lexical = lexical_project_path(anchor, path)
    if path_state(anchor, lexical) != "regular":
        raise WebpagePathError("webpage input must be a safe regular file")
    return lexical


def require_output_file(
    root: Path,
    path: Path,
    *,
    existing: bool,
) -> Path:
    """Validate an output leaf for create or explicit replacement."""

    anchor = root
    lexical = lexical_project_path(anchor, path)
    state = path_state(anchor, lexical)
    if existing and state != "regular":
        raise WebpagePathError("webpage replacement output must be a safe regular file")
    if not existing and state != "missing":
        if state == "regular":
            raise FileExistsError(lexical)
        raise WebpagePathError("webpage output or ancestor is unsafe")
    return lexical


def create_output_parents(root: Path, output: Path) -> None:
    """Create a missing publication suffix one directory at a time and revalidate."""

    anchor = root
    lexical = lexical_project_path(anchor, output)
    relative_parent = lexical.parent.relative_to(anchor)
    current = anchor
    for part in relative_parent.parts:
        current /= part
        state = path_state(anchor, current)
        if state == "missing":
            try:
                current.mkdir()
            except FileExistsError:
                pass
        if path_state(anchor, current) != "directory":
            raise WebpagePathError("webpage output ancestor is symlink/non-directory")
    state = path_state(anchor, lexical)
    if state not in {"missing", "regular"}:
        raise WebpagePathError("webpage output leaf is unsafe")
