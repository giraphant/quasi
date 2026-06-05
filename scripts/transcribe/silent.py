"""Silent-template talk.md for DEAD recordings (no usable audio).

A DEAD recording (classify.py) gets a structurally-valid talk.md skeleton —
the six fixed four-char H2 are present and *conform to TALK_BODY block kinds*
(an `### （无）` stub under 分节摘要, a table header under 关键概念, bullets under
项目关联 / 文献人物) — but no summary is forced. Pure builder + thin writer.
"""

from __future__ import annotations

from pathlib import Path

_NOTE = (
    "> **注意**:本录制**音频无有效人声**(疑似未捕获麦克风的屏幕录制,音量近数字静音),"
    "无法转写。下列各节待有效音源补回后再填;`speaker` / `themes` 暂空。"
)


def build_silent_talk_md(title: str, date: str, media: str, *, minutes: str = "?") -> str:
    """Return a TALK_BODY-conforming silent talk.md (frontmatter + 6 H2)."""
    fm = [
        "---",
        "type: talk",
        f'title: "{title}"',
        f"date: {date}",
        # speaker / themes intentionally omitted (empty → omit per YAML style)
        "rating:",
        f"media: {media}",
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
    """Write the silent template to <talk_dir>/talk.md and return the path."""
    talk_dir = Path(talk_dir)
    talk_dir.mkdir(parents=True, exist_ok=True)
    out = talk_dir / "talk.md"
    out.write_text(build_silent_talk_md(title, date, media, minutes=minutes), encoding="utf-8")
    return out
