"""Silent-template talk.md for DEAD recordings (no usable audio).

A DEAD recording (classify.py) gets a structurally-valid talk.md skeleton —
the six fixed four-char H2 are present and *conform to TALK_BODY block kinds*
(an `### （无）` stub under 分节摘要, a table header under 关键概念, bullets under
项目关联 / 文献人物) — but no summary is forced. Pure builder + thin writer.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from transcribe.talk_commit import (
    TalkFailure,
    ensure_directory,
    regular_file,
    safe_output,
    slug_lock,
)

_NOTE = (
    "> **注意**:本录制**音频无有效人声**(疑似未捕获麦克风的屏幕录制,音量近数字静音),"
    "无法转写。下列各节待有效音源补回后再填;`speaker` / `themes` 暂空。"
)


def build_silent_talk_md(title: str, date: str, media: str, *, minutes: str = "?") -> str:
    """Return a TALK_BODY-conforming silent talk.md (frontmatter + 6 H2)."""
    fm = [
        "---",
        "type: talk",
        f"title: {json.dumps(title, ensure_ascii=False)}",
        f"date: {date}",
        # speaker / themes intentionally omitted (empty → omit per YAML style)
        "rating:",
        f"media: {json.dumps(media, ensure_ascii=False)}",
        "---",
    ]
    body = f"""# {title}

**讲者**:(待补)
**日期**:{date}
**场合**:未标明
**时长**:约 {minutes} 分钟

---

{_NOTE}

## 核心论点

（录制无有效音频,无法摘要)

## 分节摘要

### （无)

（录制无有效音频,无法摘要)

## 关键概念

| 概念 | 英文 | 定义 |
|------|------|------|
| （无) |  |  |

## 项目关联

- （暂无;待有效音源)

## 文献人物

- （转写中未明确提及具名文献)

## 时间脉络

- `[00:00]` （静音,无可标注内容)
"""
    return "\n".join(fm) + "\n\n" + body


def write_silent(talk_dir: Path, title: str, date: str, media: str, *, minutes: str = "?") -> Path:
    """Legacy helper: create or reconcile the deterministic silent template."""
    talk_dir = Path(talk_dir)
    root = talk_dir
    for _ in range(3):
        root = root.parent
    out, _ = write_silent_atomic(
        root,
        talk_dir,
        build_silent_talk_md(title, date, media, minutes=minutes),
        slug=talk_dir.name,
    )
    return out


def write_silent_atomic(
    root: Path,
    talk_dir: Path,
    content: str,
    *,
    slug: str,
    mode: str = "create",
) -> tuple[Path, str]:
    """Create ``talk.md`` once, or reconcile byte-identical existing content."""
    root = Path(root)
    talk_dir = safe_output(
        Path(talk_dir), root, operation_key="talk.render-silent"
    )
    processing_parent = root / "processing" / "talks"
    ensure_directory(processing_parent, root, operation_key="talk.render-silent")
    payload = content.encode("utf-8")
    with slug_lock(
        processing_parent,
        slug,
        root,
        operation_key="talk.render-silent",
    ):
        ensure_directory(talk_dir, root, operation_key="talk.render-silent")
        out = safe_output(
            talk_dir / "talk.md", root, operation_key="talk.render-silent"
        )
        if out.exists() or out.is_symlink():
            if not regular_file(out):
                raise TalkFailure(
                    "output_not_regular",
                    f"silent Talk target is not a regular file: {out}",
                    operation_key="talk.render-silent",
                    status="blocked",
                    outcome="unknown",
                )
            if out.read_bytes() == payload:
                return out, "reconciled"
            if mode == "repair":
                fd, name = tempfile.mkstemp(
                    prefix=".talk.md.repair-", dir=str(talk_dir)
                )
                stage = Path(name)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(payload)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(stage, out)
                    directory_fd = os.open(talk_dir, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                    return out, "repair"
                finally:
                    try:
                        stage.unlink()
                    except FileNotFoundError:
                        pass
            raise TalkFailure(
                "output_exists_requires_reconcile",
                "talk.md exists with different content",
                operation_key="talk.render-silent",
                status="blocked",
                outcome="unknown",
            )
        fd, name = tempfile.mkstemp(
            prefix=".talk.md.stage-", dir=str(talk_dir)
        )
        stage = Path(name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(stage, out)
            except FileExistsError:
                if regular_file(out) and out.read_bytes() == payload:
                    return out, "reconciled"
                raise TalkFailure(
                    "output_exists_requires_reconcile",
                    "a competing silent Talk writer committed different content",
                    operation_key="talk.render-silent",
                    status="blocked",
                    outcome="unknown",
                )
            directory_fd = os.open(talk_dir, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return out, "create"
        finally:
            try:
                stage.unlink()
            except FileNotFoundError:
                pass
