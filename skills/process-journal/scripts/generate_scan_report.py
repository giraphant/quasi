#!/usr/bin/env python3
"""Generate scan.md report from papers + scores."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def load_papers(papers_path: Path) -> list[dict]:
    """Load papers JSON."""
    return json.loads(papers_path.read_text())


def load_scores(scores_dir: Path) -> dict:
    """Load all score JSON files, return {paper_id: score}."""
    scores = {}
    for score_file in scores_dir.glob("*.json"):
        paper_id = score_file.stem
        score_data = json.loads(score_file.read_text())
        scores[paper_id] = score_data
    return scores


def merge_and_sort(papers: list[dict], scores: dict) -> list[dict]:
    """Merge papers with scores, calculate overall, sort by score."""
    merged = []
    for paper in papers:
        paper_id = paper["id"]
        if paper_id in scores:
            score = scores[paper_id]
            r = score.get("r", 5)
            q = score.get("q", 5)
            i = score.get("i", 5)
            overall = round((r + q + i) / 3, 1)

            merged.append({
                **paper,
                "r": r,
                "q": q,
                "i": i,
                "overall_score": overall,
                "tags": score.get("tags", []),
                "one_liner": score.get("one_liner", "")
            })

    merged.sort(key=lambda x: x["overall_score"], reverse=True)
    return merged


def generate_report(merged: list[dict], journal_name: str) -> str:
    """Generate markdown report."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    tier1 = [p for p in merged if p["overall_score"] >= 7]
    tier2 = [p for p in merged if 5 <= p["overall_score"] < 7]
    tier3 = [p for p in merged if p["overall_score"] < 5]

    lines = [
        f"# {journal_name} — 10-Year Scan (2016-2026)",
        "",
        f"Generated: {now}",
        f"Total articles scored: {len(merged)}",
        "",
        "Scoring criteria: relevance to research interests",
        "Scale: 1-10 (R=relevance, Q=quality, I=impact, Avg=overall)",
        "",
        "---",
        "",
        f"## Tier 1: High Relevance ({len(tier1)} articles, score >= 7)",
        ""
    ]

    for p in tier1:
        tags_str = json.dumps(p.get("tags", []))
        lines.append(f"### {p['title']}")
        lines.append(f"- **Date**: {p['publication_date']} | **Score**: R={p['r']} Q={p['q']} I={p['i']} **Avg={p['overall_score']}**")
        lines.append(f"- **Tags**: {tags_str}")
        lines.append(f"- **Summary**: {p.get('one_liner', '')}")
        if p.get("doi"):
            lines.append(f"- **DOI**: {p['doi']}")
        abstract = p.get("abstract", "")
        if abstract:
            words = abstract.split()
            if len(words) > 150:
                abstract = " ".join(words[:150]) + "..."
            lines.append(f"- **Abstract**: {abstract}")
        lines.append("")

    lines.extend([
        "---",
        "",
        f"## Tier 2: Moderate Relevance ({len(tier2)} articles, score 5-6.9)",
        "",
        "| Score | Date | Title | Summary |",
        "|-------|------|-------|---------|"
    ])
    for p in tier2:
        title = p["title"].replace("|", "/")
        one_liner = p.get("one_liner", "").replace("|", "/")
        lines.append(f"| {p['overall_score']} | {p['publication_date']} | {title} | {one_liner} |")

    lines.extend([
        "",
        "---",
        "",
        f"## Tier 3: Low Relevance ({len(tier3)} articles, score < 5)",
        "",
        "<details>",
        f"<summary>Click to expand ({len(tier3)} articles)</summary>",
        "",
        "| Score | Date | Title |",
        "|-------|------|-------|"
    ])
    for p in tier3:
        title = p["title"].replace("|", "/")
        lines.append(f"| {p['overall_score']} | {p['publication_date']} | {title} |")
    lines.extend(["", "</details>"])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--papers", required=True)
    parser.add_argument("--scores", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    papers_path = Path(args.papers)
    scores_dir = Path(args.scores)
    output_path = Path(args.output)

    journal_name = output_path.stem.replace("-scan", "").replace("-", " ").title()

    papers = load_papers(papers_path)
    scores = load_scores(scores_dir)
    merged = merge_and_sort(papers, scores)

    print(f"Loaded {len(papers)} papers, {len(scores)} scores")
    print(f"Merged: {len(merged)} papers with scores")

    report = generate_report(merged, journal_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report)
    print(f"Report saved to {output_path}")


if __name__ == "__main__":
    main()


