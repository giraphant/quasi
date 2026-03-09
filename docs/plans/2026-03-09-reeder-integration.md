# Implementation Plan: Reeder Integration into process-journal

**Created**: 2026-03-09
**Design Doc**: docs/plans/2026-03-09-reeder-integration-design.md
**Estimated Time**: 2-3 hours
**Complexity**: Medium

## Overview

Integrate reeder's journal scanning capabilities (OpenAlex fetch + AI scoring) into `quasi:process-journal` as Phase 0, enabling end-to-end workflow without external dependencies.

## Prerequisites

- Design document reviewed and approved
- `requests` library available (already in quasi)
- CLAUDE.md §1.3 configured with Research Interests

## Implementation Strategy

**Approach**: Incremental implementation with testing at each step
- Build fetch_papers.py first (testable independently)
- Build generate_scan_report.py second (testable with mock data)
- Create score-single-paper.md prompt
- Update SKILL.md documentation last

**Testing**: Manual testing with small journal sample (10-20 papers)

---

## Task Breakdown

### Phase 1: Setup and Scaffolding (10 min)

#### Task 1.1: Create directory structure
**Time**: 2 min

```bash
mkdir -p skills/process-journal/scripts
mkdir -p skills/process-journal/prompts
```

**Verification**:
```bash
ls -la skills/process-journal/
# Should show: SKILL.md, scripts/, prompts/
```

---

### Phase 2: Implement fetch_papers.py (45 min)

#### Task 2.1: Create fetch_papers.py skeleton
**Time**: 5 min

Create `skills/process-journal/scripts/fetch_papers.py`:

```python
#!/usr/bin/env python3
"""Fetch papers from OpenAlex by journal name."""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

BASE_URL = "https://api.openalex.org"
HEADERS = {"User-Agent": "Quasi-Research/1.0"}

def search_journal(name: str) -> str:
    """Search journal by name, return OpenAlex source ID."""
    pass

def fetch_papers(source_id: str, from_date: str) -> list[dict]:
    """Fetch papers from source since from_date."""
    pass

def reconstruct_abstract(inverted_index: dict) -> str:
    """Reconstruct abstract from OpenAlex inverted index."""
    pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-name", required=True)
    parser.add_argument("--days-back", type=int, default=3650)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    # TODO: implement

if __name__ == "__main__":
    main()
```

**Verification**: `python3 skills/process-journal/scripts/fetch_papers.py --help`

#### Task 2.2: Implement search_journal()
**Time**: 10 min

```python
def search_journal(name: str) -> str:
    """Search journal by name, return OpenAlex source ID."""
    url = f"{BASE_URL}/sources"
    params = {"search": name, "per_page": 5}

    resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    results = data.get("results", [])
    if not results:
        raise ValueError(f"Journal not found: {name}")

    # Return first match
    source = results[0]
    source_id = source.get("id", "").split("/")[-1]  # Extract ID from URL
    print(f"Found: {source.get('display_name')} (ID: {source_id})")
    return source_id
```

**Test**:
```bash
python3 -c "
from skills.process_journal.scripts.fetch_papers import search_journal
print(search_journal('Critical Inquiry'))
"
# Expected: S121755651 (or similar)
```

#### Task 2.3: Implement reconstruct_abstract()
**Time**: 5 min

```python
def reconstruct_abstract(inverted_index: dict) -> str:
    """Reconstruct abstract from OpenAlex inverted index."""
    if not inverted_index:
        return ""
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)
```

#### Task 2.4: Implement fetch_papers()
**Time**: 15 min

```python
def fetch_papers(source_id: str, from_date: str) -> list[dict]:
    """Fetch papers from source since from_date."""
    url = f"{BASE_URL}/works"
    params = {
        "filter": f"primary_location.source.id:{source_id},from_publication_date:{from_date},type:article",
        "sort": "publication_date:desc",
        "per_page": 200,
        "page": 1
    }

    all_papers = []
    while True:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if not results:
            break

        for work in results:
            loc = work.get("primary_location") or {}
            source = loc.get("source") or {}
            authors_list = []
            for a in work.get("authorships", []):
                author = a.get("author", {})
                if author.get("display_name"):
                    authors_list.append(author["display_name"])

            all_papers.append({
                "id": work.get("id", "").split("/")[-1],
                "doi": (work.get("doi") or "").replace("https://doi.org/", ""),
                "title": work.get("title", ""),
                "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
                "authors": ", ".join(authors_list),
                "publication_date": work.get("publication_date", ""),
                "journal_name": source.get("display_name", ""),
                "cited_by_count": work.get("cited_by_count", 0)
            })

        if len(results) < 200:
            break
        params["page"] += 1

    return all_papers
```

#### Task 2.5: Complete main() function
**Time**: 10 min

```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-name", required=True)
    parser.add_argument("--days-back", type=int, default=3650)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    # Calculate from_date
    from_date = (datetime.now() - timedelta(days=args.days_back)).strftime("%Y-%m-%d")
    print(f"Fetching papers from {args.journal_name} since {from_date}")

    try:
        source_id = search_journal(args.journal_name)
        papers = fetch_papers(source_id, from_date)
        print(f"Fetched {len(papers)} papers")

        # Save to JSON
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(papers, ensure_ascii=False, indent=2))
        print(f"Saved to {output_path}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
```

