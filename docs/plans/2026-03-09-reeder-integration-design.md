# Reeder Integration Design

**Date**: 2026-03-09
**Status**: Design Phase
**Author**: Claude + User

## 1. Overview

### 1.1 Goal
Integrate reeder's journal scanning capabilities (fetch + score) into `quasi:process-journal` to create an end-to-end workflow without external dependencies.

### 1.2 User Requirements
- **B**: Integrate fetch + score (not full reeder)
- **B**: Use `requests` (consistent with quasi)
- **C**: Read config from CLAUDE.md §1.3
- **A**: Journal identification by name (search OpenAlex)

### 1.3 Scope
**In scope**:
- OpenAlex API client for journal/paper fetching
- AI-based paper scoring (per-paper subagents)
- scan.md report generation
- Integration into process-journal as Phase 0

**Out of scope**:
- Database (SQLite)
- Configuration files (YAML)
- CLI tool (reeder standalone)
- Full-text download (quasi:download already handles this)

---

## 2. Architecture

### 2.1 Integration Approach
**Selected**: Integrate into `process-journal` (not a separate skill)

**Rationale**:
- User intent: make process-journal end-to-end
- Journal scanning is not a high-frequency standalone operation
- Minimal code (~210 lines)
- Easy to extract later if needed

### 2.2 Directory Structure
```
skills/process-journal/
├── SKILL.md                          # Updated: add Phase 0
├── scripts/
│   ├── fetch_papers.py              # OpenAlex fetch (~100 lines)
│   └── generate_scan_report.py      # Report generation (~80 lines)
└── prompts/
    └── score-single-paper.md        # Single-paper scoring prompt (~30 lines)
```

### 2.3 Orchestration Pattern
**Phase 0**: scan-coordinator (foreground subagent)
- Consistent with Phase 2/3 coordinator pattern
- Manages: fetch → parallel scoring → report generation

---

## 3. Data Flow

```
User: /quasi:process-journal "Critical Inquiry"
  ↓
Main process checks vault/journals/critical-inquiry-scan.md
  ↓ (not exists)
Phase 0: scan-coordinator [foreground]
  ↓
  ├─ fetch_papers.py → /tmp/critical-inquiry-papers.json
  ├─ Read CLAUDE.md §1.3 → research_interests
  ├─ For each paper: spawn scoring subagent [background]
  │    → /tmp/critical-inquiry-scores/{paper_id}.json
  ├─ Wait for completion (Glob check)
  └─ generate_scan_report.py → vault/journals/critical-inquiry-scan.md
  ↓
Phase 1: READ (existing)
Phase 2: ACQUIRE
Phase 3: ANALYZE
Phase 4: SYNTHESIZE
```

---

## 4. Component Design

### 4.1 fetch_papers.py

**Interface**:
```bash
python3 fetch_papers.py \
    --journal-name "Critical Inquiry" \
    --days-back 3650 \
    --output /tmp/critical-inquiry-papers.json
```

**Logic**:
1. Search journal by name → source_id (OpenAlex API)
2. Fetch papers from source_id (from_date = today - days_back)
3. Parse and save to JSON

**Dependencies**: `requests`, `json`, `datetime`

**Key Functions**:
- `search_journal(name: str) -> str` - Returns source_id
- `fetch_papers(source_id: str, from_date: str) -> list[dict]` - Returns papers
- `reconstruct_abstract(inverted_index: dict) -> str` - OpenAlex format

**Paper Object**:
```python
{
    "id": "W123456789",
    "doi": "10.1086/123456",
    "title": "...",
    "abstract": "...",
    "authors": "Author1, Author2",
    "publication_date": "2023-05-15",
    "journal_name": "Critical Inquiry",
    "cited_by_count": 42
}
```

### 4.2 generate_scan_report.py

**Interface**:
```bash
python3 generate_scan_report.py \
    --papers /tmp/critical-inquiry-papers.json \
    --scores /tmp/critical-inquiry-scores/ \
    --output vault/journals/critical-inquiry-scan.md
```

**Logic**:
1. Load papers JSON
2. Load all score JSON files
3. Merge papers + scores
4. Sort by overall_score (descending)
5. Generate markdown report (Tier 1/2/3)

**Report Format** (consistent with reeder):
```markdown
# Critical Inquiry — 10-Year Scan (2016-2026)

Generated: 2026-03-09 14:07
Total articles scored: 150

## Tier 1: High Relevance (25 articles, score >= 7)

### [Paper Title]
- **Date**: 2023-05-15 | **Score**: R=8 Q=7 I=6 **Avg=7.0**
- **Tags**: ["embodiment", "AI", "media"]
- **Summary**: 探讨 AI 对身体感知的影响
- **DOI**: 10.1086/123456
- **Abstract**: ...

## Tier 2: Moderate Relevance (50 articles, score 5-6.9)
[Table format]

## Tier 3: Low Relevance (75 articles, score < 5)
[Collapsed details]
```

### 4.3 score-single-paper.md

