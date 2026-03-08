#!/usr/bin/env python3
"""Aggregate cited works across journal article analyses.

Reads all per-article analysis markdown files from a journal directory,
extracts the "核心引用文献" (cited works) section, counts citation frequency
across articles, and generates a ranked reading list.

Usage:
    python3 aggregate_refs.py <journal-dir> [--output <output-file>] [--min-count <N>]

Example:
    python3 aggregate_refs.py vault/journals/critical-inquiry/ \
        --output vault/journals/critical-inquiry-reading-list.md
"""

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path


def extract_cited_works(filepath: Path) -> list[dict]:
    """Extract cited works from a single article analysis file."""
    text = filepath.read_text(encoding="utf-8")

    # Find the cited works section
    pattern = r"## 核心引用文献\s*\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return []

    section = match.group(1).strip()
    works = []

    # Parse entries like: 1. **Author (Year)** — *Title* [type]
    entry_pattern = re.compile(
        r"\d+\.\s+\*\*(.+?)\s*\((\d{4})\)\*\*\s*[—–-]\s*\*(.+?)\*\s*\[(.+?)\]"
    )

    for m in entry_pattern.finditer(section):
        works.append({
            "author": m.group(1).strip(),
            "year": m.group(2).strip(),
            "title": m.group(3).strip(),
            "type": m.group(4).strip(),
        })

    # Fallback: try simpler patterns
    if not works:
        # Try: - **Author (Year)** — *Title*
        simple_pattern = re.compile(
            r"[-•]\s+\*\*(.+?)\s*\((\d{4})\)\*\*\s*[—–-]\s*\*(.+?)\*"
        )
        for m in simple_pattern.finditer(section):
            works.append({
                "author": m.group(1).strip(),
                "year": m.group(2).strip(),
                "title": m.group(3).strip(),
                "type": "unknown",
            })

    return works


def extract_article_title(filepath: Path) -> str:
    """Extract the article title from the analysis file."""
    text = filepath.read_text(encoding="utf-8")
    # Look for title in frontmatter
    title_match = re.search(r'^title:\s*"?(.+?)"?\s*$', text, re.MULTILINE)
    if title_match:
        return title_match.group(1)
    # Fallback: first heading
    h1_match = re.search(r"^# (.+)$", text, re.MULTILINE)
    return h1_match.group(1) if h1_match else filepath.stem


def normalize_key(author: str, title: str) -> str:
    """Create a normalized key for deduplication."""
    # Normalize author: strip whitespace, lowercase
    a = re.sub(r"\s+", " ", author.strip().lower())
    # Normalize title: first 50 chars, lowercase, strip punctuation
    t = re.sub(r"[^\w\s]", "", title.strip().lower())[:50]
    return f"{a}|{t}"


def aggregate(journal_dir: Path, min_count: int = 1) -> tuple[list[dict], dict]:
    """Aggregate references across all article analyses.

    Returns:
        (ranked_works, stats) where ranked_works is sorted by citation count.
    """
    md_files = sorted(journal_dir.glob("*.md"))
    # Skip synthesis and reading-list files
    md_files = [f for f in md_files if not f.name.startswith("00-")
                and "-synthesis" not in f.name
                and "-reading-list" not in f.name
                and "-scan" not in f.name]

    all_works: dict[str, dict] = {}  # key -> work info
    citation_count: Counter = Counter()
    cited_by: defaultdict[str, list[str]] = defaultdict(list)

    for filepath in md_files:
        article_title = extract_article_title(filepath)
        works = extract_cited_works(filepath)

        for w in works:
            key = normalize_key(w["author"], w["title"])
            citation_count[key] += 1
            cited_by[key].append(article_title)

            # Keep the best version of the entry
            if key not in all_works:
                all_works[key] = w
            elif w["type"] != "unknown" and all_works[key]["type"] == "unknown":
                all_works[key] = w

    # Build ranked list
    ranked = []
    for key, count in citation_count.most_common():
        if count < min_count:
            break
        work = all_works[key]
        ranked.append({
            **work,
            "count": count,
            "cited_by": cited_by[key],
        })

    stats = {
        "total_files": len(md_files),
        "total_unique_works": len(all_works),
        "works_cited_2plus": sum(1 for c in citation_count.values() if c >= 2),
        "works_cited_3plus": sum(1 for c in citation_count.values() if c >= 3),
    }

    return ranked, stats


def generate_report(ranked: list[dict], stats: dict, journal_name: str) -> str:
    """Generate the reading list markdown report."""
    lines = [
        f"# {journal_name} — 推荐阅读列表（参考文献聚合）",
        "",
        f"基于 {stats['total_files']} 篇文章分析的参考文献交叉比对。",
        f"共识别 {stats['total_unique_works']} 部独立著作，"
        f"其中 {stats['works_cited_2plus']} 部被 ≥2 篇文章引用，"
        f"{stats['works_cited_3plus']} 部被 ≥3 篇文章引用。",
        "",
        "---",
        "",
    ]

    # Group by citation count
    if any(w["count"] >= 3 for w in ranked):
        lines.append("## 核心文献（被 ≥3 篇文章引用）")
        lines.append("")
        for w in ranked:
            if w["count"] < 3:
                break
            lines.append(f"### {w['author']} ({w['year']}) — *{w['title']}*")
            lines.append(f"- **类型**：{w['type']} | **被引次数**：{w['count']}")
            lines.append(f"- **引用文章**：{'; '.join(w['cited_by'][:5])}")
            lines.append("")

    lines.append("## 重要文献（被 2 篇文章引用）")
    lines.append("")
    lines.append("| 作者 | 年份 | 标题 | 类型 | 被引 |")
    lines.append("|------|------|------|------|------|")
    for w in ranked:
        if w["count"] != 2:
            continue
        title = w["title"].replace("|", "/")
        lines.append(f"| {w['author']} | {w['year']} | *{title}* | {w['type']} | {w['count']} |")

    lines.append("")

    if any(w["count"] == 1 for w in ranked):
        lines.append("## 单次引用文献（仅专著）")
        lines.append("")
        lines.append("<details>")
        lines.append(f"<summary>展开（{sum(1 for w in ranked if w['count'] == 1 and w['type'] == 'monograph')} 部）</summary>")
        lines.append("")
        lines.append("| 作者 | 年份 | 标题 |")
        lines.append("|------|------|------|")
        for w in ranked:
            if w["count"] == 1 and w["type"] == "monograph":
                title = w["title"].replace("|", "/")
                lines.append(f"| {w['author']} | {w['year']} | *{title}* |")
        lines.append("")
        lines.append("</details>")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Aggregate references from journal article analyses")
    parser.add_argument("journal_dir", type=Path, help="Directory containing article analysis .md files")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output file path")
    parser.add_argument("--min-count", type=int, default=1, help="Minimum citation count to include")
    parser.add_argument("--journal-name", type=str, default=None, help="Journal display name")
    args = parser.parse_args()

    if not args.journal_dir.is_dir():
        print(f"Error: {args.journal_dir} is not a directory")
        return

    journal_name = args.journal_name or args.journal_dir.name.replace("-", " ").title()

    ranked, stats = aggregate(args.journal_dir, min_count=args.min_count)

    report = generate_report(ranked, stats, journal_name)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"Report saved: {args.output}")
    else:
        print(report)

    print(f"\nStats: {stats['total_files']} files, {stats['total_unique_works']} unique works, "
          f"{stats['works_cited_2plus']} cited ≥2x, {stats['works_cited_3plus']} cited ≥3x")


if __name__ == "__main__":
    main()