**Test**:
```bash
python3 skills/process-journal/scripts/fetch_papers.py \
    --journal-name "Grey Room" \
    --days-back 365 \
    --output /tmp/test-papers.json

# Verify output
cat /tmp/test-papers.json | jq 'length'
cat /tmp/test-papers.json | jq '.[0]'
```

---

### Phase 3: Implement generate_scan_report.py (35 min)

#### Task 3.1: Create skeleton
**Time**: 5 min

Create `skills/process-journal/scripts/generate_scan_report.py`:

```python
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
    pass

def generate_report(merged: list[dict], journal_name: str) -> str:
    """Generate markdown report."""
    pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--papers", required=True)
    parser.add_argument("--scores", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    # TODO: implement

if __name__ == "__main__":
    main()
```

---


#### Task 3.3: Implement generate_report()
**Time**: 15 min

```python
def generate_report(merged: list[dict], journal_name: str) -> str:
    """Generate markdown report."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Split by tier
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
    
    # Tier 1: detailed
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
    
    # Tier 2: table
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
    
    # Tier 3: collapsed
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
```


#### Task 3.4: Complete main()
**Time**: 5 min

```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--papers", required=True)
    parser.add_argument("--scores", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    papers_path = Path(args.papers)
    scores_dir = Path(args.scores)
    output_path = Path(args.output)

    # Extract journal name from output path
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
```

**Test** (with mock data):
```bash
# Create mock scores
mkdir -p /tmp/test-scores
echo '{"r": 8, "q": 7, "i": 6, "tags": ["test"], "one_liner": "测试论文"}' > /tmp/test-scores/W123.json

python3 skills/process-journal/scripts/generate_scan_report.py \
    --papers /tmp/test-papers.json \
    --scores /tmp/test-scores/ \
    --output /tmp/test-scan.md

cat /tmp/test-scan.md
```

---


### Phase 4: Create score-single-paper.md (10 min)

#### Task 4.1: Create prompt template
**Time**: 10 min

Create `skills/process-journal/prompts/score-single-paper.md`:

```markdown
你是学术论文评分代理。根据研究兴趣评估论文相关性。

## 研究兴趣
{research_interests}

## 待评分论文
- **标题**: {title}
- **作者**: {authors}
- **日期**: {publication_date}
- **摘要**: {abstract}

## 评分标准
1. **相关性 (R)**: 与研究兴趣的匹配度(1-10)
2. **质量 (Q)**: 学术严谨性、论证深度 (1-10)
3. **影响力 (I)**: 引用量、理论贡献潜力 (1-10)

## 输出格式（JSON）
```json
{
  "r": 8,
  "q": 7,
  "i": 6,
  "tags": ["embodiment", "AI", "media"],
  "one_liner": "探讨 AI 对身体感知的影响"
}
```

要求：
- one_liner 用中文，20 字以内
- tags 最多 3 个，用英文
- 只输出 JSON，不要其他文字
```

**Verification**: Check file exists and format is correct

---


### Phase 5: Update SKILL.md (30 min)

#### Task 5.1: Add Phase 0 documentation
**Time**: 20 min

Update `skills/process-journal/SKILL.md`:

1. Add Phase 0 section after line 50 (before Phase 2):
   - Title: "## Phase 0: SCAN (新增)"
   -調度方式: scan-coordinator (foreground subagent)
   - Include coordinator prompt template
   - Document: fetch → score → report workflow

2. Update main process flow (line 190+):
   - Add Phase 0 check before Phase 2
   - Add scan-coordinator invocation

**Key additions**:
- scan-coordinator prompt (similar to download-coordinator/analyze-coordinator)
-断点续跑: check if scan.md exists
- 从 CLAUDE.md §1.3 读取 research_interests

#### Task 5.2: Test documentation
**Time**: 10 min

Verify:
- All Phase 0 steps documented
- Coordinator prompt is complete
- Links to scripts are correct

---


### Phase 6: Integration Testing (20 min)

#### Task 6.1: End-to-end test
**Time**: 20 min

Test complete workflow with small journal:

```bash
# 1. Test fetch
python3 skills/process-journal/scripts/fetch_papers.py \
    --journal-name "Grey Room" \
    --days-back 365 \
    --output /tmp/grey-room-papers.json

# 2. Manually create 2-3 mock scores for testing
mkdir -p /tmp/grey-room-scores
# (Create mock score files based on paper IDs)

# 3. Test report generation
python3 skills/process-journal/scripts/generate_scan_report.py \
    --papers /tmp/grey-room-papers.json \
    --scores /tmp/grey-room-scores/ \
    --output /tmp/grey-room-scan.md

# 4. Verify report format
cat /tmp/grey-room-scan.md
```

**Success criteria**:
- Papers fetched successfully
- Report generated with correct format
- Tier 1/2/3 sections present
- Matches reeder output format

---

## Summary

**Files created** (3):
1. `skills/process-journal/scripts/fetch_papers.py` (~100 lines)
2. `skills/process-journal/scripts/generate_scan_report.py` (~80 lines)
3. `skills/process-journal/prompts/score-single-paper.md` (~30 lines)

**Files modified** (1):
1. `skills/process-journal/SKILL.md` (add Phase 0 docs)

**Total effort**: ~2-3 hours

**Dependencies**: `requests` (already in quasi)

**Next steps after implementation**:
1. Test with real journal (10-20 papers)
2. Verify scan-coordinator workflow
3. Update CLAUDE.md with example usage
4. Document in README if needed