**Prompt Template**:
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
{
  "r": 8,
  "q": 7,
  "i": 6,
  "tags": ["embodiment", "AI", "media"],
  "one_liner": "探讨 AI 对身体感知的影响"
}

要求：
- one_liner 用中文，20 字以内
- tags 最多 3 个，用英文
- 只输出 JSON，不要其他文字
```

**Advantages**:
- Minimal context (~1 paper vs 10 papers in batch)
- Parallel execution (all scoring subagents run in background)
- Failure isolation (one failure doesn't affect others)
- Consistent with Phase 3 pattern

---

## 5. Error Handling

### 5.1 Fetch Stage
```python
try:
    source_id = search_journal(journal_name)
    papers = fetch_papers(source_id, from_date)
    if len(papers) == 0:
        raise ValueError("No papers found")
except Exception as e:
    print(f"Fetch failed: {e}")
    sys.exit(1)
```

### 5.2 Scoring Stage (coordinator handles)
- Single paper fails → log failure, continue others
- Timeout (5 min no response) → mark as failed
- Final report: N succeeded, M failed

### 5.3 Report Generation
- Only process successfully scored papers
- Failed papers: not included in report (or listed separately)

---

## 6. Resumability

### 6.1 Phase 0 Level
```python
# Main process checks
scan_path = f"vault/journals/{journal_name}-scan.md"
if exists(scan_path) and not args.force:
    print("scan.md exists, skipping Phase 0")
    # Jump to Phase 2
```

### 6.2 Scoring Level (coordinator internal)
```python
# Check existing scores
existing_scores = glob("/tmp/{journal-name}-scores/*.json")
existing_ids = [extract_id(f) for f in existing_scores]

# Only score unfinished papers
papers_to_score = [p for p in papers if p["id"] not in existing_ids]
```

**Benefits**:
- Resume after interruption without re-scoring
- Suitable for large batches (100+ papers)

---

## 7. Configuration

### 7.1 CLAUDE.md Format
Add §1.3 (if not exists):

```markdown
## 1.3 研究参数

### Topic
技术、AI、媒介与具身化

### Preamble
这是人文/理论类文本，不是实证研究。不要寻找"数据"、"样本量"或"因果推断"。聚焦于理论论证、概念贡献和学术对话。

### Research Interests
body/embodiment, technology and AI, media theory, STS, phenomenology
```

### 7.2 Reading Logic
```python
def read_research_interests():
    path = Path("CLAUDE.md")
    content = path.read_text()
    match = re.search(r"### Research Interests\n(.+)", content)
    return match.group(1) if match else ""
```

---

## 8. Implementation Plan

### 8.1 Files to Create

**1. skills/process-journal/scripts/fetch_papers.py** (~100 lines)
- OpenAlex API client functions
- CLI interface
- JSON output

**2. skills/process-journal/scripts/generate_scan_report.py** (~80 lines)
- Load papers + scores
- Merge and sort
- Generate markdown report

**3. skills/process-journal/prompts/score-single-paper.md** (~30 lines)
- Single-paper scoring prompt
- JSON output format

### 8.2 Files to Modify

**1. skills/process-journal/SKILL.md**
- Add Phase 0 documentation
- Update main process flow
- Add scan-coordinator prompt template

### 8.3 Dependencies
- `requests` (already in quasi)
- No additional external dependencies

### 8.4 Code Estimate
- Python: ~180 lines
- Markdown: ~30 lines prompt + ~50 lines docs
- Total: ~260 lines

---

## 9. Testing Strategy

### 9.1 Unit Testing
- `search_journal()` - Mock OpenAlex API response
- `fetch_papers()` - Test pagination, date filtering
- `reconstruct_abstract()` - Test inverted index parsing

### 9.2 Integration Testing
- End-to-end: journal name → scan.md
- Test with small journal (10-20 papers)
- Verify report format matches reeder output

### 9.3 Edge Cases
- Journal not found
- No papers in date range
- Scoring timeout/failure
- Malformed abstracts

---

## 10. Migration Path

### 10.1 From Reeder
Users currently using reeder can:
1. Continue using reeder for scan.md generation
2. Gradually migrate to integrated Phase 0
3. Both approaches produce compatible scan.md format

### 10.2 Backward Compatibility
- scan.md format unchanged
- Existing process-journal workflows unaffected
- Phase 0 is optional (skip if scan.md exists)

---

## 11. Summary

**What we're building**:
- Minimal reeder integration (~260 lines)
- OpenAlex fetch + AI scoring + report generation
- Integrated into process-journal as Phase 0

**Key decisions**:
- Single-paper scoring (not batch) for minimal context
- Coordinator pattern (consistent with Phase 2/3)
- Config from CLAUDE.md (no separate config files)
- Journal name input (search OpenAlex for ID)

**Next steps**:
1. Create implementation plan with writing-plans skill
2. Implement fetch_papers.py
3. Implement generate_scan_report.py
4. Create score-single-paper.md prompt
5. Update SKILL.md with Phase 0 docs
6. Test with sample journal

